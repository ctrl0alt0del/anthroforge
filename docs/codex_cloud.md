# Codex Cloud development

Use repository `ctrl0alt0del/anthroforge`, starting branch `rc/0.3.20260905`.
The older `main` branch does not contain the current production implementation.

## Working scope

Cloud is for draft implementation, portable checks and small Blender/native
smoke tests on simple files. Full-model experiments, visual geometry acceptance
and production validation are performed locally on the Windows PC when it is
available. Do not launch the torso suite or other large-model runs by default.
Clearly label cloud changes as awaiting local acceptance where applicable.

On 2026-10-17, both Linux cloud and Windows passed 63 native/unit tests and
16 Blender integration tests. The cloud torso baseline opened, saved/reopened
and rendered, but its full rebuild failed with SIGSEGV in QuadWild quantization.
The LE/FAST torso cases therefore did not run. This is an unresolved full-model
failure, not a validated production geometry result. Preserve its logs for
local investigation; the user explicitly deferred further full-model cloud work.

## Environment setup

### Blender/native geometry runtime

The Linux runtime is installed with `python3.11 tools/cloud/geometry_setup.py`.
It pins Blender 5.0.1, verifies downloaded archives and Linux wheel hashes,
installs QuadWild Bi-MDF, and builds the four production C++ libraries with
CMake. Windows retains its existing DLLs, package checks and build scripts.
On Ubuntu install `clang cmake libomp-dev libxrender1 libxi6 libxkbcommon0
libsm6 libgl1 xvfb` first. Allow the official Blender download/mirror hosts,
GitHub release downloads and PyPI. No GPU is needed for CPU previews.

Run actual native and Blender integration tests:

```sh
.artifacts/blender-5.0.1-linux-x64/blender -b --factory-startup \
  --python-exit-code 1 --python tools/cloud/geometry_tests.py
```

The following large-model commands are retained for explicitly requested
experiments only; they are not routine cloud validation.
Supply a private torso fixture separately; setup does not upload model files.
For each case (`baseline`, `rebuild`, `arc5`, `pec2`) and method (`LE`, `FAST`):

```sh
.artifacts/blender-5.0.1-linux-x64/blender -b --factory-startup \
  --python-exit-code 1 --python tools/cloud/torso_validate.py -- \
  --fixture /workspace/fixtures/anthroforge/torso.blend \
  --output /workspace/results/torso/arc5-le --case arc5 --method LE
```

Outputs include a reopened/verified debug blend, numerical report and four CPU
renders. The pectoral fixture uses SECTION_PROFILE, so `pec2` doubles its actual
section depths, not the inactive Max Inflation property. Render-only changes
are applied after saving the debug file. A successful install is not geometry
acceptance; inspect these outputs and the full construction case locally.
Full-model cloud acceptance was not achieved and is no longer the default goal.

For everyday cloud use, `python3.11 tools/cloud/blender.py` accepts Blender's
normal arguments and supplies writable config/cache directories. Run all torso
cases, including a fresh rebuild, with:

```sh
python3.11 tools/cloud/torso_suite.py \
  --blender .artifacts/blender-5.0.1-linux-x64/blender \
  --fixture /workspace/fixtures/anthroforge/torso.blend \
  --output /workspace/results/anthroforge-torso
```

The suite writes `gallery.html`, per-case numerical reports and execution logs,
plus sampled peak RSS for the Blender process tree. It never edits the input.

### Portable-only runtime

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

- Windows DLLs and EXEs cannot run on Linux. Use the maintained Linux build
  and bundle above; do not copy Windows binaries into the Linux installation.
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
