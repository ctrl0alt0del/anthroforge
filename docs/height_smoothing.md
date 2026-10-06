# Height smoothing

Height smoothing is an optional production effect on a muscle's own inflation.
In **Edit Muscle VCP → Inflation → Height Smoothing**, select **Height** and set
Radius, Strength and Maximum Height Change. Both-side muscles have independent
controls for A and B; branches use the selected part's controls. Off is the
default and bypasses the smoothing DLL entirely. A zero strength, radius or
maximum change also bypasses it.

The base, fibers, their attachments, and inflation directions do not move.
The effect cannot remove directional noise or repair an invalid base. It is not
the proposed muscle-to-muscle support graph or position (`X`) smoothing.

## Numerical contract

For each full, pre-crop material part, obtain its native displacement
`D = Xown − B`, height `h0 = |D|` and, where nonzero, direction `d = D/h0`.
Keep exactly zero displacement fixed rather than inventing a direction there.
Using the base's deterministic triangulation, construct the cotangent Laplacian
`L`, barycentric lumped mass `M`, and `Q = Lᵀ M⁻¹ L` with libigl. PIQP solves

`min ½(h − h0)ᵀM(h − h0) + ½ strength · radius⁴ · hᵀQh`.

Constraints preserve every exterior part boundary, branch interface, and existing
zero-height crease exactly. Interior heights are nonnegative, cannot exceed the
part's original maximum, and stay within Maximum Height Change of `h0`.
Explicit part boundaries remain creases; this version does not blend across them.
The outer surface becomes `B + h d`. Existing crop interpolation is applied
after smoothing, so a new crop edge does not become a zero-height rim.
Radius and Maximum Height Change are world distances; import scaling scales both.
Strength is dimensionless. The objective does not guarantee volume preservation:
a large radius can flatten a desired broad bulge, even within the change bound.

Branched input retains native seam identities. Each part is solved separately,
with shared interfaces fixed; spatially coincident unrelated vertices are never
welded. Collapsed attachment-tip triangles are excluded from energy assembly and
reported; unused tip vertices keep their original output. Nonmanifold,
inconsistently oriented or otherwise unusable energy domains fail explicitly.

The C++ core owns assembly, PIQP iteration and independent KKT certification.
Geometric feasibility uses an absolute tolerance; stationarity and
complementarity use force/energy-relative residuals, consistent with the solver's
relative stopping criteria. Absolute complementarity is also reported. This
avoids treating an arbitrary common objective multiplier as a geometric defect.
Failed solves leave C output buffers untouched, return an
explicit error, and cannot publish partial geometry. A final local check rejects
new face reversals or collapse. This is **not** a self-intersection or bone
clearance certificate; ordinary geometry warnings and contextual review still
apply. Lowering inflation can expose an existing base/bone intersection.

## Authoring

Capability: `muscle_height_smoothing.v1`. Use the existing guarded
`muscles.inflation_inspect`, `muscles.inflation_preview` and
`muscles.inflation_configure` operations. Add this optional member to a part's
`a` or `b` side inside its `muscle_inflation_envelope.v1` configuration:

```json
"smoothing": {
  "mode": "HEIGHT",
  "radius": 0.2,
  "strength": 0.8,
  "max_change": 0.05
}
```

`mode` is `OFF` or `HEIGHT`; all three numeric values must be finite in [0,1000].
Omitting the member means default Off. Default Off settings are omitted during
capture, preserving existing envelope configuration receipts. Preview does not
mutate the scene. Configure uses the existing scene/base/configuration revision
guards, transaction, durable journal receipt and replay checks. Reconciliation
adopts the configuration into the recipe; regenerated geometry retains it.

Preview and publication diagnostics include `height_smoothing.a` and, when
applicable, `.b`: part index, solver iterations, material samples, exact pins,
excluded collapsed triangles, solve/total milliseconds, KKT residuals and maximum
height change. These are numerical diagnostics, not anatomical acceptance.

Only settings are persisted. No native handles, matrices or vertex-index cache
are stored in the blend. Every changed-input evaluation constructs a fresh native
session; existing upstream content caches remain responsible for their own
immutable inputs. Mirrors derive from the final published source geometry.

## Implementation and verification

- `native/smoothing`: isolated energy, QP adapter, certification, orchestration
  and material-domain adapter; the approved strategy interfaces remain reusable.
- `core/vcp/height_smoothing*`: immutable settings and versioned batch binding.
- `core/vcp/muscle_smoothing.py`: side/part orchestration before crop/composition.
- RNA/UI and existing envelope authoring use the same numeric pipeline.

Run `native/smoothing/build_windows.ps1` to build the versioned Windows DLL, or
`native/build_windows.ps1` for both production native targets. Dependencies are
vendored with licenses and hashes; neither build nor runtime needs experiment
directories, network downloads, SciPy, or Python optimization. The existing addon
packager requires this DLL. CMake builds the portable core and its injected-solver
tests independently; Blender's packaged binding currently targets Windows.

Run Blender with `--background --factory-startup --python tests/blender_runner.py
-- --pattern=test_height_smoothing.py`, plus the envelope and numeric regression
suites. The tests cover smoothness against known geometry, exact pins, scale and
rotation covariance, maximum change, collapsed tips, all inflation laws, Free
samples, branches, opposite sides, crop, Off bypass, input invalidation, UI
rebuilding, rollback, authoring replay, recipe regeneration, mirrors, import
scaling and save/reload.

References: [PIQP](https://predict-epfl.github.io/piqp/),
[libigl discrete differential geometry](https://libigl.github.io/tutorial/#laplacian).
