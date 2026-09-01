# Cranium Lobe Width shortcut: real Blender full-cycle profile

Date: 2026-09-01  
Fixture: `E:\development\WIP_models\skull_muscles.blend`  
Fixture SHA-256: `4855042f259135c569c3e89b50df5d0441e6794bef5e774aebf924fd8372287e`

## Executive result

The user's observation was correct at the profiled revision. The shortcut path was not solving
different Fibers in parallel. It interleaved their sessions on Blender's main thread and advanced
each selected Fiber sequentially because `AF_FIBER_V3_MULTI_SESSION` defaulted to `0`. After this
qualification, the bit-identical multi-session path was enabled by default; `0` remains the serial
reference override.

The second and larger problem is scheduling amplification. The production refinement timer returns
10 ms between slices. This Cranium edit required about 1,223 slices, so timer pacing alone contributed
about 12.22 seconds. The measured full timer-paced cycle was 20.62 seconds.

Forcing the existing native multi-session controller used four native workers, retained the exact
same output, and reduced the timer-paced cycle to 8.43 seconds. This is a controlled comparison,
not a production change.

## Method

Each run launched a fresh Blender 5.0.1 process, opened the real skull file, used the real addon,
assigned `Cranium Lobe Width.proxy_float = 1.1`, updated the real depsgraph, let the normal dependency
drivers enqueue Fibers, drained the real V3 sessions, then processed the real grouped downstream
Muscle/Fiber Surface synchronization and final view-layer update.

Two scheduler modes were measured:

- compute lower bound: the normal refinement callback was drained without the 10 ms timer wait;
- timer paced: the same callback was advanced at its production 10 ms cadence.

One additional run enabled the existing, otherwise dormant, multi-session native controller using
`AF_FIBER_V3_MULTI_SESSION=1`. No solver settings, inputs, iteration limits, or validation rules were
changed. The source blend was never saved; its hash was identical before and after every run.

## Full-cycle measurements

| Configuration | Full wall | Fiber drain | Slices | Cross-Fiber workers | Output digest |
| --- | ---: | ---: | ---: | ---: | --- |
| Current production, compute lower bound | 7.22 s | 5.65 s | 1,225 | 0 | `11427207...2732` |
| Existing multi-session path, compute lower bound | 4.93 s | 3.52 s | 349 | 4 | `11427207...2732` |
| Current production, timer paced | 20.62 s | 19.33 s | 1,223 | 0 | `11427207...2732` |
| Existing multi-session path, timer paced | 8.43 s | 7.08 s | 335 | 4 | `11427207...2732` |

The multi-session path improved the compute-only full cycle by 1.46x and the timer-paced full cycle
by 2.45x. Timer-paced output was also identical to unpaced output.

## Current production stage breakdown

The following is the compute-only lower-bound run, which separates active work from timer waiting.
`apply_points` is nested inside the phase totals and must not be added again.

| Stage | Time | Share of 5.65 s Fiber drain | Evidence |
| --- | ---: | ---: | --- |
| Native SQP solve | 3.215 s | 56.9% | 3,360 main-thread advances |
| Native/contact initialization | 1.045 s | 18.5% | 371 initialization advances |
| Planner | 0.591 s | 10.5% | 24 planners |
| Per-Fiber world preparation | 0.455 s | 8.0% | 24 WORLD phases |
| Collider phase | 0.058 s | 1.0% | 24 phases |
| Seed and span setup | 0.060 s | 1.1% | 48 phases |
| Coordinator/bookkeeping remainder | 0.231 s | 4.1% | drain minus measured phases |

Before refinement, the shortcut setter took 0.76-0.95 seconds across fresh runs. In the detailed
run, request creation occupied 0.551 seconds of that setter time, including 0.260 seconds of hard-pin
preflight and 0.119 seconds repairing the two currently invalidated pins (`FIBER_2`, `FIBER_7`).
The remaining shortcut/SCP/dependency work was about 0.402 seconds.

After all Fiber commits, the grouped downstream rebuild took 0.398 seconds and the final depsgraph
view update took 0.045 seconds. Downstream scheduling itself was only 0.004 seconds, so downstream
request creation is not the bottleneck; the actual grouped rebuild is modest but measurable.

## Why the interactive run reaches about 20 seconds

The timer-paced current-production run spent 19.33 seconds draining Fibers:

- approximately 12.22 seconds were the explicit 10 ms intervals between 1,223 callbacks;
- approximately 6.28 seconds were measured active COLLIDERS/WORLD/PLAN/SEED/SPANS/NATIVE work;
- the remainder was publication and coordinator overhead.

The timer is therefore compounding a compute problem. Each callback already has a 12 ms work
budget, but the code adds a further 10 ms before the next callback. The delay is paid more than one
thousand times for this edit.

Timer pacing also amplified viewport publication. The compute-only run called `apply_points` 806
times. The timer-paced run called it 2,264 times because 24 live sessions independently crossed the
50 ms drawing interval while the solve remained active. These are transient preview writes, not
2,264 final results. They help explain repeated viewport stalls while trying to orbit or zoom.

## Parallelism audit

Profiled serial-default evidence:

- `AF_FIBER_V3_MULTI_SESSION` was unset and resolved to disabled at the profiled revision;
- 929 coordinator turns reported zero workers;
- `step_native_controllers` was never called;
- every Fiber advance was observed on one Python/main thread;
- the scheduler often selected four Fibers, but called `_prepare`/`advance` for them sequentially.

This is cooperative round-robin scheduling, not cross-Fiber parallel solving. Native OpenMP may
still parallelize sufficiently large operations inside one Fiber, but it did not make the 24 Fiber
sessions run concurrently.

With the dormant multi-session controller forced on:

- 64 native multi-session calls were made;
- up to 12 sessions were submitted together;
- four native workers were used on 62-63 turns;
- the aggregate solver work was unchanged: 1,510 accepted steps, 1,847 rejected steps, 3,351 CCD
  sweeps, 2,854 contact queries, 2,251 measures, and 2,251 validations;
- final statuses and the complete point-data digest were identical.

The documentation says automatic multi-session scheduling is enabled, but that describes the older
sweep batching policy. The actual persistent-controller multi-session branch has no AUTO mode and
defaults to off. This is a documentation/runtime mismatch.

## Why Fibers visibly finish one by one

Ordinary shortcut recalculation commits each Fiber as soon as that Fiber terminates. In the
current compute-only run, the first Fiber committed at 3.55 seconds and the last at 6.61 seconds.
That three-second stream of individual commits creates the visible one-by-one effect.

With native multi-session enabled, the first commit occurred at 3.06 seconds and the last at
4.35 seconds. Results still commit individually, but the visible completion window shrank from
about 3.05 seconds to 1.29 seconds.

## Workload and result audit

The dependency system requested all 24 Fibers, and all 24 final point hashes changed. This was not
an unexplained full-sync fallback: every Fiber in the fixture has at least one hard-pin owner in the
Cranium hierarchy, so the current dependency contract considers every Fiber affected by the parent
change.

Every output passed final validation. Terminations were:

- 8 `CONVERGED`;
- 13 safe `STALLED`;
- 3 safe `BUDGET_EXHAUSTED`;
- 0 unsafe, blocked, invalid, or failed outputs.

`FIBER_17` is the main tail outlier. It consumed 1.139 seconds of active current-production time,
with 51 accepted steps, 269 rejected trials, 605 contact queries, and 317 CCD sweeps. The next
largest active costs were `FIBER_18` at 0.620 seconds and `FIBER_1` at 0.291 seconds. Multi-session
reduced `FIBER_17` to about 0.772 seconds, but it remained the dominant Fiber because its own
rejection/contact workload cannot be eliminated merely by running other Fibers concurrently.

## Prioritized conclusions

1. The existing persistent multi-session controller is the strongest already-implemented gain.
   This exact fixture demonstrates deterministic parity and a 2.45x timer-paced full-cycle gain.
   It should be production-qualified and activated through a real AUTO policy instead of remaining
   behind an off-by-default environment flag.
2. The 10 ms reschedule interval must be redesigned together with the 12 ms work budget. Reducing
   callbacks via multi-session helps, but paying a fixed delay after every bounded slice remains the
   largest current cost.
3. Bulk shortcut previews need publication coalescing. More than two thousand `apply_points` calls
   are unnecessary for one edit. Selected/visible Fibers can publish first while background Fibers
   publish much less often or only on validated completion.
4. WORLD, planner, and native/contact initialization remain effectively serial and total about
   2.1 seconds in the timer-paced run. They need shared world/contact capture and batched native
   initialization after multi-session solving is enabled.
5. `FIBER_17` needs a separate rejection/contact-tail investigation. It alone performs 269 rejected
   trials, but changing its numerical policy is higher risk than fixing scheduling and parallelism.
6. The downstream rebuild is not the primary problem. It is one grouped pass of about 0.4 seconds.

## Production follow-up: persistent asynchronous coordinator

The qualified follow-up is now production behavior in `fiber-v3-production-9` with native ABI
`v3_9`. The refinement timer no longer advances native numerical iterations. It performs bounded
main-thread capture/setup and polls one persistent C++ coordinator while that coordinator advances
all submitted Fiber sessions independently of Blender's event timer.

Three fresh-process runs of the same real shortcut measured 3.710-3.731 seconds full-cycle, with a
3.731-second median. The equivalent synchronous multi-session path measured 3.959-4.585 seconds,
with a 3.968-second median. This is an 82% reduction from the earlier 20.62-second paced runtime
and a further 6% reduction from paired synchronous production-9 execution. The earlier comparison
includes other accepted runtime changes made before production-9; the paired 6% result isolates
asynchrony itself.

The async and synchronous results had the exact same complete point digest,
`a9aea6fa16c9ce716b5fc6338169d666aaad2a6f5c31e8ef55b6633b0fd3b4c7`, the same status
distribution, and an unchanged source hash. Callback count fell to 148-153 and transient
`apply_points` count to 202-211. The remaining worst main-thread call is a 0.59-0.60 second
`FIBER_17` native/contact initialization; numerical SQP/CCD execution no longer blocks the main
thread in repeated timer slices.
