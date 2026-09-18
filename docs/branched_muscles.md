# Branched muscles

A branched muscle is one native Muscle with a retained main Fiber Surface and one or more retained branch Fiber Surfaces. Branches use normal fibers. Each branch fiber starts at an explicit authored midpoint of one outer main fiber; the opposite main fiber needs no corresponding midpoint. The branch root follows the solved main-fiber interval and shares mesh vertex indices with it.

## Editing

1. Create an open main loft and a separate open branch loft. Convert a legacy muscle to a Fiber Surface first if needed.
2. On the muscle panel, use **Add Fiber Loft Branch**. Supply the branch surface ID, the main outer fiber ID, and its ordered point indices, one per branch fiber. Index 0 is the main fiber start; branch roots must be interior midpoints. The command explicitly replaces the branch fibers' start references with these shared points.
3. Use **Edit Main Inflation** or **Edit Branch Inflation**, then the normal inflation controls. Each part supports Distributed or Control Point mode. A selected control-point gizmo snaps only to that part's base grid.
4. Adjust connector Width (default 0.25) and signed Fullness (default 0). Width controls how far the connector reaches into each loft; fullness uses the assembly's selected normal side. **Swap Normals** affects the whole assembly.

Binding and normal offset belong to the shared authored point. Editing a shared point affects all incident fibers. The point list shows identities and uses. Detach creates an independent copy; active branch roots cannot be detached, removed, or reordered until the connection is removed. Removing a branch connection preserves source lofts, fibers, and points. Removing the last connection returns the muscle to an ordinary loft.

The local Hermite connector uses tangents from retained surface rows. It joins independently inflated parts without adding fiber guides. It does not provide global surface smoothing, fiber-corner smoothing, collision repair, or a guarantee of tangent continuity at constrained junction ends.

## Supported topology and persistence

Multiple disjoint root intervals are supported on either outer main fiber. Intervals on the same side cannot overlap or share endpoints. Nested branches, cyclic lofts, and `use_mirrored_rows` source construction are rejected. Ordinary derived mirror display remains separate from this restriction.

Legacy files migrate each old point occurrence to a distinct identity without merging coincident positions, moving pins, or requesting a solve. Shared identities and part settings persist in normal Blender files and package imports; imports allocate new point identities while preserving internal sharing. Undo/redo clears the point lookup caches.

Restart Blender after installing this update to register the new RNA types and load the native library. Rebuild the native library with `native/fiber_ccd/build_windows.ps1` when packaging from source; the default output is `af_fiber_ccd_v3_14.dll`. Its prepared-grid inflation entry point preserves the assembled sampling and uses the existing inflation formulas.

## Authoring

Protocol 0.4 exposes `muscles.branch_inspect`, `muscles.branch_add`, `muscles.branch_remove`, `muscles.branch_configure`, and `points.inspect/edit/link/detach`. Mutations require a scene revision and request ID, support replay, and restore native records on validation failure. UI and authoring use the same branch operations and qualified SCP snapping.

A portable recipe uses strategy `branched_loft.v1` and this construction shape (each placeholder is a normal `open_loft` construction):

```json
{
  "kind": "branched_loft",
  "main": "<main open_loft construction>",
  "branches": {
    "head2": {
      "construction": "<branch open_loft construction>",
      "boundary": "last",
      "root_anchor_indices": [1, 2],
      "width": 0.25,
      "fullness": 0,
      "inflation": {"mode": "DISTRIBUTED", "amount": 0.1}
    }
  }
}
```

This is a structural illustration, not a complete compilable document. `tests/blender/test_branched_authoring.py` constructs a complete document and exercises draft, compile, publish, and reconcile restore. Recipe parameters apply to every part; explicit branch inflation overrides apply afterwards. Branch starts are copied from the selected main anchors before solving. `main` is reserved as a branch key.

Compound global shape targets and automatic fitting are explicitly unsupported; leave targets empty and fitting disabled. The inherited `shape`, `contact`, and reference measurements describe the main part before connector assembly, identified by `measurement_scope`. Per-part contact diagnostics remain in `branch_parts`; `assembly_contact_checked` is false. Surface penetration and folding are diagnostic observations, not branch publication blockers. Degenerate input and invalid root relations remain errors.

## Example and scope of validation

`tools/build_native_branch_fixture.py` builds a standalone native cube example with four visible fibers, one branched muscle, a midpoint-free opposite main fiber, and the normal SCP presentation. It uses explicitly cached cube routes to isolate assembly and lifecycle behavior; it is not a solver convergence benchmark. No lab activation script is needed to reopen or edit it.

Tests cover welded and consistently oriented seams on both sides, multiple branches, a curved root with three child fibers, per-part inflation backend parity, selected control editing, identity migration, import, save/reload, protected roots, authoring replay and publication. Whole-body performance and arbitrary anatomical configurations are not established by these fixtures. Inflation-only changes reuse cached solved fibers; changing a shared pin invalidates its incident fibers.

The cube fixture has 2,159 vertices and 2,016 quads. On the development machine, ten warm samples after two warmups gave approximately 2.6 ms capture, 1.0 ms inflation/connector evaluation, and 4.5 ms full muscle refresh. These exclude fiber solving. Geometry-keyed, bounded boundary-distance caching avoids recalculation on inflation edits and invalidates naturally when coordinates or the exterior mask change.

Regression note (2026-09-17): the broader muscle suite still reports 11 persistence assertion failures. An isolated unchanged HEAD checkout with its previous native library also reports 11 failures in that persistence suite. Current failures are base-coordinate differences up to 2.38e-7 against a 1e-7 reload tolerance. Tests were not relaxed. The native branch fixture's own reopen/regenerate tests pass; this does not resolve the existing general reload-precision issue.
