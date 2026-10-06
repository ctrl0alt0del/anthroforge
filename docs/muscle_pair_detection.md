# Muscle overlap candidates

`muscle_pair_detection.v1` detects geometric candidate pairs and localized,
directed triangle-interior footprints. It does not infer anatomical layer order,
activate stacking, move geometry, reroute fibers, or run a stacking/smoothing
solve by itself. The shared production coordinator now follows detection with
[base-ray ordering and automatic stacking](muscle_stacking.md); Auto Stacking
defaults On. A geometric candidate is not an approved support relation. Both directional
hypotheses are retained; projection warnings require explicit review.

## Use

Open **AnthroForge → Muscle overlap candidates**. Automatic refresh defaults to
On; Refresh requests an immediate scan. The panel exposes search distance,
additional displacement allowance, current status/revision, candidate summaries,
and selected-pair diagnostics. Selection and display changes do not rescan.

Defaults, in current geometry units:

| Setting | Value |
|---|---:|
| Search distance | 0.05 |
| Additional displacement allowance | 0.5 |
| Debounce | 150 ms |
| Internal workers | Up to 4, available-worker and job-count capped |
| Pair cache | 256 MiB per native root session, LRU eviction |
| Footprint working allocation | 256 MiB; released after each pair |
| Fragment ceiling | 2,000,000 |

Eviction causes recomputation. A resource-limit failure never publishes a
truncated result. Numerical tolerances remain projected area `1e-10`, epsilon
`1e-9`. There are no production optimization-strategy toggles or Python numerical
fallback. An incompatible native library reports `unavailable`.

Only configuration, explicit muscle grouping, and authoring transaction receipts
are persisted. Snapshots, BVHs, footprints and pair caches are memory-only.
Reopening performs a fresh scan. Reload Blender after installing the new native
library (`af_fiber_ccd_v3_28.dll`, fiber ABI 3, pair ABI 1, storage diagnostics ABI 1).

## Authoring protocol 0.4

All four operations use the same coordinator and revisions as the panel:

| Operation | Parameters beyond `scene_id` |
|---|---|
| `muscles.pairs_inspect` | None |
| `muscles.pairs_refresh` | None; enqueues, does not block until completion |
| `muscles.pairs_footprint` | `pair_index`, `expected_result_revision` |
| `muscles.pairs_configure` | `configuration`, `expected_scene_revision`, `expected_configuration_revision` |

Responses contain `entities[0].detection`: settings, configuration revision,
result revision (`epoch:generation`), status/completeness, summaries, issues and
timings. Inspect again after refresh completes. Use the returned pair `index`,
not its position in a filtered UI list. Footprint export requires exactly the
current result revision and writes an explicit `muscle_pair_footprint.v1` asset.
Ordinary refresh/inspection does not materialize bulk footprint arrays.

Example configuration payload (inside a normal authoring request):

```json
{
  "op": "muscles.pairs_configure",
  "params": {
    "scene_id": "AF_ROOT",
    "expected_scene_revision": "<current scene revision>",
    "expected_configuration_revision": "<current configuration revision>",
    "configuration": {
      "automatic": true,
      "search_distance": 0.05,
      "displacement": 0.5,
      "groups": {"MUSCLE_1": "anatomical-family-id", "MUSCLE_2": "anatomical-family-id"}
    }
  }
}
```

Grouping is optional and explicit. An empty group defaults to the native muscle
ID. It is never inferred from names or an external catalogue. Coordinated parts
can share a group to suppress comparisons within that family. Source and mirror
instances remain distinct; detection compares eligible different families within
the same root and instance, retaining enabled A/B domains separately.

Footprint assets contain domain keys, content revision, grouping, displacement
allowance, triangles and part/source-face provenance; fragments identify receiver
and provider triangles, polygon ranges, projected area, signed gap range and
alignment. Polygon arrays contain barycentric coordinates and world positions
on both domains. `activation_ready` remains false.

## Components and ownership

- `core/muscle_pairs/model.py`: immutable records and capture/backend ports.
- `capture.py`: Blender adapter, canonical read-only request capture, published
  result reuse and comparison against evaluated muscle proxies. It flushes
  pending dependency updates before capture; no worker touches Blender data.
- `field.py` and native `field.hpp`: canonical base/outer fields, native limiting
  directions, cropped provenance, enabled-part filtering and mirror transforms.
  Nonzero displacement determines direction. Zero-height vertices use the native
  inflation law; arbitrary mesh normals are not substituted. Disabled branches
  are filtered before field construction; their zero limiting contribution does
  not alter enabled seam directions.
- `native/fiber_ccd/pair_detection/`: numerical facade, snapshot store, existing
  triangle BVH/refit reuse, conservative rejection, cached projection math, fixed
  clipping buffers, tighter BVH traversal and deterministic parallel assembly.
  No tandem-tree code or external experiment includes are used.
- `PairResultCache`: revision-keyed, bounded LRU repository. Revisions are derived
  from actual array/metadata comparisons, not trusted caller hashes. Full batch
  submission is authoritative; absent domains and obsolete pair entries are
  removed. Topology changes rebuild; unchanged topology refits.
- `coordinator.py`: debounce, one active native job across roots, generation
  checks, cancellation, invalid-input status and independent root sessions.
- `runtime.py`, `ui/muscle_pairs.py`, authoring adapters: lifecycle and public
  access through the same service. Root/muscle-proxy transforms, successful
  publications, membership/grouping and relevant dependency changes invalidate.

Native input arrays are copied before submit returns. The worker owns snapshots
and results. Pair and ordering caches retain compact summaries. Detailed polygons
are generated on demand from the current owned snapshots for explicit export or
an active support solve. Ordinary inspection retains no bulk footprint geometry.
Export repeats the same numerical query and checks counts against its summary.
`submit/poll/cancel/release/destroy` form the separately versioned C ABI.
Release joins completed work while preserving its inspectable result; destroy
cancels, joins and frees the session. Parallelism does not change global solver
thread settings. Load, undo and redo clear sessions and start a new epoch.

Status is `not_scanned`, `queued`, `running`, `complete`, `incomplete`, `stale`,
`cancelled`, `failed` or `unavailable`. Stale/invalid muscles are listed explicitly;
their absence cannot produce an apparently complete scan. New edits invalidate
the previous footprint revision immediately. Obsolete jobs cannot publish.

## Bounded evidence storage, 2026-10-06

The former aggregate footprint retention exceeded the default budget on the
176-domain assembly. Detection now releases each completed pair's geometry;
its four workers share a live allocation budget. Vector growth accounts for
the temporary old and new buffers. The two-million-fragment ceiling still
applies to the complete scan, including cached pairs. Results are never truncated.
Ordering has a separate bounded LRU summary cache instead of clearing every
entry when aggregate detail exceeds the limit. Support masks are bounded too.

`result_bytes` reports retained pair records. `footprint_logical_bytes` reports
the unretained aggregate polygon size, not resident memory. The storage API
reports peak accounted footprint working allocation and summary-cache bytes.
These counters do not measure total process memory, BVHs or PIQP allocations.
Detailed exports can explicitly report `PAIR_FOOTPRINT_RESOURCE_LIMIT` or
`LAYER_FOOTPRINT_RESOURCE_LIMIT`; an export failure does not truncate summaries.

## Earlier qualification, 2026-10-05

Evidence is under
`E:/development/WIP_models/muscle_reconstruction_workflow/features/pair_detection/production_v001`.

- 51 detector unit tests, including the retained 26 analytic tests, cache
  invalidation/removal/eviction, resource limits, cancellation, owned inputs,
  lifecycle fakes, all inflation laws, smoothing, crops, branches and A/B sides.
- 13 Blender integration tests: common UI/authoring revision, guarded configuration
  and journal rollback, explicit footprint export, actual undo/redo, save/reopen,
  automatic publication/deletion, mirror fields, helper-transform exclusion,
  no-rerouting capture and shutdown handlers.
- Frozen fixture: 13 enabled domains, 76 eligible combinations, 24 broad candidates,
  14 geometric pairs, 80,806 fragments and 296,918 polygon vertices. Original
  optimized-array parity passes at absolute tolerance `1e-8`; exhaustive traversal
  matches after ordering by directed triangle identity.
- Canonical Blender capture compares 13 original source domains and also captures
  their mirrors. Original scenes are read only. Smoothing output is reused; its
  evaluated output is not replaced with an unsmoothed mesh.
- Existing smoothing and native fiber regression checks were run. Six legacy CCD
  tests requiring the old ABI-1 filename were additionally run against the actual
  compatible exports in the new DLL, and passed.
- The broad 210-test muscle suite has 12 failure entries in pre-existing reload,
  control and invalid-profile inspection tests. The exact pre-change dirty tree
  reproduces all 12, including the identical `2.38418579e-7` reload drift. They are
  recorded in `baseline_persistence.log` / `baseline_profiles.log`; this feature
  does not claim those unrelated tests pass.
- Two initial Blender attempts crashed during fixture construction inside the
  existing deletion handler, before the first detector job. Subsequent package
  runs passed; three pre-change single-fixture runs also passed. This intermittent
  setup crash remains unisolated and is recorded in `qualification.json`.

Interleaved frozen-fixture medians (milliseconds; no Blender capture/disk I/O):

| Stage | Cold | One gluteus domain edit |
|---|---:|---:|
| Submission / owned input copy | 2.52 | 2.02 |
| Native preparation / refit | 9.64 | 0.77 |
| Broad filtering | 0.002 | 0.003 |
| Detailed mapping | 26.52 | 15.37 |
| Result assembly / cache | 0.011 | 0.23 |
| Native total | 36.31 | 16.32 |
| Summary ready, including submission/polling | 40.25 | 19.50 |
| Explicit all-footprint array export | 7.01 | 7.65 |
| Total including all-array export | 47.29 | 27.08 |
| Optimized experimental baseline total | 57.37 | 33.32 |

The local edit recomputes one broad pair and reuses 23. Cold and update native paths
do not regress beyond 25%. These are fixture/host measurements, not full-body
latency guarantees. JSON serialization and downstream PIQP/stacking are excluded.
The capture report measures the original per-muscle scenes separately; do not add
their timings to this table and call it a measured whole-scene run.

The package builder checks required pair ABI exports in a subprocess, so the
OpenMP runtime does not leave the staging directory locked. Qualification uses a
temporary Git index to include new production files without changing the user's
index, then tests an extracted offline package with an external test harness.
