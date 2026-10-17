# Authoring storage policy

The workflow keeps current catalogue builds, their journals, approval history and
anatomical evidence available at their original paths. Storage maintenance changes
file representation, not reconstruction geometry or approval status.

## Policy

`FileStore` discovers `.authoring-storage.json` in the journal's ancestors. No
policy means the existing storage behavior. The workflow root uses:

```json
{
  "schema_version": 1,
  "immutable_asset_pool": "storage/immutable-assets",
  "compress_journals": true,
  "export_save_versions": 0,
  "compress_blend_exports": true
}
```

Only content-addressed JSON/SVG assets share storage. Their filename must equal
their content SHA-256. Journal paths remain ordinary files; NTFS hard links share
the underlying bytes with the pool. Copying a journal elsewhere produces readable
files without requiring the pool. Unsupported hard linking falls back to normal
atomic file copies. Treat assets as immutable; do not edit their bytes in place.
Deleting an unused pool link does not delete a journal's other hard links.

Mutable keyed records, including requests, transactions, recipes and drafts, are
never hard linked. Transparent NTFS compression reduces their storage without
changing JSON, paths, checksums or reader APIs. Existing category directories and
new pool directories receive the compression attribute when opened for authoring.
Non-Windows hosts skip NTFS compression. The policy is opt-in on compatible volumes.

`StaticScene.save_copy` temporarily applies the export backup preference and restores
the user's setting even after failure. `save_debug_copy` still prepares normal
fiber visibility and SCP colors. Export compression is explicit. Continue using
separately versioned candidate filenames: disabling automatic `.blend1` creation
does not replace versioned milestones or an external backup.

## Maintenance

Run `tools/muscle_workflow/storage_maintenance.py` with the workflow's external
Python (`runtime/.venv/Scripts/python.exe`). It requires `zstandard`. Use a new,
existing directory under `maintenance` for each run. Each run records an inventory,
per-file checksums, operation receipts and verification results.

```text
storage_maintenance.py protect --root ROOT --run RUN
storage_maintenance.py assets --root ROOT --run RUN
storage_maintenance.py compress --root ROOT --run RUN
storage_maintenance.py verify --root ROOT --run RUN
```

Run these phases sequentially. Do not maintain files being authored. Never repeat a
completed phase into its original receipt filename; use a new run. `assets` checks
content identity before sharing storage; `compress` checks bytes before and after
and processes each underlying file once. The protected verification covers current
catalogue scenes/journals and catalogue, knowledge and asset evidence. Inspect every
result's `failures`; a completed command alone is not a successful verification.

Backup retirement additionally requires an operator-reviewed `bootstrap.json`
listing candidate cold runs. `backup-plan` scans catalogue/current paths and
metadata/source references, retains current recovery copies and referenced backups,
and checks the newer primary's complete Blender container. It understands both
historic headers and Blender 5 large-block headers. Before `backup-apply`, load
every proposed primary with Blender using `storage_blender_check.py`:

```text
blender --background --factory-startup --disable-autoexec --python-exit-code 1
  --python tools/muscle_workflow/storage_blender_check.py -- ROOT RUN
```

`backup-apply` requires this successful load proof, an unchanged catalogue revision
and unchanged primary/backup fingerprints. It removes only the explicitly planned
`.blend1` paths, with a receipt. It never removes `.blend` primaries.

`archive-create` selects only unreferenced, non-current historical runs from the
reviewed bootstrap. It stores a ZIP plus a manifest containing every original path,
SHA-256, size and modification time. It verifies every member before publication.
`archive-retire` verifies the archive again, refuses current catalogue paths and
changed originals, removes only manifested files, and leaves an `ARCHIVED.json`
pointer. Referenced experiments stay available. Archives on the same drive are
cold storage, not protection against drive failure.

Restore without overwriting edited files:

```text
storage_maintenance.py archive-restore --root ROOT --manifest storage/archives/NAME.manifest.json
```

The restore verifies archive and member hashes before publication. Existing identical
files are retained; different files cause refusal. Keep the ZIP and manifest together.

## Accounting and validation

Folder properties can still count each hard-link path in logical "Size". Use
`storage_inventory.measure` for unique-file stored data, plus volume free space.
Its byte count excludes filesystem metadata and cluster slack. Do not sum logical
journal sizes to estimate physical use after sharing and compression.

Tests: `test_authoring_storage_policy`, `test_storage_maintenance`,
`test_storage_archive`, and Blender `test_authoring_storage_export.py` cover
immutable sharing, independent mutable writes, corruption rejection, compression,
retention guards, archive restoration and debug save/reopen presentation.

References: [NTFS compression](https://learn.microsoft.com/windows/win32/fileio/compression-attribute),
[Blender save preferences](https://docs.blender.org/manual/en/5.0/editors/preferences/save_load.html),
[Blender 5 file-format changes](https://developer.blender.org/docs/release_notes/5.0/core/).

Review validation (October 17, 2026): 23 storage unit tests and Blender export/presentation tests passed, including actual NTFS compression, hard-link sharing, compressed save/reopen, archive retirement/restoration and refusal to overwrite edited files. Catalogue protection handles both absolute and root-relative paths. Archive sources must be canonical immediate children of `runs/`; traversal aliases such as `runs/../assets` are rejected. Maintenance deletion tests ran only in temporary fixtures; no live workflow history was retired during this review.
