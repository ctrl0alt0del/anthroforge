# Bidirectional inflation

One unchanged fiber surface can now generate two independently configured sides. Existing muscles remain **One Side**. No fibers are added, moved, resnapped or solved by an inflation edit.

## Blender controls

Select a muscle and open **Edit Muscle VCP → Sides → Both Sides**. The first activation copies all of A's settings to B, including branch settings. Later toggles retain B. Each depth is measured from the base; enabling B adds thickness rather than halving A.

Choose **Edit Side A/B**, then the inflation law and its controls. Ordinary open lofts support Control Point, Distributed and Section Profile, independently on each side. Branched assemblies retain Control Point and Distributed; Section Profile is disabled in the mode selector for the entire assembly.

- Copy A to B / B to A copies the selected part's complete retained parameter banks.
- All Parts copy actions apply to every part.
- Section Profile Scale/Reset acts on the selected side only.
- Reverse Inflation Sides reverses the envelope without changing source winding or fiber placement.
- The selected Control Point gizmo edits only that part and side. A/B direction arrows are viewport overlays, not additional scene objects; hide them with Blender's global overlay toggle.
- Disabling B retains a flat base-side surface. Disabling the envelope displays the base once. Zero/coincident faces are not duplicated.

The BASE and INFL object identities stay intact. INFL now has its own topology and a face attribute `af_inflation_side`: 0 coincident, 1 A, 2 B. A cropped output uses the same base-domain clipping on both sides. No artificial caps are added.

## Authoring

Capability: `muscle_inflation_envelope.v1`, protocol 0.4.0.

1. `muscles.inflation_inspect`, with `target: {muscle_id: ...}`, returns configuration, retained banks, supported laws, base/configuration revisions and last-published diagnostics.
2. `muscles.inflation_preview` requires the complete configuration plus `expected_scene_revision`, `expected_base_revision`, `expected_configuration_revision`. `include_geometry: true` returns base, A, B and composed topology as an asset. It does not mutate Blender.
3. `muscles.inflation_configure` uses `muscle_id`, the same configuration and guards. Publication and the journal receipt roll back together on failure. A repeated request ID replays only while its persisted postcondition is still current.

The configuration is the `muscle_inflation_envelope.v1` object specified in the design. Parts use `main` and stable branch connection IDs. Each side contains `enabled`, `mode`, and complete active-mode `parameters`; Control Point accepts `control: "automatic"` or a world-space point. Inactive mode settings remain stored and inspectable.

`muscles.create_from_surface` also accepts `initial_envelope`, mutually exclusive with `initial_configuration`. Document volume presets accept `envelope`. Compilation, publication, reconciliation/adoption and regeneration preserve both sides. Automatic envelope fitting and shape-intent rewriting are explicitly unsupported; configuration remains explicit. Ordinary section measurements expose both side profiles and their material span; they are not a certified solid-volume measurement.

The previous `profile_preview`, `profile_configure`, and branch inflation mutations reject a Both Sides target with `ENVELOPE_API_REQUIRED`. Domain/crop edits preserve the envelope. All legacy One Side operations retain their existing interpretation.

## Implementation boundaries

- `core/authoring/envelope_config.py`: wire validation and storage-independent configuration.
- `core/authoring/envelope_numeric.py`: lowering into immutable numerical requests.
- `app/use_cases/muscle_envelope.py`: shared preview/configure transaction for UI and authoring.
- `core/visualization/muscle_envelope_storage.py`: Blender A/B storage, initialization and part mapping.
- `core/vcp/muscle_envelope.py`: prepared-side caching, orientation, crop and result assembly.
- `native/fiber_ccd/af_muscle_envelope_*.hpp`: native Section Profile evaluation, existing legacy-kernel access, composition and geometry diagnostics.

Build with `native/fiber_ccd/build_windows.ps1`; the default library is `af_fiber_ccd_v3_28.dll`. Missing envelope exports fail explicitly. There is no Python numerical fallback for this feature. Existing branch preparation and connector orchestration are reused; the solver and transfer implementation are unchanged.

## Validation and practical limits

The numerical tests cover native Section Profile parity, all three Control Point falloffs against independently evaluated signed sides, mixed laws, reflection, cropping, zero depth and cache isolation. Blender integration covers UI actions, B gizmo movement, no solver invocation, branch persistence and reversal, import scaling, complete document adoption/regeneration, mirrors, stale receipts, journal/publication rollback and crop edits.

Final verification: 1,050 unit tests completed successfully (6 skipped, 1 expected failure), 19 feature-specific Blender tests passed, 29 authoring-profile tests passed, and 37 branch regression tests passed. The broader 104-test muscle run reports 11 legacy precision subtest failures reproduced on clean pre-feature code, as detailed below. Generated transfer schemas remain structurally unchanged.

The FDI fixture has 910 base vertices / 832 quads. Both Sides produces 1,666 vertices / 1,664 quads. Across two runs on this machine, each with 15 preview samples, median times were 4.9–8.7 ms cold, 1.5–3.0 ms warm and 1.8–3.0 ms for a B-only edit; full configure/publication took 60–99 ms. The final run overlapped the unit suite. These are this fixture's measurements, not a whole-body performance guarantee.

The existing FDI base is an underside, not a centered sheet. Equal B depth produced sampled bone penetration of 0.0537 scene units; half-depth B produced 0.0340. The saved conservative test copy uses B at 2% of A and reports 0.00917 maximum sampled penetration, below the user's 0.01 review tolerance. No triangle-crossing pairs were found by the explicit self-intersection check. This validates feature operation, not a new anatomical fit or an exhaustive collision certificate.

Native diagnostics separately report boundary/nonmanifold edges, degenerate faces, wrong-side samples and large normal turns relative to the base. A normal turn over 90 degrees is a review trigger, not proof of a self-intersection. Bone collisions and full self-intersections are not certified by these cheap diagnostics. A pair of open surfaces is not automatically a valid closed solid.

On save/reopen, the FDI test retains both configurations, topology, all Free path records, visible source/mirrored fibers (66), and native SCP colors. Evaluated coordinates drift by up to 0.0000186 scene units; the unchanged one-sided FDI reproduces exactly the same drift. Separate synthetic envelope persistence tests are exact. Legacy muscle persistence tests also reproduce their existing 0.000000238 coordinate discrepancy on a clean pre-feature commit; those failures are reported separately rather than counted as envelope passes.

Feature fixtures, timings, previews, and `fdi_bidirectional.blend` are under `E:/development/WIP_models/muscle_reconstruction_workflow/features/2026-09-26-bidirectional-inflation/v001`. The review copy was saved with `StaticScene.save_debug_copy` and reopened normally. The production FDI source was not overwritten.
