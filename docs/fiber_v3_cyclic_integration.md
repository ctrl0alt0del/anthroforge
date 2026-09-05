# Fiber V3 Global Cyclic Integration

## Production decision

Fiber V3 production 7 supports open, cyclic, and symmetric-loop Fibers. A loop is
one globally coupled optimization state. It is not decomposed into independent
anchor-to-anchor spans, and it no longer falls back to V1.

V3 has zero curvature and every supported loop has at least one exact authored
anchor. The implementation therefore cuts the cyclic indexing at the first hard
anchor, duplicates that anchor as the last internal point, and pins both copies.
This is an exact linear representation of the same closed polyline objective:

- the internal state has `N + 1` points and includes the closing edge;
- the two endpoint copies are identical exact pins;
- true length, spacing, contact, CCD, and validation include every cyclic edge;
- one global SQP controller owns one contact set and one accepted-step budget;
- the duplicate endpoint is removed before diagnostics and publication.

This hard-anchor cut preserves the block-banded open solve. A cyclic Woodbury
factorization is unnecessary for the accepted V3 objective because no curvature
stencil crosses the cut and the cut position is fixed exactly.

## Integrated behavior

- Planner output remains a seed. Cyclic planner anchor indices are remapped to the
  exact V3 reference indices before optimization.
- Warm states are cached and remapped cyclically, including the final-to-first
  anchor span.
- Optional shortcut processing includes the closing planner span.
- Native owner-contact intervals cover both incident edges of every hard anchor.
- Symmetric-loop expansion mirrors anchor ownership as well as positions.
- Static validation checks all edges, including the closing edge.
- Precise terminal configuration errors survive the final publication wrapper.

The accepted numerical objective, adaptive regularization, conditional spacing,
native controller, publication rules, and collision guarantees are otherwise
unchanged from V3 production 6.

## Qualification

Automated coverage includes exact output count, closing-edge length, global-state
shape, native/Python clear-case parity, cyclic warm continuation, localized owner
contact, blocked hard-pin diagnostics, Blender cyclic commit, and Blender
symmetric-loop routing.

Full verification after integration:

- 599 unit tests passed (6 skipped, 1 expected failure).
- 201 Blender Fiber tests passed.
- Architecture guardrails and the 15-line function limit passed.

Read-only qualification used `skull_muscles.blend` without modifying its source
hash. Representative native results on the current workstation were:

| Fiber | Result | Validated | Accepted / rejected | Wall time |
|---|---|---:|---:|---:|
| FIBER_15 | STALLED | yes | 8 / 20 | 216.6 ms |
| FIBER_18 | BUDGET_EXHAUSTED | yes | 180 / 199 | 335.1 ms |

Both outcomes are publishable under the accepted V3 finite-work policy because
their final states passed independent collision validation. `FIBER_17` has an
authored hard anchor owned by `SCP_3` inside unrelated collider `SCP_2:11`; it now
reports `INVALID_CONFIGURATION` precisely. V3 cannot legally move that hard pin
or exempt the unrelated collider.

Source SHA-256 before and after qualification:

`A7C4033AB2EB7479EAEC4A069CB1D7DDF9FECC5D5C43037863B02A9F9BB7EF06`
