"""Resolve named material stations against the current native hard anchors."""
from types import SimpleNamespace
import numpy as np
from ..authoring.codec import decode, encode
from ..authoring.compilation import material_coordinates
from ..authoring.errors import require
from ..authoring.runtime import surface as material_surface
from ..vcp.fiber_solver import FiberSolver
from ..utils import depsgraph_for_scene


def evaluate_material(root, scene, surface, fibers, rows):
    material = decode(surface["af_authoring_material"])
    solver = FiberSolver()
    runtime = solver._runtime_registry(scene, depsgraph_for_scene(scene))
    material["row_s"] = [coordinates(root,scene,solver,runtime,fiber,row,material) for fiber,row in zip(fibers,rows)]
    return material_surface(rows, encode(material),boundary_resolver(root,scene,material))


def boundary_resolver(root,scene,material):
    if "boundary_document" not in material:
        return None
    if any(t['binding'].get('id', '').startswith('AFI_') for t in material['boundary_document']['targets'].values()):
        return instance_boundary_resolver(root, scene, material)
    from ...adapters.authoring.capture import capture_mesh
    from ..authoring.model import SceneSnapshot
    from ..authoring.regions import RegionResolver
    meshes = tuple(filter(None,(capture_mesh(root,scene,s) for s in root.af_scp_system.scps)))
    return RegionResolver(material["boundary_document"],SceneSnapshot(root.name,"native_rebuild",meshes))


def instance_boundary_resolver(root, scene, material):
    from ...adapters.authoring.scene import StaticScene
    from ..authoring.regions import RegionResolver
    return RegionResolver(material['boundary_document'], StaticScene(root, scene).capture(root.name))


def coordinates(root, scene, solver, runtime, fiber, row, material):
    method = solver._loop_route_anchors if material["closed"] else solver._route_anchors
    anchors = method(root,scene,runtime,fiber)
    require(anchors is not None and len(anchors) == len(material["stations"]), "MATERIAL_ANCHORS_CHANGED")
    plan = SimpleNamespace(anchors=anchors, stations=material["stations"], closed=material["closed"])
    return material_coordinates(np.array(row), plan).tolist()
