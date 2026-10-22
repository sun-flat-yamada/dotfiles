<#
.SYNOPSIS
    Bootstrap and manage sun-flat-yamada/dotfiles on Windows 11 / PowerShell 7.
.DESCRIPTION
    Idempotent installer and diagnostics entrypoint for Windows workstations.
    Supports -DryRun, -Profile (full, core, git, shell, terminal, editor, ai, wsl, packages),
    -Method (auto, symlink, copy), -Status, -Doctor, -Validate, and -RollbackBackupDir.
.EXAMPLE
    .\install.ps1 -DryRun
    .\install.ps1 -Profile full
    .\install.ps1 -Status
    .\install.ps1 -Doctor
    .\install.ps1 -RollbackBackupDir "$HOME\.dotfiles-backup\20261022T143000Z"
#>
[CmdletBinding()]
param(
    [ValidateSet("full", "core", "git", "wsl", "terminal", "shell", "starship", "editor", "ai", "packages")]
    [string]$Profile = "full",

    [ValidateSet("auto", "symlink", "copy")]
    [string]$Method = "auto",

    [string]$TargetHome = $HOME,

    [string]$RollbackBackupDir = "",

    [switch]$DryRun,
    [switch]$Status,
    [switch]$Doctor,
    [switch]$Validate
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$EngineScript = Join-Path $RepoRoot "scripts\dotfiles.py"

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Error "Python 3.10+ is required to run the dotfiles engine ($EngineScript)."
    exit 1
}

# Export actual Windows MyDocuments path so redirected Documents folders are resolved accurately
try {
    $myDocs = [Environment]::GetFolderPath('MyDocuments')
    if ($myDocs) {
        $env:DOTFILES_DOCUMENTS_DIR = $myDocs
    }
} catch {}

if ($Validate) {
    & python $EngineScript validate
    exit $LASTEXITCODE
}

if ($Doctor) {
    & python $EngineScript doctor
    exit $LASTEXITCODE
}

if ($RollbackBackupDir) {
    $rbArgs = @("rollback", "--backup-dir", $RollbackBackupDir)
    if ($DryRun) { $rbArgs += "--dry-run" }
    & python $EngineScript @rbArgs
    exit $LASTEXITCODE
}

if ($Status) {
    & python $EngineScript status --profile $Profile --target-home $TargetHome
    exit $LASTEXITCODE
}

$installArgs = @("install", "--profile", $Profile, "--method", $Method, "--target-home", $TargetHome)
if ($DryRun) {
    $installArgs += "--dry-run"
}

& python $EngineScript @installArgs
exit $LASTEXITCODE
