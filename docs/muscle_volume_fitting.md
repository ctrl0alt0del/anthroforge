# Fitting anatomical volume after native base reconstruction

These are draft authoring practices, informed by reconstruction experiments.
They are not an anatomical accuracy guarantee or a new automatic fitter in the
addon. Executable experiments, case measurements and immutable evidence remain
in the external workflow artifact/knowledge store. Use the production
[reconstruction workflow](authoring_muscle_reconstruction.md) and
[inflation controls](section_profile.md) for native creation and publication.

## Simplified game-muscle target

The September 21, 2026 user correction sets the target as a designer-built,
low-complexity muscle approximation: preserve general silhouette, head arrangement,
belly position, broad volume distribution and meaningful attachment neighborhoods.
Do not reproduce small creases, bumps, serrations or incidental reference concavities,
even when those features are real anatomy. This takes precedence over earlier
case acceptance based on close surface residuals or preserving every concavity.

Design the retained underside as a few broad, smooth forms with sparse editable
controls. Simplify both borders and interior; smoothing borders alone is insufficient.
Fit Free paths as deliberate simple curves on that designed form rather than copying
every sample of a triangulated parameterization. Add a bend, control or fiber only
when it materially preserves the silhouette, broad sectional volume distribution,
head arrangement or an essential attachment/route. Reject unexplained alternating
bends even when distance, width and topology checks pass. Dense evaluation samples
may tessellate a simple curve; they must not become independent modeling detail.

Compare large-scale silhouettes, belly position, head proportions and broad section
width/depth/area before pointwise residuals. Retain raw anatomy for context, not as
an instruction to recover discarded detail during inflation. No universal spline
control count, triangle budget or proven simplification algorithm is established by
this correction. Final output tessellation and modeling-control complexity are
separate decisions. Existing accepted cases require reassessment under this target.

## Separate the decisions

Operationally there are three stages: transfer, combined simplified base/native
Free fibers, and inflation. Use `anatomy.smooth_base_preview` / `smooth_base_publish`
as described in [the combined API](smooth_native_base.md). The four checks below
remain separate evidence categories inside that workflow, not four independent
construction passes. A native reproduction failure is corrected inside stage two.

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
4. Reconstruct the reviewed underside directly through native Free paths. Keep
   physical endpoints on qualified zero-offset SCP bindings and preserve deliberate
   contact/junction binding contracts; unbound shape samples may lie off bone.
   Start sparse, fit actual boundaries and belly width, and measure the native
   loft. Do not route the reviewed shape through the solver or project every
   sample onto bone. The eight-routing-correction limit applies only when
   Controlled routing is explicitly chosen. Never relax anatomical tolerance to
   force an unresolved candidate through publication.

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
native loft and inflated output. Retain source anatomy, head identities,
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
| Selected underside is adequate, but native Free loft loses width or path | Free curve sampling/layout, ordering, shared junctions, qualified attachments or output-domain mapping. |
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

The reviewed underside now supplies native Free paths; see
[Free fibers](free_fibers.md). Reuse suitable accepted transfer/base checkpoints.
Check qualified SCP support at actual physical endpoints, contacts and shared
junctions. Suspended boundary and interior shape samples may lie off bone; do not
replace them with nearest-surface solver pins or move the target onto the SCP.
Retain explicit supported junction offsets and the declared output extent.
Old Controlled shortest-route failures remain mode-specific evidence.

Measure the **actual native loft after all resampling**, not just ideal source
curves. Inspect identical camera views and five interior cross-sections. Record
boundary placement, local width, orientation and separation from the reference
underside. A 15% width/depth discrepancy is a review trigger inherited from the
rebuild plan, not automatic acceptance or a universal biological tolerance.
Run the intended Free recomputation before freezing this fitting base: attachment
resolution and downstream rebuilding must finish without planner/solver calls.
Record native path/binding validity and observed collisions; solver convergence
is not applicable. If deformation or an explicit edit changes the path, regenerate
the loft and recheck or refit the thickness target. Use the current deformed
points when editing, not stale capture coordinates.

For branches, compare both raw assembled base and actual zero-depth connected
output. Connector evaluation can move the displayed surface with inflation
disabled. Treat that movement separately from inflation and do not certify only
the pre-connector grids. Bound redundant Free sample density by geometric error
and native allocation limits; union sampling can multiply surface size. Preserve
structural tags and remeasure after simplification.

Choose positional tolerances using local belly width and thickness, with a
separate policy for thin tendons. Overall muscle length or bounding-box diagonal
alone can conceal severe local narrowing despite a small normalized route error.
The production planner still accepts one scene-unit tolerance; station checks
are an additional review step, not an implemented per-station planner constraint.

For the current open loft modes, inflation leaves the perimeter fixed. A missing
boundary, collapsed width, wrong attachment or wrong base orientation returns to
base construction. Adding interior fibers only helps when the missing shape is
in the base. It does not automatically fix the height model.

Before accepting a thin-area omission, compare its width/thickness and section
area within the affected anatomical head or slip as well as across the whole
muscle. A small total-volume fraction can conceal a substantial portion of a
small head. The September 21 pectoral omission audit rejected such a crop before
native creation; its section-integrated estimates are diagnostic, not occupied
union volumes or universal thresholds.

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

A direction mode called Smooth is not evidence of a smooth inflated surface.
Compare actual sections, silhouettes and localized self-overlap extent after
fitting each direction. In the September 21 brachioradialis Free-fiber case,
Smooth and Local produced conspicuous loops while Section preserved the broad
body with only localized proximal rim overlap. The canonical lesson
`brachioradialis-inflation-direction-geometry-20260921` records the exact inputs;
this is a case result, not a rule to select Section for every muscle.

Keep the native base fixed while comparing the existing modes:

| Mode | First controls to fit | When to increase complexity |
|---|---|---|
| Control Point | Side, amplitude, control position, radius and direction depth | A bulge is misplaced, too concentrated or displaced tangentially. |
| Distributed | Side, amplitude, boundary strength/band and end taper | Broad thickness is present but its boundary transition is wrong. |
| Section Profile | Direction and four depths; begin with centered peaks and roundness 1 | Independent widthwise peak movement or section fullness materially improves the fit. |

Use the actual addon evaluator. For fixed Control Point settings, a unit-amplitude
evaluation permits a weighted least-squares amplitude estimate, followed by actual
evaluation. Distributed stabilization can be nonlinear: evaluate a bounded scalar
search instead of assuming amplitude scales the result linearly. Profile fitting
uses bounded depths, peaks and roundness with rebuilt native direction frames.
Freeze unidentifiable controls: a three-row grid has only one interior across
sample and cannot independently determine a peak location and roundness.

Control Point direction depth moves the displacement source behind its control;
it changes direction, not just magnitude. Diagnose a narrow but already deep
section before increasing amplitude. Prepared branch inflation derives each
part's effective side from assembly orientation and boundary ordering; a stored
per-part flip is not an independent side override. Evaluate the assembled output.

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

Faces wholly outside the retained half-space are discarded before triangulation;
folded construction geometry in an excluded extension cannot block the retained
muscle. Vertex references and part labels remain validated. Faces touching or
crossing the retained domain still require valid triangulation. A genuinely
nonplanar quad with a crossing 2D projection uses its fixed 0-2 diagonal; its
two triangles define the existing warped surface without moving any vertex.
Planar bowties still reject. Record local folds separately: triangulation does
not repair or certify the complete construction surface.
