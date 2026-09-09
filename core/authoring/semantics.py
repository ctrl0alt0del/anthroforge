"""Cross-reference and phase invariants for the bundled DSL."""
from .errors import require as ensure


def walk(value, path=""):
    yield path, value
    pairs = value.items() if isinstance(value, dict) else enumerate(value) if isinstance(value, list) else ()
    for key, child in pairs:
        yield from walk(child, path + "/" + str(key))


def increasing(values, end=None):
    return values[0] == 0 and all(a < b for a, b in zip(values, values[1:])) and (end is None or values[-1] == end)


def check_frame(frame, data):
    ensure(frame["owner"] in data["targets"], "UNKNOWN_FRAME_OWNER")
    if frame["kind"] == "landmark_box":
        return
    axes = frame["axes_owner_local"]
    ensure(all(abs(sum(v * v for v in axis) - 1) < 1e-6 for axis in axes), "NONUNIT_FRAME")
    ensure(all(abs(sum(a * b for a, b in zip(axes[i], axes[j]))) < 1e-6 for i, j in ((0, 1), (0, 2), (1, 2))), "NONORTHOGONAL_FRAME")
    x, y, z = axes
    cross = (x[1] * y[2] - x[2] * y[1], x[2] * y[0] - x[0] * y[2], x[0] * y[1] - x[1] * y[0])
    ensure(sum(a * b for a, b in zip(cross, z)) > 0.999999, "LEFT_HANDED_FRAME")


def check_lengths(path, value, data):
    if value.get("unit") == "mm":
        ensure(data["context"]["units"]["mode"] == "metric", "UNCALIBRATED_MM")
    if value.get("of") == "frame_extent":
        ensure(value["frame"] in data["frames"], "UNKNOWN_LENGTH_FRAME")
    if (path.startswith("/regions/") or path.endswith("/offset")) and value.get("of", "").startswith("reference_"):
        ensure(False, "PHASE_INVALID_LENGTH")
    if path.endswith(("/amount", "/radius", "/direction_depth", "/search_distance", "/max_surface_error")):
        ensure(value.get("value", value.get("fraction", 0)) > 0, "ZERO_REQUIRED_LENGTH")


def check_evidence(value, data):
    if "basis" in value and "sources" in value:
        ensure(all(source in data["sources"] for source in value["sources"]), "UNKNOWN_SOURCE")


def check_region(region, data):
    ensure(region["frame"] in data["frames"], "UNKNOWN_REGION_FRAME")
    shape = region["definition"]
    if shape["kind"] == "curve":
        ensure(not shape["closed"] or len(shape["seeds"]) >= 3, "SHORT_CLOSED_CURVE")
        ensure(all(a != b for a, b in zip(shape["seeds"], shape["seeds"][1:])), "DUPLICATE_CURVE_SEED")
    for key in ("direction_in_frame", "expected_normal_in_frame"):
        ensure(abs(sum(x * x for x in region["projection"][key]) - 1) < 1e-6, "NONUNIT_PROJECTION_VECTOR")


def check_station_roles(recipe):
    build, roles = recipe["construction"], recipe["region_roles"]
    if build["kind"] == "closed_loft":
        anchors = [anchor for loop in build["loops"] for anchor in loop["anchors"].values()]
    else:
        anchors = build["stations"]
    for anchor in anchors:
        ensure(anchor["region_role"] in roles, "UNKNOWN_STATION_ROLE")
        sample = anchor.get("sample", anchor.get("at"))["kind"]
        kind = {"curve_span": "curve", "patch_segment": "patch"}.get(sample, sample)
        ensure(kind == roles[anchor["region_role"]]["region_kind"], "SAMPLER_DIMENSION_MISMATCH")


def check_recipe(recipe):
    build = recipe["construction"]
    ensure((recipe["architecture"] == "ring") == (build["kind"] == "closed_loft"), "ARCHITECTURE_CONSTRUCTION_MISMATCH")
    ids = [item["id"] for item in build["stations"]]
    ensure(len(ids) == len(set(ids)), "DUPLICATE_STATION_ID")
    ensure(increasing([item["s"] for item in build["stations"]], 1 if build["kind"] == "open_loft" else None), "INVALID_STATION_ORDER")
    ensure(build["nodes_per_fiber"] >= len(ids), "INSUFFICIENT_STATION_SAMPLES")
    check_station_roles(recipe)
    if build["kind"] == "open_loft":
        ensure(increasing(build["fiber_u"], 1), "INVALID_FIBER_ORDER")
        ensure([build["stations"][0]["role"], build["stations"][-1]["role"]] == ["origin", "insertion"], "INVALID_ENDPOINT_ROLES")
        ensure(all(item["role"] == "guide" for item in build["stations"][1:-1]), "INVALID_INTERIOR_ROLE")
    else:
        check_loops(build, ids)


def check_loops(build, ids):
    ensure(build["stations"][-1]["s"] < 1, "DUPLICATE_CLOSED_SEAM")
    ensure(increasing([loop["u"] for loop in build["loops"]], 1), "INVALID_LOOP_ORDER")
    ensure(all(set(loop["anchors"]) == set(ids) for loop in build["loops"]), "LOOP_STATION_MISMATCH")


def check_binding(role, binding, data, side):
    ensure(binding["region"] in data["regions"], "UNKNOWN_BOUND_REGION")
    region = data["regions"][binding["region"]]
    ensure(region["definition"]["kind"] == role["region_kind"], "REGION_KIND_MISMATCH")
    ensure(region["purpose"] == role["purpose"], "REGION_PURPOSE_MISMATCH")
    if binding["relationship"] == "direct":
        ensure(region["concept"] == role["anatomical_target"], "DIRECT_ANATOMY_MISMATCH")
    owner = data["targets"][data["frames"][region["frame"]]["owner"]]
    ensure(owner["side"] in (side, "midline"), "ATTACHMENT_SIDE_MISMATCH")


def check_muscle(muscle, data):
    for field, group in (("recipe", "recipes"), ("volume_preset", "volume_presets"), ("policy", "policies")):
        ensure(muscle[field] in data[group], "UNKNOWN_" + field.upper())
    recipe = data["recipes"][muscle["recipe"]]
    ensure(set(recipe["region_roles"]) == set(muscle["region_bindings"]), "INCOMPLETE_REGION_BINDINGS")
    for name, role in recipe["region_roles"].items():
        check_binding(role, muscle["region_bindings"][name], data, muscle["side"])
    volume = data["volume_presets"][muscle["volume_preset"]]
    ensure(recipe["concept"] in volume["applies_to"], "WRONG_VOLUME_PRESET")
    if recipe["construction"]["kind"] == "closed_loft":
        ensure(volume["boundary"]["along"] == 0 and volume.get("length_taper", 0) == 0, "CLOSED_END_TAPER")
        ensure(data["policies"][muscle["policy"]]["refinement"]["method"] == "none", "CLOSED_REFINEMENT_DEFERRED")
    if muscle["symmetry"]["mode"] == "native_mirror":
        ensure(muscle["symmetry"]["plane_frame"] in data["frames"], "UNKNOWN_MIRROR_FRAME")


def check_roster(data):
    instances = [item for entry in data["roster"].values() for item in entry.get("instances", [])]
    ensure(len(instances) == len(set(instances)), "DUPLICATE_ROSTER_INSTANCE")
    ensure(set(instances) == set(data["muscles"]), "ROSTER_COVERAGE_MISMATCH")


def semantic_check(data):
    for frame in data["frames"].values():
        check_frame(frame, data)
    for region in data["regions"].values():
        check_region(region, data)
    for recipe in data["recipes"].values():
        check_recipe(recipe)
    for muscle in data["muscles"].values():
        check_muscle(muscle, data)
    for path, value in walk(data):
        if isinstance(value, dict):
            check_lengths(path, value, data)
            check_evidence(value, data)
    check_roster(data)
