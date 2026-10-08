# Base surface intersection diagnostics

`muscles.base_intersections` (authoring protocol 0.4) scans **all native muscles
on the requested root in the loaded scene**, including hidden BASE objects and
their mirrors. It returns unordered surface-instance pairs, muscle IDs/names,
object names, triangle counts, and bounded world-space intersection witnesses.
It does not load separate catalogue candidates or infer placement between files.

```python
from uuid import uuid4
from anthroforge.app.authoring.api import execute

request = dict(
    dsl="anthroforge.authoring.protocol", version="0.4.0",
    message_type="request", request_id=str(uuid4()),
    op="muscles.base_intersections", params=dict(scene_id=root.name))
result = execute(request, root, scene, journal_directory)
report = result["entities"][0]["intersections"]
pairs = [pair for pair in report["pairs"] if pair["intersection"]]
```

Optional parameters:

| Parameter | Default | Meaning |
|---|---|---|
| `muscle_ids` | All native muscles | Restrict **both** sides to this set of native IDs |
| `include_mirrors` | `true` | Include mirrors and source↔mirror comparisons |
| `tolerance` | `1e-7` | Positive world-space distance tolerance, in scene units |
| `witness_limit` | `8` | 0–64 witnesses **per category per pair** |
| `expected_scene_revision` | Omitted | Optional authoring revision guard |

The query is live on every call. `geometry_revision` hashes the actual world-space
base coordinates, triangulation and identity metadata, independently of the general
authoring revision. Native pair grouping and stacking exclusions do not suppress
these diagnostics. A source and its own mirror are distinct physical instances.
There is no A/B inflation-side duplication, and no self-intersection scan inside
one base object. Branched bases are checked as one published mesh per instance.

## Interpreting the result

Each pair has `triangle_pair_counts` with three categories:

- `crossing`: noncoplanar triangle intersection of positive length, except a seam
  lying on the topological boundary of **both** surfaces.
- `coplanar_overlap`: coplanar area overlap greater than `tolerance²`. Opposite
  winding and one triangle wholly inside another are handled.
- `contact`: point or boundary-only contact, including the shared seam above.

`intersection` is true when either of the first two counts is nonzero. Contact-only
pairs are retained separately through `contact_only_pair_count`; they should not
automatically be treated as defective muscles. Neither an intersection nor an
intentional shared base determines anatomical validity or layer order.

Witnesses identify triangulation indices, original Blender polygon indices, vertex
indices and a world-space segment (possibly zero length). For coplanar overlap the
segment spans the clipped polygon. `coplanar_area` sums triangle-pair overlap areas;
duplicate or self-overlapping input triangles can double-count area. Counts describe
triangle pairs, not connected intersection curves or penetration depth. Bounded
witnesses may be truncated; **pair lists and counts are never truncated**. A resource
limit fails explicitly instead of returning a clean-looking partial result.

`complete=false` and top-level `status="unresolved"` mean some geometry could not be
certified: missing, duplicate, stale, invalid, empty or degenerate bases are listed
in `issues`. Valid remaining triangles/surfaces are still checked, and their pairs
are still returned. Degeneracy means triangle altitude at or below the chosen
tolerance; lower tolerance deliberately if smaller features matter. Unknown native
IDs and malformed parameters fail validation rather than selecting another muscle.
Orphan BASE objects without a native muscle record also prevent a complete result.

## Scope and implementation

The diagnostic reads the **published native BASE mesh**, its triangulation and object
world transform. It does not reroute fibers, regenerate bases, require an inflated
mesh, modify display settings, save a blend, or start the automatic stacking pipeline.
It respects the published output crop; it does not inspect discarded construction
strips. Display modifiers are not applied to substitute a different diagnostic mesh.
No replay receipt or diagnostic asset is written; the response is returned directly.

Python captures Blender data and formats reports. The existing native Fiber library
(`af_fiber_ccd_v3_32.dll`, base-intersection ABI 1) builds its existing triangle BVHs,
rejects separated surface boxes, traverses candidate triangles and runs triangle
intersection tests in C++. This is independent of the inflation projection scan
(`muscles.pairs_refresh`), which can include separated surfaces and filters groups.
No optimizer, solver callbacks, new package, or Python numerical fallback is used.

These are tolerance-based floating-point surface tests, not exact-arithmetic solid
Boolean operations or containment tests. Near-coplanar surfaces within tolerance
can be reported as coincident. The surface-pair versus solid-containment distinction
also appears in [CGAL's mesh intersection API](https://doc.cgal.org/5.6/Polygon_mesh_processing/group__PMP__intersection__grp.html).
Reload Blender after installing the native binary. Run unit tests in
`tests/unit/test_base_intersections.py` and Blender tests in
`tests/blender/test_authoring_base_intersections.py`.

For a headless scan, run `blender -b body.blend -P tools/authoring_base_intersections.py -- --summary`.
Omit `--summary` to include all witnesses. Use `--root NAME` if the scene contains
multiple native roots. The tool prints JSON and does not save any files.

## Validation on the reconstructed assembly, 2026-10-07

Read-only scan of
`E:/development/WIP_models/muscle_reconstruction_workflow/features/stacking_completion/v001/assembled-default.blend`
(file SHA-256 `4cf80d368df1c0bef837ff730a663828c798276e6e29cf841da9bcd0d3e3be8f`):

- 78 native muscle records, 156 source/mirrored base instances; 12,090 possible pairs.
- 600 pairs survived bounding-box rejection; 100,756 triangle tests.
- 72 intersecting pairs: 36 source-side pairs and the corresponding 36 mirror pairs.
  Another 12 pairs had contacts only. No missing, stale or degenerate bases.
- Capture plus native scan took approximately 0.44 seconds on this run; this does
  not include loading Blender or the authoring inventory capture.
- Independent Blender BVH queries across all pairs confirmed all 72 intersections
  and 10 contact-only pairs. The remaining two were tolerance-level contacts between
  pronator teres and flexor carpi ulnaris (source and mirror); Blender reported no
  overlap for those. Blender returned no pair absent from the native report.
- Actual pectoralis/biceps triangle patches and intersection witnesses were inspected
  from two directions. Synthetic tests additionally cover coplanar overlap, which
  was not present in this assembly's reported intersections.

These measurements describe this saved assembly, not every separate catalogue
candidate or unsaved edits in another Blender session. The 13 numerical tests and
8 public Blender API tests passed; 61 related detection/order/packaging checks also
passed. Existing disk-journal regression tests could not run successfully under
the session's temporary-directory permissions. No-journal-write behavior of this
new query was verified with an explicit failing write guard.
