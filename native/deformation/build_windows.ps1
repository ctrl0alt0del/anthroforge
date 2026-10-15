$ErrorActionPreference = 'Stop'
$Here = $PSScriptRoot
$VsWhere = 'C:/Program Files (x86)/Microsoft Visual Studio/Installer/vswhere.exe'
$ClangRoot = & $VsWhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Llvm.Clang -property installationPath
$ToolsRoot = & $VsWhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
$Clang = Join-Path $ClangRoot 'VC/Tools/Llvm/x64/bin/clang-cl.exe'
$VcVars = Join-Path $ToolsRoot 'VC/Auxiliary/Build/vcvars64.bat'
$Flags = '/nologo /MD /O2 /EHsc /std:c++17 /DNOMINMAX /DEIGEN_DONT_PARALLELIZE /DEIGEN_MPL2_ONLY /clang:-ffp-model=precise'
$Includes = '/I"{0}/vendor" /I"{0}/../smoothing/vendor"' -f $Here
New-Item -ItemType Directory -Force -Path "$Here/build" | Out-Null
$Command = 'call "{0}" && "{1}" {2} {3} /LD "{4}/native.cpp" /Fo:"{4}/build/deformation.obj" /Fe:"{4}/build/deformation.next.dll" /link /NOIMPLIB' -f $VcVars,$Clang,$Flags,$Includes,$Here
cmd.exe /d /s /c $Command
if ($LASTEXITCODE -ne 0) { throw 'Final-skin deformation build failed; existing DLL preserved' }
Move-Item -LiteralPath "$Here/build/deformation.next.dll" -Destination "$Here/af_deformation_v1.dll" -Force
