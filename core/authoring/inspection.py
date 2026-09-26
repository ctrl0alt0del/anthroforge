"""Dependency-free orthographic inspection assets for the protocol."""
from html import escape
import numpy as np
from .geometry import world_vertices


def svg(snapshot, output, view):
    parts = ['<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="470" viewBox="0 0 1200 470">',
             '<rect width="1200" height="470" fill="#f4f1eb"/>',
             '<text x="20" y="26" font-family="sans-serif" font-size="18">'+escape(view)+': authoring inspection (scene units)</text>']
    for index, axes in enumerate(((1,2),(0,2),(1,0))):
        parts.extend(panel(snapshot, output, view, axes, index))
    return ''.join(parts)+'</svg>'


def panel(snapshot, output, view, axes, index):
    points = np.array(output.get("inflated", output.get("points", [a["point"] for a in output.get("anchors",[])])))
    if not len(points):
        return []
    xy = points[:,axes]
    low, high = xy.min(0), xy.max(0)
    scale = 335/max(float(np.max(high-low)), .01)
    origin = np.array([index*400+35,430])+np.array([-low[0],low[1]])*scale
    project = lambda rows: np.asarray(rows)[:,axes]*np.array([scale,-scale])+origin
    parts = [f'<g><text x="{index*400+20}" y="55" font-family="sans-serif">{"XYZ"[axes[0]]} / {"XYZ"[axes[1]]}</text>']
    parts.extend(context(snapshot, project, low, high, axes))
    parts.extend(surface(output, project, view))
    parts.extend(paths(output, project))
    parts.extend(sections(output,project) if view == "sections" else [])
    return parts+['</g>']


def polygon(points, fill, opacity="1", stroke="none"):
    coordinates = ' '.join(f'{p[0]:.2f},{p[1]:.2f}' for p in points)
    return f'<polygon points="{coordinates}" fill="{fill}" opacity="{opacity}" stroke="{stroke}" stroke-width=".4"/>'


def context(snapshot, project, low, high, axes):
    parts = []
    for mesh in snapshot.meshes:
        vertices = world_vertices(mesh)
        tri = vertices[mesh.triangles]
        selected = tri[np.all(tri[:,:,axes].max(1) >= low,axis=1) & np.all(tri[:,:,axes].min(1) <= high,axis=1)]
        parts.extend(polygon(project(row), "#718a88", ".08") for row in selected)
    return parts


def sections(output,project):
    if "side_a" in output:
        return _envelope_sections(output, project)
    from .inflation import sample
    if "inflated" not in output:
        return []
    u,s = output["u"],output["s"]
    grid = np.asarray(output["inflated"]).reshape(len(u),len(s),3)
    markers = sorted(set([.25,.5,.75]+[row["s"] for row in output.get("shape",[])]))
    parts = []
    for marker in markers:
        values = [sample(grid,u,s,x,marker,output["fibers"][0]["closed"]) for x in u]
        points = ' '.join(f'{p[0]:.2f},{p[1]:.2f}' for p in project(values))
        parts.append(f'<polyline points="{points}" fill="none" stroke="#154bc2" stroke-width="2"/>')
    return parts


def surface(output, project, view):
    if "faces" not in output or view == "fibers":
        return []
    vertices = np.array(output["inflated"])
    faces = output.get("inflated_faces", output["faces"])
    contacts = {i % len(faces) for i in output.get("contact",{}).get("triangles",[])}
    return [polygon(project(vertices[face]), "#df1630" if view == "contacts" and i in contacts else "#b76150",
                    ".7" if view == "contacts" and i in contacts else ".35", "#904638")
            for i,face in enumerate(faces)]


def paths(output, project):
    fibers = output.get("fibers", [output])
    parts = []
    for fiber in fibers:
        values = fiber.get("points", [])
        if values:
            points = ' '.join(f'{p[0]:.2f},{p[1]:.2f}' for p in project(values))
            parts.append(f'<polyline points="{points}" fill="none" stroke="#a42223" stroke-width="1.3"/>')
        for anchor in fiber.get("anchors", []):
            x,y = project([anchor["point"]])[0]
            parts.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="3" fill="#efb02a" stroke="#563d12"/>')
    return parts


def _envelope_sections(output, project):
    result = []
    for key in ('side_a', 'side_b'):
        value = dict(output, inflated=output[key]); value.pop('side_a'); value.pop('side_b')
        result.extend(sections(value, project))
    return result
