# Soft Tissue VCP

Status: production implementation for Blender 5.0.

Soft Tissue is a first-class VCP for one-off static construction:

`base object → inflated rest shape → optional static relaxation → final mesh cache`

It does not install timeline handlers, animation dynamics, or a real-time tissue
simulation. Automatic recompute is a debounced rerun of this static pipeline.

## Shipped contract

Evaluation is selected by the base domain, never by anatomy or preset name.

| Domain | Source | Construction |
| --- | --- | --- |
| `POINT` | Empty | Legacy-compatible radial sphere/ellipsoid |
| `CURVE` | One Curve spline or one Fiber | Closed profile sweep; open and cyclic sources |
| `SURFACE` | One connected manifold Mesh or Fiber Surface | Painted/boundary-weighted normal inflation and backing shell |

`CLOSED_BULK`, `RIM`, `LAYER`, and `POUCH` assign defaults only. `CUSTOM`
exposes the same compatible fields without an anatomical evaluator branch.

The persistent record contains the base reference, construction parameters,
surface-target identity and topology signature, versioned base/control bindings, attachment
rows, and solver controls. Rest and final meshes are derived caches. User-owned
Curve and Mesh bases remain visible in the hierarchy; Point bases created by the
add-on are owned controls.

## Inflation and relaxation

- Point uses radial inflation and the Blob icosphere. Its legacy-compatible geometric
  iterations, nearest queries, and segment clamps run in C++.
- Curve uses profile width, depth, power, segments, and endpoint taper. Its rest
  shape is unsagged; geometric relaxation moves only the free bulge.
- Surface uses minimum/maximum thickness, a power curve, and
  `AF_ST_INFLATION`. If that group is absent, an open surface receives normalized
  shortest-edge distance from its boundary; a closed surface receives weight 1.
  An existing group, including an all-zero group, is authoritative. Evaluation
  never creates a default group on the artist's source.
- A boundary-only Surface base, including a single Plane, is deterministically
  refined in the evaluated sample using Base Resolution. The artist's source
  mesh remains unchanged while the generated tissue gains free interior vertices.
- Relaxation modes are `NONE`, `GEOMETRIC`, and `STATIC_PBD`. Surface Static PBD
  treats the host-sealed shell as a flexible envelope containing retained volume.
  Inflation supplies the target volume but is not preserved as the final profile.
- Volume growth and gravity are solved together. Stretch is resisted, compression
  can redistribute material toward gravity, surface tension rounds the envelope,
  and the backing and fixed rim remain exact. A gravity-support inequality prevents
  tangential pouches from expanding above their unsagged surface while allowing
  normal inflation on upward-facing bases.
- Static load scales with tissue thickness relative to the unchanged base, so
  larger Amount values naturally sag more instead of receiving the same tip offset.
- Pouch calibration preserves the accepted mapping: sagginess `0.58` maps to a
  gravity step of `0.0015`.

Shape retention controls tensile edge memory and envelope surface tension. It
changes how load is distributed but remains distinct from Sagginess. Volume
retention drives the watertight volume constraint. Pouch fixes `BOUNDARY` and
`BACKING`; additional soft suspension masks are authored explicitly. The
convergence threshold is capped relative to the gravity step so an oversized
tolerance cannot cancel relaxation. Preset numbers are artistic defaults rather
than biological constants. Layer's Geometric mode maps sagginess directly to a
visible rest-scale displacement.

## Surface attachment

One tissue can target `SCP_GEOMETRY`, `MUSCLE_BASE`, or `MUSCLE_INFL`; Muscle
INFL is the normal default and roles never silently fall back. Raw base controls
and deterministic evaluated samples are captured as triangle/barycentric bindings
with signed surface-frame offsets. On target deformation, existing bindings
resolve without selecting new triangles; the
resolved positions are written back to the original base under an update guard,
then rest and final meshes rebuild.

Bézier control points are bound individually. Left/right handle vectors are
stored in the captured surface frame so host rotation does not collapse the
handles onto the surface. NURBS uses Blender's evaluated unbeveled centerline,
including rational weights, order, and cyclic closure. Temporary evaluation data
is discarded without changing the source. Surface inflation normals come from
resolved base geometry before publication, so the first host rotation is current.

Attachment masks can be `ALL`, `BACKING`, `BOUNDARY`, `ENDPOINTS`,
`SUSPENSION`, or a custom Mesh vertex group mapped to generated front/back
vertices. Rows can be added, removed, and assigned masks through the mask picker.
`FIXED` cores reach their resolved goals, with feathered exterior vertices treated
as Soft. `SOFT` strength multiplies continuous painted influence and feathers;
zero strength is inactive. Captured region offsets preserve the reference shape
in the target frame; live Normal Offset moves its goal along the current normal.
Soft constraints are point tethers to that goal, not changing rest-length tethers.
Geometric mode blends directly toward Soft goals and applies Fixed goals last.
Contradictory Fixed goals are errors. With no target, Fixed masks retain rest
positions and target offsets/tethers are inactive.

Surface Static PBD always pins its structural backing. Backing-only controls are
disabled and broader masks explicitly retain their pinned backing vertices.
`NONE` is inflation-only; unsupported solver/material controls are hidden.

If target topology changes, the last valid final mesh is retained and the VCP
enters `ERROR` until explicit Rebind. Missing base or target objects behave the
same way. A guarded target-driven base rewrite is not treated as an artist edit;
an artist edit schedules one coalesced recapture.

Schema-1 SCP identities are accepted by the common target adapter. Schema-2 bindings include target type, entity ID,
surface role, exact evaluated triangle topology, and rest topology. Constraint
mode, strength, and normal offset remain live settings and do not require recapture.

Evaluation revision 1 is assigned explicitly to newly created tissues. Missing
revisions are legacy: load, dependency updates, and import retain their cached
appearance and show **Upgrade required: Recompute or Rebind**. A forced automatic
sync is not upgrade authorization. Explicit Recompute upgrades only when stored
target topology still matches; changed topology requires Rebind. Both import
paths preserve and remap legacy caches. Failed evaluation/publication restores
the previous caches, source pose, bindings, and evaluation revision together.

## Fiber Surface sources

Fiber Surface is a persistent construction entity between Fiber and its tissue
consumers. `LOFT` evaluates two or more compatible OPEN Fibers or two or more
compatible LOOP Fibers; one mirrorable OPEN Fiber may expand into mirrored rows.
`LOOP_PATCH` fills one literal LOOP Fiber using deterministic best-fit-plane
projection, constrained triangulation, subdivision, and fixed-boundary fairing.

Fiber Surface owns row order, cross-row closure, mirrored-row expansion, normal
orientation, and patch resolution. It owns no inflation, tissue material, or SCP
attachment. Its locked Mesh proxy is a derived cache and is never persisted as a
source object reference.

New Muscles store only `fiber_surface_id` and inflation controls. Legacy Muscles
remain readable through `LEGACY_FIBERS`; manual conversion commits only after
topology, winding, and world geometry match within `2e-6`. A Fiber or Fiber
Surface can feed multiple Muscles and Soft Tissues without ownership transfer.
Deleting a referenced source is blocked until its consumers are removed.

Soft Tissue records use `OBJECT`, `FIBER`, or `FIBER_SURFACE` source identity.
Derived sources are sampled from evaluated geometry and are never rewritten by
the surface-target recapture path.

## Runtime and integration

The dependency graph contains `SCP → Fiber → Fiber Surface → Muscle`,
independent `Fiber/Fiber Surface → Soft Tissue` source edges, and
`SCP/Muscle → Soft Tissue` attachment edges. Property/base edits schedule
coalesced `SOFT_TISSUE_UPDATE` work on Blender's main thread. Manual mode remains
`DIRTY` until Recompute. Final proxies are transform-locked caches; deleting one
causes recreation on sync. Explicit VCP deletion removes both caches and an
owned Point control while preserving user Curve/Mesh bases.

Soft Tissue participates in the VCP tree, selection, shortcuts, mirrors, Draft
Skin capture, full-package import, and VCP-only import. Mirrors copy only the
solved cache according to the attachment target's effective mirror rule.

Legacy Blob remains readable/editable. Add Blob is hidden from normal creation.
Manual conversion accepts centered sphere/ellipsoid Blobs with `NONE` or `SCP`
targets, builds a Closed Bulk candidate, and removes the Blob only after topology,
vertex (`≤2e-6`), and volume (`≤1e-6`) equivalence checks pass.

## Native solver and diagnostics

The existing `af_fiber_ccd_v3_32.dll` exposes tissue interface version 1 and
capability bit `536870912`. Envelope, generic static, and Point geometric
iterations are batched native calls. A missing/incompatible library is an error;
there is no Python optimization fallback. Build with
`native/fiber_ccd/build_windows.ps1`. Frozen Python envelope code lives only in
the test tree for migration comparisons.

Shell walls follow directed face boundaries; backing faces reverse the source
winding. Inconsistent/nonmanifold face winding is rejected. Signed volume uses
centered double-precision coordinates, including opposite cavity orientation.

`soft_tissue_diagnostic` retains its four-value API. `soft_tissue_solve_report`
adds termination state, iterations, final change, total displacement, relative
volume error, fixed-goal error, and native timing. States are `NOT_APPLICABLE`,
`CONVERGED`, `ITERATION_LIMIT`, `INVALID_INPUT`, `NUMERICAL_FAILURE`, and
`NATIVE_UNAVAILABLE`. `CLEAN` means the output is current; iteration-limit output
is usable and visibly warned about. Convergence includes the final projections.
Failed Recompute/Rebind and failed creation/preset evaluation return failure.

## Regression fixtures

`artifacts/soft_tissue_native_regression/v1` contains native lip, abdominal Layer,
breast Pouch, Closed Bulk, and Muscle-attachment scenes, reopened renders, and
measured receipts. Build them with `tools/build_soft_tissue_native_fixtures.py`.
They use the existing prototype input geometry with production native records.
They are functional geometry fixtures, not anatomical validation of a finished avatar.
All five reopened with zero cached-vertex difference. The Muscle fixture retains
both source fibers in normal curve display; all scenes retain Solid/Object SCP colors.

`tools/benchmark_soft_tissue_native.py` measures five warmed runs per size.
The recorded solver-call medians improved 17.9× at 2,178 vertices and 13.1× at
8,450 vertices, with maximum reference deviation `1.49e-8`. This measures solver
calls, not full Blender recompute. Default Pouches still report `ITERATION_LIMIT`;
the migration preserves their algorithm and does not claim convergence.

## Historical prototypes

The immutable experiment artifacts remain under:

- `artifacts/soft_tissue_lips`
- `artifacts/soft_tissue_abdominal_fat`
- `artifacts/soft_tissue_breast`
- `artifacts/soft_tissue_closed_bulk`

Those files contain prototype meshes rather than native tissue records. Their
historical numerical results are not evidence for the current production path.
Current checks include 33 lip samples, `0.008–0.28` abdominal rest thickness,
Pouch volume error below `5e-5`, and legacy Blob compatibility within `2e-6`.

## Future work (not shipped)

- Arbitrary-object or tissue-to-tissue attachment.
- Contact, compression, friction, self-collision, or sliding attachment.
- XPBD, animation dynamics, or timeline simulation.
- Multi-component bases or multiple targets per tissue.
- Skin functionality; skin remains a separate system.

These extensions must add target adapters or solver capabilities without adding
anatomical evaluator branches to presets.
