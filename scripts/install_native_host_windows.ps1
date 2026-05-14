param(
    [Parameter(Mandatory = $true)]
    [string]$HostPath,

    [Parameter(Mandatory = $true)]
    [string]$ExtensionId,

    [ValidateSet("Chrome", "Edge", "Both")]
    [string]$Browser = "Chrome",

    [string]$InstallDir = "$env:LOCALAPPDATA\PaperDownloader\NativeMessagingHost"
)

$ErrorActionPreference = "Stop"

function Register-Host([string]$RegistryPath, [string]$ManifestPath) {
    New-Item -Path $RegistryPath -Force | Out-Null
    Set-Item -Path $RegistryPath -Value $ManifestPath
}

$resolvedHostPath = (Resolve-Path $HostPath).Path
$resolvedInstallDir = [System.IO.Path]::GetFullPath($InstallDir)
$targetHostPath = Join-Path $resolvedInstallDir "paperdownloader-host.exe"
$manifestPath = Join-Path $resolvedInstallDir "paperdownloader.host.json"

New-Item -ItemType Directory -Path $resolvedInstallDir -Force | Out-Null
Copy-Item -Path $resolvedHostPath -Destination $targetHostPath -Force

$manifest = @{
    name = "paperdownloader.host"
    description = "PaperDownloader native host"
    path = $targetHostPath
    type = "stdio"
    allowed_origins = @("chrome-extension://$ExtensionId/")
} | ConvertTo-Json -Depth 5

Set-Content -Path $manifestPath -Value $manifest -Encoding UTF8

if ($Browser -eq "Chrome" -or $Browser -eq "Both") {
    Register-Host "HKCU:\Software\Google\Chrome\NativeMessagingHosts\paperdownloader.host" $manifestPath
}
if ($Browser -eq "Edge" -or $Browser -eq "Both") {
    Register-Host "HKCU:\Software\Microsoft\Edge\NativeMessagingHosts\paperdownloader.host" $manifestPath
}

Write-Host "Installed native host manifest at $manifestPath"
Write-Host "Registered paperdownloader.host for $Browser"
