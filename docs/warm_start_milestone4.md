# Warm-start Milestone 4 acceptance

The production harness is `tools/warm_start_acceptance.py`. It runs edits through the
normal shortcut, bake, coordinated-worker, import, and forced-full comparison paths.
Reported surface distances are in scene world units.

## Recorded results

- The legacy skull skin retained an identical vertex hash while receiving 19 binding
  attributes. All 214,205 vertices bound successfully; one-time preparation took
  130.58 seconds.
- The guide-free body small and medium edits used warm skin plus topology rebinding.
  Warm skin took about 2.1 seconds and the total coordinated operation about 19 seconds,
  compared with about 32 seconds for a full solve.
- The 20% extreme edit correctly rebuilt the skin, then rebound the unchanged topology.
- The ribs/contact stress edit also selected the safe skin-rebuild path while preserving
  and rebinding the existing topology.
- Symmetric and asymmetric runs preserved connectivity and produced zero inversions and
  reported self-intersections. Enabled symmetry is exact to the recorded precision.

## Known acceptance blocker

The skull facial-guide cold topology solve reaches Instant Meshes, then fails during the
previously deferred guide-annulus transition stage with `face already exists`. Milestone 4
does not alter that transition algorithm. Consequently, facial guide-row warm acceptance
cannot run on that scene until the deferred transition defect is fixed.
