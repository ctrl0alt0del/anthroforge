"""Guarded source selection, declared seams, and qualified physical endpoints."""
import numpy as np
from ...core.authoring.errors import require
from ...core.authoring.smooth_chart import grid
from ...core.authoring.transfer_meshes import world
from .base_definitions import source


def inputs(service, params):
    row = source(service, params); vertices = np.asarray(world(row['geometry'])); triangles = np.asarray(row['geometry']['triangles'])
    parts = params['patches']; names = [p['id'] for p in parts]; heads = {h['id'] for h in params['heads']}
    require(len(set(names)) == len(names) and len(heads) == len(params['heads']), 'BASE_DUPLICATE_ID')
    require(all(p['head_ids'] and set(p['head_ids']) <= heads for p in parts), 'BASE_UNKNOWN_HEAD')
    require({h for p in parts for h in p['head_ids']} == heads, 'BASE_UNUSED_HEAD')
    grids = [grid(vertices, triangles, p) for p in parts]; joins = connections(parts, params['seams'])
    aliases = fiber_aliases(parts, joins); hits = qualified(service, parts, aliases, params['settings'])
    return grids, joins, aliases, hits


def connections(parts, seams):
    names = [p['id'] for p in parts]; output, occupied = [], set()
    require(len({s['id'] for s in seams}) == len(seams), 'BASE_DUPLICATE_SEAM')
    for seam in seams:
        ends = [(x['patch_id'], x['side']) for x in (seam['first'], seam['second'])]
        require(all(p in names for p, _ in ends) and ends[0][0] != ends[1][0], 'BASE_INVALID_SEAM')
        require(not occupied.intersection(ends), 'BASE_OVERLAPPING_SEAMS'); occupied.update(ends)
        output.append([names.index(ends[0][0]), ends[0][1], names.index(ends[1][0]), ends[1][1]])
    return output


def fiber_aliases(parts, joins):
    result = {(i, j): (i, j) for i, p in enumerate(parts) for j in range(len(p['endpoints']))}
    for a, sa, b, sb in joins:
        first = (a, 0 if sa == 0 else len(parts[a]['endpoints'])-1)
        second = (b, 0 if sb == 0 else len(parts[b]['endpoints'])-1)
        require(parts[first[0]]['endpoints'][first[1]] == parts[second[0]]['endpoints'][second[1]], 'BASE_SEAM_PIN_CONFLICT', 'Declare the same endpoint definitions on both sides of a shared boundary.')
        keep, replace = min(first, second), max(first, second); result[replace] = keep
    return result


def qualified(service, parts, aliases, settings):
    output = {}
    for key, canonical in aliases.items():
        if key != canonical: continue
        row = parts[key[0]]['endpoints'][key[1]]; output[key] = []
        for end in ('start', 'end'):
            spec = row[end]; request = dict(instance_id=spec['instance_id'], points=[spec['position']],
                max_distance=spec['max_distance'], collision_radius=settings.get('collision_radius', .002))
            hit = service.scene.snap_points(request, service.inventory)[0]
            require(hit.get('valid'), 'BASE_PIN_UNRESOLVED', str(hit.get('diagnostics', [])))
            hit = junction(service, hit, spec, canonical, aliases)
            hit['mode'] = spec.get('mode', 'fit')
            output[key].append(hit)
    return {key: output[canonical] for key, canonical in aliases.items()}


def junction(service, hit, spec, canonical, aliases):
    offset = spec.get('normal_offset', 0.)
    if not offset: return hit
    require(list(aliases.values()).count(canonical) > 1 and bool(spec.get('purpose')), 'BASE_OFFSET_REQUIRES_SHARED_JUNCTION')
    return service.scene.smooth_base_junction(hit, offset, spec['purpose'])


def fit_pins(parts, grids, hits, aliases):
    result = []
    for i, part in enumerate(parts):
        for j in range(len(part['endpoints'])):
            if aliases[i, j] != (i, j): continue
            u = j/(len(part['endpoints'])-1)
            for along in (0, 1):
                hit = hits[i, j][along]; point = hit['point']
                if hit['mode'] == 'extend':
                    edge = grids[i][:, 0 if along == 0 else -1]
                    point = [np.interp(u, np.linspace(0, 1, len(edge)), edge[:, k]) for k in range(3)]
                result.append([i, u, along, *point])
    return result
