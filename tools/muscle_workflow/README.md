# Muscle workflow support

This is agent orchestration and evidence/retrieval support, independent of the
Blender addon runtime. It does not replace the native authoring API or execute an
automatic muscle fitter. The entry point for reconstruction is the personal
`anthroforge-muscle-reconstruction` skill. Project agent roles are in
`.codex/agents/af_muscle_*.toml`; the primary agent coordinates them.

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
then semantically retrieves lessons filtered by stage/status. A generic query
still receives the base-width check at the fiber stage. Distances rank candidates;
the librarian must assess applicability from actual geometry and context.
If the retrieval service fails, the packet retains required procedures and marks
`retrieval_status: unavailable`; repair retrieval while continuing independent work.
Hypotheses and rejected/superseded entries never become mandatory procedures merely
because someone assigned them the procedure kind.

`remember` verifies evidence, accepts only the next revision, keeps prior revisions
immutable and updates the index. Repeating an identical record is idempotent.
Supply a new revision to mark a record superseded; historical evidence remains.
Failed index writes can be recovered with `reindex`, without losing canonical JSON.
Historical measurements apply only to their recorded fixture/revision. Requirements
and case observations have separate statuses; neither implies a successful repair.

`contracts.py` holds the v1 schemas. Validation checks actual evidence files and
their hashes. A ready handoff needs a matching stage context and librarian brief
for the same inputs; it cannot contain failed/unresolved checks. This detects stale
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

Sources: [Chroma MCP](https://github.com/chroma-core/chroma-mcp),
[Chroma client/server mode](https://docs.trychroma.com/docs/run-chroma/client-server),
[Codex custom agents](https://learn.chatgpt.com/docs/agent-configuration/subagents).
