# On-demand Fiber pin repair

## Scope

`Repair Fibers` is a recovery command for any loaded file. It does not depend
on a preceding shortcut, deformation, edit, or solve. The command evaluates the
file exactly as it exists when the user presses the button. It is available in
**Action Library → Fiber Utilities** and operates on the active AnthroForge root.

## Repair contract

- Detect invalid endpoint, midpoint, and loop pins with the same production
  preflight, collider world, owner exemptions, radius, and numerical slack used
  by Fiber solving.
- Minimize world-space displacement from the authored pin while preserving its
  current SCP whenever a valid attachment exists.
- Preserve midpoint normal offset.
- Permit an automatic owner transfer only for a clear unrelated-SCP outlier.
- Produce valid `surface_param_v2` barycentric bindings.
- Apply repairs per Fiber atomically and create one Blender undo step.
- Recompute every Fiber in the active root as one final-quality group after all
  repairs are committed.
- Leave unresolved pins unchanged, highlighted, and reported by Fiber and role.

## Search algorithm

1. Capture one evaluated collider world and one evaluated surface per relevant
   SCP.
2. Run hard-pin preflight on every Fiber and deduplicate violations by authored
   pin.
3. For each invalid pin, search its current owner surface for collision-valid
   barycentric samples. Cache candidate validity by owner, offset, radius, and
   collider generation so pins sharing an SCP reuse the expensive work.
4. Select the nearest valid seeds, project the segment from the original pin to
   each seed back onto the owner surface, and bisect the first invalid-to-valid
   transition. This finds a close feasible boundary attachment rather than
   snapping to a coarse mesh vertex.
   Candidate clearance includes a scale-aware serialization guard so stored
   barycentric weights remain valid after save and reload.
5. If an unrelated blocker requires movement greater than five collision radii,
   also solve on the blocker surface. Transfer ownership only when that repair is
   within three radii and less than half the same-owner displacement.
6. Apply all planned bindings for one Fiber in memory and rerun the full
   production preflight. Roll back that Fiber if any planned pin remains invalid.
7. Publish the successful Fiber repairs, invalidate attachment/solver caches,
   and enqueue one all-Fiber recompute group through the production V3 coordinator.

Production search should start with a coarse barycentric subdivision and refine
only the best triangles. It may increase subdivision when no feasible seed is
found. The independent final preflight is mandatory regardless of search level.

## Skull baseline result

The untouched `skull_muscles.blend` contains eight invalid hard pins across
seven Fibers before any shortcut or edit. The read-only experiment found and
applied feasible plans in memory for all eight. Final production preflight
reported zero remaining violations for every affected Fiber.

- Seven repairs preserve their original owner.
- One `FIBER_7` touch transfers from `Brow_Ridge` to the unrelated
  `Brow_Ridge.001`: 4.49 mm instead of a much larger same-owner move.
- Selected movements span 4.49–19.10 mm in the current one-unit-equals-one-metre
  convention.
- The production runtime scan takes 2.45 seconds in a fresh Blender process.
  Slice p95 is 7.26 ms and the measured maximum is 15.06 ms.
- The grouped 24-Fiber final recompute takes 6.45 seconds versus 6.61 seconds
  through the prior ungrouped V3 entry points on the same repaired fixture.
- The source file SHA-256 remains
  `a7c4033ab2eb7479eaec4a069cb1d7ddf9fecc5d5c43037863b02a9f9bb7ef06`.

## Required production safeguards

- Preview the count, maximum displacement, and every proposed owner transfer in
  the confirmation/report area before committing.
- Never transfer between ancestor and descendant SCPs automatically.
- Never treat a nearest-surface result as proof of clearance; use the complete
  collider query and final preflight.
- Abort or retain individual Fibers when no feasible attachment is found.
- Do not run downstream solves until the pin-repair transaction is complete.

## Qualification artifacts

- `tools/fiber_repair_qualification.py` runs the production scanner, transaction,
  grouped recompute, source-hash check, and save/reload verification.
- Generated reports and `.blend` copies live under ignored `artifacts/`; the source
  fixture is never saved by automated qualification.
