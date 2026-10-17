# Partial fiber tightening

`fibers.tighten_preview` (authoring protocol 0.4) tightens the **current Free path** using the existing native V3 length solver. It returns an exact sampled candidate and measurements without changing the scene, mode, attachments, journal or generated objects. Apply the returned `path` with the existing revision-guarded `fibers.path_update`; that operation regenerates dependent outputs and records the edit. No automatic solve is added to Free evaluation.

## Controls

- `fiber_id`, `expected_scene_revision`, `expected_path_revision`: select and guard the current input.
- `max_displacement`: required positive maximum movement of any sample, in **world scene units**, relative to this invocation's input. It is a distance, not a target shortening percentage. Do not assume scene units are meters.
- `accepted_steps`: optional integer 1–64, default **1 per structural span**. This is a work budget, not a percentage or guaranteed iteration count. Rejected trials do not consume accepted steps; the native trial cap still applies.

The operation preserves sample IDs, count, order, topology, structural indices and every fixed anchor. Open and loop paths are supported. Each interval between structural samples is a separate exact seed, preventing ordinary solver resampling from moving a nonuniformly placed middle pin. Loop closing intervals are included. Controlled fibers must first be frozen with `fibers.mode_configure`; tightening does not change their mode implicitly.

## Why steps are not an amount

V3 minimizes regularized true length plus a fidelity term to its anchor-based reference, using adaptive SQP regularization, trust radius and native continuous collision detection. Accepted steps can grow, shrink or stall. There is no universal logarithmic relation between step count, length reduction and arch height. Length reduction is also not monotonically proportional to point displacement. These are standard distinctions between iteration budgets and trust-region step sizes; see the [Ceres solver documentation](https://ceres-solver.readthedocs.io/latest/nnls_solving.html).

For a requested displacement budget `D` and accepted-step budget `K`, the authoring solve caps the existing native trust radius at `D/K`. Each native accepted update moves every sample at most that distance. By the triangle inequality, total displacement is at most `D`, including when fewer steps are accepted. Rejections move no samples. This configures the existing C++ solver; it does **not** blend or clip a collision-checked output afterward. No native ABI or production default changes are needed.

All optimizer iterations, objective calculations, trial acceptance and collision queries stay in the existing C++ controller. Python captures Blender data, configures requests, orchestrates independent spans and validates/reports results. The unbounded core option exists for diagnostics; the public authoring operation requires a bound.

## Validation and limits

Both seed and result must satisfy the existing native SCP/selected-support clearance policy, including its authored local owner-contact exception. An already intersecting seed returns `TIGHTENING_UNRESOLVED` with `TIGHTENING_UNSAFE_SEED`; this tool does not silently reroute or repair that input. Results must retain exact pins, nondegenerate consecutive samples, finite coordinates, the displacement bound, and nonincreasing total length. A budget-exhausted but validated partial result is expected, not a convergence claim.

The response contains `entities[0].path`, `points_before`, `tightening` metrics and per-span accepted/rejected steps and termination. Native backend failure or an unsafe result returns unresolved with no edit. Preview runs are not replay-cached. Revision guards still apply.

These are **source fiber** checks. Mirrored collision, reconstructed base folds, inflation and muscle-to-muscle intersections are not validated by the preview. Native path publication regenerates mirrors and dependent surfaces. Review those results and run `muscles.base_intersections` after applying a set of edits. Tightening cannot remove an arch imposed by fixed structural attachments, nor does shortening alone establish a better anatomical shape.

## Example

```python
preview_request = {
    "dsl": "anthroforge.authoring.protocol", "version": "0.4.0",
    "message_type": "request", "request_id": "tighten-preview-001",
    "op": "fibers.tighten_preview",
    "params": {
        "scene_id": root.name, "fiber_id": fiber.id,
        "expected_scene_revision": current_scene_revision,
        "expected_path_revision": fiber.free_path_revision,
        "accepted_steps": 1, "max_displacement": 0.04,
    },
}
preview = execute(preview_request, root, scene, journal_directory)
assert preview["status"] == "success", preview["diagnostics"]

# Apply the exact preview through the ordinary Free-path transaction.
apply_request = dict(preview_request, request_id="tighten-apply-001", op="fibers.path_update")
apply_request["params"] = {
    k: v for k, v in preview_request["params"].items()
    if k not in ("accepted_steps", "max_displacement")
}
apply_request["params"]["path"] = preview["entities"][0]["path"]
applied = execute(apply_request, root, scene, journal_directory)
```

The example distance is in scene units and is not a universal default. Use fresh request IDs for different inputs. A stale scene/path revision requires a new preview.

## Measured starting point (October 11, 2026)

Fixture: `E:/development/WIP_models/muscle_reconstruction_workflow/features/stacking_completion/v001/assembled-default.blend`, SHA-256 `4cf80d368df1c0bef837ff730a663828c798276e6e29cf841da9bcd0d3e3be8f`. Measurements cover one existing Free fiber each from gastrocnemius, tibialis anterior, sartorius, semitendinosus and rectus femoris; no saved muscle was changed.

One unrestricted step moved samples by **3.30–4.46% of original path length**. Gastrocnemius reached 25.15% movement at an eight-step budget, while semitendinosus reached 6.17%: step count is not a transferable strength setting.

For these five paths, **one step with `D = 0.005 × original path length`** produced modest visible tightening, reducing length by **0.296–0.406%**, with pins unchanged and native source-path validation passing. Four steps under the same total displacement bound produced similar small changes. This is an experimentally supported starting point for these fixtures, not a universally approved anatomical correction.

Reproduce the read-only experiment with `tools/fiber_tightening_probe.py` in background Blender, passing the fixture after `--`. Plot its saved numeric observations with `tools/fiber_tightening_plot.py`. Outputs go to `.artifacts/tightening/`; neither script saves a Blender scene. Tests cover displacement bounds, sampling/scale, exact middle pins, loops, collision blocking, invalid seeds, no Python optimizer/planner, preview immutability and retained attachment deformation.

An additional in-memory apply experiment used all three tibialis anterior fibers through the public preview and `fibers.path_update` APIs. Only that muscle's four source/mirrored BASE/INFL mesh arrays changed; bindings and Free modes were retained, and immediate request replay succeeded without a second application. This is publication/regeneration evidence, not anatomical or inter-muscle packing acceptance. No reconstruction file was saved.

Revalidated October 17, 2026: the combined fiber-tightening/authoring-storage review passed 131 unit tests and 16 Blender integration tests, including real disk-journal preview/apply/replay, compressed debug export reopening, and native source/mirror presentation. The earlier disk-journal permission limitation no longer applies. All 35 read-only trials on the five saved leg fibers completed successfully; the capped one-step length reductions remained 0.296�0.406%. The numeric comparison plot was inspected. The original fixture was not saved or modified; mirrored collision and dependent-muscle quality remain outside the preview validation contract.
