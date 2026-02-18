class ShapeRegistry:
    _registry = {}

    @classmethod
    def register(cls, shape_cls):
        cls._registry[shape_cls.type_id] = shape_cls

    @classmethod
    def get(cls, type_id):
        return cls._registry.get(type_id)

    @classmethod
    def enum_items(cls):
        return [(s.type_id, s.label, "") for s in cls._registry.values()]

    @classmethod
    def create_from_prop(cls, scp_prop):
        shape_cls = cls.get(scp_prop.shape_type)
        return shape_cls.from_scp_prop(scp_prop) if shape_cls else None

    @classmethod
    def register_scene_props(cls):
        for shape_cls in cls._registry.values():
            shape_cls.register_scene_props()

    @classmethod
    def unregister_scene_props(cls):
        for shape_cls in cls._registry.values():
            shape_cls.unregister_scene_props()

    @classmethod
    def draw_creation_ui(cls, shape_type, layout, scene):
        shape_cls = cls.get(shape_type)
        if shape_cls:
            shape_cls.draw_creation_ui(layout, scene)

    @classmethod
    def apply_creation_to_scp(cls, shape_type, scene, scp_prop):
        shape_cls = cls.get(shape_type)
        if shape_cls:
            shape_cls.apply_creation_to_scp(scene, scp_prop)

    @classmethod
    def draw_scp_ui(cls, shape_type, layout, scp_prop, readonly=False):
        shape_cls = cls.get(shape_type)
        if shape_cls:
            shape_cls.draw_scp_ui(layout, scp_prop, readonly=readonly)
