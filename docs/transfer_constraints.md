# Locally configurable transfer constraints

`anatomy.transfer_preview` accepts `shape_preservation.constraints` with version
`transfer_constraints.v1`. It uses the same preview, publication, journal and
stale-input checks as existing transfer. The required native export is
`af_transfer_constraints_fit`, packaged in `af_fiber_ccd_v3_19.dll`.
Restart Blender after updating a process that already loaded the previous DLL.

Legacy requests without `constraints` retain the previous native ABI and solve.
In explicit mode omit `protected_bands` and `attachment_bands` (an empty
`protected_bands` is also accepted). Mixing nonempty legacy bands with the list
is rejected. Only `max_iterations`, `cluster_radius_fraction` and `convergence`
are accepted in explicit-mode `settings`; forces come from the constraint list.

## Responsibilities

- The coordinator identifies anatomy, intended attachment areas and useful local
  domains, then chooses constraints using evidence and previous case experience.
- App-layer resolvers validate captured identities, indexed selections, qualified
  target regions and saved reference meshes. Resolution strategies are registered
  by type; they do not depend on the numerical implementation.
- The adapter packs resolved records, invokes one solve, and combines native
  constraint reports with independent final-surface checks.
- C++ computes geodesic influence, positional/shape/contact projections, iteration,
  residuals and coverage. Projection strategies share a small interface; the
  iteration loop does not implement individual anatomical constraint types.
- Python never runs an optimization loop or per-iteration callback. The existing
  separate legacy correction API is not invoked by this feature.

## Records and domains

Each item has `id`, `type`, `selection`, `enforcement`, and `tolerance`.
`enabled` defaults to true. IDs must be unique. Input order has no priority;
resolution sorts IDs deterministically and soft forces add within one solve.

`selection` contains the captured `source_object`, `topology_digest`,
`geometry_digest`, and either `vertex_indices` or `triangle_indices`.
Triangle selections expand to their vertices. Indices remain structurally usable
after a topology-preserving deformation, but the geometry digest must be refreshed
after reviewing the changed anatomical selection. Stale captures fail explicitly.

Soft records require a dimensionless `weight` from 0 to 1000. Optional `falloff`
is a distance in **source-world units**, default zero. Influence is one on the
selected vertices and decays with cubic smoothstep to zero over that distance
along source triangle edges. It never crosses between source objects or jumps
between disconnected components. Exact records do not accept falloff.

Zero weight and `enabled: false` remove that record's force. They do not subtract
another overlapping record's force. To weaken a guide locally, split its domain
into an outside selection and a local selection with different weights.
Disabled records still undergo identity and schema validation.

## Implemented types

| Type | Enforcement | Additional fields | Acceptance residual |
|---|---|---|---|
| `attachment` | `exact` | `target`, `mapping` or `target_bindings`, `coverage` | World distance from qualified target; coverage and collapsed target faces also checked |
| `protection` | `exact` | `reference` of kind `preview` | World distance from saved coordinates |
| `shape` | `soft` | `weight`, optional `falloff` | Maximum absolute incident-edge log strain relative to placed source |
| `guide` | `soft` | `weight`, `reference`, optional `falloff` | World distance from guide |
| `clearance` | `soft` | `weight`, `obstacle_instance_ids`, `clearance`, optional `falloff` | Maximum vertex gap deficit over selected obstacles |

Attachment targets reuse [explicit indexed bands](shape_preserving_transfer.md).
`mapping` uses explicit source/target bone frames and qualified nearest-region
projection. `target_bindings` supplies one indexed SCP binding per active source
vertex. Neither mapping infers the anatomical contact side.

A guide reference is `{"kind":"initial_field"}` or a saved preview reference:

```json
{
  "kind": "preview",
  "preview_id": "previous-preview-id",
  "geometry_digest": "digest-of-that-source-mesh-vertices-array"
}
```

Compute the digest with `core.authoring.codec.digest(mesh['vertices'])` on the
matching source object's mesh in the preview record. Source topology and geometry
must match. The immutable preview is resolved from the same authoring journal;
its digest is rechecked on request replay and publication. A protection record
cannot use the unsolved initial field as an approved snapshot.

Initial-field guides are explicitly reported as **not attachment-retargeted**.
Changing hard attachment targets does not silently regenerate that field. Select
a suitable saved guide or weaken/remove its attraction where it conflicts.
The initial skeletal field still establishes the source's initial uniform
similarity placement, even when no guide force is enabled.

Shape projection uses local rigid cluster matching within each source object.
It resists local strain; it does not enforce exact curvature, silhouette, bending
or volume. There are no fields claiming those unsupported capabilities.
All positional projection terms use the same reference-length normalization
(`rest_extent²`); the common factor cancels in their weighted update. Each vertex
has equal positional mass. Shape projections average overlapping clusters before
weighting. Reported edge strain is a diagnostic, not the displacement objective.

Clearance penalizes inside vertices and exterior vertices closer than the requested
gap. Exact vertices remain exact. A positive-gap requirement conflicting with an
exact target beyond the clearance record's tolerance fails before iteration,
identifying the involved IDs and packed vertex. Zero-gap residual penetration is
reported even on fixed vertices. Soft clearance is not a collision guarantee.

## Intended attachment coverage

Attachment `coverage` is required and independent of its active selection:

```json
{
  "intended": {"vertex_indices": [12, 13, 14, 15]},
  "axes": [[1, 0, 0], [0, 1, 0]],
  "stations": [10, 4],
  "minimum_fraction": 0.9
}
```

`intended` also accepts `triangle_indices` on the same captured source.
Active attachment vertices must be a subset. The two nonparallel axes define
longitudinal/transverse directions in source-world space. Stations are equal
intervals over the intended domain's projected extent (1–16 per axis).

Native reports include selected/intended vertex fraction, source lumped-area
fraction, and each occupied station's lumped-area fraction. Vertex area is one
third of each incident source triangle's area. Every occupied station and the
overall area fraction must meet the supplied threshold; empty bins are `-1`.
Thus retaining both ends cannot hide a missing middle interval. This audits the
declared **source sampling coverage**, not exact continuous target footprint area
or anatomical correctness. Do not reduce the intended selection to disguise a
failed active selection. Collapsed fully constrained target triangles are reported
separately and make the constraint unresolved.

## Example guide record

```json
{
  "version": "transfer_constraints.v1",
  "items": [{
    "id": "belly-guide", "type": "guide", "enabled": true,
    "selection": {
      "source_object": "Reference muscle",
      "topology_digest": "captured-topology",
      "geometry_digest": "captured-geometry",
      "vertex_indices": [20, 21, 22]
    },
    "enforcement": "soft", "weight": 0.2, "tolerance": 0.02,
    "falloff": 0.01, "reference": {"kind": "initial_field"}
  }]
}
```

Add an enabled exact attachment or protection selection for every selected source
object. This partial example alone is therefore insufficient for a complete solve.

## Feedback and validation

The preview stores the complete requested configuration and resolved-input digest.
Reports retain each ID, requested/intended/active indices, influence and residual
heatmaps indexed by local source vertex, movement from the initial field, targets,
coverage, reference provenance and any target-face collapse indices. Packed vertex
offsets locate native conflicts. Initial and final vertices are stored separately.
`enabled` is the requested flag; `active` also accounts for zero soft weight.

`TRANSFER_CONSTRAINT_UNSATISFIED` marks unresolved records. Hard conflicts reject
before solving; incompatible soft goals can reach the iteration limit or fail
their residual thresholds. A small iteration step is not evidence that constraints
or anatomy passed. Whole-surface triangle/collision review remains independent
of per-vertex constraints, and publication preserves unresolved review status.

The rejected FDI provides two regression checks: its shortened normal-filtered
index origin fails coverage despite zero active-pin error, while restoring every
proximity candidate reports collapsed target faces. Neither is accepted anatomy.
The new API exposes and checks these configurations; it does not automatically
choose a correct contact-side strip. Unit and Blender integration tests separately
exercise locality, zero guide weight, exact protection, conflicts, stale inputs,
order independence, publication and save/reload.
