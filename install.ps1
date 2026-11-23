# Vidyax Installer for Windows (PowerShell)
# Usage: irm https://raw.githubusercontent.com/Vidyax-Lang/Vidyax/main/install.ps1 | iex
$ErrorActionPreference = "Stop"

$Repo = "Vidyax-Lang/Vidyax"
$InstallDir = Join-Path $HOME ".vidyax\bin"
$BinaryPath = Join-Path $InstallDir "vidyax.exe"
$ReleaseUrl = "https://github.com/$Repo/releases/latest/download/vidyax-windows-x86_64.exe"

New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null

Write-Host "[Vidyax] Downloading latest Windows release..."
try {
    Invoke-WebRequest -Uri $ReleaseUrl -OutFile $BinaryPath -UseBasicParsing
} catch {
    Write-Error "Prebuilt Windows binary is not published yet. On Windows, use WSL2 with: curl -fsSL https://raw.githubusercontent.com/$Repo/main/install.sh | sh"
    exit 1
}

$UserPath = [Environment]::GetEnvironmentVariable("Path", "User")
if (-not ($UserPath -split ";" | Where-Object { $_ -eq $InstallDir })) {
    [Environment]::SetEnvironmentVariable("Path", "$UserPath;$InstallDir", "User")
    Write-Host "[Vidyax] Added $InstallDir to user PATH. Restart your terminal."
}

Write-Host "[Vidyax] Installed to $BinaryPath. Run: vidyax --version"
