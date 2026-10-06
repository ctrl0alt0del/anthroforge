param([string]$OutputName = 'af_height_smoothing_v1.dll')
$ErrorActionPreference = 'Stop'
$Here = $PSScriptRoot
$VsWhere = 'C:/Program Files (x86)/Microsoft Visual Studio/Installer/vswhere.exe'
$ClangRoot = & $VsWhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Llvm.Clang -property installationPath
$ToolsRoot = & $VsWhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
$Clang = Join-Path $ClangRoot 'VC/Tools/Llvm/x64/bin/clang-cl.exe'
$VcVars = Join-Path $ToolsRoot 'VC/Auxiliary/Build/vcvars64.bat'
$Flags = '/nologo /MD /O2 /EHsc /std:c++17 /DNOMINMAX /DEIGEN_DONT_PARALLELIZE /DEIGEN_MPL2_ONLY /clang:-ffp-model=precise'
$Includes = '/I"{0}/include" /I"{0}/vendor"' -f $Here
New-Item -ItemType Directory -Force -Path "$Here/build" | Out-Null
foreach ($Source in @('core', 'height')) {
    $Command = 'call "{0}" && "{1}" {2} {3} /c "{4}/src/{5}.cpp" /Fo:"{4}/build/{5}.obj"' -f $VcVars,$Clang,$Flags,$Includes,$Here,$Source
    cmd.exe /d /s /c $Command
    if ($LASTEXITCODE -ne 0) { throw "Smoothing compilation failed: $Source" }
}
$Command = 'call "{0}" && "{1}" /LD /MD "{2}/build/core.obj" "{2}/build/height.obj" /Fe:"{2}/build/height.next.dll" /link /NOIMPLIB' -f $VcVars,$Clang,$Here
cmd.exe /d /s /c $Command
if ($LASTEXITCODE -ne 0) { throw 'Smoothing link failed; existing DLL preserved' }
Move-Item -LiteralPath "$Here/build/height.next.dll" -Destination (Join-Path $Here $OutputName) -Force
