"""Apply a shared field to reference surfaces and annotations, retaining topology."""
import numpy as np
from .codec import digest
from .errors import require
from .transfer_field import fit, evaluate, serialize
from .transfer_quality import mesh_report, landmark_report, diagnostics


def world(geometry):
    matrix = np.asarray(geometry['matrix'], dtype=float)
    return np.asarray(geometry['vertices'], dtype=float) @ matrix[:3, :3].T + matrix[:3, 3]


def build(sources, names, pairs, settings, annotations):
    source, target = np.asarray([p['source'] for p in pairs]), np.asarray([p['target'] for p in pairs])
    field = fit(source, target, settings.get('smoothing', 0.))
    meshes = [transfer_mesh(field, name, sources[name], settings) for name in names]
    reports = {row['source_object']: row['quality'] for row in meshes}
    landmarks = landmark_report(field, source, target, [p['id'] for p in pairs])
    checks = diagnostics(reports, landmarks['max_error'], settings)
    return dict(version='skeleton_transfer.v1', method='shared_cubic_rbf.v1', field=serialize(field), meshes=meshes,
                landmarks=landmarks, correspondences=pairs, annotations=transfer_annotations(field, annotations),
                diagnostics=checks, status='unresolved' if any(d['severity'] == 'error' for d in checks) else 'success',
                validation=dict(anatomy='not_evaluated', collisions='not_evaluated', native_fibers='not_created',
                                deformation='sampled_only'), condition=field.condition)


def transfer_mesh(field, name, row, settings):
    geometry = row['geometry']
    source, triangles = world(geometry), np.asarray(geometry['triangles'], dtype=int)
    output = evaluate(field, source)
    require(np.isfinite(output).all(), 'TRANSFER_OUTPUT_INVALID')
    report = mesh_report(field, source, output, triangles, settings)
    reverse = report['orientation']*np.linalg.det(np.asarray(geometry['matrix'])[:3, :3]) < 0
    faces = triangles[:, ::-1] if reverse else triangles
    return dict(source_object=name, vertices=output.tolist(), triangles=faces.tolist(), quality=report,
                source_topology_digest=row['topology_digest'], source_geometry_digest=row['geometry_digest'], color=row['color'])


def transfer_annotations(field, annotations):
    if not annotations:
        return []
    output = evaluate(field, [a['point'] for a in annotations])
    return [dict(row, transferred_point=point.tolist()) for row, point in zip(annotations, output)]


def fingerprint(sources):
    return digest({name: row['geometry_digest'] for name, row in sorted(sources.items())})
