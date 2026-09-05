param([string]$CudaRoot = "$env:TEMP\anthroforge-cuda-13.3\toolkit")
$ErrorActionPreference = "Stop"
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$VsWhere = "C:\Program Files (x86)\Microsoft Visual Studio\Installer\vswhere.exe"
$VisualStudio = & $VsWhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
$VcVars = Join-Path $VisualStudio "VC\Auxiliary\Build\vcvars64.bat"
$Nvcc = Join-Path $CudaRoot "bin\nvcc.exe"
$Source = Join-Path $Here "af_fiber_cuda_experiment.cu"
$Output = Join-Path $Here "af_fiber_cuda_experiment.dll"
$Runtime = Join-Path $CudaRoot "bin\x64\cudart64_13.dll"
if (-not (Test-Path $Nvcc)) { throw "CUDA 13.3 nvcc is unavailable" }
if (-not (Test-Path $VcVars)) { throw "Visual C++ x64 build tools are unavailable" }
$Command = 'call "{0}" && "{1}" -O3 -std=c++17 -arch=sm_89 --shared "{2}" -o "{3}" -Xcompiler "/O2 /EHsc"' -f $VcVars,$Nvcc,$Source,$Output
cmd.exe /d /s /c $Command
if ($LASTEXITCODE -ne 0) { throw "CUDA Fiber experiment build failed: $LASTEXITCODE" }
Copy-Item -LiteralPath $Runtime -Destination $Here -Force
Remove-Item -LiteralPath (Join-Path $Here "af_fiber_cuda_experiment.exp") -ErrorAction SilentlyContinue
Remove-Item -LiteralPath (Join-Path $Here "af_fiber_cuda_experiment.lib") -ErrorAction SilentlyContinue
