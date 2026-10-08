"""The same single native worker performs detection, ordering and stacking."""
import ctypes as C
from dataclasses import asdict, replace
import numpy as np
from ..muscle_pairs import abi as pairs
from ..muscle_pairs.native import NativePairEngine, live_identities, owned
from . import abi
from .model import StackingSettings, material
from . import vector
from ..muscle_relationships import native as relationships

ORDER = ('supported', 'no_upward_evidence', 'coincident_bases', 'intersecting_bases',
         'conflicting_local_order', 'incompatible_directions', 'projection_failure', 'excluded')
STACK = ('own_only', 'stacked', 'blocked', 'failed')


def order_record(row, domains):
    key = lambda identity: asdict(domains[identity].key) if identity else None
    return dict(status=ORDER[row.status], underlying=key(row.underlying), covering=key(row.covering),
        positive_fragment_area=list(row.positive), negative_fragment_area=list(row.negative),
        area_semantics='sum_of_directional_fragments_not_union_coverage', coincident_area=row.coincident,
        depth_range=[row.minimum, row.maximum] if row.fragments else None, crossings=row.crossings,
        projection_warnings=row.warnings, fragments=row.fragments, points=row.points, diagnostic=row.diagnostic.decode())


def output_record(row, domains, metrics):
    return dict(domain=asdict(domains[row.id].key), status=STACK[row.status], maximum_displacement=row.maximum,
        maximum_bonus=row.maximum, maximum_bonus_deprecated=True,
        constraint_witness=constraint_witness(row.message.decode(), domains[row.id]),
        diagnostics=row.message.decode(), existing_defects=dict(self_intersections=row.baseline_self,
        bone_crossings=row.baseline_bone_crossings, sampled_bone_penetration=row.baseline_penetration,
        open_obstacles_without_volume_test=row.open_obstacles, assessed=bool(metrics['baseline_assessed'])),
        vector=metrics, support_ms=row.map_ms, solve_ms=row.solve_ms, validation_ms=row.validation_ms)


def constraint_witness(message, domain):
    import re
    matched = re.search(r'material_pin=(\d+)', message)
    if matched is None: return None
    index = int(matched.group(1)); material = domain.material
    labels = [row.identity for row in material.constraints if any(i == index and w > 0 for i, w in zip(row.indices, row.weights))]
    return dict(material_vertex=index, identities=labels)


class NativeStackEngine(NativePairEngine):
    def code(self, kind, value):
        if kind != 'domain': return super().code(kind, value)
        from hashlib import sha256
        import json
        identity = int.from_bytes(sha256(json.dumps(asdict(value), sort_keys=True).encode()).digest()[:8], 'little') & ((1 << 63)-1) or 1
        if any(k != (kind, value) and k[0] == kind and v == identity for k, v in self.identities.items()):
            raise ValueError('STACK_DOMAIN_ID_COLLISION')
        self.identities[kind, value] = identity
        return identity

    def __init__(self):
        library = vector.bind(relationships.bind(abi.library())); super().__init__(); self.library = library; self.orders, self.outputs = (), ()

    def _material(self, domain):
        value = domain.material
        if value is None: raise ValueError('STACK_MATERIAL_MISSING')
        return abi.Material(self.code('domain', domain.key), *(pairs.pointer(v) for v in
            (value.vertices, value.faces, value.interpolation, value.weights, value.fixed)),
            len(value.vertices), len(value.faces), len(domain.base), value.interpolation.shape[1], len(value.fixed), int(domain.valid))

    def submit(self, domains, settings, generation):
        values = owned_values(domains); inputs = (pairs.Input*len(values))(*(self._input(v) for v in values))
        materials = (abi.Material*len(values))(*(self._material(v) for v in values))
        config = pairs.Settings(settings.search_distance, settings.min_projected_area, settings.epsilon,
            settings.fragment_limit, settings.workers, settings.cache_bytes, settings.result_bytes)
        stack = settings.stacking or StackingSettings()
        native = abi.Settings(stack.enabled, stack.clearance, stack.radius, stack.strength, settings.displacement)
        exclusions = self._exclusions(values, stack.exclusions); obstacles = self._obstacles(values)
        status = vector.submit(self, values, settings.relationships, (self.handle, inputs, len(values), C.byref(config), materials,
            C.byref(native), exclusions, len(exclusions)//2, obstacles, len(obstacles), generation), stack)
        if status: raise ValueError('STACK_BUSY' if status == 2 else 'STACK_SUBMISSION_INVALID')
        self.domains = {self.code('domain', v.key): v for v in values}; self.generation, self.rows = generation, None
        self.identities = {k: v for k, v in self.identities.items() if k in live_identities(values)}

    def _obstacles(self, values):
        bones = values[0].obstacles if values else ()
        return (abi.Obstacle*len(bones))(*(abi.Obstacle(pairs.pointer(b.vertices), pairs.pointer(b.faces),
            len(b.vertices), len(b.faces)) for b in bones))

    def _exclusions(self, domains, exclusions):
        keys = {(d.key.muscle, d.key.instance, d.key.side): self.code('domain', d.key) for d in domains}
        values = [keys[tuple(k)] for pair in exclusions if all(tuple(k) in keys for k in pair) for k in pair]
        return (C.c_uint64*len(values))(*values)

    def summary(self):
        result = super().summary(); self.orders = (abi.Order*len(self.rows))(); timings = (C.c_double*5)()
        if self.library.af_layer_summary(self.handle, self.generation, self.orders, len(self.orders), timings): raise RuntimeError('STACK_STALE_RESULT')
        self.outputs = (abi.Output*len(self.domains))()
        if self.library.af_stack_summary(self.handle, self.generation, self.outputs, len(self.outputs)): raise RuntimeError('STACK_STALE_RESULT')
        result['pairs'] = tuple(dict(pair, order=order_record(order, self.domains)) for pair, order in zip(result['pairs'], self.orders))
        result['timings'].update(zip(('ordering_ms', 'support_ms', 'stack_solve_ms', 'stack_validation_ms', 'stack_preparation_ms'), timings))
        result['timings'].update(order_storage_stats(self))
        records = tuple(output_record(row, self.domains, vector.metrics(self, row.id)) for row in self.outputs)
        result['stacking'] = dict(algorithm='vector-localized-v1', status='incomplete' if any(r['status'] in ('blocked', 'failed') for r in records) else 'complete', domains=records)
        relationships.enrich(self, result)
        return result

    def order_footprint(self, index, generation):
        if generation != self.generation or not 0 <= index < len(self.orders): raise ValueError('PAIR_STALE_RESULT')
        row = self.orders[index]; fragments, points = (pairs.Fragment*row.fragments)(), (pairs.Point*row.points)()
        status = self.library.af_layer_footprint(self.handle, generation, index, fragments, len(fragments), points, len(points))
        if status: raise ValueError('LAYER_FOOTPRINT_RESOURCE_LIMIT' if status == 3 else 'PAIR_STALE_RESULT')
        return dict(fragment_array=np.ctypeslib.as_array(fragments), point_array=np.ctypeslib.as_array(points))

    def surfaces(self):
        result = {}
        for row in self.outputs:
            values = np.empty((row.vertices, 3), dtype=float)
            if self.library.af_stack_output(self.handle, self.generation, row.id, pairs.pointer(values), len(values)): raise RuntimeError('STACK_STALE_RESULT')
            result[self.domains[row.id].key] = values
        return result

    def resolve_pair(self, first, second, exhaustive=False):
        result = abi.Order()
        status = self.library.af_layer_resolve_pair(self.handle, self.generation, self.code('domain', first),
            self.code('domain', second), int(exhaustive), C.byref(result))
        if status: raise ValueError('LAYER_QUERY_FAILED')
        return order_record(result, self.domains)


def owned_values(domains):
    from .obstacles import Obstacle
    from ..muscle_pairs.model import immutable
    values = tuple(domains)
    bones = tuple(Obstacle(immutable(b.vertices, float, (None, 3)), immutable(b.faces, 'int64', (None, 3))) for b in (values[0].obstacles if values else ()))
    return tuple(owned_domain(d, bones) for d in values)


def order_storage_stats(engine):
    values = (C.c_double * 5)()
    if engine.library.af_layer_storage_stats(engine.handle, engine.generation, values, 5): raise RuntimeError('STACK_STALE_RESULT')
    return dict(zip(('ordering_peak_working_bytes', 'ordering_summary_cache_bytes', 'ordering_result_bytes',
                     'ordering_computed', 'ordering_reused'), values))


def owned_domain(domain, bones):
    value = domain.material
    if value is None: raise ValueError('STACK_MATERIAL_MISSING')
    m = material(value.vertices, value.faces, value.interpolation, value.weights, value.fixed, value.constraints)
    if len(m.interpolation) != len(domain.base) or m.weights.shape != m.interpolation.shape: raise ValueError('STACK_MATERIAL_SIZE')
    return replace(owned(domain), material=m, output_indices=domain.output_indices, obstacles=bones, valid=domain.valid)
