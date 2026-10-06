"""Native multi-provider and serial-layer fixtures with actual Free attachments."""
from _helpers import root
from _stacking_fixture import muscle
from anthroforge.core.muscle_pairs import configuration


def fixture(kind):
    owner = root(); owner.af_pair_settings.automatic = False
    specs = [('Lower', (-1, 1), (-.65, .65), 0., .38),
             ('Middle', (-1.5, 1.5), (-1, 1), -.07, .10),
             ('Top', (-2, 2), (-1.3, 1.3), -.14, .08)]
    if kind == 'overlap':
        specs = [('Provider A', (-1.4, .5), (-.8, .8), 0., .40),
                 ('Provider B', (-.5, 1.4), (-.8, .8), -.025, .44),
                 ('Cover', (-2, 2), (-1.3, 1.3), -.10, .055)]
    muscles = [muscle(owner, *row) for row in specs]
    if kind == 'overlap':
        with configuration.transaction(owner, dict(groups={m.id: 'Sibling support' for m in muscles[:2]})): pass
    return owner, muscles


def bindings(owner):
    return [(f.id, f.a_parent_id, f.b_parent_id, f.a_attach_param, f.b_attach_param, f.behavior_mode)
            for f in owner.af_vcp_system.fibers]
