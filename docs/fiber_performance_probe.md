# Fiber Performance Probe

`tools/fiber_perf_probe.py` runs in a disposable Blender process. It opens the input `.blend` without saving it and emits one machine-readable line prefixed with `AF_PROBE_JSON=`.

Every result includes benchmark metadata: OS, CPU, machine, Python and Blender versions, Blender build hash, repository commit, arguments, foreground/background state, input size, and SHA-256. This makes results comparable across machines and revisions.

## Runtime scenarios

- `property-burst`: applies a solver-property burst, verifies debounce/coalescing, flushes the request, and records refinement slice distribution.
- `handle-burst`: moves an endpoint handle while exercising the production attachment request path.
- `selection`: measures repeated targeted selection requests and exposes accidental downstream work.
- `touch-batch`: applies multiple touch edits under one authoring transaction and emits one targeted attachment request.
- `hydration`: measures file load and records all runtime work caused during hydration.
- `cache-lifecycle`: compares cold, warm, invalidated, and post-invalidation solves.
- `telemetry-overhead`: alternates equivalent solves with collection disabled/enabled and reports median overhead.
- `runtime-scenarios`: runs all scenarios in isolated reloads of the supplied file.

Example:

```powershell
& 'C:\Program Files\Blender Foundation\Blender 5.0\blender.exe' `
  --background --factory-startup --python tools\fiber_perf_probe.py -- `
  --blend 'E:\development\WIP_models\skull_muscles.blend' `
  --mode property-burst --fiber FIBER_14 --events 20
```

## Request telemetry

Set `AF_DEPS_TELEMETRY=1` to collect records without console tracing. `AF_DEPS_TRACE=1` enables both telemetry and the human-readable trace unless telemetry is explicitly disabled. Both are off by default.

The runtime retains at most 256 completed records. Each record contains cause, source, event, aspects, quality, queue/run time, dependency and driver phase timings, solver iterations, actual BVH queries, persistent Fiber curve writes, low-level timings, bounded-cache bytes, and a fixed-bucket progressive-slice histogram. Use `request_telemetry(clear=True)` from `core.deps.runtime_trace` to retrieve and clear records.

Progressive work retains the originating request record after the request itself returns. Later slices, collision queries, iterations, writes, and cache publication therefore remain attributed to the edit that started the solve.
