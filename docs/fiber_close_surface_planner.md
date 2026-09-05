# Close Same-Surface Fiber Planner

## Correct problem

This is a local same-surface route-quality defect, not a missing global
free-space planner. When two anchors are close on one surface, the Fiber should
take a tight, smooth collision-clear route near that surface. It should not make
an unnecessary upward jig.

The torus counterexample still matters only as a guard: distant same-surface
anchors must not be forced to follow a long surface geodesic when a much shorter
valid three-dimensional route exists.

## Proven cause in V2.4

`core/vcp/v2/planner.py::_surface_on_collider` evaluates candidates in this
order:

1. `_local_surface_bridge`;
2. `_surface_mesh_path` plus `_best_offset_route`.

The first valid local bridge returns immediately. `_local_surface_bridge` tries
normal offsets of `1.25`, `1.75`, `2.5`, `4.0`, and `8.0` times the collision
radius. `_bridge_points` applies that offset to a straight chord using
interpolated endpoint normals. On a curved patch, the middle can remain too
close to the owner surface, so progressively larger factors fail until a visibly
elevated route becomes valid.

Because that valid bridge returns immediately, the tighter mesh-surface route
is never computed or compared. This is why the route can jig upward even when a
better local route exists.

## Targeted V2.4 experiment

Do not add a new solver version and do not build another global roadmap.

For every blocked same-owner anchor pair:

1. Preserve the direct collision-clear test.
2. Compute the existing lifted bridge candidate without early return.
3. Compute the existing offset-surface candidate as well.
4. Independently validate every candidate with identical owner/collider rules.
5. Compare valid candidates rather than selecting the first one.
6. Pass only the selected candidate to exact-count handoff and final validation.

Start with lexicographic candidate quality:

1. valid clearance;
2. shortest path length;
3. lowest maximum excess distance from the owner surface for near-equal lengths;
4. lowest maximum turn as the final tie-breaker.

The excess-distance tie-break prevents a tiny numerical length difference from
selecting a conspicuous upward jig.

## Local route method

The existing vertex-graph surface path is a useful baseline but can zigzag
because it is restricted to mesh edges. Two stronger local candidates are:

- trace a smooth geodesic from a prefactored heat-method distance field; or
- use the mesh graph only to identify a local triangle strip, then unfold that
  strip and compute the continuous geodesic across triangle interiors.

The [Heat Method](https://www.cs.cmu.edu/~kmcrane/Projects/HeatMethod/paperTOG.pdf)
is attractive for repeated edits because its matrices can be prefactored once
per stable SCP topology and solved in near-linear time. It computes surface
distance rather than a clearance route, so the resulting curve must be offset
along the surface normals and collision-validated.

For the first experiment, use the existing native mesh path. Candidate ordering
is the demonstrated defect and can be tested without introducing a new numerical
dependency. Only investigate the heat method or triangle-strip unfolding if the
selected surface candidate still has mesh-induced zigzags.

## Torus-safe selection

Do not classify solely from `owner_id` or Euclidean endpoint distance. Always
compare the valid local-surface and spatial candidates:

- close points: their lengths should be similar, so the lower-lift local route
  wins the near-equal tie-break;
- opposite torus sides: a valid spatial route through the hole is materially
  shorter than the surface route, so it wins on length before lift is considered.

The near-equal tolerance must be measured, not guessed. Test `{1%, 2%, 5%}` and
select the smallest value that removes the reproduced jig without changing the
torus choice.

## Required tests

- close points on a sphere reproducing the upward jig;
- the same pair on coarse and fine tessellations;
- opposite torus sides with a clear central route;
- torus with the central route blocked;
- high-curvature but genuinely local anchors;
- `skull_muscles_skin.blend/FIBER_1` and all same-owner production Fibers.

Record candidate length, maximum owner-surface excess distance, maximum turn,
collision work, selected candidate, planner time, and editable Blender renders.

Acceptance requires no clearance regression, no close-pair upward jig, the
correct torus route, deterministic output, and no meaningful regression over
V2.4 planner time.
