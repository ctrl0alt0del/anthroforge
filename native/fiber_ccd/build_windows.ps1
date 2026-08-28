$ErrorActionPreference = "Stop"
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$VsWhere = "C:\Program Files (x86)\Microsoft Visual Studio\Installer\vswhere.exe"
$ClangRoot = & $VsWhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Llvm.Clang -property installationPath
$ToolsRoot = & $VsWhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
$Clang = Join-Path $ClangRoot "VC\Tools\Llvm\x64\bin\clang-cl.exe"
$VcVars = Join-Path $ToolsRoot "VC\Auxiliary\Build\vcvars64.bat"
$Runtime = Join-Path $ClangRoot "VC\Tools\Llvm\x64\bin\libomp.dll"
$Source = Join-Path $Here "af_fiber_ccd.cpp"
$Output = Join-Path $Here "af_fiber_ccd_v3.dll"
$Staged = Join-Path $Here "af_fiber_ccd_v3.next.dll"
$Object = Join-Path $Here "af_fiber_ccd_v3.next.obj"
$Export = Join-Path $Here "af_fiber_ccd_v3.next.exp"
if (-not (Test-Path $Clang)) { throw "C++ Clang Compiler for Windows is unavailable" }
if (-not (Test-Path $VcVars)) { throw "Visual C++ x64 build tools are unavailable" }
if (-not (Test-Path $Runtime)) { throw "LLVM OpenMP runtime is unavailable" }
$Command = 'call "{0}" && "{1}" /nologo /O2 /openmp /EHsc /std:c++17 /LD "{2}" /Fo:"{3}" /Fe:"{4}" /clang:-ffp-model=precise /link /NOIMPLIB' -f $VcVars, $Clang, $Source, $Object, $Staged
cmd.exe /d /s /c $Command
if ($LASTEXITCODE -ne 0) { throw "Native Fiber CCD build failed: $LASTEXITCODE" }
Move-Item -LiteralPath $Staged -Destination $Output -Force
Copy-Item -LiteralPath $Runtime -Destination (Join-Path $Here "libomp.dll") -Force
Remove-Item -LiteralPath $Object -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $Export -ErrorAction SilentlyContinue
