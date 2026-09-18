"""Validate native attachment constraints before sampling or solving fibers."""
from .errors import require
from .references import lookup


def zero(value, pointer):
    amount = value.get('value', value.get('fraction', 0)) if isinstance(value, dict) else value
    require(amount == 0, 'UNSUPPORTED_ANCHOR_OFFSET',
            'Endpoints and loop anchors must lie on the SCP surface; only open-fiber middle touches support offsets.', pointer)


def construction(build, pointer):
    if build['kind'] == 'branched_loft':
        construction(build['main'], pointer+'/main')
        for key, branch in build['branches'].items():
            construction(branch['construction'], pointer+'/branches/'+key+'/construction')
        return
    if build['kind'] == 'open_loft':
        rows = build['stations']
        for index in (0, len(rows)-1):
            zero(rows[index].get('offset', 0), f'{pointer}/stations/{index}/offset')
    else:
        for index, loop in enumerate(build['loops']):
            for name, anchor in loop['anchors'].items():
                zero(anchor.get('offset', 0), f'{pointer}/loops/{index}/anchors/{name}/offset')


def instances(document):
    yield from (('/instances/'+key, row) for key, row in document.get('instances', {}).items())
    for key, assembly in document.get('assemblies', {}).items():
        yield from ((f'/assemblies/{key}/instances/{name}', row) for name, row in assembly['instances'].items())


def routes(document, instance, pointer):
    if not instance.get('route_overrides') or '#' in instance['recipe']:
        return
    closed = lookup(document, instance['recipe'])['construction']['kind'] == 'closed_loft'
    for key, route in instance['route_overrides'].items():
        rows = route['anchors']
        for index in range(len(rows)) if closed else (0, len(rows)-1):
            zero(rows[index].get('offset', 0), f'{pointer}/route_overrides/{key}/anchors/{index}/offset')


def validate(document):
    for name, recipe in document.get('recipes', {}).items():
        construction(recipe['construction'], '/recipes/'+name+'/construction')
    for pointer, instance in instances(document):
        routes(document, instance, pointer)


def defaults(build):
    rows = build['stations'] if build['kind'] == 'open_loft' else [a for loop in build['loops'] for a in loop['anchors'].values()]
    for row in rows:
        row.setdefault('offset', dict(value=0, unit='scene'))
    return build
