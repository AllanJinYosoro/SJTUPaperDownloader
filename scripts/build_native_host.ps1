param(
    [string]$SourcePath = (Join-Path $PSScriptRoot "paperdownloader_native_host.cs"),
    [string]$OutputPath = (Join-Path (Split-Path -Parent $PSScriptRoot) "dist\paperdownloader-host.exe")
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $SourcePath)) {
    throw "Native host source file not found: $SourcePath"
}

$outputDir = Split-Path -Parent $OutputPath
New-Item -ItemType Directory -Path $outputDir -Force | Out-Null

$code = Get-Content -Raw -Encoding utf8 -LiteralPath $SourcePath
$buildOutput = Join-Path $outputDir ([System.IO.Path]::GetRandomFileName() + ".exe")
Add-Type `
    -TypeDefinition $code `
    -Language CSharp `
    -OutputAssembly $buildOutput `
    -OutputType ConsoleApplication `
    -ReferencedAssemblies @("System.dll", "System.Core.dll", "System.Net.Http.dll")

Move-Item -LiteralPath $buildOutput -Destination $OutputPath -Force
Write-Output "Built native host executable: $OutputPath"
