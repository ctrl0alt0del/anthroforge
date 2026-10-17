# Muscle workflow support

This is coordinator-operated evidence/retrieval support, independent of the
Blender addon runtime. It does not replace the native authoring API or execute an
automatic muscle fitter. The entry point for reconstruction is the personal
`anthroforge-muscle-reconstruction` skill. No stage or librarian agent is required.

Storage policy, conservative cleanup and archive restoration are documented in
[authoring storage](../../docs/authoring_storage.md). Current builds and evidence
retain their original paths; automated exports use versioned filenames.

## Installed paths

- Artifacts: `E:/development/WIP_models/muscle_reconstruction_workflow`.
- Python: `runtime/.venv/Scripts/python.exe` inside that directory.
- Canonical lesson revisions: `knowledge/lessons/<id>/r000001.json`.
- Evidence snapshots: `knowledge/evidence`; indexed copies: `knowledge/chroma`.
- Model cache: `runtime/embeddings/all-MiniLM-L6-v2`; embeddings run locally.
- MCP: `anthroforge_chroma` in the user's Codex configuration.

The official `chroma-mcp` package uses one Chroma HTTP service bound to
`127.0.0.1:8769`. The launcher starts it hidden on demand. A shared service avoids
several agent processes opening the embedded database independently. There is no
cloud API key or remote vector store. The registered MCP exposes retrieval tools;
curation uses the helper so JSON history and the index stay consistent.

`AF_MUSCLE_WORKFLOW_HOME` overrides the artifact root. Its `settings.json` supplies
the loopback port. A new root needs `runs`, `knowledge/lessons`, `knowledge/chroma`,
`runtime`, `checks`, `logs`, settings and its installed runtime. Do not point two
roots at the same port. Keep source references outside a run read-only.

## Commands

Run these with the external Python and `tools/muscle_workflow/workflow.py`:

```text
init-run --name fcu --source SOURCE_FILE --target TARGET_FILE
context --stage base --query "Prepare this multihead muscle" --run RUN_DIRECTORY --inputs HEAD2 BONE_CONTEXT
context --stage base --query "Unequal length branched Free paths" --features branch material-stations --run RUN_DIRECTORY
features --stage base
lesson --id LESSON_ID --revision REVISION
record-use --run RUN_DIRECTORY --file DECISION_NOTE_JSON
usage --run RUN_DIRECTORY
catalogue
catalogue-save --file UPDATED_CATALOGUE_JSON --expected-revision CURRENT_REVISION
authoring-version
reference --file ARTIFACT
remember --file LESSON_JSON
validate --kind librarian_brief --file BRIEF_JSON
validate --kind handoff --file HANDOFF_JSON
validate --kind feedback --file FEEDBACK_JSON
reindex
health
```

`init-run` creates stage, knowledge, feedback, log and temporary directories plus
a hashed source/target manifest. It references large originals without moving or
copying them. `context` rejects changed original inputs and saves a receipt bound
to the actual stage inputs. It always includes applicable active procedures,
then retrieves four topic-diverse short lesson cards. Both `base` and `fibers`
include the combined stage's procedures and lessons. Optional geometric feature
tags prioritize matching conditions; the coordinator still assesses applicability.
Default modeling queries exclude engineering fixes and historical experiments;
use `--category engineering|history|all` deliberately. Superseded advice is never
injected. `--full` returns full records, or use `lesson` to open just one exact case.
If the retrieval service fails, the packet retains required procedures and marks
`retrieval_status: unavailable`; repair retrieval while continuing independent work.
Hypotheses and rejected/superseded entries never become mandatory procedures merely
because someone assigned them the procedure kind.

`remember` verifies evidence, accepts only the next revision, keeps prior revisions
immutable and updates the index. Repeating an identical record is idempotent.
New revisions require a curated `card`: `when`, `do`, `check`, `limits`, `basis`,
`topic`, `tags`, `category`. The condition, action, checks, limits and tags must fit
240 actual model tokens; oversized cards fail ingestion rather than lose their tail.
Full observations and evidence remain in immutable case JSON. Legacy records remain
readable and are explicitly marked for curation in packets. Index-version changes
trigger reindexing even if record revisions have not changed.
Supply a new revision to mark a record superseded; historical evidence remains.
Failed index writes can be recovered with `reindex`, without losing canonical JSON.
Historical measurements apply only to their recorded fixture/revision. Requirements
and case observations have separate statuses; neither implies a successful repair.
Group cards by shared mechanism using `topic`, not merely muscle name. Retain useful
starting configurations, uncertainty and user acceptance. Keep exact parameter
presets in case metadata; do not turn case-specific tolerances into general rules.

`record-use` saves an immutable decision note bound to the actual retrieved revision
and context receipt. Each selected lesson gets a disposition (`applied`, `adapted`,
`not_applicable`, `skipped`), a brief decision/result, and effect (`helped`, `neutral`,
`harmed`, `unknown`, `not_tested`). Observed effects require evidence. Record important
decisions, not every retrieved card; do not backfill invented usage for historical runs.
`usage` summarizes notes without claiming causal benefit. See the skill's practical
knowledge reference for JSON examples and generalization criteria.

`contracts.py` holds the backward-compatible v1 schemas, including optional legacy
lesson cards and the new usage record. Validation checks actual evidence files and
their hashes. A ready handoff needs a matching stage context and librarian brief
for the same inputs; the coordinator authors that legacy-named brief. It cannot contain failed/unresolved checks. This detects stale
or incomplete records, not anatomical correctness. The coordinator still owns
dependency invalidation, visual review and the final acceptance decision.

## Installation and checks

The installed versions are pinned in `requirements.txt`; the complete resolved
environment is recorded in `runtime/requirements.lock.txt` in the artifact root.
Install into that external virtual environment with `uv pip install --python ...
-r tools/muscle_workflow/requirements.txt`. `seed_knowledge.py` bootstraps the maintained
procedures from project documentation; rerunning skips existing IDs so later
knowledge is not replaced. Historical cases and their immutable evidence remain
in the external knowledge store and are curated with `remember`, not bundled as
dependencies on a particular local experiment. `configure_codex.py` sets only missing
options on the already registered `anthroforge_chroma` entry.

Check the actual protocol with `check_mcp.py`, which retrieves a seeded procedure
in one fresh session and two concurrent fresh sessions, without requiring any
historical muscle study. Run record/storage tests with:

```text
python -m unittest discover -s tools/muscle_workflow -p "test_*.py" -v
```

New MCP registrations may require a fresh Codex session to appear in its tool list.
The helper can be run directly without waiting for tool-list discovery. Installation
must preserve unrelated model, service-tier and permission preferences.

## Completion and build versions

The central register is `catalogue/catalogue.json` under the artifact root;
immutable revisions are in `catalogue/revisions`. The old run-specific catalogues
are historical evidence. Schema v2 lives in `catalogue_schema.py`; its exported
JSON Schema is alongside the central data. Entries count anatomical work items,
including separately planned portions/slips; they are not a count of all human muscles.
The three deltoid portions are grouped into one family for completion.

Each accepted family identifies an exact blend, journal manifest, user-acceptance
evidence, technical review, authored/mirrored sides and build provenance. Earlier
candidates do not imply completion. The user accepted only the latest pectoral and
deltoid on September 24. Read `next_selection` for the current queue; queued does
not mean construction has already started. `not_started` denotes no current
registered candidate, not proof that no older experiment ever existed.

`needs_reverification` means a saved candidate is deliberately held for a future
check and is **not approved**. It differs from `ready_for_review` (awaiting the
current review) and `needs_rebuild` (known reconstruction work required). It
requires a current build with pending acceptance, the review stage, and a reason
or verification task in `remaining_work`. It does not count as accepted and does
not prevent selecting a different muscle. Preserve its exact build and journal.

AI approach IDs and per-stage method versions describe construction choices;
authoring protocol, Git revision, source fingerprint and native runtime build are
separate fields. Named approach definitions are immutable: materially changing
the method needs a new ID. Parameter tuning alone does not require a new approach.
Historical exact addon builds not captured at the time remain explicitly unknown.

`init-run` now captures the current approach and local authoring source fingerprint,
including dirty production files. `authoring-version` refreshes it after code changes.
The fingerprint identifies on-disk sources, not code already loaded inside Blender;
record the active native build from the actual runtime when available. Before
publishing a catalogue build, record the methods and implementation actually used,
including stage changes after run initialization. Changing defaults never rewrites
the provenance or user acceptance of previous artifacts. Save uses an expected
revision guard and retains prior records.

Sources: [Chroma MCP](https://github.com/chroma-core/chroma-mcp),
[Chroma client/server mode](https://docs.trychroma.com/docs/run-chroma/client-server),
[Codex custom agents](https://learn.chatgpt.com/docs/agent-configuration/subagents).
