# QuadWild anatomical topology

Topology Method defaults to **QuadWild: Muscle FLOW + Paths** for construction.
**Instant Meshes** remains explicitly selectable. Changing the method marks the
construction settings stale; it does not change an existing final mesh or rebuild
it automatically. Final-skin LE/FAST updates remain independent of this setting.

## Production flow

1. Capture the draft surface, authored LOOP guides, native muscle material charts,
   explicit FLOW fibers, hierarchical density settings and root symmetry plane.
2. Sample longitudinal muscle directions with surface normals. Each native chart
   supplies a central longitudinal feature path. Explicit FLOW fibers supply
   additional paths through the fiber's **Topology FLOW Guide** checkbox (open
   fibers only; this does not change the fiber's OPEN/LOOP geometry mode). Mirror
   charts are captured only where a mirror rule exists.
3. Prepare the existing surface proxy and authored LOOP annuli. Solve one half
   when symmetry is enabled, in arbitrary root-plane coordinates.
4. Run QuadWild's automatic field preparation, then the native AnthroForge
   confidence-weighted four-way field solver and existing-edge path routing.
   If Bi-MDF specifically rejects an unsupported patch valence, retry once with
   paths selected longest-first at 8%-of-longest-axis spatial separation. This
   refinement retains all captured direction samples in the field and reports an
   explicit warning with selected/requested path counts. Other failures do not
   trigger this retry. These are C++
   calculations. No fixture IDs or experiment paths are used.
5. Trace the guided field and run Bi-MDF quantization. Up to four bounded density
   attempts select the closest realized quad count. The requested count is a
   target, not a guarantee. Apply the existing adaptive density refinement,
   mirror assembly, authored annuli and validation pipeline.
6. Prepare and publish the durable LE/FAST reference through the existing
   construction transaction. Temporary draft removal follows successful reference
   publication, as before.

The guiding paths are snapped to existing triangle edges. They are not exact
anatomical curves embedded into the mesh. The automatic native chart selection
replaces the experiment's four manually selected fiber indices; it is deterministic
and applies to all native muscles with regular charts. Unsupported charts produce
warnings and can still receive explicit FLOW fiber guidance.

## Issues and failure policy

Finite, usable quad meshes can publish with geometry warnings. These include
intersections, native discarded patches, topology validation failures, unmet density targets and unresolved
guide joins. When authored annuli cannot be stitched, the annuli and automatic fill
are retained, joining strips are omitted, and an explicit **open seams** warning is
reported. This is not a successful watertight join or a hidden fallback.

Missing/corrupt dependencies, failed native tracing, nonfinite geometry, invalid
indices, absent output, cancellation and resource limits fail the job and preserve
the existing output. No automatic switch to Instant Meshes occurs.

The upstream Windows v0.0.2 quantization executable can return `2147483651` after
writing its mesh. That specific exit is accepted only when a freshly generated,
finite, indexed all-quad artifact can be read. It always emits a warning. Other
nonzero exits fail. Stale output files cannot satisfy this exception.

Native phases have a 600-second / 6-GiB process budget; the enclosing field/remesh
worker has an 1,800-second / 6-GiB process budget. Cancellation terminates the process
tree. Runtime records and logs are retained in the job's diagnostic folder. The
memory measurements are per process, not a total machine-memory guarantee.

Deformation-reference preparation runs in a separate Blender process with a
600-second / 6-GiB budget. Failure retains construction inputs and reports a
preparation issue. A legacy mesh can retain its new topology and draft for retry;
an existing durable reference and final mesh are preserved when replacement
preparation fails. Geometry generation does not imply reference readiness.

## Distribution and compatibility

`vendor/quadwild/manifest.json` pins the Windows x64 executables, configuration and
license hashes. Runtime loading is offline and verifies all listed files. Build the
AnthroForge native field helper with `native/topology/build_windows.ps1` or the
maintained `native/build_windows.ps1` entrypoint. The package tool verifies both the
helper ABI and dependency bundle.

Topology protocol 6 persists FLOW samples, identities and paths. Readers accept
protocols 4 and 5 with empty guidance. Root settings use the normal Blender
save/undo/duplication and import/export paths. The capture hash includes guidance
and backend settings; construction signatures include the selected backend.

QuadWild Bi-MDF is GPL-3.0, shipped unmodified with its license. Corresponding source:
https://github.com/cgg-bern/quadwild-bimdf/tree/v0.0.2 . Upstream usage:
https://github.com/cgg-bern/quadwild-bimdf/blob/main/README_release.md .

The backend does not guarantee stable layout after rebuilding a slightly changed
surface, collision-free geometry, or superior deformation. Anatomical organization,
mesh validity, and deformation quality must be evaluated separately.
