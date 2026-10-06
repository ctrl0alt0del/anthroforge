# Persistent muscle relationships

`muscle_relationships.v1` adds durable intent to the existing pair detection and
stacking service. It preserves the existing defaults, base-ray ordering, native
support mapper and PIQP solver. An order request must agree with current geometry;
it cannot force a reversed order or repair intersecting bases.

## Identity and storage

Each skeleton root owns `af_relationship_namespace`, a UUID independent of Blender
session handles. A domain key is `[muscle_id, source|mirror, A|B]`. The relationship
ID is UUID5 of the root namespace and its sorted domain keys, independent of order.

`af_muscle_relationships` contains a checksummed schema-1 JSON document with a
document revision, exact dependency fingerprints, algorithm version and records.
Records separate intent (exclusion, requested cover, selected source faces) from
last evidence and current validation state. Disappeared relationships stay inactive
and retain intent. Stored evidence never activates stacking without fresh queries.

Three tokens have different purposes:

- Configuration revision changes when settings or user intent change.
- Relationship-document revision changes on committed intent or evidence updates.
- Result revision is the transient session epoch and generation.

Exact array content, including topology, directions, own output, provenance,
material constraints and obstacles, controls reuse. Claimed revision labels cannot
override it. Reopening rebuilds numerical caches; even small numerical differences
invalidate the corresponding dependency fingerprint.

Legacy exclusions migrate atomically into the document. The old `exclusions`
configuration field remains a compatibility view of that single authoritative
state. Unknown schemas, invalid identities, damaged checksums and malformed records
are preserved and reported; the affected root cannot publish stacked output.

## Runtime and transactions

The existing coordinator still owns one background job, the 150 ms debounce,
cancellation and generation checks. Capture produces owned immutable arrays and
intent. The versioned `af_stack_submit_relationships_v1` C ABI validates and copies
the complete batch before replacing native state. There is no Python numerical
fallback. Missing relationship ABI support reports unavailable.

Native policy status is separate from raw geometric order. Exclusions suppress
activation; `manual_order_conflict` and `stale_selected_region` block affected
components and descendants. Clearing a region restores full resolved support.
Selected `(part, source-face)` masks participate in solve signatures, while
unprotected smoothing may propagate beyond the mask.

Publication rechecks namespace, generation, configuration and document revision.
Geometry, output markers, relationship evidence and downstream updates commit in
one main-thread transaction. A failure restores prior records and current own-only
geometry, and leaves an incomplete result. Published caches and notifications are
updated only after commit. Configuration uses a separate transaction: a successful
authoring receipt means intent was saved and evaluation queued, not that solving
succeeded. Journal failure rolls back intent; solver failure retains it.

## Authoring

`muscles.pairs_inspect` and `muscles.stacking_inspect` expose `relationship_revision`,
`relationships`, `relationship_id` on current pairs and the result revision.
Inactive records remain inspectable. `muscles.pairs_footprint` and
`muscles.pairs_order_footprint` accept `relationship_id` with
`expected_result_revision`; revision-guarded `pair_index` is still supported.

Both configure operations accept a `configuration.relationships` array:

```json
{
  "relationships": [{
    "id": "stable-relationship-uuid",
    "excluded": false,
    "cover": ["muscle-id", "source", "A"],
    "region": [[0, 12], [0, 13]]
  }]
}
```

Mutations require `expected_scene_revision`, `expected_configuration_revision` and
`expected_relationship_revision`. Setting a region additionally requires
`expected_result_revision`. Regions must contain known source faces and cannot be
empty. `region: null` clears only the region; `cover: null` restores automatic
ordering and clears its dependent region. Omitted choices stay unchanged.
Do not combine legacy `exclusions` and `relationships` in one request.

`muscles.stacking_preview` accepts the same configuration without allocating
persistent IDs or changing records, geometry, settings or journals. It returns an
inline `muscle_stacking_preview` entity containing `preview`; no asset or request
receipt is written. Replaying a successful configuration request ID returns its
durable receipt even after an automatic evidence
refresh advanced the document revision.

## Visual controls

**Muscle overlap candidates** includes a stable relationship selector, inactive
records, raw geometric order, requested order, exclusion and region state, and
separate policy/solve/publication diagnostics.

**Edit support region** creates a temporary selectable covering-base copy. Displayed
triangles with the same source-face provenance select together. Orange wire geometry
shows the overlapping footprint on that base. Apply uses the same guarded mutation
service as authoring; Cancel leaves intent unchanged; Clear Region restores full
support. Smoothing may extend beyond the selected faces.

Any change of result/document revision makes the draft stale. Apply rejects edits
to preview coordinates, topology or object transform; it never edits the authored
base. Saving removes temporary objects and restores the in-memory draft afterward,
without implicitly applying it. File replacement, root deletion and addon shutdown
remove drafts. The face-selection UI timer performs no detection or solving.

## Import and recovery

Package import remaps endpoints through the importer's actual muscle-ID map, uses
the destination namespace and preserves destination settings and unrelated records.
Missing endpoints receive quarantined identities and retain their original source
identity; they cannot bind to matching destination strings by accident. Imported
evidence is stale, and selections must pass topology/provenance validation before use.
Import rollback includes relationship data even without Free fibers.

Free-surface packages also retain authored material-station correspondence. Import
validates stations before mutation, then remaps fiber/sample IDs after restoring
the point graph. Omitting this non-RNA data can change loft sampling and inflate
mesh size even when fiber paths themselves survived import. Shortcut rollback
captures stored controls rather than evaluating their live `proxy_*` accessors.

A known copied or appended root is rekeyed. Ambiguous loaded duplicate namespaces
report `RELATIONSHIP_IDENTITY_CONFLICT`; **Rekey this root** is the explicit recovery.
Experimental `af_experiment_relationships_v1` data is never activated automatically.
**Import experimental records** validates and remaps it, preserving unrelated
records and rejecting conflicting existing user intent.

## Qualification scope

Maintained tests cover the 16 incremental/fresh scenarios, focused persistence,
native policy, exact fingerprints, missing references, import rollback, mirrored
and A/B identities, branch provenance, crops, authoring replay, revision guards,
visual drafts and publication failures. Existing detector, ordering, stacking,
fiber and smoothing suites remain applicable. Clean-install tests must block access
to the development checkout and experiment directories.

Performance fields separate capture, fingerprints, reconciliation, native detection,
ordering, support, solving, validation, publication and document commit. The latter
includes validation, serialization and root assignment. Five-domain and frozen
13-domain integration measurements are qualification fixtures; they do not establish
whole-body responsiveness.

Exact obstacle fingerprints are shared within one manifest when domains reference
the same immutable obstacle arrays. Every new manifest rehashes the actual content;
this does not introduce a revision-only or rounded-content cache.
