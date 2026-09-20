# Fitting anatomical volume after native base reconstruction

These are draft authoring practices, informed by reconstruction experiments.
They are not an anatomical accuracy guarantee or a new automatic fitter in the
addon. Executable experiments, case measurements and immutable evidence remain
in the external workflow artifact/knowledge store. Use the production
[reconstruction workflow](authoring_muscle_reconstruction.md) and
[inflation controls](section_profile.md) for native creation and publication.

## Separate the decisions

Keep four separately validated results: **transfer correspondence**, **underside
definition**, **native base reproduction**, and **inflation fit**. Native route
acceptance proves neither anatomical placement nor adequate muscle width. A fit
to a transferred reference cannot certify that the transfer itself is correct.

1. Validate the transferred volume against its bones and neighbors. Record source
   identity, laterality, units, landmarks, attachment bands, head identities and
   soft-tissue attachment proxies. Repair overlapping source solids first, then
   check closure and spatial defects. Preserve the original reference.
2. Select the **whole bone-facing underside**, including spans away from bone.
   Do not substitute contact faces, a flattened projection or the superficial
   skin. Produce a smooth anatomical approximation with intentionally designed
   borders, preserving broad belly width, attachment bands, heads and clefts.
   Extraction/projection artifacts are not constraints to reproduce. Inspect
   border and interior smoothness independently of residuals, topology and
   spatial checks; see the base preparation contract.
3. Give each chart four corners spanning the complete origin and insertion bands.
   A tiny neighborhood around a geometric extremum can collapse an attachment
   band. Declare heads and seams explicitly; a head ending at a common soft-tissue
   junction must not be independently extended to a convenient distal bone.
4. Reconstruct through native qualified SCP pins. In the current base workflow,
   authored points have zero offsets; dense curve samples are not authored pins.
   Start sparse, allow at most eight routing corrections per fiber, and reject a
   candidate whose surface-bound guides cannot reproduce the selected underside.
   Use that failure to revise its routes or earlier construction decisions. Do not
   increase the tolerance merely to turn unresolved anatomy into an accepted result.

User scope correction, September 20, 2026: define a retained anatomical extent
at the base stage and omit thin tendon-like extensions that do not contribute
useful inflated volume. Keep that extent as an explicit input to every later
stage. Do not spend repeated repairs on excluded tendrils or silently recreate
them in native output. Use source sections, relative area and head connectivity
to choose the cutoff; do not use a previous fitting mask as an anatomical crop.
Classify new cut edges as modeling boundaries. A material-domain crop applies
the same base-derived intersection weights to base and inflated geometry, so
it does not invent physical attachments or force a new zero-depth perimeter.
Keep original anatomy available and label measurements of the retained extent.

## Feedback across stages

User-directed workflow policy, September 19, 2026: a downstream failure must drive
repair of the responsible earlier decisions. Completion belongs to the final
muscle; intermediate success remains provisional. The agent-managed workflow is
installed through `anthroforge-muscle-reconstruction`, with versioned context,
handoff/feedback validation and local Chroma retrieval in
`tools/muscle_workflow/workflow.py`. Agents perform the diagnosis and repair;
this is not an autonomous numerical reconstruction controller.

Preserve versioned checkpoints for the transfer, selected/prepared underside,
native solved loft and inflated output. Retain source anatomy, head identities,
allowed indexed attachment regions, intended proportions and acceptance criteria
as independent evidence. A transfer may be corrected against that evidence; it
must not be distorted merely to make reconstruction easier. Changed targets need
independent revalidation, not a comparison of fit scores to different targets.

Each failed check should identify the affected head/patch/station, measured error,
supporting geometry/view, suspected cause, proposed repair, and expected observable
effect. Keep measured symptoms separate from causal hypotheses. Localize width,
depth, boundary, coverage, attachment and head/convergence errors separately;
one global distance score can conceal a missing head or collapsed belly.

| Evidence | First repair to test |
|---|---|
| Native underside and outline fit, but belly depth/profile does not | Inflation direction, settings or another supported mode. |
| Selected underside is adequate, but native solved loft loses width or route | Qualified pin placement, routing, ordering, shared junctions or fiber layout. |
| Selected underside itself omits a head, cuts the origin band or bridges a cleft | Underside selection, boundary roles and patch/branch decomposition. |
| Selected underside has unexplained kinks, jagged borders or interior ripples | Redesign smooth anatomical borders and fair or rebuild the base before making more fibers. |
| The transferred volume disagrees with independent skeletal correspondence | Transfer landmarks, local mapping or the transfer method. |

Use small controlled candidate changes to test attribution. For example, compare
the failed boundary on the selected underside and actual native loft, then move
the responsible pins within their allowed regions and regenerate. A diagnostic
fit on an ideal base can help isolate native reproduction loss, but cannot certify
that base as natively achievable. If adequate base and direction checks pass yet
supported inflation modes fail, investigate the representation rather than force
an unrelated upstream change. A stalled local fit is not proof of impossibility.

After a repair, invalidate and rebuild every affected downstream result, including
shared fibers/branches and neighboring transfers affected by a shared deformation
field. Keep unaffected work cached. Judge the complete regenerated muscle against
the same anatomical checks, independent samples and fixed views; an intermediate
score may worsen while the final result improves. Keep the best verified checkpoint
and roll back rejected candidates. Do not accept regressions in required anatomy
in exchange for a lower pooled error.

After 3–4 unsuccessful refinements, change the repair strategy or modeling method
rather than continue the same parameter tweaks. A numerical attempt budget bounds
that experiment; it does not complete the task. Record rejected hypotheses and
confirmed repairs with their input versions. Reuse successful decisions for similar
cases, while keeping single-case evidence distinct from a generally validated rule.

## Stage agents and practical-knowledge librarian

User-directed architecture, September 19, 2026; stage roles, a coordinator skill,
artifact helpers and local retrieval are now installed. Assign
transfer, whole-underside preparation, native-fiber reconstruction and inflation
to agents with separate working contexts. Each receives the shared anatomical
target and constraints, its complete maintained stage procedure, versioned inputs,
and relevant case evidence. The coordinator owns dependency invalidation, scheduling,
the best verified checkpoint, and final anatomical/mechanical review. Stage success
does not complete the whole muscle. Agent roles do not require simultaneous scene
writes: work in isolated candidates and publish accepted changes through authoring.

Every stage agent must both produce and receive repair feedback. A feedback record
contains the exact input/output revisions, affected muscle/head/patch, expected
versus observed result, measurements and view/geometry references, suspected cause
separate from observation, requested correction or diagnostic experiment, preserved
constraints, and the downstream check that will resolve it. A repair response names
the actual changes and new evidence; the coordinator reruns affected dependents.
Unsupported causal claims return for inspection rather than becoming accepted facts.

The librarian owns practical-knowledge retrieval and curation, and independently
inspects cases to discover applicable lessons. A worker can ask a specific question
or send the original anatomical muscle as a versioned mesh/scene asset without
first diagnosing its problem. Include source bone context and anatomical labels
where available, target SCP/discovery references, the current stage, and any current
transfer/base/native output. The original muscle alone does not establish its
correspondence to a different target skeleton.

The librarian uses geometry queries, calibrated views and sections to assess
width/depth profiles, heads/clefts, attachment transitions, wrapping and thin
continuations. It records observed features separately from inferred anatomy,
retrieves candidate lessons/examples, checks their applicability and version, and
returns a compact brief: observed features with evidence, relevant lessons with
reasons and limits, per-stage actions/checks, and unresolved questions. Geometry
remains in the artifact store; a semantic index such as Chroma indexes descriptions
and metadata rather than being expected to interpret raw Blender meshes.

Known stage procedures are supplied automatically before shape-specific retrieval;
the agent need not recognize a belly to receive its width-preservation check.
Request a librarian assessment before construction, at materially changed stage
inputs, and when diagnosis needs more experience. Reuse analysis only for matching
input versions. The librarian receives before/after evidence from repairs and
curates lessons as hypotheses, case-verified practices or superseded entries.
Promote reliable measurable practices into initial planning and executable checks;
a worker's assertion of success alone is insufficient. Persistent evidence and
knowledge revisions outlive the librarian's conversation context. This architecture
supports focused inspection; it does not itself certify recognition or anatomy.

## Check the base before fitting depth

Before selecting longitudinal boundary fibers, measure suspended boundary extrema
and proposed shared seams against qualified surfaces of the allowed SCPs. A guide
whose target lies away from every allowed SCP cannot be reproduced by simply
placing another zero-offset pin there. This is a layout feasibility check, not
proof that every native decomposition fails.
Compare a different supported layout or explicitly permitted normal offsets;
preserve the original underside and record any changed approximation contract.

Measure the **actual native loft after all resampling**, not just ideal source
curves. Inspect identical camera views and five interior cross-sections. Record
boundary placement, local width, orientation and separation from the reference
underside. A 15% width/depth discrepancy is a review trigger inherited from the
rebuild plan, not automatic acceptance or a universal biological tolerance.
Run the intended native recomputation before freezing this fitting base. Record
route acceptance separately from solver convergence. If a later recomputation
changes the routes, regenerate the loft and recheck or refit the thickness target.

Choose positional tolerances using local belly width and thickness, with a
separate policy for thin tendons. Overall muscle length or bounding-box diagonal
alone can conceal severe local narrowing despite a small normalized route error.
The production planner still accepts one scene-unit tolerance; station checks
are an additional review step, not an implemented per-station planner constraint.

For the current open loft modes, inflation leaves the perimeter fixed. A missing
boundary, collapsed width, wrong attachment or wrong base orientation returns to
base construction. Adding interior fibers only helps when the missing shape is
in the base. It does not automatically fix the height model.

## Derive and fit a thickness target

For each native base sample, ray-cast through the repaired volume in a candidate
outward direction. Record both intersections and their orientation. Keep the
signed gap to the deep intersection separately from the desired displacement to
the superficial intersection. This is whole-underside thickness, not half-depth.
Missing intersections, multiple volume intervals, negative outward displacement,
or a large deep gap are correspondence problems; do not interpolate across them
and silently count them as successful fits.

Use anatomical bone context to establish the side. Then compare Local, Smooth and
Section directions where supported. Swap Side is a geometric choice that must be
rechecked when direction or chart ordering changes. A globally reversed side
does not repair an incoherent or folded chart.

Keep the native base fixed while comparing the existing modes:

| Mode | First controls to fit | When to increase complexity |
|---|---|---|
| Control Point | Side, amplitude, control position and radius | A localized bulge is misplaced or too concentrated. |
| Distributed | Side, amplitude, boundary strength/band and end taper | Broad thickness is present but its boundary transition is wrong. |
| Section Profile | Direction and four depths; begin with centered peaks and roundness 1 | Independent widthwise peak movement or section fullness materially improves the fit. |

Use the actual addon evaluator. For fixed Control Point settings, a unit-amplitude
evaluation permits a weighted least-squares amplitude estimate, followed by actual
evaluation. Distributed stabilization can be nonlinear: evaluate a bounded scalar
search instead of assuming amplitude scales the result linearly. Profile fitting
uses bounded depths, peaks and roundness with rebuilt native direction frames.
Freeze unidentifiable controls: a three-row grid has only one interior across
sample and cannot independently determine a peak location and roundness.

Fit with area weights and bounded evaluation counts. Reserve samples for checking
the fit, then compare against independent samples of the entire reference and
candidate in both directions. Report unsupported area alongside supported error.
Selecting a mode on those check samples makes them model-selection evidence;
they are not an untouched final test set. Keep the simpler mode when a more
flexible one offers no visible or meaningful geometric improvement.

## Acceptance and stopping

- Review five section widths/depths, fixed views, taper, all heads, attachment
  neighborhoods and neighbors. Numerical improvement cannot override an obvious
  misplaced or narrow muscle.
- Treat repeated parameter-bound hits and error concentrated on unsupported rays
  as prompts to inspect the base and direction. Do not keep adding coefficients.
- Distinguish unsigned surface distance, section dimensions, actual volume match,
  and collision checks. None is interchangeable with the others.
- Save fitted settings, target/base fingerprints, counts, approximation notes and
  rejected configurations. Reopen normally and compare persisted parameters and
  regenerated geometry. Export with `StaticScene.save_debug_copy`; all source and
  mirrored fibers stay visible as normal curves, with native SCP colors.

Section Profile currently supports ordinary open lofts only. Native branches
remain on Control Point or Distributed; fitting branch roots requires a separate
seam contract. A successful fitting experiment on one muscle does not establish
a general multihead reconstruction method or justify an automatic whole-body run.

### Material output domains

Native muscles can retain a plane-bounded modeled extent without moving physical attachments or changing their complete construction fiber graph. `muscles.domain_inspect` returns the current domain and base revision. `muscles.domain_configure` uses the usual live scene and base revision guards and either `{"mode":"full"}` or `{"mode":"plane","space":"root_local","origin":[0,0,0],"normal":[0,0,1],"keep_positive":true}`. The cut is a modeling boundary, not an anatomical attachment. The muscle panel exposes the same persisted settings.

The domain classifies the evaluated base after native inflation and complete branch connector evaluation. The same intersection weights interpolate base and inflated coordinates, so no new boundary taper or artificial pinch is introduced. The inflated cut can depart from the geometric plane because it follows the same material as the base. Source fibers and branch roots remain complete and visible; full FiberSurface objects are construction geometry and can be hidden independently in a final presentation. Both published muscle meshes and their derived mirrors contain only the retained extent. Mirrors reflect the already cropped source, and the source plane follows avatar root motion using inverse-transpose normal transformation.

Cropped numeric results contain triangle faces, `source_faces` indexing the original evaluated polygons, and `face_parts` (0 main, 1 onward child order). Their row/column counts are zero because output no longer forms a rectangular grid; requests retain the complete original grids and inflation settings. Profile inspection revisions, previews and receipt postconditions include the domain. Historical untrimmed version 1/2 profile receipts remain compatible. An empty cut is rejected by the guarded authoring configuration.
