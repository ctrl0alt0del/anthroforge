# Isolated Fiber CUDA collision experiment

This directory is not imported by AnthroForge and does not replace the production V3 backend.
It measures whether a shared multi-Fiber batch is large enough to amortize GPU launch,
transfer, and synchronization costs.

The experiment implements the same double-precision segment/triangle distance primitive as
`native/fiber_ccd/af_fiber_ccd.cpp`. Triangles remain resident on the GPU. Pair indices may
either be uploaded per query or cached, while moving Fiber segments are uploaded per query.

## Build

```powershell
./setup_toolchain.ps1
./build_windows.ps1
```

`setup_toolchain.ps1` downloads SHA-verified CUDA 13.3 redistributable compiler components
from NVIDIA into `%TEMP%/anthroforge-cuda-13.3`. It does not install a system-wide toolkit.
The compiled DLL and CUDA runtime remain local to this directory.

## Benchmark

```powershell
python ../../tools/fiber_cuda_collision_experiment.py `
  --dataset ../../artifacts/fiber_cuda_experiment/skull_cranium_valid.npz `
  --output ../../artifacts/fiber_cuda_experiment/skull_cranium_valid_benchmark.json
```

See `artifacts/fiber_cuda_experiment/REPORT.md` for the current RTX 4080 result.

Official references:

- [CUDA installation guide for Windows](https://docs.nvidia.com/cuda/cuda-installation-guide-microsoft-windows/)
- [CUDA event timing](https://docs.nvidia.com/cuda/cuda-runtime-api/group__CUDART__EVENT.html)
- [CUDA Graphs](https://developer.nvidia.com/blog/cuda-graphs/)
