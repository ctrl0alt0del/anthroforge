"""Common-scale comparisons and typed non-muscle candidate previews."""
import numpy as np
from ...core.authoring.preview import svg
from ...core.authoring import substrate
from ...core.authoring.references import lookup


def compare(store, first, second):
    a, b = [r.get('compiled', {}).get('outputs', {}) for r in (first, second)]
    assets = []
    for name in sorted(set(a) & set(b)):
        points = np.array(a[name]['inflated']+b[name]['inflated'])
        bounds = points.min(axis=0), points.max(axis=0)
        for label, output in [('First', a[name]), ('Second', b[name])]:
            polygons = np.asarray(output['inflated'])[np.asarray(output['faces'])].tolist()
            assets.append(store.image(svg(polygons, label+' '+name+'; same scale', bounds)))
    return assets


def typed_geometry(document, inventory, specification, proposal):
    kind, value = proposal['kind'], proposal['value']
    if kind == 'frame':
        chart = substrate.frame(document, inventory, specification['target'])
        corners = np.array([[x,y,z] for x in (0,1) for y in (0,1) for z in (0,1)])
        points = substrate.world(chart, corners).tolist()
        return [[points[a], points[b]] for a in range(8) for b in range(a+1, 8) if np.sum(corners[a] != corners[b]) == 1]
    if kind == 'measurement' and value['kind'] == 'distance':
        landmarks = [lookup(document, value[key]) for key in ('first', 'second')]
        return [[substrate.world(substrate.frame(document, inventory, p['frame']), p['q']).tolist() for p in landmarks]]
    return []
