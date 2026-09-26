# Configurable local transfer constraints

Design recorded September 25, 2026 from the user's requested division of work:
authoring provides configurable constraints and evidence; the AI selects their
anatomical scope and configuration using source geometry and practical experience.
The extension is implemented as `transfer_constraints.v1`; see
[the API contract](transfer_constraints.md) for exact fields, units and verified
behavior. This design is not a claim that the rejected FDI has been repaired.

## Existing capabilities and the missing extension

`anatomy.transfer_preview` already accepts indexed protected bands, explicit
region-bound attachment targets, obstacle instances and global shape settings.
`anatomy.transfer_correct_preview` separately supports localized repair, protected
bands and contact targets. Reuse their identities, region bindings, validation and
journal conventions. The new list unifies the five initial constraint families;
the legacy correction API remains a separate operation.

The legacy C++ shape fitter hard-codes the relationship between attachment
influence, RBF-guide weight and shape weight. Its local clusters do not enforce
whole-muscle silhouette or volume. Retargeting a fixed band leaves the movable
guide unchanged. These are concrete limitations of the current implementation.

The extension is an explicit versioned list of enabled constraints, compiled into
one native solve, with indexed local domains and per-constraint measurements.
"Dynamic" means add, remove, enable, disable or edit records between previews;
the optimizer must not autonomously delete or weaken required anatomical inputs.
List order must not act as a sequence of destructive geometry corrections.

## Constraint record

Each record has a stable ID, supported type, source selection, target/reference,
enabled state, enforcement semantics and acceptance tolerance. Soft terms also
have a dimensionless weight after documented unit/scale normalization. Optional
influence falloff uses mesh geodesic distance, with an explicit distance scale.
Zero weight must actually disable a soft term; no hidden minimum guide attraction.

Source selections use captured source object identity, topology/geometry digests,
vertex indices or indexed triangle patches. Target attachments use existing
indexed SCP regions and surface bindings. A selection must survive coordinate-only
changes structurally; changed geometry requires anatomical revalidation. Missing
indices, stale snapshots and unsupported constraint types fail explicitly.

Separate the intended anatomical attachment domain from any computational
subsampling. The latter cannot silently redefine or shorten the former.
Coverage checks examine area and longitudinal/transverse stations, not merely
the smallest and largest selected index or axis position. Their thresholds are
explicit case requirements, not invented universal anatomical constants.

## Initial constraint families

| Type | Local effect | Existing starting point / missing work |
| --- | --- | --- |
| Attachment | Keep a declared origin/insertion strip at qualified targets. | Existing explicit bands; add coverage requirements and per-constraint reporting. Point contact alone does not guarantee patch area or orientation. |
| Shape preservation | Resist strain of selected source tissue while permitting its pose to change. | Existing cluster fit; expose local weights. Do not label this exact curvature, silhouette or volume preservation. |
| Guide | Attract selected tissue toward an explicitly identified guide, or disable that influence. | Existing RBF term; separate its weight/domain from automatic attachment influence. Record whether the guide reflects updated attachment targets. |
| Clearance | Penalize penetration against selected SCPs over a declared tissue domain. | Existing native queries/penalty; expose local scope and weight, and verify actual triangles separately. Contact bands must not simultaneously require a positive gap. |
| Protection | Hold an approved selection at its saved coordinates during a local revision. | Existing fixed-mask behavior; expose a named reference snapshot and domain. |

Curvature/bending, sectional width/depth and volume constraints are possible later
types. They require explicit mathematical definitions and representative tests;
they must not be accepted as schema fields while secretly mapping to ordinary
cluster stiffness. Diagnostics for those quantities can precede optimization support.

## Enforcement and feedback

Only implemented exact positional constraints may be labeled hard. Weighted
clearance and shape terms are soft even when heavily weighted. Mandatory final
checks can reject a result without pretending that the solve guaranteed them.
Conflicting hard targets fail before fitting. Other unmet requirements remain
visible by constraint ID; do not claim automatic minimal-conflict identification.

Report requested versus active selection, coverage, target residuals, movement,
strain and collision measurements as applicable. Include vertex/face indices and
heatmap values locating the failure. Show source, initial guide, compiled targets
and final mesh separately. Report computational cost and stop reason independently
of anatomical acceptance. Keep filtering decisions and removed samples explicit.

The AI defines the anatomical domains, chooses supported constraints and weights,
reads their reports and inspects the shape. Save the configuration and outcome as
a versioned case. Generalize a lesson by the condition that made a choice useful,
including its failure limits; do not turn one muscle's weights into global defaults.

## FDI regression requirement

The rejected FDI's normal filter kept index-origin constraints only from 21.5% to
62.1% of the metacarpal landmark axis. It removed 20 lower candidates through
96.4%. Those vertices had gaps below 0.00000561 units when constrained in the
earlier diagnostic, versus 0.181–0.271 after removal. This is direct evidence of
missing attachment coverage, not proof that the existing lower targets form a
valid noncollapsed surface.

For the first case configuration, select the complete intended index-origin
strip from the source, preserve its coverage, qualify its target surface mapping,
apply shape preservation to the belly, and explicitly control guide attraction
near corrected attachments. Include relevant bone clearance. Do not automatically
project both sides of thin tissue or restore all proximity candidates as a claimed
repair. Validate the source contact side and target triangle span together.

Success requires both continuous intended attachment and acceptable broad shape.
Reintroducing collapsed triangles to close the gap fails, as does keeping a good
score by deleting the lower attachment. Local changes must leave distant approved
tissue stable within a declared tolerance. The existing rejected previews are
regression fixtures; they are not production-ready anatomical results.

## Implementation boundary

All new numerical fitting, constraint compilation involving optimization,
geodesic propagation, iterative queries and objective/residual calculations run
in C++ through the existing native build/load infrastructure. Python handles
Blender capture, schema validation, orchestration, serialization and publication.
Preserve legacy requests and their behavior; record the compiled configuration
and native method version in new receipts. No Python optimization fallback.

The architectural pattern is established in
[CGAL's ROI/control-vertex deformation](https://doc.cgal.org/latest/Surface_mesh_deformation/index.html)
and [ShapeOp's indexed weighted constraints](https://shapeop.org/ShapeOpDoc.0.1.0/class_shape_op_1_1_constraint.html).
These references support the design pattern, not an assertion that their algorithms
solve this project's FDI case. No dependency replacement is selected by this design.
