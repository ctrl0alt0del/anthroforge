$ErrorActionPreference = "Stop"
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$VcRoot = "C:\Program Files (x86)\Microsoft Visual Studio\2019\BuildTools\VC"
$VcVars = Join-Path $VcRoot "Auxiliary\Build\vcvars64.bat"
$Source = Join-Path $Here "af_fiber_ccd.cpp"
$Output = Join-Path $Here "af_fiber_ccd_v3.dll"
$Object = Join-Path $Here "af_fiber_ccd.obj"
$Export = Join-Path $Here "af_fiber_ccd.exp"
$Runtime = Get-ChildItem (Join-Path $VcRoot "Redist\MSVC") -Filter vcomp140.dll -Recurse |
    Where-Object { $_.FullName -match '\\x64\\Microsoft\.VC.*\.OpenMP\\vcomp140\.dll$' } |
    Select-Object -First 1
$Command = 'call "{0}" && cl /nologo /O2 /openmp /EHsc /std:c++17 /LD "{1}" /Fo:"{2}" /Fe:"{3}" /link /NOIMPLIB' -f $VcVars, $Source, $Object, $Output
cmd.exe /d /s /c $Command
if ($LASTEXITCODE -ne 0) { throw "Native Fiber CCD build failed: $LASTEXITCODE" }
if (-not $Runtime) { throw "Visual C++ OpenMP runtime is unavailable" }
Copy-Item -LiteralPath $Runtime.FullName -Destination (Join-Path $Here "vcomp140.dll") -Force
Remove-Item -LiteralPath $Object -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $Export -ErrorAction SilentlyContinue
