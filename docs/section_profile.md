# Section Profile controls and native authoring

Section Profile is an opt-in inflation mode for ordinary open LOFT surfaces and
open legacy fiber muscles. Create a muscle from a Fiber Surface, then choose
**Inflation Mode → Section Profile** in its edit panel. The first activation
initializes four depths from the stored legacy amount as `[0.5, 1, 1, 0.5] × amount`.
Returning to a previous mode preserves both sets of controls. Direct RNA enum
assignment does not initialize a profile.

Depths at 20%, 40%, 60%, and 80% are absolute world-scene distances, each in
`[0, 10]`. Peaks in `[0.1, 0.9]` move the belly across the ordered chart, with `0.5`
centered. Roundness in `[0.25, 4]` changes shoulder fullness: `1` is parabolic.
Local uses coherent local normals; Smooth filters them in chart coordinates;
Section shares an area-weighted direction across each section. **Swap Side** changes
the muscle's displacement sign without changing its source surface winding.
**Scale Depths** rejects overflow; **Reset Profile…** shows the replacement peak
depth before applying it. These actions support ordinary Blender undo and redo.

Start/End follow prepared fiber point order. First/Last labels identify the actual
outer source or mirrored rows; they do not imply anatomical origin/insertion.
The panel displays the root's physical unit reference. Profile values are stored
at RNA float32 precision. Disabled or zero-depth profiles preserve the exact
prepared base; the outer perimeter always stays fixed.

Closed axes, LOOP_PATCH, and branched charts are unsupported. Missing/stale native
fiber output reports `PROFILE_BASE_NOT_CURRENT`: update the source fibers first.
Invalid parameters clear the target output and remain inspectable. A future
profile version is preserved until an explicit reset. Profile editing never
solves fibers, changes their hard-point counts, or fits anatomical thickness.

Branched main and child parts keep Control Point and Distributed inflation.
Their mode menu edits the selected part and disables Section Profile. Switch an
ordinary profile to a legacy mode before adding a branch. Directly assigning
Section Profile to either part reports `PROFILE_DOMAIN_UNSUPPORTED` and clears
only that muscle's invalid output; it never uses Control Point as a fallback.

## Protocol 0.4

`anatomy.discover` advertises `section_profile.v1` and `muscle_from_surface.v1`.
Use `anthroforge.app.authoring.api.execute(request, root, scene, journal_directory)`
in the addon runtime. All requests use a unique root-scoped `request_id`.

| Operation | Required parameters beyond `scene_id` |
| --- | --- |
| `muscles.profile_inspect` | `target` containing exactly one `muscle_id` or `fiber_surface_id` |
| `muscles.profile_preview` | `target`, complete `configuration`, both revision guards; optional `include_geometry` |
| `muscles.profile_configure` | `muscle_id`, complete `configuration`, both revision guards |
| `muscles.create_from_surface` | `surface_id`, both revision guards; optional `name`, `initial_configuration` |

Inspect returns the live `scene_revision`, and an entity with `base_revision`,
eligibility, reasons, ordered row provenance, current configuration, profile state,
initialization proposal and ownership. Preview validates the same capture and
evaluator as publication, optionally returning a geometry asset without scene
mutation. Its `numeric_ms` excludes capture, publication and other request costs;
`cost.total_ms` measures service work through response construction. Time the API
call separately for its full validation, journal and warning overhead. No viewport
latency guarantee is implied.

This example runs in Blender with AnthroForge registered and an existing current
open `SURFACE_1`. It inspects, previews and creates one muscle:

```python
from uuid import uuid4
from anthroforge.app.authoring.api import execute
import bpy

root, scene = bpy.data.objects['AF_ROOT'], bpy.context.scene
journal = 'E:/development/WIP_models/profile_example_journal'
envelope = dict(dsl='anthroforge.authoring.protocol', version='0.4.0', message_type='request')

def send(op, **params):
    request = dict(envelope, request_id=str(uuid4()), op='muscles.' + op,
                   params=dict(scene_id=root.name, **params))
    return execute(request, root, scene, journal)

state = send('profile_inspect', target=dict(fiber_surface_id='SURFACE_1'))
guards = dict(expected_scene_revision=state['scene_revision'],
              expected_base_revision=state['entities'][0]['base_revision'])
profile = dict(mode='section_profile', profile_version=1, enabled=True,
    flip_normals=False, depths=[dict(value=v, unit='scene') for v in (.02, .04, .04, .02)],
    peaks=[.5, .5, .5, .5], roundness=1, direction='smooth')
preview = send('profile_preview', target=dict(fiber_surface_id='SURFACE_1'),
               configuration=profile, include_geometry=True, **guards)
created = send('create_from_surface', surface_id='SURFACE_1', name='Profile example',
               initial_configuration=profile, **guards)
```

Check `status == 'success'` and `eligible` before dependent actions. For configure,
inspect the returned muscle ID for fresh guards, then send the same complete
profile with `muscle_id`. A configuration may instead be exactly
`{"mode": "control_point"}` or `{"mode": "distributed"}` to restore saved legacy
values. Omitting creation's initial configuration selects the existing default
Control Point behavior. Unknown/partial fields and non-scene native depth units
are rejected. Creation accepts only a complete Section Profile as its explicit
initial configuration.

Current branched muscles can be inspected and switched between their stored main
legacy modes through these revision guards. Edit child settings through
`muscles.branch_configure`; Section Profile remains unsupported on every part.
Profile, branch, shared-point and recompute commands share the root-scoped request
ID namespace. Native branch/recompute retries still run their live receipt or
progress checks.

Retries reuse the **identical entire request**, including its ID. Do not mint a new
ID to retry an uncertain creation. Configure receipts recheck live profile,
shared-side/enabled state, source, base and marker; manual edits or undo return
`STALE_PROFILE_RECEIPT`. Creation receipts return the same existing muscle after
later legitimate profile edits. Deleted/undone creation or a changed base returns
`STALE_CREATION_RECEIPT`, without recreating it. Reusing an ID for different content
or another operation returns `REQUEST_ID_REUSED`. Valid saved native markers can
recover missing journal entries. Publication and journal persistence roll back
together on failure. Keep the journal with the corresponding `.blend`.

Base revisions hash the actual prepared geometry and ordered chart, excluding
profile parameters. They deliberately do not round away source changes. An
unchanged file with stable source output replays after reopening; recomputed source
geometry, including a floating-point change, requires a fresh inspection/request.
Package/VCP import remaps source IDs and copies independent profile vectors without
carrying request receipts or creation tokens. `apply_scalar_dict(...,
geometry_scale=factor)` validates and scales depths before writing any RNA value.

## Authored documents and review

In a 0.4 `shape_presets` entry, `native` accepts the same Section Profile fields plus
the existing `applies_to`, `calibration`, `shape_checks` and `evidence` metadata.
Authored depth quantities use the existing length measurement resolver. Legacy
amount/radius/boundary fields cannot coexist with this alternative.
`shape_intent.height_scale` scales all depths; width, belly-position and taper
intents report `PROFILE_INTENT_UNSUPPORTED`. Enabled fitting reports
`PROFILE_FITTING_UNSUPPORTED`.

The shared 0.3 volume schema also contains this alternative because 0.4 documents
lower through the existing 0.3 native intermediate representation. The four new
native operations are exposed only by protocol 0.4.

A native profile edit on a document-owned muscle leaves its stored ownership
fingerprint intact. Use explicit `anatomy.reconcile` with `mode='adopt'` to create a
complete authored Section Profile before regenerating. Muscle creation from an
existing base does not alter source records or the base plan's fingerprint.
When changing an authored Section Profile back to legacy controls, first choose a
legacy authored preset: its boundary/control correspondence has no unique inverse
from the Section Profile shape and adoption reports `INVERSE_MAPPING_UNAVAILABLE`.

Save review artifacts with `StaticScene.save_debug_copy`, reopen using the same
profile-capable addon, and inspect multiple views. Current source and mirrored
fibers stay visible as normal curves; SCPs retain native Solid/Object colors.
Mathematical validity does not certify collision clearance, correspondence,
anatomical fit or conservation of volume.
