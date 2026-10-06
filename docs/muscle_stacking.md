# Automatic muscle stacking

The production pipeline is own inflation → candidate detection → direct base-ray
ordering → dependency graph → supported scalar inflation → validated publication.
Auto Stacking defaults **On**, including roots without saved configuration. Its
persistent Off control restores current intrinsic outputs. Evaluation never saves
the Blender file automatically.

## Geometry and responsibility

`B` is the authored base, `X_own` is the intrinsic inflation output including its
height smoothing, and `X_final = X_own + b*d`. Only the displayed inflated surface
changes. Fiber paths, attachments, bases, branch structure and inflation settings
remain authored inputs. The cached intrinsic result is never replaced by stacking.

The resolver tests both base-to-base directions over triangle interiors, using the
mean native inflation direction of each source triangle. Its finite range spans
the pair, independently of the candidate detector's proximity distance. Independent
triangle intersection tests catch transverse base crossings, including crossings
aligned with triangle edges; ordinary shared-boundary contact is allowed.

The resolver reports supported local order, no upward evidence, coincident bases,
intersecting bases, conflicting local order, incompatible directions or projection
failure. A ray miss is not evidence of the reverse order. Positive material
footprints above the existing numerical area tolerance remain eligible. Names and
anatomical labels do not override geometry. Reported fragment-area sums are **not
union coverage** or a whole-muscle anatomical coverage percentage.

The graph is over stable muscle/source-or-mirror/A-or-B identities. Providers are
evaluated first. Every cover receives joint support inequalities against its
providers' **final** surfaces, restricted to the resolved material footprints.
Overlapping providers form an envelope; their heights are not added. Transitive
ancestors can contribute constraints without contributing their height twice.

Support acts on the virtual carrier `Y = B + b*d`, not directly on the final
outer surface. Require `Y` to clear each provider's final surface, then publish
`X_final = Y + (X_own - B)`. Thus a cover retains its intrinsic thickness, without
moving its authored base or bindings. For flat layers, provider heights 0.400 and
0.465 with cover thickness 0.055 produce 0.520, not their sum. A three-layer
chain of thicknesses 0.38, 0.10 and 0.08 produces heights 0.38, 0.48 and 0.56.
Smooth constrained cases may rise further where the energy couples neighboring
samples; these values describe the flat analytic controls.

The maintained PIQP/cotangent-biharmonic core minimizes

`0.5 bᵀ M b + 0.5 strength radius⁴ bᵀ Lᵀ M⁻¹ L b`

with `0 <= b <= maximum_bonus`, exact fixed values and signed affine support
inequalities. Constraint mapping and independent solver certification remain
separate. Bonus can spread smoothly beyond the footprint while retaining support
inside it. Welded branch interfaces share variables. Original fixed boundaries
remain protected; crop-generated borders do not become attachments. Exact material
interpolation carries clipping into the constraints. Zero own height alone does
not create a new pin. Explicit interior fixed material indices are also supported
by the native material contract.

## Components and native interfaces

Python modules under `core/muscle_stacking` capture Blender state, own immutable
arrays, publish transactionally, and refresh dependent blobs/soft tissues without
rerunning intrinsic muscle inflation. `core/muscle_pairs/coordinator.py` remains the
only scheduler and accepts capture/backend/publication ports for lifecycle tests.

Native modules under `native/fiber_ccd/layer_stacking` separate ordering, material
topology, support mapping, dependency planning, caching and validation. They reuse
the existing triangle snapshots/BVHs and the maintained smoothing core. Base and
obstacle BVHs are refitted where topology permits. Numerical preparation, queries
and solving execute on the owned native job; workers never access Blender.

`af_fiber_ccd_v3_28.dll` preserves fiber and pair interfaces and provides separately
versioned ordering/stacking ABI 1 interfaces. Existing height-smoothing ABI 1 is
unchanged. There are no experiment-directory includes and no Python optimizer
fallback. Missing/incompatible native support is explicitly unavailable. Restart
Blender after replacing a loaded native DLL.

## Runtime and failure behavior

The October 6 completion run is recorded under
`E:/development/WIP_models/muscle_reconstruction_workflow/features/stacking_completion/v001`.
On frozen 176-domain anatomical inputs, bounded summaries preserve all 498
overlap results and exact exported evidence. Five interleaved trials changed
median unchanged native evaluation from 3358 ms to 324 ms; an outer-only edit
changed from 3310 ms to 314 ms. Cold evaluation remained about 3.6 s. The older
build needed an enlarged result budget to complete this comparison; the new
build used production defaults. Pair/order summaries occupy about 388 KiB;
peak accounted detector footprint buffers were below 49 MiB in these trials.

Four actual Free-fiber Blender sets cover local support, disjoint providers,
overlapping grouped providers and a three-layer chain. Their 176-domain tiled
native stress case stacks 80 covering sides: cold median 3.95 s, unchanged
103 ms, local edit 190 ms. This is successful synthetic scale qualification,
not certification of an anatomical whole-body result. Invalid authored bases
remain explicit input rejection; repairing them is outside stacking.

The real assembled Blender scene takes about 6.8 s cold and 4.0 s unchanged
including capture, exact fingerprints, reconciliation and publication. Capture
and publication dominate its remaining overhead; native timings alone must not
be presented as interactive end-to-end performance. Reopening preserves 530
visible fibers, bindings, native SCP colors and stable relationship identities.
The valid scene shows a separate intrinsic reload drift of 2.19e-6 scene units
(AF-32); its reopened incremental stacked output matches a fresh solve exactly.

Qualification includes 122 focused unit tests, 112 clean-install Blender tests,
103 current fiber regression tests, five smoothing kernel groups and eight
stacking kernel groups. Six legacy ABI-1 fiber tests are unavailable in this
ABI-3 build. The clean-install tests block original-checkout and unrelated
experiment-file access. On-demand exports, cache eviction, crops, branches,
mirrors, both sides, constraint failures and transaction rollback remain covered.

- One active background job across roots; up to four workers for independent graph
  branches. Relevant changes coalesce for 150 ms. Generation checks prevent stale
  jobs from publishing; cancellation, load, undo, redo and shutdown clear ownership.
- Order caching depends on actual base/direction/topology content, separately from
  outer-surface support caching. Provider changes invalidate descendants; deletion
  and disappearance remove relationships. Repeated rebuilds do not accumulate bonus.
- Order summaries remain cached independently of detailed polygons. Only uncached
  support solves materialize eligible order footprints. Solve keys include exact
  base, direction, topology and provenance arrays plus final provider output,
  constraints, policy and obstacles; caller revision labels cannot authorize reuse.
- Support timing includes material-footprint preparation and the initial support
  check. Validation timing includes final pair-contact validation. Per-cover
  worker times are accumulated CPU-stage measurements, not additive wall time.
- Cycles, invalid ordering, infeasible fixed constraints/bounds, failed certification
  or validation block the affected muscles and descendants. Other valid components
  continue. Blocked components display current own-only output with incomplete status.
- A previously valid but now invalid capture retains an explicitly invalid domain
  to block known neighbors. If an invalid muscle has never supplied usable geometry,
  its neighborhood is unknowable: the root is conservatively own-only and incomplete.
- Validation rejects new folds/collapses, new transverse self/surface intersections,
  and increased sampled bone penetration. Bone volume checks use closed SCP meshes;
  open obstacles receive triangle crossing checks and an explicit volume-test
  limitation. Signed penetration is checked at vertices and triangle centroids;
  this is not a continuous exact-volume certificate. Existing defects are reported
  separately for evaluated candidates, not silently repaired.
- A final supported pair's triangle contact is not automatically a crossing.
  If the strict test reports a new surface intersection, a separate native check
  maps all final overlapping triangle interiors in the supported direction.
  Contact is allowed only with nonempty, warning-free evidence and no penetration
  above the existing 2e-7 tolerance. Unordered pairs, cancellation and resource
  failures cannot use this exception. Base-ordering, self and bone checks remain
  strict; no relationship is reversed.
- Publication and dependent geometry refresh are reversible. Authoring failures
  roll back configuration and durable journal records. No solver failure reverses
  a relationship or releases an attachment.

Only settings, explicit grouping/exclusions and authoring receipts persist. Inferred
relationships, BVHs, footprint arrays and solved fields are in-memory and rebuilt
after reopening. Cache eviction causes recomputation. Resource-limit failures do
not publish truncated results.

## UI and authoring

Use **AnthroForge → Muscle overlap candidates**. Refresh runs the complete enabled
pipeline. Auto Stacking, clearance, maximum bonus, smoothing radius/strength and a
selected-pair exclusion are available beside local order, fragment area and failure
diagnostics. Automatic refresh and automatic stacking are separate controls.

| Setting | Default, in current geometry units |
|---|---:|
| Automatic refresh / Auto Stacking | On / On |
| Candidate search distance | 0.05 |
| Maximum bonus and search displacement allowance | 0.5 |
| Clearance | 0 |
| Bonus smoothing radius / strength | 0.2 / 0.8 |
| Pair/order/solve cache limits | 256 MiB each |
| Footprint result / support-row budget | 256 MiB; 2,000,000 fragments/rows |

Protocol 0.4 advertises `muscle_layer_order.v1` and `muscle_stacking.v1` alongside
`muscle_pair_detection.v1`.

Persistent intent, stable identities, visual support selection and guarded import
are described in [Persistent muscle relationships](muscle_relationships.md), with
the additional capability `muscle_relationships.v1`.

| Operation | Additional parameters |
|---|---|
| `muscles.pairs_inspect`, `muscles.stacking_inspect` | None |
| `muscles.pairs_refresh` | None; enqueues the shared pipeline |
| `muscles.pairs_order_footprint` | `pair_index`, `expected_result_revision` |
| `muscles.stacking_preview` | Optional `configuration`; non-mutating |
| `muscles.stacking_configure` | `configuration`, `expected_scene_revision`, `expected_configuration_revision` |

Configuration fields are `stacking`, `clearance`, `displacement`, `smoothing_radius`,
`smoothing_strength`, `automatic`, `search_distance`, `groups`, and `exclusions`.
An exclusion is a pair of `[muscle_id, "source"|"mirror", "A"|"B"]` keys.
Existing pair configuration commands use the same transaction/service. Preview
refuses while another native job is active and returns an inline evaluation entity
without writing a journal or asset. Detailed ordering footprints are exported only
when requested at the current epoch/generation.
Ordering support, stacking feasibility and publication success have distinct fields.

## Qualification

Maintained tests include the 28 frozen analytic ordering cases with reversed,
exhaustive and inflation-invariance checks; the existing 26 detector geometry
cases; cache, lifecycle, material and stacking tests; native kernel tests; and
Blender publication, cropping, mirror, rollback and reopening tests.
Multi-provider regressions additionally exercise overlapping/disjoint footprints,
retained thickness, duplicates, redundant ancestors, provider edits/removal, fixed
conflicts, displacement exhaustion, mesh resolution, rotation and zero own height.
Independent native triangle-interior queries validate the support carrier after
solving. Native Free-fiber examples exercise multiple providers and serial layers
through automatic load regeneration, unchanged bindings and disabling stacking.

The frozen real geometry retains the experiment's two expected clean orders, five
labeled invalid intersecting-base pairs, and the tiny forearm overlap's actual geometric
order, including its disagreement with a family-level anatomical label. Those
expectations have not been changed to claim anatomical agreement.

Interleaved seven-run qualification on the 13-domain fixture measured cold ordering
at approximately 156 ms for 14 detected pairs (experimental baseline 187 ms), with
unchanged reuse around 1.2 ms. Detector-only medians were 36.2 ms versus 34.6 ms for
the preceding DLL, about 5% difference. These are fixture/machine measurements,
not a full-body latency promise. Capture, preparation, detection, ordering, support,
solve, validation and publication have separate timing fields; independent-worker
support/solve timings are summed work, not wall latency.

Position smoothing, anatomical reconstruction repair, and whole-solid muscle
collision guarantees remain outside this scalar outer-surface feature.

### Production review, October 6

The earlier full-scene report under `features/full_scene_qualification/v001`
predates the bounded-summary implementation. Its allocation and cache failures
are superseded by the completion measurements above. The anatomical input defects
remain separate from the successfully qualified stacking implementation.

The final review adds failure-injection regressions for native poll/summary errors:
the failed root reports its error, releases its backend, and permits other roots
and later retries to continue. Both submission interfaces validate settings before
replacing completed work; malformed legacy ABI requests retain the prior result.
Production packages include only the current fiber DLL, check warning and height
smoothing interfaces, and retain the licensed native dependency sources. Historical
experiment notes and intermediate builds are archived outside the addon under
`features/stacking_production_review/v001/archived-byproducts`.

The final package passes 131 isolated Blender integration tests and reopens both
the valid four-set fixture and the 176-domain scene using its packaged DLL only.
The complete unit suite runs 1,233 tests under Blender's Python 3.11 and its pinned
dependency bundle: six legacy ABI tests skip and one existing test is an expected
failure. All remaining tests pass, as do the 13 native kernel groups. Testing with
an unrelated NumPy 2 environment is not equivalent to this supported runtime.
