import json
import os
import re
import uuid
import bpy


_INDEX_FILE = "index.json"


def _assets_dir():
    # Global per-user storage (cross-session, cross-project on same machine).
    return bpy.utils.user_resource(
        "SCRIPTS",
        path=os.path.join("presets", "anthroforge", "scp_assets"),
        create=True,
    )


def _index_path():
    return os.path.join(_assets_dir(), _INDEX_FILE)


def _safe_slug(text):
    t = (text or "").strip().lower()
    t = re.sub(r"[^a-z0-9_ -]+", "", t)
    t = t.replace(" ", "_").replace("-", "_")
    t = re.sub(r"_+", "_", t).strip("_")
    return t or "mesh_asset"


def _read_index():
    p = _index_path()
    if not os.path.exists(p):
        return {"assets": []}
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {"assets": []}
        if "assets" not in data or not isinstance(data["assets"], list):
            data["assets"] = []
        return data
    except Exception:
        return {"assets": []}


def _write_index(data):
    p = _index_path()
    with open(p, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def list_assets():
    data = _read_index()
    out = []
    for a in data["assets"]:
        if not isinstance(a, dict):
            continue
        asset_id = a.get("id", "")
        display_name = a.get("name", asset_id)
        file_name = a.get("file", "")
        mesh_name = a.get("mesh_name", "")
        if not asset_id or not file_name or not mesh_name:
            continue
        full_path = os.path.join(_assets_dir(), file_name)
        if not os.path.exists(full_path):
            continue
        out.append(
            {
                "id": asset_id,
                "name": display_name,
                "file": file_name,
                "mesh_name": mesh_name,
                "path": full_path,
            }
        )
    out.sort(key=lambda x: x["name"].lower())
    return out


def enum_items():
    items = []
    for a in list_assets():
        items.append((a["id"], a["name"], a["id"]))
    if not items:
        items.append(("__NONE__", "No Mesh Assets", "Register one first"))
    return items


def save_asset_from_object(obj, display_name=None):
    if obj is None or obj.type != "MESH" or obj.data is None:
        raise ValueError("Selected object must be a mesh object.")

    base_name = display_name or obj.name or "Mesh Asset"
    asset_id, file_name, file_path = _new_asset_paths(base_name)
    mesh_copy = _baked_mesh_copy(obj, asset_id)
    try:
        _replace_existing_file(file_path)
        bpy.data.libraries.write(file_path, {mesh_copy}, fake_user=True)
        _append_asset_index(asset_id, base_name, file_name, mesh_copy.name)
        return asset_id
    finally:
        if mesh_copy.users == 0 and mesh_copy.name in bpy.data.meshes:
            bpy.data.meshes.remove(mesh_copy)


def _new_asset_paths(base_name):
    slug = _safe_slug(base_name)
    asset_id = f"{slug}_{uuid.uuid4().hex[:8]}"
    file_name = f"{asset_id}.blend"
    file_path = os.path.join(_assets_dir(), file_name)
    return asset_id, file_name, file_path


def _baked_mesh_copy(obj, asset_id):
    mesh_copy = obj.data.copy()
    mesh_copy.name = f"AF_ASSET_{asset_id}"
    m = obj.matrix_world.copy()
    m.translation = (0.0, 0.0, 0.0)
    mesh_copy.transform(m)
    mesh_copy.update()
    return mesh_copy


def _replace_existing_file(file_path):
    if os.path.exists(file_path):
        os.remove(file_path)


def _append_asset_index(asset_id, base_name, file_name, mesh_name):
    data = _read_index()
    data["assets"].append(
        {"id": asset_id, "name": base_name, "file": file_name, "mesh_name": mesh_name}
    )
    _write_index(data)


def load_asset_mesh(asset_id):
    assets = list_assets()
    asset = next((a for a in assets if a["id"] == asset_id), None)
    if asset is None:
        return None

    file_path = asset["path"]
    mesh_name = asset["mesh_name"]

    # Reuse already-loaded mesh with same internal name if present.
    existing = bpy.data.meshes.get(mesh_name)
    if existing is not None:
        return existing

    loaded = None
    with bpy.data.libraries.load(file_path, link=False) as (data_from, data_to):
        if mesh_name in data_from.meshes:
            data_to.meshes = [mesh_name]

    if data_to.meshes and data_to.meshes[0] is not None:
        loaded = data_to.meshes[0]

    return loaded

def delete_asset(asset_id):
    data = _read_index()
    assets = data.get("assets", [])
    idx = next((i for i, a in enumerate(assets) if a.get("id") == asset_id), -1)
    if idx < 0:
        return False

    a = assets[idx]
    file_name = a.get("file", "")
    mesh_name = a.get("mesh_name", "")

    # remove library file
    if file_name:
        p = os.path.join(_assets_dir(), file_name)
        if os.path.exists(p):
            try:
                os.remove(p)
            except Exception:
                pass

    # remove from index
    assets.pop(idx)
    _write_index(data)

    # unload mesh datablock if present
    m = bpy.data.meshes.get(mesh_name)
    if m is not None and m.users == 0:
        bpy.data.meshes.remove(m)

    return True
