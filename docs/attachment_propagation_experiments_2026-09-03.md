# Attachment Propagation Optimization Experiments

Date: 2026-09-03

## Scope

All timings below come from Blender 5.0.1 executing the real `Cranium Lobe Width`
shortcut in the latest filesystem copy of `skull_muscles.blend`. The source SHA-256
was `4855042F259135C569C3E89B50DF5D0441E6794BEF5E774AEBF924FD8372287E`
before and after every run.

The controlled workload was `7, 1, 7, 1, 7, 1`. Each variant ran in a fresh
factory-startup Blender process. The benchmark includes the real property setter,
dependency runtime, SCP propagation, all 24 Fiber-node attachments, Muscle rebuilds,
and mirror synchronization.

## Results

| Variant | Full median | Attachment median | Muscle median | Mirror median | Result |
|---|---:|---:|---:|---:|---|
| BASE | 755.64 ms | 236.63 ms | 374.88 ms | 69.40 ms | Reference |
| FAST_CAPTURE | 692.89 ms | 193.91 ms | - | - | Accept candidate |
| FAST_HANDLES | 607.57 ms | 100.82 ms | - | - | Accept candidate |
| SHARED_MIRROR | 559.41 ms | 204.13 ms | 324.23 ms | 4.41 ms | Accept with ownership guard |
| FAST_MUSCLE_SIGNATURE | 552.52 ms | - | 244.45 ms | - | Accept candidate |
| FAST_EXACT | **335.25 ms** | **56.51 ms** | **231.82 ms** | **4.63 ms** | Best exact combination |
| PRODUCTION_INTEGRATED | **344.72 ms** | **64.80 ms** | **229.06 ms** | **3.46 ms** | Shipped implementation |
| FAST_MUSCLE_INFLATION | 570.47 ms | - | 255.31 ms | - | Reject: numerical mismatch |
| BARRIER_FUSION | 612.31 ms | 175.51 ms | - | - | Reject: geometrically wrong |
| SPARSE_STENCILS | 706.91 ms | 281.74 ms | - | - | Reject Python implementation |

`FAST_EXACT` combines fast capture, indexed active-handle publication, shared source
geometry for transform-only mirrors, and binary Muscle signatures. Compared with
BASE it is 2.25 times faster, a 55.6% reduction in median full-cycle time.

The final production run reproduces that combined result within 2.9% full-cycle
timing while adding copy-on-write ownership and a compact last-good Fiber snapshot
to prevent stale previews from mutating mirrors. Muscle mesh hashes match `BASE`
and `FAST_EXACT` exactly; active handles match `FAST_EXACT` exactly.

Correctness checks for `FAST_EXACT`:

- every downstream mesh has identical topology and coordinates quantized to `1e-7`;
- zero failed SCPs and zero failed Fibers;
- zero planner or solver jobs;
- SCP and Fiber round-trip errors match BASE;
- all active handles exist and differ from BASE by at most `2.67e-7` world units;
- the `.blend` source is unchanged.

## Findings by proposal

### Change classification

Fourteen of nineteen SCP evaluated local meshes changed between values 1 and 7.
Only SCPs 9, 10, 11, 13, and 16 retained the same evaluated local coordinates.
The existing deformation-generation split is useful, but this production case is
not predominantly transform-only.

### Precompiled attachment stencils

Across the five propagation phases, the runtime captured 22,104 surface vertices,
while the operations referenced only 825 unique vertices, or 3.73%.

A sparse prototype fetched only referenced vertices and remapped indices. It remained
geometrically correct, but capture rose from 99.23 ms to 150.73 ms because many
indexed Blender/RNA reads are slower than one bulk `foreach_get`. Keep stencil
precompilation as a future bulk extraction/native-interface design; reject the
Python implementation.

### Dependency barriers

Capturing all dependency depths once reduced some overhead, but it produced a
maximum Fiber round-trip error of 0.885 world units and a maximum SCP error of 1.805
world units. Descendant evaluated surfaces depend on committed ancestor waves.
Global barrier removal is invalid. A future selective implementation may fuse only
branches proven to preserve evaluated local geometry.

### Fiber handle publication

The old propagation commit resolves four selected handles through general surface
attachment code and scans selection state after all 24 Fiber curves were already
computed. Updating only active handles from the committed node results reduces the
attachment median from 236.63 ms to 100.82 ms by itself. In the combined run,
Fiber commit and handle publication are 10.84 ms.

### Muscle work

Profiling one real shortcut event found:

- about 374 ms in distributed per-vertex inflation;
- about 341 ms in mesh publication;
- about 200 ms in coordinate/topology signature construction;
- topology hashes were calculated twice per output surface.

One binary coordinate/topology signature retains exact output and reduces Muscle
median to 244.45 ms. NumPy-vectorized inflation was faster but failed the strict
`1e-7` geometry comparison, so it is not accepted.

Fixed-topology deformation weights are not valid for the full shortcut range. Several
Muscles change adaptive row counts between values 1 and 7. The exact next step is a
native/vectorized implementation of the current adaptive inflation and surface build,
not freezing topology.

### Mirror synchronization

Current mirror synchronization clears and reconstructs source-identical mesh/curve
data and then mirrors only the object transform. Sharing the authoritative source
data reduces mirror work materially. Production now detaches shared data before a
mirror-specific mutation and restores a compact last-good Fiber snapshot if a stale
source is encountered.

### Slider burst coalescing

The real gradual sequence `1 → 2 → ... → 7 → ... → 1` took 4,287.88 ms across
twelve full requests even with `FAST_EXACT`. Processing only the final value of each
direction would require two requests totaling about 706.09 ms in the same run, an
83.5% reduction. This is a scheduling improvement for dragging; it does not reduce
the latency of one typed value change.

## Production status

The first four recommendations are integrated in `attachment-wave-2`. Remaining
independent work is latest-value slider coalescing and, only if still necessary,
native/vectorized exact adaptive Muscle inflation and surface generation.

Do not ship global barrier fusion, Python sparse stencil capture, or the current
vectorized-inflation prototype.

## Research basis

- Blender dependency graph design: <https://developer.blender.org/docs/features/core/depsgraph/>
- Lazy incremental scene graph evaluation: <https://diglib.eg.org/server/api/core/bitstreams/5a1c9322-1dc1-47ad-8118-50a18934f656/content>
- Self-adjusting computation: <https://www.cs.cmu.edu/~blelloch/papers/ABBHT09.pdf>
- OpenMP 6.0 task/dependency facilities: <https://www.openmp.org/wp-content/uploads/OpenMP-API-Specification-6.0.pdf>
- Coupled cage/skeleton deformation: <https://perso.telecom-paristech.fr/boubek/papers/CoupledCageSkel/CoupledCageSkel.pdf>
- Embedded deformation: <https://people.inf.ethz.ch/~sumnerb/research/embdef/Sumner2007EDF.pdf>

## Artifacts

The isolated runner is `tools/attachment_propagation_experiment.py`. Raw JSON results
are stored in the task visualization directory under `propagation_*.json`.
