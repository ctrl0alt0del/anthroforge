$ErrorActionPreference = "Stop"
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$VcVars = "C:\Program Files (x86)\Microsoft Visual Studio\2019\BuildTools\VC\Auxiliary\Build\vcvars64.bat"
$Source = Join-Path $Here "af_fiber_ccd.cpp"
$Output = Join-Path $Here "af_fiber_ccd_v3.dll"
$Object = Join-Path $Here "af_fiber_ccd.obj"
$Export = Join-Path $Here "af_fiber_ccd.exp"
$Command = 'call "{0}" && cl /nologo /O2 /EHsc /std:c++17 /LD "{1}" /Fo:"{2}" /Fe:"{3}" /link /NOIMPLIB' -f $VcVars, $Source, $Object, $Output
cmd.exe /d /s /c $Command
if ($LASTEXITCODE -ne 0) { throw "Native Fiber CCD build failed: $LASTEXITCODE" }
Remove-Item -LiteralPath $Object -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $Export -ErrorAction SilentlyContinue
