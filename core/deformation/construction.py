"""Reference assembly; numerical preparation crosses the native boundary in batches."""
from dataclasses import asdict
import numpy as np
from .reference import DeformationReference, SCHEMA, CAPABILITY
from .native import PreparedSolver, array, library


def assemble(vertices, quads, proxy, contributors, points, faces, settings, cancel_path):
    samples, weights, owners, addresses = sample_anatomy(contributors, points, faces)
    arrays = dict(vertices=vertices, quads=quads, vertex_ids=np.arange(len(vertices), dtype=np.int32),
        proxy_vertices=proxy["vertices"], proxy_tets=proxy["tets"], samples=samples,
        sample_weights=weights, sample_owners=owners, sample_addresses=addresses)
    retain_contributors(arrays, contributors, points, faces)
    metadata = dict(schema=SCHEMA, capability=CAPABILITY, contributors=contributors, settings=asdict(settings))
    with PreparedSolver(DeformationReference(arrays, metadata), settings, cancel_path) as prepared:
        replay, diagnostics, _ = prepared.solve(samples)
        arrays["embedding_indices"], arrays["embedding_weights"] = prepared.embedding()
    error = float(np.linalg.norm(replay-vertices, axis=1).max())
    if error > 1e-6*max(float(np.ptp(vertices, axis=0).max()), 1e-12):
        raise ValueError("Deformation reference identity replay failed.")
    metadata["reference_diagnostics"] = dict(identity_error=error, native=diagnostics.tolist())
    return DeformationReference(arrays, metadata)


def retain_contributors(arrays, contributors, points, faces):
    for index, row in enumerate(contributors):
        arrays[f"contributor_{index}_vertices"] = points[row["key"]]
        arrays[f"contributor_{index}_faces"] = faces[row["key"]]


def sample_anatomy(contributors, points, faces):
    lib = library(); samples, weights, owners, addresses = [], [], [], []
    for owner, record in enumerate(contributors):
        p, f = array(points[record["key"]]), array(faces[record["key"]], True)
        ids, mass = sample_surface(lib, p, f)
        samples.extend(p[ids]); weights.extend([mass/len(ids)]*len(ids))
        owners.extend([owner]*len(ids)); addresses.extend(ids)
    weights = np.asarray(weights); weights /= weights.sum()
    return array(samples), weights, array(owners, True), array(addresses, True)


def sample_surface(lib, points, faces):
    from .reference import mesh
    mesh(points, faces, faces.shape[1])
    mass = np.zeros(len(points)); lib.af_ad_areas(points,len(points),faces,len(faces),faces.shape[1],mass)
    keep = np.flatnonzero(mass > 0)
    if not len(keep): raise ValueError("Contributor has no nondegenerate material surface.")
    cumulative = np.cumsum(mass[keep]); count = min(80, len(keep))
    selected = np.unique(keep[np.searchsorted(cumulative, (np.arange(count)+.5)*cumulative[-1]/count)])
    return selected, float(cumulative[-1])
