"""Batched native unilateral contact and shared symmetry constraints."""
import ctypes as C
from dataclasses import replace
import numpy as np
from .native import library, array, P, I
from .reference import DeformationReference


def configured_library():
    lib = library()
    lib.af_ad_contact.argtypes = [P,P,P,C.c_int,I,C.c_int,I,P,C.c_uint64,C.c_char_p,P,P]
    lib.af_ad_symmetry.argtypes = [P,C.c_int,P,I,P]
    return lib


def prepare_contact(reference, origin=(0,0,0), normal=(0,0,0)):
    a = dict(reference.arrays); plane = array((*origin,*normal)); partners = np.full(len(a["vertices"]),-1,np.int32)
    maximum = np.zeros(1); lib = configured_library()
    if np.linalg.norm(plane[3:]) > 0:
        plane[3:] /= np.linalg.norm(plane[3:])
        if not lib.af_ad_symmetry(array(a["vertices"]),len(partners),plane,partners,maximum):
            raise RuntimeError(lib.af_ad_error().decode())
    a.update(symmetry_partners=partners,symmetry_plane=plane)
    metadata = dict(reference.metadata,contact_version=1,reference_symmetry_error=float(maximum[0]))
    return DeformationReference(a,metadata)


def project(context, candidate):
    a = context.deformation_reference.arrays
    if "symmetry_partners" not in a: raise ValueError("Reference lacks shared contact preparation; initialize explicitly.")
    faces = array(np.concatenate((a["quads"][:,[0,1,2]],a["quads"][:,[0,2,3]])),True)
    output = np.empty_like(a["vertices"],dtype=np.float64); stats = np.zeros(8); lib = configured_library()
    code = lib.af_ad_contact(array(a["vertices"]),array(context.topology.vertices),array(candidate.vertices),len(output),
        faces,len(faces),array(a["symmetry_partners"],True),array(a["symmetry_plane"]),context.memory_budget or 2**30,
        context.cancel_path.encode(),output,stats)
    if not code: raise RuntimeError(lib.af_ad_error().decode())
    diagnostics = dict(candidate.diagnostics,contact=dict(unresolved=int(stats[0]),tested=int(stats[1]),passes=int(stats[2]),
        limit_reached=bool(stats[3]),negative_separation=float(stats[4]),motion_validation_incomplete=bool(stats[6]),
        published_motion_violations=int(stats[5]),symmetry_error=float(stats[7])))
    return replace(candidate,vertices=output,diagnostics=diagnostics,message=contact_warnings(stats))


def contact_warnings(stats):
    warnings = ["Contact motion validation is incomplete for coplanar trajectories."] if stats[6] else []
    if stats[0] or stats[3]: warnings.append("Unilateral contact correction remains unresolved or reached its work limit.")
    if stats[5] > 0: warnings.append("Motion from the displayed mesh contains unresolved crossing constraints.")
    if stats[5] < 0: warnings.append("Motion from the displayed mesh could not be fully validated.")
    return " ".join(warnings)
