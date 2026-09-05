# Fiber V3 Persistent Native Controller — Production Trial

## Outcome

The persistent C++ controller is compiled into the packaged production DLL and is the default for
both synchronous `solve_v3(...)` and progressive `begin_v3(...)`. Human visual review accepted the
qualified collision-valid native paths despite their non-bitwise Python trajectories.

The controller owns the contact query, active-set SQP solve, limiter injection, CCD, acceptance,
regularization, trust update, span scheduling, and final native validation. Python performs capture,
one begin call, one finish call, publication, and independent stitched validation.

## Correctness corrections made during productionization

- CCD limiters migrate to a current surface contact or retire immediately.
- Contact identity distinguishes distance, crossing, containment, and limiting features.
- Same-key contacts reproduce Python dictionary replacement semantics.
- Repeated limiter injection preserves trust twice and shrinks it on the third injection.
- Coherent obstacle-side metadata and contact model gaps are retained natively.
- Stationary rejection and stalled termination are available in the native controller.
- The packaged ABI advertises the operation, coordinator, and controller capability bits.

The first accepted `skeleton_comb_base/FIBER_1` step now agrees with the Python controller within
`1.26e-11`; at 20 accepted steps the maximum difference is `1.27e-5` and accepted/rejected counts
match at `20/30`.

## Read-only production benchmark

Four native workers were used. Source hashes before and after each run were identical.

| Fixture | Python V3 | C++ controller | Speedup | C++ status | Maximum point delta |
|---|---:|---:|---:|---|---:|
| sphere/FIBER_2 | 759.6 ms | 131.1 ms | 5.80x | BUDGET_EXHAUSTED, valid | 0.206481 |
| skull/FIBER_1 | 1103.5 ms | 223.0 ms | 4.95x | STALLED, valid | 0.001016 |
| skull/FIBER_14 | 257.5 ms | 313.1 ms | 0.82x | BUDGET_EXHAUSTED, valid | 0.032578 |
| skull-skin/FIBER_1 | 1104.5 ms | 218.1 ms | 5.06x | STALLED, valid | 0.001035 |
| skeleton/FIBER_1 | 2526.2 ms | 2296.0 ms | 1.10x | BUDGET_EXHAUSTED, valid | 0.005546 |

The remaining divergence comes from the rank-deficient contact active-set solve. NumPy uses a
rank-revealing least-squares solution; the fast native solve uses deterministic diagonal
regularization. A native full rank-revealing decomposition was tested, but made the real skull run
exceed two minutes and was rejected.

## Activation policy

The production path defaults to native:

```text
AF_FIBER_V3_NATIVE_CONTROLLER=1  -> persistent C++ controller (default)
AF_FIBER_V3_NATIVE_CONTROLLER=0  -> Python diagnostic reference
```

The controller exposes resumable `begin/step/finish/cancel` calls. Progressive execution advances
one native SQP trial per scheduler step; synchronous execution batches 64 trials without changing
trial order. Planner/warm seed selection, shortcutting, checkpoints, cancellation, migration,
publication and stitched independent validation retain their production interfaces. Missing or
incompatible native capability fails closed and never selects Python automatically.

## Python functionality retained at the boundary

| Capability | Owner after native default |
|---|---|
| Blender capture, planner and warm-seed selection | Python, unchanged |
| Optional shortcut policy and cache identity | Python, unchanged |
| Exact midpoint span construction and owner synchronization | Shared setup, unchanged |
| Length/fidelity/spacing objective and adaptive regularization | Native controller |
| Active contacts, limiter injection, CCD and validation | Native controller |
| Global accepted-step budget and round-robin span scheduling | Native controller |
| Interactive checkpoints and cancellation | Python scheduler over resumable native trials |
| Final stitched validation, migration, provenance and publication | Python, unchanged |
| Missing/incompatible native backend | Fail closed as `BACKEND_UNAVAILABLE` |
| Diagnostic reference | Explicit `AF_FIBER_V3_NATIVE_CONTROLLER=0` only |

The native trajectory is deterministic but deliberately not bitwise identical to NumPy SQP.
The result records `diagnostics.controller`, and every real-file comparison above validated both
outputs independently. The accepted native path can therefore differ in termination or finite-cap
geometry without silently losing a production feature.

Benchmark artifacts:

- `v3-production5-native-default-sphere.json`
- `v3-production5-native-default-skull.json`
- `v3-production5-native-default-skull-skin.json`
- `v3-production5-native-default-skeleton.json`

They are stored in the task visualization directory, not in the add-on or source `.blend` files.
