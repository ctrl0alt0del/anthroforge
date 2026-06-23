import bpy

_TAU = 6.283185307179586
_CURVE_GROUP = "AF_CurveGroup_v1"
_LOFT_GROUP = "AF_LoftTwoCurves_v1"


def build_curve_loft_group(name, curve_count, overwrite=False, single_angle=False):
    curve_group = ensure_curve_group()
    loft_group = ensure_loft_group()
    group = _top_group(name, overwrite)
    group.is_modifier = True
    _build_curve_loft(group, curve_count, curve_group, loft_group, single_angle)
    return group


def ensure_curve_group(rebuild=False):
    return _ensure_helper(_CURVE_GROUP, _build_curve_group, rebuild)


def ensure_loft_group(rebuild=False):
    return _ensure_helper(_LOFT_GROUP, _build_loft_group, rebuild)


def _ensure_helper(name, builder, rebuild=False):
    group = bpy.data.node_groups.get(name)
    if group and not rebuild:
        return group
    target = bpy.data.node_groups.new(name, "GeometryNodeTree") if group is None else _prepare_group(group)
    return builder(target)


def _top_group(name, overwrite):
    group = bpy.data.node_groups.get(name)
    return _prepare_group(group) if group and overwrite else bpy.data.node_groups.new(name, "GeometryNodeTree")


def _prepare_group(group):
    group.links.clear()
    group.nodes.clear()
    group.interface.clear()
    return group


def _build_curve_group(group):
    _curve_interface(group)
    nodes = _curve_nodes(group)
    _curve_links(group, nodes)
    return group


def _curve_interface(group):
    _new_socket(group, "Value", "OUTPUT", "NodeSocketVector")
    _new_socket(group, "Object", "INPUT", "NodeSocketObject")
    _new_socket(group, "Count", "INPUT", "NodeSocketInt", 10)
    _new_socket(group, "Value", "INPUT", "NodeSocketVector")
    _new_socket(group, "Factor", "INPUT", "NodeSocketFloat", 0.0)


def _curve_nodes(group):
    return {
        "out": _node(group, "NodeGroupOutput", "Group Output", (380, 0)),
        "in": _node(group, "NodeGroupInput", "Group Input", (-520, 0)),
        "info": _node(group, "GeometryNodeObjectInfo", "Object Info", (-320, 0)),
        "self": _node(group, "GeometryNodeSelfObject", "Self Object", (140, -180)),
        "self_info": _node(group, "GeometryNodeObjectInfo", "Self Info", (340, -180)),
        "invert": _node(group, "FunctionNodeInvertMatrix", "Invert Matrix", (540, -180)),
        "local": _node(group, "FunctionNodeTransformPoint", "To Local", (340, 0)),
        "resample": _node(group, "GeometryNodeResampleCurve", "Resample Curve", (-80, 0)),
        "transform": _transform_node(group, "Transform Geometry", (-200, 0)),
        "sample": _sample_curve_node(group, "Sample Curve", (140, 0)),
    }


def _curve_links(group, nodes):
    _curve_source_links(group, nodes)
    _curve_local_links(group, nodes)


def _curve_source_links(group, nodes):
    _link(group, nodes["in"], "Object", nodes["info"], "Object")
    _link(group, nodes["info"], "Transform", nodes["transform"], "Transform")
    _link(group, nodes["info"], "Geometry", nodes["transform"], "Geometry")
    _link(group, nodes["transform"], "Geometry", nodes["resample"], "Curve")
    _link(group, nodes["in"], "Count", nodes["resample"], "Count")
    _link(group, nodes["resample"], "Curve", nodes["sample"], "Curves")
    _link(group, nodes["in"], "Value", nodes["sample"], "Value")
    _link(group, nodes["in"], "Factor", nodes["sample"], "Factor")


def _curve_local_links(group, nodes):
    _link(group, nodes["self"], "Self Object", nodes["self_info"], "Object")
    _link(group, nodes["self_info"], "Transform", nodes["invert"], "Matrix")
    _link(group, nodes["sample"], "Value", nodes["local"], "Vector")
    _link(group, nodes["invert"], "Matrix", nodes["local"], "Transform")
    _link(group, nodes["local"], "Vector", nodes["out"], "Value")


def _build_loft_group(group):
    _loft_interface(group)
    nodes = _loft_nodes(group)
    _loft_links(group, nodes)
    return group


def _loft_interface(group):
    _new_socket(group, "Geometry", "OUTPUT", "NodeSocketGeometry")
    _new_socket(group, "Vertices X", "INPUT", "NodeSocketInt", 3)
    _new_socket(group, "Factor", "INPUT", "NodeSocketFloat", 0.5)
    _new_socket(group, "A", "INPUT", "NodeSocketVector")
    _new_socket(group, "B", "INPUT", "NodeSocketVector")
    _new_socket(group, "Rows", "INPUT", "NodeSocketInt", 2)


def _loft_nodes(group):
    return {
        "out": _node(group, "NodeGroupOutput", "Group Output", (360, 0)),
        "in": _node(group, "NodeGroupInput", "Group Input", (-420, 0)),
        "grid": _node(group, "GeometryNodeMeshGrid", "Grid", (-220, 0)),
        "set": _node(group, "GeometryNodeSetPosition", "Set Position", (140, 0)),
        "mix": _mix_node(group, "Mix", (-40, 0)),
    }


def _loft_links(group, nodes):
    _link(group, nodes["in"], "Vertices X", nodes["grid"], "Vertices X")
    _link(group, nodes["in"], "Rows", nodes["grid"], "Vertices Y")
    _link(group, nodes["grid"], "Mesh", nodes["set"], "Geometry")
    _link(group, nodes["in"], "Factor", nodes["mix"], "Factor")
    _link(group, nodes["in"], "A", nodes["mix"], "A", in_index=1)
    _link(group, nodes["in"], "B", nodes["mix"], "B", in_index=1)
    _link(group, nodes["mix"], "Result", nodes["set"], "Position", out_index=1)
    _link(group, nodes["set"], "Geometry", nodes["out"], "Geometry")


def _build_curve_loft(group, curve_count, curve_group, loft_group, single_angle):
    _top_interface(group, curve_count, single_angle)
    nodes = _top_nodes(group, curve_count, single_angle)
    _top_math_links(group, nodes)
    curve_nodes = _add_curve_nodes(group, nodes, curve_count, curve_group, single_angle)
    loft_nodes = _add_loft_nodes(group, nodes, curve_nodes, loft_group)
    _top_output_links(group, nodes, loft_nodes)


def _top_interface(group, curve_count, single_angle):
    _new_socket(group, "Geometry", "OUTPUT", "NodeSocketGeometry")
    _new_socket(group, "Geometry", "INPUT", "NodeSocketGeometry")
    for index in range(curve_count):
        _new_socket(group, _curve_name(index), "INPUT", "NodeSocketObject")
    _new_socket(group, "Resolution", "INPUT", "NodeSocketInt", 64)
    for name in _angle_names(curve_count, single_angle):
        _new_socket(group, name, "INPUT", "NodeSocketFloat", _TAU, subtype="ANGLE")


def _top_nodes(group, curve_count, single_angle):
    nodes = _top_base_nodes(group)
    nodes["angle_factors"] = _angle_factors(group, nodes, curve_count, single_angle)
    return nodes


def _top_base_nodes(group):
    return {
        "out": _node(group, "NodeGroupOutput", "Group Output", (1040, 0)),
        "in": _node(group, "NodeGroupInput", "Group Input", (-940, 0)),
        "position": _node(group, "GeometryNodeInputPosition", "Position", (-940, -240)),
        "index": _node(group, "GeometryNodeInputIndex", "Index", (-940, 140)),
        "split": _node(group, "ShaderNodeSeparateXYZ", "Separate XYZ", (-740, -240)),
        "row": _math(group, "Row Factor", "ADD", (-540, -240), b=0.5),
        "join": _node(group, "GeometryNodeJoinGeometry", "Join Geometry", (820, 0)),
        "rows": _int_node(group, "Rows", (-740, 300), 2),
        "pair": _math(group, "Pair Index", "DIVIDE", (-540, 140), b=2.0),
        "floor": _math(group, "Pair Floor", "FLOOR", (-340, 140)),
        "span": _math(group, "Curve Span", "DIVIDE", (-140, 140), clamp=True),
    }


def _angle_names(curve_count, single_angle):
    if single_angle:
        return ["Angle"]
    return [f"Angle {index + 1:02d}" for index in range(curve_count)]


def _angle_factors(group, nodes, curve_count, single_angle):
    factors = []
    for index, name in enumerate(_angle_names(curve_count, single_angle)):
        factors.append(_angle_factor(group, nodes, name, index))
    return factors


def _angle_factor(group, nodes, name, index):
    chain = _angle_factor_nodes(group, name, index)
    _link_angle_factor(group, nodes, chain, name)
    return chain


def _angle_factor_nodes(group, name, index):
    y = 460 + (index * 200)
    return {
        "norm": _math(group, f"{name} Norm", "DIVIDE", (-540, y), b=_TAU),
        "offset": _math(group, f"{name} Offset", "SUBTRACT", (-340, y), a=1.0),
        "half": _math(group, f"{name} Half", "DIVIDE", (-140, y), b=2.0),
        "mul": _math(group, f"{name} Span", "MULTIPLY", (60, y - 160)),
        "factor": _math(group, f"{name} Factor", "ADD", (260, y - 160)),
    }


def _link_angle_factor(group, nodes, chain, name):
    _link(group, nodes["in"], name, chain["norm"], "Value")
    _link(group, chain["norm"], "Value", chain["offset"], "Value", in_index=1)
    _link(group, chain["offset"], "Value", chain["half"], "Value")
    _link(group, nodes["span"], "Value", chain["mul"], "Value")
    _link(group, chain["norm"], "Value", chain["mul"], "Value", in_index=1)
    _link(group, chain["mul"], "Value", chain["factor"], "Value")
    _link(group, chain["half"], "Value", chain["factor"], "Value", in_index=1)


def _top_math_links(group, nodes):
    _link_row_math(group, nodes)
    _link_span_math(group, nodes)


def _link_row_math(group, nodes):
    _link(group, nodes["position"], "Position", nodes["split"], "Vector")
    _link(group, nodes["split"], "Y", nodes["row"], "Value")


def _link_span_math(group, nodes):
    _link(group, nodes["index"], "Index", nodes["pair"], "Value")
    _link(group, nodes["rows"], "Integer", nodes["pair"], "Value", in_index=1)
    _link(group, nodes["pair"], "Value", nodes["floor"], "Value")
    _link(group, nodes["floor"], "Value", nodes["span"], "Value")
    _link(group, nodes["in"], "Resolution", nodes["span"], "Value", in_index=1)


def _add_curve_nodes(group, nodes, curve_count, curve_group, single_angle):
    curve_nodes = []
    for index in range(curve_count):
        curve_nodes.append(_curve_sample_node(group, nodes, curve_group, index, single_angle))
    return curve_nodes


def _curve_sample_node(group, nodes, curve_group, index, single_angle):
    node = _node(group, "GeometryNodeGroup", f"{_curve_name(index)} Sample", (-160, -40 - (index * 180)))
    node.node_tree = curve_group
    _link_curve_node(group, nodes, node, index, single_angle)
    return node


def _link_curve_node(group, nodes, node, index, single_angle):
    factor = nodes["angle_factors"][_angle_factor_index(index, single_angle)]
    _link(group, nodes["in"], _curve_name(index), node, "Object")
    _link(group, nodes["in"], "Resolution", node, "Count")
    _link(group, nodes["position"], "Position", node, "Value")
    _link(group, factor["factor"], "Value", node, "Factor")


def _angle_factor_index(index, single_angle):
    return 0 if single_angle else index


def _add_loft_nodes(group, nodes, curve_nodes, loft_group):
    loft_nodes = []
    for index in range(len(curve_nodes) - 1):
        loft_nodes.append(_loft_segment_node(group, nodes, curve_nodes, loft_group, index))
    return loft_nodes


def _loft_segment_node(group, nodes, curve_nodes, loft_group, index):
    node = _node(group, "GeometryNodeGroup", f"Loft {index + 1:02d}", (420, -40 - (index * 180)))
    node.node_tree = loft_group
    _link_loft_node(group, nodes, curve_nodes, node, index)
    return node


def _link_loft_node(group, nodes, curve_nodes, node, index):
    _link(group, nodes["in"], "Resolution", node, "Vertices X")
    _link(group, nodes["row"], "Value", node, "Factor")
    _link(group, curve_nodes[index], "Value", node, "A")
    _link(group, curve_nodes[index + 1], "Value", node, "B")
    _link(group, nodes["rows"], "Integer", node, "Rows")


def _top_output_links(group, nodes, loft_nodes):
    for node in loft_nodes:
        _link(group, node, "Geometry", nodes["join"], "Geometry")
    _link(group, nodes["join"], "Geometry", nodes["out"], "Geometry")


def _new_socket(group, name, in_out, socket_type, default=None, subtype=None):
    socket = group.interface.new_socket(name=name, in_out=in_out, socket_type=socket_type)
    _set_socket_subtype(socket, subtype)
    return _set_socket_default(socket, default)


def _set_socket_default(socket, default):
    if default is not None and hasattr(socket, "default_value"):
        socket.default_value = default
    return socket


def _set_socket_subtype(socket, subtype):
    if subtype and hasattr(socket, "subtype"):
        socket.subtype = subtype


def _node(group, bl_idname, name, location):
    node = group.nodes.new(bl_idname)
    node.name = name
    node.location = location
    return node


def _mix_node(group, name, location):
    node = _node(group, "ShaderNodeMix", name, location)
    node.data_type = "VECTOR"
    return node


def _sample_curve_node(group, name, location):
    node = _node(group, "GeometryNodeSampleCurve", name, location)
    node.data_type = "FLOAT_VECTOR"
    return node


def _transform_node(group, name, location):
    node = _node(group, "GeometryNodeTransform", name, location)
    node.inputs["Mode"].default_value = "Matrix"
    return node


def _int_node(group, name, location, value):
    node = _node(group, "FunctionNodeInputInt", name, location)
    node.integer = value
    return node


def _math(group, name, op, location, a=None, b=None, clamp=False):
    node = _node(group, "ShaderNodeMath", name, location)
    node.operation = op
    node.use_clamp = clamp
    _set_default(node.inputs[0], a)
    _set_default(node.inputs[1], b)
    return node


def _set_default(socket, value):
    if value is not None:
        socket.default_value = value


def _curve_name(index):
    return f"Curve {index + 1:02d}"


def _link(group, out_node, out_name, in_node, in_name, out_index=0, in_index=0):
    group.links.new(_socket(in_node.inputs, in_name, in_index), _socket(out_node.outputs, out_name, out_index))


def _socket(sockets, name, index=0):
    return [sock for sock in sockets if sock.name == name][index]
