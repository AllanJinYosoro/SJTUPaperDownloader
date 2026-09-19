param(
    [string]$HostName = "com.sjtu.paperdownloader",
    [string]$ExtensionId = "hnmnojlkimfjgmeelnghlegofogpohoi"
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$buildScript = Join-Path $PSScriptRoot "build_native_host.ps1"

if (-not (Test-Path $buildScript)) {
    throw "Native host build script not found: $buildScript"
}

powershell -NoProfile -ExecutionPolicy Bypass -File $buildScript
if ($LASTEXITCODE -ne 0) { throw "Native host build failed." }

$exePath = Join-Path $repoRoot "dist\paperdownloader-host.exe"

if (-not (Test-Path $exePath)) {
    throw "Native host executable not found: $exePath"
}

$manifestDir = Join-Path $repoRoot ".native-host-stage"
New-Item -ItemType Directory -Path $manifestDir -Force | Out-Null
$manifestPath = Join-Path $manifestDir "$HostName.json"
$allowedOrigin = "chrome-extension://$ExtensionId/"

$manifest = @{
    name = $HostName
    description = "SJTU Paper Downloader native messaging host"
    path = $exePath
    type = "stdio"
    allowed_origins = @($allowedOrigin)
}

[System.IO.File]::WriteAllText($manifestPath, ($manifest | ConvertTo-Json -Depth 4), [System.Text.UTF8Encoding]::new($false))

$registryPath = "HKCU:\Software\Google\Chrome\NativeMessagingHosts\$HostName"
New-Item -Path $registryPath -Force | Out-Null
Set-Item -Path $registryPath -Value $manifestPath

Write-Output "Installed native host manifest:"
Write-Output "  Host name: $HostName"
Write-Output "  Extension: $allowedOrigin"
Write-Output "  Manifest: $manifestPath"
Write-Output "  Executable: $exePath"
