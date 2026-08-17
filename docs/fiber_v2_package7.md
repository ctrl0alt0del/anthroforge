# Fiber V2 Package 7 — Fixed Objective and Adaptive Progress

## Qualification outcome

Package 7.1 and Package 7.2 are both **rejected as production candidates**.
Package 7.1 froze the raw planner corridor and produced undesirable anatomical
arching. Package 7.2 acquired and froze a P5.1-style shape, which removed that
visual regression, but adaptive recovery converged on only one of seven
production Fibers and was slower than Package 6.1 on all seven.

The Package 7.2 trace proves that the remaining failure is below the controller:
the post-solve heuristic contact projection does not generate a coherent descent
direction for the fixed structural/contact merit. Trust adaptation can shorten
a useful direction but cannot repair an inconsistent local/global map. No
Package 7.3 should be attempted until contact targets are integrated into the
global banded system.

See `docs/fiber_v2_package71.md` and `docs/fiber_v2_package72.md` for evidence.

## Decision

Package 7 will be an isolated V2 solver experiment built on Package 6.1. Its
purpose is to make the unaccelerated solver converge to one defined answer and
to distinguish genuine blockage from a recoverable rejected step.

Package 7 will not add Anderson acceleration, change Blender runtime
publication, migrate saved Fibers, or enable V2. Those remain later packages.

Package 6.1 solved a dispatch problem: it activates Package 6 only when trust
bounding and distance certificates are likely to pay for themselves. It did not
solve the base iteration problem. In the seven-fixture benchmark:

| Result | Count |
|---|---:|
| `CONVERGED` | 1 |
| `BLOCKED` | 5 |
| `BUDGET_EXHAUSTED` | 1 |

The failures are not all equivalent. Skeleton/FIBER_1 accepts all 12 trials and
reduces merit from `337.86` to `224.17`; it is progressing and correctly reports
budget exhaustion. The five Package 5.1 paths stop after their first or second
rejected trial even when prior accepted steps reduced merit materially.

## Baseline defects Package 7 must not preserve

The current executable Package 5.1/6 map does not fully match the written V2
mathematical contract:

1. `_base_candidate` passes the current iterate to `solve_structural`, replacing
   the planner fidelity reference every trial.
2. `_merit` evaluates `structural_energy(points, points)`, which makes fidelity
   energy identically zero and ignores the fixed planner reference.
3. `_stationarity` differentiates the same moving-reference objective.
4. Convergence checks only the accepted displacement; fixed-objective
   stationarity, relative energy progress, feasibility stability, and contact
   stability are not required.
5. Package 5.1 maps any rejected unchanged-contact trial directly to `BLOCKED`.
   It does not distinguish a zero CCD step, a merit rejection, a nonfinite
   proposal, or a proposal that only needs damping.
6. Package 6 changes trust radius from accepted/CCD state only. It has no ratio
   between predicted and achieved reduction, and a clipped step can never
   report convergence even when the unbounded fixed-point residual is small.

Package 7 begins by making the fixed objective executable. Adaptive stopping is
not allowed to hide or compensate for these defects.

## Preserved contracts

- Package 4.3 produces one validated route branch and exact-count reference.
- Package 6.1 remains the initial P5.1/P6 collision-policy dispatcher.
- Planner, contacts, CCD, and final validation use one immutable collider and
  owner-contact policy.
- Authored endpoint/touch pins are eliminated exactly.
- Length and curvature weights remain independent and normalized.
- Every accepted move from a valid state is native-CCD certified.
- Final safety uses the independent static validator.
- Accepted-step properties remain hard caps, not requested iteration counts.

## Package 7 mathematical contract

### Fixed objective

For each resolution level, capture one immutable planner-derived reference
`q`. With normalized spacing `h`, use:

\[
E_s(x;q)=\rho\|x-q\|^2+
         \frac{w_L}{h}\|D_1x\|^2+
         \frac{w_B}{h^3}\|D_2x\|^2.
\]

Collision projections introduce auxiliary targets `p`:

\[
F(x,p)=E_s(x;q)+w_C\sum_c\|A_cx-p_c\|^2.
\]

- `q`, pin indices, constraint-slot layout, weights, and factorization key are
  fixed for the level.
- The local step updates only `p` from the current accepted `x`.
- The global step minimizes `F(x,p)` with exact pin elimination.
- A warm seed may initialize `x`; it cannot change `q` or the objective.
- Contact-free solving must reach the direct banded solution in one global
  step, independent of iteration cap.

Package 7 may initially retain the qualified Package 5 contact response as an
implementation reference, but it must compare that response against the fixed
`q` objective. A contact formulation that cannot produce a coherent predicted
reduction fails the package before adaptive control is enabled.

### Normalization

All progress tests use the request length scale `L`:

\[
\bar F=F/L^2,
\quad r_{fp}=\|G(x)-x\|_\infty/L,
\quad r_{stat}=\|\nabla_xF(x,p(x))\|_\infty/L.
\]

`G(x)` is the unbounded local/global proposal before trust clipping or CCD.
Testing the accepted displacement alone is forbidden because a tiny CCD
fraction can make a blocked state appear converged.

Relative energy progress is:

\[
r_E=|\bar F_k-\bar F_{k-1}|/
    \max(1,|\bar F_0|,|\bar F_k|).
\]

Clearance and pin tolerances remain the resolved world-space tolerances already
captured in the request.

## Base trial

Each trial executes exactly:

1. Project local contact targets from the current accepted state.
2. Solve the fixed-`q` global system.
3. Compute predicted reduction using the frozen local targets.
4. Apply Package 6.1's current P5.1 or trust-bounded collision policy.
5. Certify the motion with native CCD.
6. Reproject contacts at the trial state and compute achieved reduction.
7. Accept only a finite, feasible, merit-improving state.
8. Record residuals and update the adaptive controller.

For a valid proposal, define:

\[
\rho_k=\frac{F(x_k,p(x_k))-F(x_{trial},p(x_{trial}))}
              {F(x_k,p_k)-F(y_k,p_k)}.
\]

The denominator is the local/global model's predicted reduction. A nonpositive
or nonfinite denominator is a model failure, not convergence.

Initial controller thresholds:

| Ratio/state | Action |
|---|---|
| nonfinite candidate/model | reject, count numerical failure |
| invalid or uncertain CCD | reject, fail closed |
| `rho < 0.10` | reject and halve trust/damping |
| `0.10 <= rho < 0.25` | accept only if feasible; halve next radius |
| `0.25 <= rho <= 0.75` | accept and keep radius |
| `rho > 0.75` at trust boundary | accept and grow radius by `1.5` |

Contact-set changes suppress radius growth for that trial. Thresholds are
engine-versioned and will be tuned only through the prescribed ablation, not per
Fiber.

## Dynamic recovery above Package 6.1

Package 6.1 chooses an initial collision policy from the first workload. Package
7 adds a deterministic state transition rather than terminating after the first
failure:

```text
P51_FAST
  -> DAMPED_P51       on one merit/model rejection
  -> TRUST_RECOVERY   on two limited/zero CCD steps or two rejected damped steps

TRUST_RECOVERY
  -> P51_FAST         after two full, high-quality, stable-contact steps
  -> BLOCKED          after two zero steps at minimum trust with the same limiter
```

Rules:

- The first proposal remains the fast Package 5.1 proposal.
- A rejected trial does not consume the accepted-step cap.
- Total trials are still bounded by `2 * accepted_cap + 8`.
- At most two recovery activations are allowed per level.
- A changing limiting pair/contact set resets the blockage counter.
- Package 7 records why every proposal was rejected.

This recovery is separate from Package 6.1's performance dispatcher: a workload
that was initially cheap may still need temporary trust control after it reaches
an obstacle.

## Adaptive resolution levels

The authored final node count remains exact. Package 7 uses nested counts only
to obtain a cheaper starting state:

1. Start at `max(anchor_count, min(8, final_count))`.
2. Double the count until the authored final count is reached.
3. Derive a fixed corridor reference `q_N` independently at every level.
4. Resample the accepted state only as the next level's initial seed.
5. Preserve pin ordering and pin targets exactly during every transition.
6. Never promote an unsafe level.

Budget policy:

- no more than 25% of the accepted-step cap may be spent before the final level;
- at least 75% remains reserved for the authored final count;
- promote after two feasible stable-contact steps when either the coarse
  residual reaches `10x` the target tolerance or three-step residual reduction
  falls below 20%;
- a coarse level can guide the next level but can never be the committed result.

The experiment must ablate levels separately. If the fixed final-count solve is
faster or more reliable on a fixture, Package 7 skips coarse levels for that
request signature. Level selection must not become another unconditional cost.

## Convergence and termination

### `CONVERGED`

All conditions must hold on the authored final node count:

- pins satisfy the resolved pin tolerance;
- independent node and edge clearance are within slack;
- no CCD uncertainty remains;
- normalized fixed-point residual is at most `1e-4` interactive or `1e-6`
  final;
- normalized stationarity residual meets the same threshold;
- relative energy progress is at most `1e-5` interactive or `1e-7` final for
  three accepted steps;
- the contact set and route branch are stable for those three steps.

### Other terminal states

- `BLOCKED`: two zero CCD steps at minimum trust with the same limiting pair and
  stable contacts after the allowed recovery activation.
- `STALLED`: eight accepted final-level steps reduce neither fixed/stationarity
  residual nor normalized merit by at least 1% while CCD can still move.
- `BUDGET_EXHAUSTED`: the accepted-step cap ends while a five-step progress
  window still shows at least 1% improvement.
- `UNSAFE_OUTPUT`: repeated nonfinite/model failures or independently invalid
  final points.
- `NO_FEASIBLE_PATH`: planner or exact-count corridor construction fails.
- `BACKEND_UNAVAILABLE`: required native collision capability is unavailable.

One merit rejection is never sufficient evidence for `BLOCKED`.

## Best validated preview

Package 7 never exposes a rejected candidate. It tracks one best independently
validated state per level, ranked lexicographically by:

1. safety and pin validity;
2. highest completed resolution level;
3. normalized fixed-point plus stationarity residual;
4. fixed-objective energy.

Only an improved state can replace the previous preview. If Package 7 terminates
without convergence, the best exact-count validated state is returned with its
truthful terminal reason. Runtime publication and `FAILED_PREVIEW` UI behavior
remain deferred, but the experiment records the exact state that would be
shown.

## Diagnostics

Add bounded trace fields for:

- fixed `q` signature and level count;
- fixed-objective fidelity, length, curvature, contact, and total energy;
- predicted and achieved reductions and their ratio;
- unbounded fixed-point and normalized stationarity residuals;
- accepted/rejected trial count per level;
- rejection reason: `CCD_ZERO`, `CCD_UNCERTAIN`, `MERIT`, `MODEL`, `NONFINITE`;
- P5.1/damped/trust mode transitions and recovery count;
- trust/damping radius before and after each trial;
- contact-set signature and limiting CCD pair;
- progress-window classification;
- best-preview replacement count;
- controller, projection, global solve, CCD, and validation time.

The adaptive controller's own timing is measured separately from candidate and
collision work.

## Implementation portions

Package 7 is implemented and benchmarked in four isolated portions. A failed
portion stops the package; later portions do not compensate for it.

### P7.1 — Fixed-reference truth

- Make `q` immutable in candidate, energy, merit, and stationarity paths.
- Implement coherent local-target/global-solve ordering.
- Add normalized residuals and predicted/achieved reduction diagnostics.
- Retain the current fixed final node count and Package 6.1 dispatch.

Gate:

- collision-free output matches the direct dense/banded reference;
- warm and cold output agree within tolerance;
- raising the cap cannot change a converged clear result;
- accepted fixed-objective energy is nonincreasing.

### P7.2 — Rejection recovery and truthful termination

- Add ratio-based damping/trust updates and bounded recovery transitions.
- Replace immediate rejection-to-`BLOCKED` mapping.
- Add progress windows and precise reasons.

Gate:

- synthetic merit rejection recovers without false blockage;
- true zero-step fixture reaches `BLOCKED` within its bounded trial limit;
- Skeleton/FIBER_1 remains progressing or converges, never falsely stalls;
- no recovery crosses the planner homotopy or weakens clearance.

### P7.3 — Adaptive levels

- Add nested references, exact pin transfer, promotion, and final-budget reserve.
- Compare fixed-count and adaptive variants before enabling per signature.

Gate:

- final count and pins are exact;
- adaptive and direct converged results agree within tolerance;
- adaptive levels materially reduce wall time or accepted final-level steps;
- otherwise the dispatcher selects direct final-count solving.

### P7.4 — Best-state preview record

- Track and expose only improved validated states.
- Add render/probe artifacts for accepted, rejected, promoted, and terminal
  states without connecting Blender runtime.

Gate:

- recorded oscillation fixture shows no visible retry or rollback sequence;
- every displayed comparison state is independently valid;
- unsuccessful output retains the best exact-count attempt and truthful reason.

## Experiment matrix

Compare V1, Package 5.1, Package 6.1, and each Package 7 portion.

Mandatory fixtures:

- Skull: Fibers 4, 9, 13, 14, and 22.
- Skull-skin: Fiber 1.
- Skeleton: Fiber 1.
- The recorded oscillating/1000-iteration Fiber.

Protocol:

- verify nonblocking pins before every run;
- use one immutable snapshot and route policy per comparison;
- seven warmed repetitions in randomized order;
- record cold and warm results separately;
- retain source-file SHA-256 and never save supplied files;
- produce left-to-right Blender renders and temporary review `.blend` files;
- include an ablation table for fixed `q`, recovery, adaptive levels, and full
  Package 7;
- report controller cost separately from solver/collision work.

## Gates

Correctness:

- all outputs returned as valid pass independent node/edge validation;
- exact pins pass on every level and final result;
- fixed objective and stationarity are computed against immutable `q`;
- warm/cold and higher-cap converged results agree within tolerance;
- no single rejection maps to `BLOCKED`;
- no coarse result is mislabeled final/converged.

Behavior:

- at least five of the seven currently eligible fixtures converge;
- every remaining result identifies the limiting condition precisely;
- the 1000-iteration fixture terminates truthfully within 64 accepted final-level
  steps;
- repeated solve of a converged result changes no point beyond tolerance;
- previews never show rejected or lower-quality rollback states.

Performance:

- controller overhead p95 below `0.10 ms` per trial and below 1% end-to-end;
- direct Skull/FIBER_13 remains below `30 ms` median;
- no already-converged/unchanged fast-path case regresses more than 5% from
  Package 6.1;
- representative 64-node validated result remains below `250 ms`;
- Skeleton/FIBER_1 first target below `300 ms`, stretch target below `200 ms`;
- adaptive levels must save at least 15% wall time or 25% final-level accepted
  steps on every signature where they activate.

Package 7 fails if it improves the convergence label by loosening tolerances,
accepting an unsafe state, or merely spending substantially more iterations.

## Deferred work

- Package 8: safeguarded Anderson acceleration using the qualified Package 7
  map as the base reference.
- Package 9: production-owned resumable arrays and fair multi-Fiber scheduling.
- Package 10: migration, packaging, rollout, and human anatomical qualification.

## Research basis

- [Projective Dynamics](https://www.projectivedynamics.org/projectivedynamics.pdf)
  establishes the fixed local/global energy-decrease structure.
- [Trust Region Methods](https://epubs.siam.org/doi/10.1137/1.9780898719857)
  motivates accepting and resizing steps from achieved versus predicted
  reduction.
- [IPC](https://ipc-sim.github.io/file/IPC-paper-fullRes.pdf) motivates
  feasibility-preserving collision-aware acceptance.
- [Anderson Acceleration for Geometry Optimization and Physics Simulation](https://archive.ymsc.tsinghua.edu.cn/pacm_download/523/11728-AALG.pdf)
  is intentionally deferred until this unaccelerated fixed map is correct.
