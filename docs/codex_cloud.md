# Codex Cloud development

Use repository `ctrl0alt0del/anthroforge`, starting branch `rc/0.3.20260905`.
The older `main` branch does not contain the current production implementation.

## Environment setup

Create a private environment in Settings > Codex Cloud > Environments, select
this repository and the current branch, and use this setup request:

> Prepare AnthroForge on Python 3.11. Read AGENTS.md and docs/codex_cloud.md.
> Run python3.11 tools/cloud/setup.py. Use the resulting
> .artifacts/cloud-venv/bin/python for tests. No service, API key, or Blender
> instance is needed for the portable suite. Verify the suite, then publish
> the environment. Do not claim native geometry or Blender validation.

The install script is `python3.11 tools/cloud/setup.py` (Python 3.12 also works
with the pinned dependencies). Package installation needs PyPI access.
There is no background service to start. For subsequent checks run:

```sh
.artifacts/cloud-venv/bin/python tools/cloud/check.py
```

The environment must be published in Codex; committing these files does not
create or publish an account environment. Select the published environment on
mobile to start work that can continue while the Windows computer is off.
See [official environment setup](https://learn.chatgpt.com/docs/environments/cloud-environments).

## What is covered

The explicit smoke suite covers issue reporting, authoring storage contracts,
topology data/protocol operations, branched muscle FLOW, deformation scheduling,
and durable reference validation. Each module runs in a separate process to
avoid cross-test mock/module pollution. Failures are never silently excluded.
The NTFS-only test and two Windows-native deformation execution tests are
explicitly skipped on Linux; reference serialization/identity tests still run.

GitHub Actions runs the same command on Ubuntu/Python 3.11. Extend the suite
when another test module is verified portable. Do not interpret this selected
suite as the complete regression suite.

## Boundaries and handoff

- Production targets Blender 5.0 on Windows. Native DLLs, QuadWild EXEs,
  package loaders and Windows build scripts are not Linux executables.
- Do not bypass native checks, create Python optimizer fallbacks, or rewrite
  platform paths merely to make cloud tests pass. Native changes require the
  maintained Windows build/load workflow and representative geometry tests.
- Blender integration tests live under tests/blender. Actual fixture models,
  authoring journals, comparison galleries and skills on C:/ or E:/ are local,
  not included in this checkout. Missing fixture access is not passing QA.
- No external model archives or local credentials are uploaded by setup.
  Personal skills named in AGENTS.md are not installed in cloud automatically;
  disclose unavailable required skills rather than inventing their contents.
- Keep a cloud task's final response explicit about tests run, checks not run,
  and Windows/Blender follow-up commands. Preserve production geometry behavior
  unless changing it is the actual task. Work on codex/ branches when creating
  branches; do not merge or push without the user's authorization.

## Current implementation landmarks

- QuadWild production topology and muscle FLOW: core/topology,
  adapters/topology, native/topology, vendor/quadwild. Branched patches derive
  FLOW from evaluated material grids and shared seams; they do not promise
  exact retained edge rings or eliminate all mesh defects.
- Build-once final skin: core/deformation and its adapters/workers. LE is the
  default, FAST selectable. Updates preserve connectivity; no silent rebuild.
- Generic issues: core/issues. Report recoverable quality defects as warnings.
- Native Free-fiber tightening: core/vcp/v3/tightening.py and
  app/authoring/native_tightening.py. Preview is read-only; apply via path_update.
- Opt-in storage pooling: core/authoring/storage*.py;
  maintenance tools under tools/muscle_workflow remain Windows-oriented.

Historical visual results and local chat history are not available solely
because a cloud task uses this repository. Ask for the relevant evidence when
an experiment depends on those results.
