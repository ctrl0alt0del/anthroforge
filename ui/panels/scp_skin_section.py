def draw_skin_collagen_box(layout, scp):
    box = layout.box()
    box.label(text="Draft Skin Collagen")
    box.prop(scp, "skin_collagen_mode", text="Mode")
    mode = str(getattr(scp, "skin_collagen_mode", "AUTO"))
    if mode == "AUTO":
        box.label(text="Ear, cartilage, and nasal SCPs use zero.", icon="INFO")
        return
    box.prop(scp, "skin_collagen", text="Collagen")
    if mode == "PAINTED":
        box.operator("af.paint_skin_collagen", icon="WPAINT_HLT")
