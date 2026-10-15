# Maintained production native targets. Individual target scripts remain usable.
$ErrorActionPreference = 'Stop'
& "$PSScriptRoot/fiber_ccd/build_windows.ps1"
if ($LASTEXITCODE -ne 0) { throw 'Fiber library build failed' }
& "$PSScriptRoot/smoothing/build_windows.ps1"
if ($LASTEXITCODE -ne 0) { throw 'Height smoothing build failed' }
& "$PSScriptRoot/deformation/build_windows.ps1"
if ($LASTEXITCODE -ne 0) { throw 'Final-skin deformation build failed' }
