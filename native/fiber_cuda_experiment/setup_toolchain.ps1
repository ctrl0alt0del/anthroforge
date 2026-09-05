param([string]$Destination = "$env:TEMP\anthroforge-cuda-13.3")
$ErrorActionPreference = "Stop"
$BaseUrl = "https://developer.download.nvidia.com/compute/cuda/redist"
$Packages = @(
    @("cccl", "cccl-windows-x86_64-13.3.3.4.1-archive.zip", "48fab83097a636c4119da28bd3c9c9af9327e34c1efed17a14449cc2956ca6d1"),
    @("cuda_crt", "cuda_crt-windows-x86_64-13.3.73-archive.zip", "9227ec7c80db10b7cb0d4ee71ed62ec7ae36e67890216413ab6f9afa35d577f0"),
    @("cuda_cudart", "cuda_cudart-windows-x86_64-13.3.29-archive.zip", "1feb7dd266813ffe8dbc24e115183a5ac35a4795c8d34aca0df85ab616b64d9c"),
    @("cuda_nvcc", "cuda_nvcc-windows-x86_64-13.3.73-archive.zip", "270214eaee58e49f8fca52a910a46afbfab227858e70897cba8afae10826280b"),
    @("libnvvm", "libnvvm-windows-x86_64-13.3.73-archive.zip", "ca8f11d5173ac16a166be8fafefbf9676542a097de1fce61b3f17696dffc1f27")
)

function Get-Package($Root, $Spec) {
    $Archive = Join-Path $Root $Spec[1]
    if (-not (Test-Path $Archive)) {
        Invoke-WebRequest "$BaseUrl/$($Spec[0])/windows-x86_64/$($Spec[1])" -OutFile $Archive
    }
    $Digest = (Get-FileHash -LiteralPath $Archive -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($Digest -ne $Spec[2]) { throw "SHA256 mismatch for $($Spec[1])" }
    return $Archive
}

function Expand-Package($Archive, $Root) {
    $Name = [IO.Path]::GetFileNameWithoutExtension($Archive)
    $Expanded = Join-Path $Root $Name
    if (-not (Test-Path $Expanded)) { Expand-Archive -LiteralPath $Archive -DestinationPath $Expanded }
    return (Get-ChildItem -LiteralPath $Expanded -Directory | Select-Object -First 1).FullName
}

function Merge-Package($Source, $Toolkit) {
    Get-ChildItem -LiteralPath $Source | ForEach-Object {
        Copy-Item -LiteralPath $_.FullName -Destination $Toolkit -Recurse -Force
    }
}

$Resolved = [IO.Path]::GetFullPath($Destination)
$Downloads = Join-Path $Resolved "downloads"
$Toolkit = Join-Path $Resolved "toolkit"
New-Item -ItemType Directory -Force -Path $Downloads, $Toolkit | Out-Null
foreach ($Spec in $Packages) {
    $Archive = Get-Package $Downloads $Spec
    Merge-Package (Expand-Package $Archive $Downloads) $Toolkit
}
$Nvcc = Join-Path $Toolkit "bin\nvcc.exe"
if (-not (Test-Path $Nvcc)) { throw "nvcc.exe was not assembled" }
Write-Output $Toolkit
