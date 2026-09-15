param([string]$OutputName = "af_fiber_ccd_v3_13.dll")
$ErrorActionPreference = "Stop"
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$VsWhere = "C:\Program Files (x86)\Microsoft Visual Studio\Installer\vswhere.exe"
$ClangRoot = & $VsWhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Llvm.Clang -property installationPath
$ToolsRoot = & $VsWhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
$Clang = Join-Path $ClangRoot "VC\Tools\Llvm\x64\bin\clang-cl.exe"
$VcVars = Join-Path $ToolsRoot "VC\Auxiliary\Build\vcvars64.bat"
$Runtime = Join-Path $ClangRoot "VC\Tools\Llvm\x64\bin\libomp.dll"
$Source = Join-Path $Here "af_fiber_ccd.cpp"
$Output = Join-Path $Here $OutputName
$Stem = [IO.Path]::GetFileNameWithoutExtension($OutputName)
$Staged = Join-Path $Here "$Stem.next.dll"
$Object = Join-Path $Here "$Stem.next.obj"
$Export = Join-Path $Here "$Stem.next.exp"
$Define = if ($OutputName -match "experiment") { "/DAF_V3_OPERATION_EXPERIMENT=1 /DAF_V3_NATIVE_CONTROLLER=1" } else { "/DAF_V3_NATIVE_CONTROLLER=1" }
if (-not (Test-Path $Clang)) { throw "C++ Clang Compiler for Windows is unavailable" }
if (-not (Test-Path $VcVars)) { throw "Visual C++ x64 build tools are unavailable" }
if (-not (Test-Path $Runtime)) { throw "LLVM OpenMP runtime is unavailable" }
$Command = 'call "{0}" && "{1}" /nologo /O2 /openmp /EHsc /std:c++17 /LD {2} "{3}" /Fo:"{4}" /Fe:"{5}" /clang:-ffp-model=precise /link /NOIMPLIB' -f $VcVars, $Clang, $Define, $Source, $Object, $Staged
cmd.exe /d /s /c $Command
if ($LASTEXITCODE -ne 0) { throw "Native Fiber CCD build failed: $LASTEXITCODE" }
Move-Item -LiteralPath $Staged -Destination $Output -Force
$RuntimeTarget = Join-Path $Here "libomp.dll"
$RuntimeMatches = (Test-Path $RuntimeTarget) -and ((Get-FileHash $Runtime).Hash -eq (Get-FileHash $RuntimeTarget).Hash)
if (-not $RuntimeMatches) { Copy-Item -LiteralPath $Runtime -Destination $RuntimeTarget -Force }
Remove-Item -LiteralPath $Object -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $Export -ErrorAction SilentlyContinue
