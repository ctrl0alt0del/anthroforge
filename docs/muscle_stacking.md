# Automatic vector muscle stacking

The production pipeline is own inflation → pair detection → base-ray ordering → dependency graph → vector correspondence → localized vector smoothing → independent validation → transactional publication. Algorithm `vector-localized-v1` replaces scalar stacking for existing and new files. Auto Stacking defaults On; switching it Off restores current own-only geometry. Evaluation never saves a file.

The selected baseline is `vector_inflation/v002` (pointwise preservation). `v003` remains a rejected multiscale experiment. Frozen inputs and measurements remain intact under the external muscle workflow directory; production does not load them. Current qualification evidence is under `features/vector_stacking_production/v001`. Earlier scalar and continuation timings do not measure this algorithm.

## Geometry and numerical contract

`B` is the authored base, `X_own` includes intrinsic inflation and intrinsic height smoothing, and `X_final = X_own + P U`. `P` is exact material-to-evaluated interpolation. Authored bases, fibers, attachments, creases and intrinsic settings remain unchanged.

For `B_cover = B_provider(q) + t v_provider(q)`, use:

`U_raw = X_final,provider(q) - B_provider(q) + max(0,-t) v_provider(q)`.

Correspondence retains the v002 chart convention, deterministic nearest match and native limiting directions at zero inflation. Actual displacement vectors carry tangential movement and preceding stacking.

Simultaneous providers compete by greatest outward projection along the covering sample's native direction; stable provider identity resolves ties. They are not summed. All eligible providers contribute inequalities to one solve. Chains evaluate providers first using final output; redundant ancestors do not contribute displacement twice. Relationship footprints and selected regions restrict both raw candidates and support construction.

The maintained PIQP core minimizes:

`0.5 Σ_i m_i w_i ||(P U)_i - U_raw,i||² + 0.5 strength radius⁴ (P U)ᵀ Q (P U)`.

`Q` is cotangent-biharmonic energy on the visible cropped base. Preservation weights range from 1 to the configured maximum (default 100), using squared displacement normalized by the connected component's area-weighted 90th percentile. Mesh-edge distances start at overlap footprints and raw displaced samples. Cubic falloff limits adjustment through the blend band; added displacement is zero beyond it.

There is one frozen support construction at raw stacking and one solve, followed by remapping and independent validation. No multiscale fidelity, provider-load continuation, contact repair or scalar fallback runs. Solver certification alone is not geometry validation.

### Exact constraints and crops

Structural constraints remain equations `C U = 0` separately for three coordinates. Interpolated attachments do not pin every contributing vertex. Welded seams share variables, protected creases retain genuine equations, and generated crop borders create no attachments. Energy is pulled back through exact `P`. A rank-revealing basis of `[P; C]` removes unobservable degrees of freedom without visible regularization or dropping constraint equations. Material vertices hidden by cropping can still participate in attachments.

## Ordering, relationships and validation

Automatic ordering retains direct base rays, both directional hypotheses, finite pair-extent range, triangle-interior footprints and independent transverse-intersection checks. A ray miss does not establish reverse order. Fragment-area sums are not union coverage or anatomical coverage percentages. Names do not override geometry.

[Persistent relationships](muscle_relationships.md) retain exclusions, regions and order intent. Requested order must agree with evidence. Explicit order may resolve crossing/ambiguous bases. Directions must agree with each domain's intrinsic displacement; explicit vector transport does not require every projected face pair to have positively aligned directions. Automatic ordering retains its stricter directional evidence.

The dependency graph uses stable root/muscle/source-or-mirror/A-or-B identities. Cycles, invalid policy, infeasible attachments, failed certification or failed validation block affected muscles and descendants. Unrelated valid components may publish. Blocked components show current own-only geometry, never a stale stacked result.

Separate checks cover remapped support, exact attachments, folds/collapses, new self/provider intersections and worsened bone penetration. Open SCPs receive triangle crossing checks; closed SCPs also receive sampled volume tests. Vertex/centroid sampling is not a continuous exact-volume certificate. Existing defects are reported separately.

Actual geometry and smoothing margins expand queries. Final BVHs check newly encountered neighbors beyond initial candidates before publication. Contact without a resolved valid relationship blocks the component and reports both domain IDs. Failure never silently reverses order or releases an attachment.

### Recorded numerical limitations

Six frozen v002 configurations pass on source and mirror. The three deliberately deferred configurations remain rejected: `provider_4.0` introduces a fold/collapse; `proximal` and `cover_0.0` fail remapped support. Passing uncropped results match within existing tolerances. Cropped calf differs slightly because exact production interpolation replaces the experiment's cropped-mesh substitution; measured differences and independent checks are recorded in qualification.

Additional Blender controls expose one-solve limitations: a long blend band can create reverse biharmonic lobes crossing tiny fixture anchors; a narrow-radius two-muscle control can self-intersect. These remain explicit rejection regressions. Successful multi-provider/chain tests use a 0.35 blend band; the rapid-edit success test uses a validated radius range. The addon does not silently change these settings or weaken collision checks.

## Runtime and persistence

The existing single-flight coordinator retains 150 ms debounce, cancellation and generation/configuration/relationship guards. One shared native budget permits at most four workers without nested pools. Workers do not access Blender. Capture reads intrinsic geometry, so rebuilds do not accumulate stacking. Load, undo, redo and shutdown reset transient state.

Correspondence, material energy/layout, locality and solved-field caches use actual array dependencies. Keys include algorithm version, interpolation, exact constraints, topology/provenance, provider final output, settings, policy and obstacles. Base order is independent of outer-only changes. Deletion evicts domain entries; eviction causes recomputation. Persistent evidence never activates a relationship without fresh evaluation. Numerical structures rebuild on reopening.

Publication commits surfaces, records and downstream updates transactionally on the main thread. Failure restores current own-only geometry and prior durable records with incomplete status. Journal failure rolls back configuration/intent; later numerical failure retains saved intent and diagnostics. Existing import remapping and relationship persistence remain authoritative.

## Controls and migration

| Setting | Default in geometry units |
|---|---:|
| Automatic refresh / Auto Stacking | On / On |
| Pair search distance / allowance | 0.05 / 0.5 |
| Clearance | 0 |
| Smoothing radius / strength | 0.5 / 0.8 |
| Blend distance | 1.0 |
| Maximum preservation weight | 100 |
| Smoothing adjustment per coordinate | 4.0 |

Saved radius, strength, clearance and automatic controls retain their values. New settings use these defaults. The old saved `displacement` is only a pair-search allowance, not a total movement cap. The Maximum bonus control is removed. `smoothing_max_adjustment` bounds changes around raw stacking in x/y/z; falloff further limits them outside the footprint.

## Interfaces and packaging

`native/fiber_ccd/vector_stacking` separates correspondence, composition, locality, material mapping, QP assembly, caching and validation. It reuses fiber BVHs and maintained PIQP/cotangent code. Python handles Blender capture, immutable transfer, configuration and publication. No experiment dependency or Python optimizer fallback exists.

The packaged native library is `af_fiber_ccd_v3_32.dll`. Versioned `af_vector_stack_submit_v1` atomically accepts domains, policy and exact constraint rows. Malformed submissions preserve the prior completed result. Retired scalar submissions return code 4 and `STACK_SCALAR_SUBMISSION_RETIRED`, never another algorithm. Unrelated fiber, detector, ordering, intrinsic-height and relationship inspection interfaces retain their versions. Restart Blender after installation to load the replacement library.

Capability `muscle_vector_stacking.v1` extends `muscle_stacking.v1`. Existing inspect, preview and configure operations use the shared service and revision guards. Preview is non-mutating. New fields: `blend_distance`, `preservation_weight`, `smoothing_max_adjustment`. Inspection reports algorithm, raw/final displacement, preservation/locality, attachment/contact checks, cache reuse and stage timings. The old result field `maximum_bonus` is a deprecated alias of measured `maximum_displacement`, not a bound.

Qualification covers frozen parity/rejections, multiple providers and chains, duplicates/ancestry, exact attachments, hidden crop variables, new neighbors, branches/A/B/mirrors, Blender lifecycle/imports, preview/journal/publication rollback, save/reopen presentation and isolated packaging. Current fixture timing reports are not claims of whole-body responsiveness.
