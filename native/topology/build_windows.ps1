$ErrorActionPreference = 'Stop'
$Root = (Resolve-Path "$PSScriptRoot/../..").Path
$VsWhere = 'C:/Program Files (x86)/Microsoft Visual Studio/Installer/vswhere.exe'
$ClangRoot = & $VsWhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Llvm.Clang -property installationPath
$ToolsRoot = & $VsWhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
$Clang = Join-Path $ClangRoot 'VC/Tools/Llvm/x64/bin/clang-cl.exe'
$VcVars = Join-Path $ToolsRoot 'VC/Auxiliary/Build/vcvars64.bat'
$Flags = '/nologo /MD /O2 /EHsc /std:c++17 /DNOMINMAX /DEIGEN_DONT_PARALLELIZE /DEIGEN_MPL2_ONLY'
New-Item -ItemType Directory -Force -Path "$PSScriptRoot/build" | Out-Null
$Command = 'call "{0}" && "{1}" {2} /I"{3}/native/smoothing/vendor" /LD "{4}/field.cpp" /Fo:"{4}/build/field.obj" /Fe:"{4}/build/field.next.dll" /link /NOIMPLIB' -f $VcVars,$Clang,$Flags,$Root,$PSScriptRoot
cmd.exe /d /s /c $Command
if ($LASTEXITCODE -ne 0) { throw 'Topology field build failed; existing DLL preserved' }
Move-Item -LiteralPath "$PSScriptRoot/build/field.next.dll" -Destination "$PSScriptRoot/af_topology_field_v1.dll" -Force
