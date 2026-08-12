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
SCP identity and topology signature, versioned base/control bindings, attachment
rows, and solver controls. Rest and final meshes are derived caches. User-owned
Curve and Mesh bases remain visible in the hierarchy; Point bases created by the
add-on are owned controls.

## Inflation and relaxation

- Point uses radial inflation and reuses the Blob icosphere and geometric solver.
- Curve uses profile width, depth, power, segments, and endpoint taper. Its rest
  shape is unsagged; geometric relaxation moves only the free bulge.
- Surface uses minimum/maximum thickness, a power curve, and
  `AF_ST_INFLATION`. If that group is absent, an open surface receives normalized
  shortest-edge distance from its boundary; a closed surface receives weight 1.
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

## SCP attachment

V1 supports one SCP host. Raw base controls and deterministic evaluated samples
are captured as triangle/barycentric bindings with signed normal offsets. On an
SCP deformation, existing bindings resolve without selecting new triangles; the
resolved positions are written back to the original base under an update guard,
then rest and final meshes rebuild.

Bézier control points are bound individually. Left/right handle vectors are
stored in the captured surface frame so host rotation does not collapse the
handles onto the surface.

Attachment masks can be `ALL`, `BACKING`, `BOUNDARY`, `ENDPOINTS`,
`SUSPENSION`, or a custom Mesh vertex group mapped to generated front/back
vertices. `FIXED` rows set zero inverse mass; `SOFT` rows create weighted target
tethers.

If host topology changes, the last valid final mesh is retained and the VCP
enters `ERROR` until explicit Rebind. Missing base or host objects behave the
same way. A guarded host-driven base rewrite is not treated as an artist edit;
an artist edit schedules one coalesced recapture.

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
the SCP recapture path.

## Runtime and integration

The dependency graph contains `SCP → Fiber → Fiber Surface → Muscle`,
`Fiber → Soft Tissue`, and `Fiber Surface → Soft Tissue` paths in addition to
object-based `SCP → Soft Tissue`. Property/base edits schedule
coalesced `SOFT_TISSUE_UPDATE` work on Blender's main thread. Manual mode remains
`DIRTY` until Recompute. Final proxies are transform-locked caches; deleting one
causes recreation on sync. Explicit VCP deletion removes both caches and an
owned Point control while preserving user Curve/Mesh bases.

Soft Tissue participates in the VCP tree, selection, shortcuts, mirrors, Draft
Skin capture, full-package import, and VCP-only import. Mirrors copy only the
solved cache according to the host SCP's effective mirror rule.

Legacy Blob remains readable/editable. Add Blob is hidden from normal creation.
Manual conversion accepts centered sphere/ellipsoid Blobs with `NONE` or `SCP`
targets, builds a Closed Bulk candidate, and removes the Blob only after topology,
vertex (`≤2e-6`), and volume (`≤1e-6`) equivalence checks pass.

## Accepted references

The immutable experiment artifacts remain under:

- `artifacts/soft_tissue_lips`
- `artifacts/soft_tissue_abdominal_fat`
- `artifacts/soft_tissue_breast`
- `artifacts/soft_tissue_closed_bulk`

Their accepted checks are 33 samples per lip curve, abdominal thickness
`0.008–0.28` with centroid drop `0.10222`, breast relative volume error below
`5e-5` with centroid drop `0.12342`, and Closed Bulk vertex error below `2e-6`.

## Future work (not shipped)

- Muscle, arbitrary-object, or tissue-to-tissue attachment.
- Contact, compression, friction, self-collision, or sliding attachment.
- XPBD, animation dynamics, or timeline simulation.
- Multi-component bases or multiple hosts per tissue.
- Skin functionality; skin remains a separate system.

These extensions must add target adapters or solver capabilities without adding
anatomical evaluator branches to presets.
