import bpy


class AF_UL_SCPList(bpy.types.UIList):

    def draw_item(
        self, context, layout, data, item, icon, active_data,
        active_propname, index
    ):
        scp = item

        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            layout.label(text=scp.id, icon='DOT')
            layout.label(text=scp.shape_type)

        elif self.layout_type == 'GRID':
            layout.alignment = 'CENTER'
            layout.label(text="", icon='DOT')
