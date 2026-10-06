"""Owned C++ warning jobs. This module never imports or retains Blender data."""
from ctypes import POINTER, Structure, byref, c_double, c_int, c_int64, c_uint64, c_void_p
from ..vcp.v2 import collision_native as native
from ..vcp.v2.collision import V2ContactPair, _owner_token_map


class MeshInput(Structure):
    _fields_ = [('vertices', POINTER(c_double)), ('faces', POINTER(c_int64))]
    _fields_ += [(name, c_int) for name in ('vertex_count', 'face_count', 'owner')]
    _fields_ += [(name, POINTER(c_double)) for name in ('matrix', 'inverse')]


class AnchorInput(Structure):
    _fields_ = [('point', c_double * 3), ('owner', c_int), ('threshold', c_double)]


class JobStatus(Structure):
    _fields_ = [(name, c_int) for name in ('state', 'code', 'rows', 'anchors')]
    _fields_ += [('elapsed_ms', c_double)]


def configure(library):
    calls = dict(version=([], c_int), create=([], c_void_p), destroy=([c_void_p], None),
        submit=([c_void_p, POINTER(MeshInput), c_int, POINTER(AnchorInput), c_int, POINTER(c_uint64)], c_int),
        poll=([c_void_p, c_uint64, POINTER(JobStatus)], c_int),
        read=([c_void_p, c_uint64, POINTER(native._NativeContactPair), c_int,
               POINTER(native._NativeWorldContacts), c_int], c_int))
    calls.update({name: ([c_void_p, c_uint64], c_int) for name in ('cancel', 'release')})
    for name, (args, result) in calls.items():
        fn = getattr(library, 'af_warning_async_' + name); fn.argtypes, fn.restype = args, result
    if library.af_warning_async_version() != 1: raise RuntimeError('Unsupported warning worker ABI')
    return library


def mesh_inputs(colliders, owners):
    points, faces, forward, inverse = native._batch_inputs(
        [c.vertices for c in colliders], [c.triangles for c in colliders], None)
    inputs = (MeshInput * len(colliders))(*(MeshInput(native._double(p), native._integer(f),
        len(p), len(f), owners.get(c.owner_id, 0), native._double(m), native._double(inv))
        for c, p, f, m, inv in zip(colliders, points, faces, forward, inverse)))
    return inputs, (points, faces, forward, inverse)


def anchor_inputs(anchors, owners):
    return (AnchorInput * len(anchors))(*(AnchorInput((c_double * 3)(*point), owners.get(owner, 0), threshold)
                                         for point, owner, threshold in anchors))


def contact_pair(row, colliders):
    return V2ContactPair(row.edge, colliders[row.collider].collider_id, row.instance, row.face,
        row.factor, row.distance, tuple(row.closest), tuple(row.normal), bool(row.contained))


class NativeWarningExecutor:
    def __init__(self):
        self.library = configure(native.load_native())
        self.handle = self.library.af_warning_async_create()
        self.job, self.abandoned = None, False
        if not self.handle: raise RuntimeError('Cannot start warning worker')

    def submit(self, colliders, anchors):
        if self.job is not None: raise RuntimeError('Warning worker is busy')
        owners = _owner_token_map(colliders)
        meshes, buffers = mesh_inputs(colliders, owners)
        pins, token = anchor_inputs(anchors, owners), c_uint64()
        code = self.library.af_warning_async_submit(self.handle, meshes, len(meshes), pins, len(pins), byref(token))
        if code: raise RuntimeError(f'Cannot submit warning snapshot ({code})')
        self.job, self.abandoned = token.value, False
        return self.job

    def poll(self, token):
        status = JobStatus()
        if self.library.af_warning_async_poll(self.handle, token, byref(status)):
            raise RuntimeError('Unknown warning job')
        return status

    def read(self, token, colliders):
        status = self.poll(token)
        if status.state != 2: raise RuntimeError(f'Warning job failed ({status.state}, {status.code})')
        rows = (native._NativeContactPair * status.rows)()
        stats = (native._NativeWorldContacts * status.anchors)()
        if self.library.af_warning_async_read(self.handle, token, rows, len(rows), stats, len(stats)):
            raise RuntimeError('Cannot read warning result')
        return tuple(contact_pair(row, colliders) for row in rows), tuple(stats), status.elapsed_ms

    def release(self, token):
        if self.library.af_warning_async_release(self.handle, token): raise RuntimeError('Warning job is still running')
        self.job, self.abandoned = None, False

    def cancel(self, token):
        if self.job == token:
            self.library.af_warning_async_cancel(self.handle, token)
            self.abandoned = True

    def reap(self):
        if self.abandoned and self.job is not None and self.poll(self.job).state >= 2: self.release(self.job)
        return self.job is not None

    def close(self):
        if self.handle: self.library.af_warning_async_destroy(self.handle)
        self.handle, self.job = None, None
