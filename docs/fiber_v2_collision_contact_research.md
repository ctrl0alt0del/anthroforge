# Fiber V2 collision/contact research

Date: 2026-08-26

## Decision in one paragraph

The current Fiber problem is not primarily a weak accelerator or an insufficient
iteration cap. It is a contact-discretization problem. V2 constrains a curve against
individual triangle features. Near feature changes, several locally valid contact
rows can create a resultant force or feasible cone with an artificial tangential
component. The optimizer then reaches a genuine stationary point of the discrete
problem, but that point is not the tight path on the intended anatomical surface.
The best-supported production direction is therefore a **smooth contact patch model
for optimization, combined with exact triangle collision for safety**. Geometric
Contact Potential (GCP) is the first implementation candidate; robust IMLS is the
strongest alternative. Direction-aware Planar-DAT is a complementary step safeguard,
not a replacement contact objective. More SQP, Anderson acceleration, raw IPC barriers,
or different scheduling cannot remove the wrong stationary point.

## Fiber problem being solved

For each hard-pin span, Fiber needs a deterministic static centerline that minimizes
length and the authored curvature regularizer while maintaining world-space clearance
from SCP collision surfaces. It must:

- allow deliberately intersecting DIRECT seeds;
- slide without friction along an obstacle while shortening;
- move contact entry and exit locations as part of the solve;
- preserve exact endpoint and midpoint positions;
- treat midpoints as hard rerouters where a kink is legal;
- remain collision-valid once feasibility has been reached;
- work on tessellated, transformed, deforming, open, and occasionally nonmanifold SCPs;
- produce nearly the same anatomical path after harmless remeshing;
- remain fast enough for live editing.

This is a constrained shape-optimization problem, not a dynamic contact simulation.
Simulation literature is useful only where its contact geometry and numerical methods
transfer to this static problem.

## Evidence from the current FIBER_2 trace

The full trace in `docs/fiber_v2_sqp_unevenness_diagnostic.md` establishes:

- the visible bump first appears in proposal 17 when collision constraints are injected;
- later structural proposals are much smoother, but point strongly into the obstacle;
- CCD allows only 0.27--0.37% of those proposed movements;
- two contacts act almost at the same shared node from its adjacent Fiber edges;
- their normals differ by 25.073 degrees;
- the final structural and contact gradient norms are 311.840 and 311.832;
- their cosine is -0.999999998;
- the normalized stationarity residual is `3.2115e-8`;
- increasing the cap from 60 to 240 produces point-identical geometry.

The structural-metric CCD experiment also changed 34 outer rejections to one without
changing the final turn (`22.70948` versus `22.70919` degrees). It reached the same
stationary point more efficiently.

The scientifically defensible interpretation is that the current optimizer is solving
its current discrete contact problem accurately. The contact problem itself does not
faithfully represent frictionless sliding on one continuous anatomical surface. A
controlled triangulation-invariance test is still required to prove how much of this
specific bump is faceting versus a real geometric ridge, but the measured mechanism is
the same one identified in the contact literature.

## Central result from the literature: no free slide

Du, Li, Coros, and Thomaszewski identify a fundamental limitation of contact on
piecewise-linear or other C0 surface discretizations. Selecting individual closest
features produces discontinuous normals. Summing per-primitive IPC potentials can also
produce artificial potential walls as a contact crosses triangle boundaries. The
result is a nonphysical tangential force in nominally frictionless contact. It can
change macroscopic results and prevent inverse-design problems from converging.

Their peer-reviewed 2024 method replaces the faceted contact representation with a C2
Implicit Moving Least Squares surface. The smooth normal field removes the force
irregularities and improves robustness and accuracy. The important lesson for Fiber is
not merely "smooth the final curve." The *collision gap and its derivatives* must be
smooth across the SCP triangles during optimization.

Sources:

- No Free Slide: https://arxiv.org/abs/2308.01696
- Peer-reviewed smooth-contact paper: https://doi.org/10.1111/cgf.15187
- Open paper record and PDF: https://diglib.eg.org/items/90f62ee5-d364-4e85-b235-70135718f6db

## Candidate methods

### 1. Geometric Contact Potential (GCP)

GCP derives a contact potential from the geometry of a smooth or piecewise-smooth
surface instead of summing every nearby primitive solely by Euclidean distance. Its
interaction set includes local-minimum and exterior-direction tests. Smooth directional
weights and distance mollifiers let one contact contribution fade while the correct
neighbor contribution becomes active. This is designed to eliminate spurious forces,
reduce resolution dependence, and permit a larger activation distance.

Why it fits Fiber:

- It directly targets the false-force mechanism seen in FIBER_2.
- It handles face, edge, and vertex features and piecewise-smooth triangle meshes.
- The discrete potential includes gradients and Hessians.
- It is a drop-in contact-potential replacement rather than a complete simulator.
- It has an MIT-licensed reference implementation in IPC Toolkit.
- IPC Toolkit 1.5+ contains the authors' GCP implementation; the separate GCP toolkit
  was archived after the implementation was merged.
- Current IPC Toolkit supports nonmanifold smooth edges and composable filters, both
  relevant to owner exemptions and imperfect SCP meshes.

Limitations for Fiber:

- GCP is a barrier formulation and normally expects a feasible starting state. DIRECT
  can be intersecting, so GCP cannot be the only infeasible-start mechanism.
- `SmoothCollisions` must be rebuilt as positions change because its interaction set
  depends on current distances, normals, and tangents.
- It supplies a potential, not a complete solver.
- It has parameters controlling directional support. Too-small support is less smooth
  and harder to optimize; too-large support costs more and can involve more features.
- Fiber is a moving 1D edge mesh against fixed triangle surfaces, so the exact
  codimensional integration and scaling must be verified rather than assumed.

Recommended role:

Use GCP or its interaction-set aggregation to define the feasible-state contact merit,
gradient, and positive-semidefinite Hessian contribution. Keep Fiber's structural
objective, hard-pin elimination, span model, and banded solve. Keep exact triangle CCD
and static validation as independent safety mechanisms.

Sources:

- Paper/project: https://huangzizhou.github.io/research/smooth-contact.html
- Official tutorial: https://ipctk.xyz/tutorials/gcp.html
- Current reference implementation: https://github.com/ipc-sim/ipc-toolkit
- Archived standalone implementation: https://github.com/geometryprocessing/GCP-toolkit

### 2. Robust Implicit Moving Least Squares (IMLS)

IMLS constructs a smooth implicit surface from position and normal samples. A local,
smoothly clamped weighting kernel produces a signed field and a smooth normal. Robust
IMLS reduces the influence of samples whose normals are inconsistent, which helps
preserve actual sharp features rather than blindly averaging through them.

Why it fits Fiber:

- It provides a signed gap inside and outside a closed oriented SCP, so the same
  filter-SQP/augmented-Lagrangian loop can start infeasible.
- It gives a single smooth contact normal across tessellation boundaries.
- The published method specifically demonstrates removal of artificial tangential
  contact forces and improved convergence.
- SCP topology is stable. Neighborhood/connectivity data can persist; transform-only
  updates transform samples and normals, while deformation updates sample positions and
  normals without rebuilding topology.
- Fiber only queries a narrow tube around a small curve, so a local IMLS evaluation is
  more plausible than a full scene grid.

Limitations for Fiber:

- Reliable signs need consistent orientation and are difficult for open or badly
  nonmanifold surfaces.
- Local support radius is a new scale-sensitive parameter.
- Smoothing can round intentional anatomical creases or thin features.
- The cited implementation is substantially more expensive per Newton iteration than
  raw IPC in some scenes, even when total convergence improves.
- IMLS collision/CCD is more involved than triangle CCD.

Recommended role:

Treat robust local IMLS as the strongest alternative and as the best candidate for the
infeasible-start signed constraint. Use it only for optimization guidance. Exact mesh
CCD and final validation still enforce the requested radius against the authored SCP.

Sources:

- https://doi.org/10.1111/cgf.15187
- https://arxiv.org/abs/2308.01696

### 3. Offset Geometric Contact (OGC)

OGC constructs an offset volume around the surface as a whole rather than capsule-like
offsets around every primitive. The resulting contact force is orthogonal to the
appropriate surface feature, and the model supports meaningful nonzero thickness for
codimensional objects. That maps directly to Fiber's `collision_radius`.

Why it fits Fiber:

- It is specifically designed for codimensional geometry and finite contact radius.
- It avoids the non-orthogonal resultant forces that can arise in per-primitive IPC.
- It uses local operations and per-vertex displacement bounds.
- IPC Toolkit 1.5+ provides a native implementation.

Limitations for Fiber:

- The original OGC trust region is isotropic: it restricts tangential and escaping
  motion as well as dangerous inward motion. The 2026 DAT paper demonstrates locking
  and artificial damping from this behavior in dense contact.
- OGC's penetration-free guarantee is naturally formulated from a valid state; it does
  not by itself solve an arbitrarily intersecting DIRECT seed.
- Its published speedups concern parallel dynamic simulation, especially GPU/VBD, not
  this CPU static centerline problem.

Recommended role:

OGC is a credible second GCP alternative, especially if exact offset semantics prove
more important than a continuously smooth implicit surface. It should be paired with
Planar-DAT, not its original isotropic filter.

Sources:

- Paper: https://doi.org/10.1145/3731205
- Author PDF: https://cemyuksel.com/research/papers/Offset_Geometric_Contact-SIGGRAPH2025.pdf
- IPC Toolkit implementation: https://github.com/ipc-sim/ipc-toolkit/releases

### 4. Planar Divide-and-Truncate (Planar-DAT)

DAT assigns collision primitives exclusive spatial regions and truncates proposed
movement to keep them in those regions. The Planar-DAT variant uses direction-aware
half-spaces. It limits motion toward an opposing surface but leaves tangential and
escaping motion substantially less restricted. The paper reports that this removes the
artificial damping and deadlock of isotropic bounds and preserves far more of the
intended displacement than a single global CCD fraction.

Why it fits Fiber:

- FIBER_2 repeatedly loses almost its entire global step because one pair limits it.
- Per-node or per-edge direction-aware bounds can preserve safe motion elsewhere.
- It is solver-agnostic and now exposed by IPC Toolkit 1.6 in C++ and Python.
- Its intent matches the required behavior: block inward motion without manufacturing
  friction in tangent directions.

Limitations for Fiber:

- It changes step acceptance, not the underlying contact energy. It cannot alone remove
  a false stationary point caused by conflicting per-triangle forces.
- Contacts outside the query radius fall back to conservative behavior.
- The current 2026 publication is new and its primary validation is physical simulation.
- Used as a separate repair pass it would violate Fiber's desired architecture. It must
  be the trust-region operation inside each solver iteration.

Recommended role:

Use it only after a smooth contact model exists, as the in-iteration feasible-step
safeguard replacing a global CCD fraction. Exact CCD can remain a final certificate or
fallback for uncertain pairs.

Sources:

- Paper: https://arxiv.org/abs/2604.15513
- Toolkit release/API summary: https://github.com/ipc-sim/ipc-toolkit/releases

### 5. CHOMP/covariant trajectory optimization

CHOMP combines a smoothness objective with a workspace obstacle functional and applies
the inverse smoothness metric to the obstacle gradient. A local obstacle signal is
therefore distributed smoothly over the entire trajectory. Its obstacle gradient is
projected relative to path velocity, and the objective is designed to be insensitive to
trajectory reparameterization.

Why it fits Fiber:

- It explains how to distribute a local contact correction without making a local kink.
- It starts from paths that can be in collision.
- Its natural-gradient metric resembles applying Fiber's structural inverse.

Why it is not the missing fix by itself:

- The structural-metric CCD experiment already distributed limiting constraints through
  the complete Fiber structural solve and reached the same bump.
- CHOMP still depends on the quality and differentiability of its signed distance field.
- A faceted or noisy field merely distributes a wrong gradient more coherently.

Recommended role:

Borrow its arc-length obstacle functional and reparameterization treatment only after
GCP or IMLS supplies a correct smooth contact field. Do not replace V2 with CHOMP.

Source:

- https://publications.ri.cmu.edu/storage/publications/pub_files/2013/5/CHOMP_IJRR.pdf

### 6. TrajOpt, SQP, active-set, and semismooth Newton methods

TrajOpt uses sequential convex optimization, hinge collision costs, penalty updates,
and continuous-time collision checks. Primal-dual active-set and semismooth Newton
methods solve unilateral contact as complementarity or variational-inequality systems.
These are sound optimizer families. V2's SQP, multiplier updates, active contacts, and
CCD injection already belong to this family.

What they can improve:

- superlinear local convergence after the correct contact manifold is known;
- truthful complementarity and KKT stopping criteria;
- handling of infeasible initial states through filter or elastic modes;
- dynamic trust radii and per-constraint step control.

What they cannot fix:

- a discontinuous or geometrically incorrect contact normal;
- duplicate adjacent-triangle forces that form a false equilibrium;
- an objective whose discrete stationary point is the visible bump.

Recommendation:

Retain SQP/filter logic as the outer optimizer. Change the contact representation before
revisiting acceleration.

Sources:

- TrajOpt: https://rll.berkeley.edu/~sachin/papers/Schulman-IJRR2014.pdf
- Semismooth Newton contact: https://www.jstage.jst.go.jp/article/jcst/3/1/3_1_54/_article

### 7. Mortar and segment-to-segment contact

Engineering contact literature identifies the same weakness in node-to-segment and
node-to-surface contact: nodes sliding from facet to facet see force jumps, poor
nonlinear convergence, and nonphysical oscillation. Mortar methods weakly integrate
contact over overlapping segments or patches rather than collocating independent hard
constraints at individual nodes.

Why it is relevant:

- Fiber is a 1D curve contacting a 2D surface, so a line-to-surface patch constraint is
  more faithful than unrelated node/edge rows.
- Integrating contact over a contiguous Fiber span can stop adjacent edges from pinching
  their shared node.

Why it is not the first implementation:

- Full mortar machinery is designed for two discretized continuum bodies.
- It requires contact-patch intersection, multiplier basis choices, and quadrature.
- GCP offers a more recent, already implemented geometric answer for codimensional mesh
  contact.

Recommendation:

Use mortar as design evidence for **patch aggregation**, not as the first codebase to
port. If GCP/IMLS still leaves sampling artifacts, a lightweight line-to-surface mortar
constraint is the next serious alternative.

Source:

- https://doi.org/10.1016/j.cma.2007.08.009

### 8. Ropelength and constrained curve tightening

Ridgerunner minimizes polygonal curve length while maintaining thickness constraints.
It finds active `struts` and `kinks`, projects the length gradient into the cone of
first-order thickness-preserving motions, and checks a KKT-style balance between length
forces and active constraints.

Why it is relevant:

- The mathematical target is close to Fiber: shortest thick centerline under
  inequality constraints.
- It distinguishes the true constrained length gradient from a generic smoothing force.
- It suggests monitoring active contact multipliers and projected length descent rather
  than movement alone.

Why it does not directly solve the SCP problem:

- Published Ridgerunner handles curve self-thickness/contact, not arbitrary external
  triangle obstacles and authored owner exemptions.
- Its active constraint gradients would still inherit faceted obstacle normals if
  ported naively.
- It is a first-order constrained descent, so live convergence is not automatically
  better than SQP.

Recommendation:

Borrow its projected-gradient/KKT validation and active-strut interpretation. Do not
replace the contact geometry or native banded SQP with Ridgerunner.

Source:

- https://arxiv.org/abs/1002.1723

### 9. Higher-order collision geometry

High-Order IPC represents the physical geometry with curved/high-order bases while
retaining a dense linear proxy for collision guarantees and mapping forces between
them. Higher-order geometry is less sensitive to mesh quality and locking artifacts.

Why it may help:

- A curved SCP contact representation is closer to the intended anatomical surface.
- It separates optimization geometry from the conservative collision proxy.

Why it is not the first choice:

- AnthroForge does not currently own a reliable high-order representation for every SCP.
- Fitting subdivision or polynomial patches introduces seam, feature, and deformation
  maintenance work.
- GCP and IMLS solve the immediate smooth-normal problem without converting every SCP.

Source:

- https://zferg.us/research/high-order-ipc/

### 10. Smooth SDFs and LogSumExp distances

Smooth signed-distance fields are widely used in robotics trajectory optimization.
Grid SDFs give cheap repeated queries, while IMLS, convolution fields, and LogSumExp
soft minima provide smoother derivatives than raw closest-triangle distance.

Useful properties:

- fast gap and gradient queries after precomputation;
- invalid-seed support through signed values;
- straightforward integration into filter-SQP.

Risks:

- trilinear grid interpolation does not by itself give a sufficiently smooth gradient;
- grids blur thin anatomy and require memory/rebuild policies;
- LogSumExp changes the true minimum distance and needs a conservative error correction;
- unsigned fields cannot decide how to escape an intersecting closed obstacle;
- any approximate field still needs exact triangle safety validation.

Recommendation:

Do not start with a global voxel SDF. A local robust IMLS field is better matched to
hierarchical deforming SCPs. A cached narrow-band cubic SDF remains a performance option
if IMLS queries prove too costly.

Sources:

- Smooth co-dimensional distances: https://www.dgp.toronto.edu/projects/smooth-distances/
- CHOMP signed-distance use: https://publications.ri.cmu.edu/storage/publications/pub_files/2013/5/CHOMP_IJRR.pdf

## Methods rejected as the primary answer

| Method | Reason it does not solve the observed failure |
|---|---|
| More iterations or a larger cap | The 60- and 240-step results are point-identical. |
| Anderson/L-BFGS acceleration | Reaches the same wrong stationary point faster and can amplify contact-set discontinuities. |
| Current structural-metric injection | Removes rejections but produced the same FIBER_2 geometry. |
| Raw IPC per-primitive barrier | The literature documents spurious tangential force and energy walls. |
| CCD alone | Certifies a trajectory; it does not supply the correct surface-following direction. |
| Isotropic displacement bounds | Restrict safe tangent motion and can deadlock. |
| Plain surface geodesic | Incorrectly constrains free portions of Fiber to the obstacle surface. |
| Global exact 3D shortest path | General 3D obstacle shortest paths are computationally hard and ignore authored routing semantics. |
| Planner-only correction | Planner is a seed; it cannot repair the solver's false contact equilibrium. |
| Curvature tuning | Changes how visible the bump is but does not remove the false contact force. |
| XPBD or rod dynamics | Adds time/inertia/compliance that the static centerline does not need. |
| Neural SDF | Difficult to update, qualify conservatively, package, and reproduce deterministically. |

## Recommended Fiber contact architecture

The recommended architecture keeps collision inside the core optimization while
separating the *differentiable model used to choose a path* from the *exact mechanism
used to certify safety*.

### Optimization contact layer

1. Query a local connected candidate patch on each relevant SCP.
2. Compute one smooth patch gap, normal, gradient, and PSD Hessian contribution.
3. Aggregate contacts that touch the same Fiber node from adjacent edges before
   assembly; do not give them independent tangential authority.
4. Use GCP interaction-set weights first. Evaluate robust IMLS as the competing model.
5. Assemble patch contact with length and curvature in the same native block-banded
   SQP/augmented-Lagrangian system.
6. Keep hard pins eliminated exactly and midpoint spans C0-coupled only at the pin.
7. Start an intersecting seed with the same smooth signed-gap constraints under the
   existing filter acceptance: maximum violation must decrease, then aggregate
   violation, then objective.
8. Once feasible, require accepted iterations to remain feasible.

This is not postprocessing. Collision gradients participate in every structural solve.
The infeasible and feasible cases are two merit regimes of the same optimizer, not a
separate push-out tool.

### Feasible-step layer

1. Apply per-node/per-edge Planar-DAT-style half-space limits to preserve tangential and
   outward motion.
2. Requery the smooth patch when a contact feature changes.
3. Use exact native CCD for uncertain or previously inactive pairs.
4. Do not scale the entire Fiber by the earliest unrelated collision when independent
   local bounds can certify more motion.

### Safety layer

1. Exact segment/triangle minimum distance uses the authored mesh and world radius.
2. Exact native CCD certifies every movement that could cross the mesh boundary.
3. Final validation is independent of the smooth optimization field.
4. A mismatch is an engine diagnostic and failed solve, never silent publication.

The smooth field is allowed to guide the optimizer toward the anatomically intended
surface. It is not allowed to redefine the final safety boundary.

## Why one aggregate contact patch matters

At the FIBER_2 bump, two adjacent Fiber edges apply contacts at factors almost one and
zero, effectively acting on the same shared node. Giving each feature an independent
multiplier lets the combination oppose both inward and useful tangential movement. A
contact patch instead represents the local obstacle as one surface neighborhood:

- the normal component enforces clearance;
- tangent components remain free in a frictionless solve;
- weights change smoothly as the closest location crosses a triangle edge;
- actual sharp features retain a cone of legitimate normals;
- duplicate coplanar triangles cannot multiply the contact strength;
- remeshing the same shape should not materially change the Fiber.

The distinction between a smooth patch and a true crease must come from SCP geometry,
not from triangle boundaries alone. Candidate rules can use dihedral angle, normal
clustering, authored sharp-edge metadata, and connectedness.

## Controlled qualification plan

### Test 1: free-slide falsification fixture

Create one geometrically flat plane with several triangulations: regular, alternating
diagonals, irregular, and a refined version. Place a Fiber segment at exactly the
activation distance and request pure tangent motion.

Measure:

- tangential contact gradient divided by normal gradient;
- movement preserved after the step filter;
- contact energy along a straight slide across triangle boundaries;
- variation between triangulations.

Expected correct result: essentially zero tangential contact force, no energy walls,
and triangulation-independent motion.

### Test 2: curved remeshing invariance

Use one analytic sphere/cylinder represented with coarse, fine, and irregular meshes.
Solve identical pinned Fibers and compare resampled world-space paths.

Gate:

- exact clearance passes for every mesh;
- remeshed path difference is at most `0.1 * collision_radius` away from genuine sharp
  features;
- path length differs by less than 1%;
- turn distribution changes smoothly with resolution.

### Test 3: true sharp feature

Use a box and a wedge with an authored sharp edge. The method must not average through
the solid corner. It must retain the correct feasible normal cone and clearance.

This distinguishes useful smoothing from unsafe geometric blurring.

### Test 4: invalid DIRECT seeds

Run a sphere, cube, thin blocker, two sequential blockers, containment, and an open mesh
from intersecting DIRECT seeds with planner calls disabled.

Gate:

- maximum violation decreases monotonically until feasible;
- no generic `collision-invalid` termination;
- once feasible, no accepted state becomes invalid;
- impossible topology or pins return a precise reason.

### Test 5: FIBER_2 mechanism

Record the same full trace for current contact, GCP-patch contact, and robust IMLS.

Compare:

- node-10 local turn and neighboring turn distribution;
- path length;
- structural, contact, and projected tangent gradients;
- contact normal change across iterations;
- number and identity of active patches versus raw primitive rows;
- KKT residual under the new model;
- exact clearance and final render from several angles.

Success is not just fewer rejections. The false opposing tangential component must
disappear, the bump must reduce materially, and the final exact validator must pass.

### Test 6: production files and performance

Run all selected non-blocking Fibers from `fiber_sphere.blend`, `skull_muscles.blend`,
`skull_muscles_skin.blend`, and `skeleton_comb_base.blend`.

Profile separately:

- candidate broad phase;
- patch construction;
- smooth gap/gradient/Hessian evaluation;
- native banded assembly/factor/solve;
- Planar-DAT filtering;
- exact CCD;
- static validation.

Only after shape correctness passes should the experiment be optimized or selected by a
dynamic performance rule.

## Proposed research sequence

### Phase A: prove the diagnosis

Add the planar free-slide and remeshing-invariance harnesses to the existing diagnostic
tools. Measure the current model before implementing a replacement. This should be a
small, decisive experiment.

### Phase B: compare two contact models

Implement two isolated native prototypes behind the existing experiment boundary:

1. GCP contact/derivatives from IPC Toolkit 1.6.
2. Local robust IMLS signed gap and derivatives.

Run both with the same Fiber SQP, structural weights, seeds, iteration budgets, and
exact safety backend. Do not tune the structural objective separately per method.

### Phase C: select by correctness

Prefer GCP if it removes the energy wall, passes invalid-seed integration through a
stable signed/filter formulation, and remains remeshing-invariant. Prefer IMLS if GCP's
piecewise model still locks or cannot support the infeasible-start contract. Consider a
hybrid only if the data establishes that IMLS is needed only until feasibility and GCP
is materially faster afterward.

### Phase D: add direction-aware step control

After the contact model produces the correct stationary path, compare global CCD
scaling with Planar-DAT plus exact certification. This targets iteration efficiency and
must not be confused with the shape fix.

### Phase E: production integration

Replace the raw per-primitive contact rows only after:

- the free-slide artifact is absent;
- remeshing invariance passes;
- true creases remain safe;
- invalid DIRECT seeds solve in the same core loop;
- all final results pass exact native validation;
- real-file renders are accepted;
- timings are measured under the same request-to-commit boundary.

## Current recommendation and confidence

1. **GCP patch contact + exact CCD/validation** — first prototype; highest implementation
   fit because a maintained native implementation and derivatives already exist.
2. **Robust local IMLS + exact CCD/validation** — strongest smooth-surface alternative
   and likely best invalid-seed field; greater implementation and sharp-feature risk.
3. **Planar-DAT in-step filter** — add after the contact model is correct to prevent one
   local pair from suppressing useful tangent movement.
4. **Lightweight line-to-surface mortar/contact-arc model** — fallback if GCP/IMLS still
   show sampling or patch-transition artifacts.

Confidence that the current bump cannot be fixed by more iterations or acceleration is
high. Confidence that a smooth contact representation addresses the measured mechanism
is high and directly supported by published controlled experiments. Confidence that GCP
rather than IMLS is the final production winner is moderate; the controlled Fiber tests
above are required because GCP's standard barrier assumes a feasible state while Fiber
explicitly permits an intersecting DIRECT seed.

## Primary references

- Du et al., *No Free Slide*: https://arxiv.org/abs/2308.01696
- Du et al., *Robust and Artefact-Free Deformable Contact*: https://doi.org/10.1111/cgf.15187
- Huang et al., *Geometric Contact Potential*: https://huangzizhou.github.io/research/smooth-contact.html
- IPC Toolkit GCP tutorial: https://ipctk.xyz/tutorials/gcp.html
- Chen et al., *Offset Geometric Contact*: https://doi.org/10.1145/3731205
- Chen et al., *Divide and Truncate*: https://arxiv.org/abs/2604.15513
- Li et al., *Incremental Potential Contact*: https://ipc-sim.github.io/
- Ferguson et al., *High-Order IPC*: https://zferg.us/research/high-order-ipc/
- Ratliff et al., *CHOMP*: https://publications.ri.cmu.edu/storage/publications/pub_files/2013/5/CHOMP_IJRR.pdf
- Schulman et al., *TrajOpt*: https://rll.berkeley.edu/~sachin/papers/Schulman-IJRR2014.pdf
- Puso et al., segment-to-segment mortar contact: https://doi.org/10.1016/j.cma.2007.08.009
- Ashton et al., constrained ropelength descent: https://arxiv.org/abs/1002.1723
