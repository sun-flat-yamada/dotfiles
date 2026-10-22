# ==============================================================================
# PowerShell 7 Profile (Microsoft.PowerShell_profile.ps1)
# Author: Youhei Yamada (@sun-flat-yamada)
# Design: Sub-50ms Lazy-Loaded Startup, Secret-Safe History, Dark 2026 Palette
# ==============================================================================

$global:DotfilesProfileTimer = [System.Diagnostics.Stopwatch]::StartNew()

# ------------------------------------------------------------------------------
# 1. UTF-8 Encoding & Core Environment
# ------------------------------------------------------------------------------
try {
    [Console]::InputEncoding  = [System.Text.Encoding]::UTF8
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
} catch {
    # Non-interactive or redirected console handles may not support setting encoding
}
$OutputEncoding       = [System.Text.Encoding]::UTF8
$env:EDITOR           = "code --wait"
$env:VISUAL           = "code --wait"
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8       = "1"
$env:STARSHIP_CONFIG  = Join-Path $HOME ".config/starship.toml"

# Ensure ~/.local/bin and mise shims are in PATH (<1ms) so uv/claude/node/python/go work immediately
$candidatePaths = @(
    (Join-Path $HOME ".local/bin"),
    (Join-Path $HOME ".local/share/mise/shims")
)
if ($env:LOCALAPPDATA) {
    $candidatePaths += (Join-Path $env:LOCALAPPDATA "mise\shims")
}
foreach ($dir in $candidatePaths) {
    if ($dir -and (Test-Path $dir) -and ($env:PATH -notlike "*$dir*")) {
        $env:PATH = "$dir$([IO.Path]::PathSeparator)$env:PATH"
    }
}

# ------------------------------------------------------------------------------
# 2. PSReadLine Configuration & Secret-Safe History Filter (2026 Standard)
# ------------------------------------------------------------------------------
if ($Host.Name -eq 'ConsoleHost' -or $Host.Name -eq 'Visual Studio Code Host') {
    if (Get-Module -Name PSReadLine -ErrorAction SilentlyContinue) {
        Set-PSReadLineOption -EditMode Windows
        Set-PSReadLineOption -HistoryNoDuplicates
        Set-PSReadLineOption -HistorySearchCursorMovesToEnd
        Set-PSReadLineOption -BellStyle None

        try {
            if ([Console]::WindowWidth -gt 0 -and $PSVersionTable.PSVersion.Major -ge 7) {
                Set-PSReadLineOption -PredictionSource HistoryAndPlugin -ErrorAction SilentlyContinue
                Set-PSReadLineOption -PredictionViewStyle ListView -ErrorAction SilentlyContinue
            }
        } catch {
            # Ignore in non-interactive or headless terminals
        }

        Set-PSReadLineKeyHandler -Key UpArrow -Function HistorySearchBackward
        Set-PSReadLineKeyHandler -Key DownArrow -Function HistorySearchForward
        Set-PSReadLineKeyHandler -Key Tab -Function MenuComplete
        Set-PSReadLineKeyHandler -Chord 'Ctrl+d' -Function DeleteCharOrExit

        # Zero-Leak Defense: Never persist commands starting with space or containing secrets/tokens
        Set-PSReadLineOption -AddToHistoryHandler {
            param([string]$line)
            if ([string]::IsNullOrWhiteSpace($line) -or $line.StartsWith(' ')) { return $false }
            $secretPatterns = @(
                '(?i)(api[_-]?key|secret|password|passwd|token|credential)\s*[:=]',
                'gh[pousr]_[A-Za-z0-9_]{20,}',
                'github_pat_[A-Za-z0-9_]{20,}',
                'sk-ant-[A-Za-z0-9_-]{20,}',
                'sk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{20,}',
                'AIza[0-9A-Za-z_-]{35}',
                '(?:AKIA|ASIA)[0-9A-Z]{16}',
                'xox[baprs]-[0-9A-Za-z-]{10,}',
                'hf_[A-Za-z0-9]{30,}',
                '(?i)Bearer\s+[A-Za-z0-9._-]+'
            )
            foreach ($pattern in $secretPatterns) {
                if ($line -match $pattern) {
                    return $false
                }
            }
            return $true
        }
    }
}

# ------------------------------------------------------------------------------
# 3. Ergonomic Navigation & Developer Functions
# ------------------------------------------------------------------------------
function .. { Set-Location .. }
function ... { Set-Location (Join-Path ".." "..") }
function .... { Set-Location (Join-Path ".." (Join-Path ".." "..")) }

function mkcd {
    param([Parameter(Mandatory = $true)][string]$Path)
    New-Item -ItemType Directory -Path $Path -Force | Out-Null
    Set-Location -Path $Path
}

function touch {
    param([Parameter(Mandatory = $true)][string]$Path)
    if (Test-Path $Path) {
        (Get-Item $Path).LastWriteTime = Get-Date
    } else {
        New-Item -ItemType File -Path $Path | Out-Null
    }
}

function which {
    param([Parameter(Mandatory = $true)][string]$Name)
    Get-Command $Name -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source
}

# Modern directory listing (uses eza if available, falls back to Get-ChildItem)
if (Get-Command eza -ErrorAction SilentlyContinue) {
    function ll { eza --long --header --git --icons @args }
    function la { eza --long --all --header --git --icons @args }
    function lt { eza --tree --level=2 --icons @args }
} else {
    function ll { Get-ChildItem -Force @args }
    function la { Get-ChildItem -Force @args }
}

# Git shortcuts (remove built-in Alias:\gl -> Get-Location so 'gl' maps to git log)
Set-Alias -Name g -Value git -Force
Remove-Item Alias:\gl -Force -ErrorAction SilentlyContinue
function gs { git status -sb @args }
function gd { git diff @args }
function gl { git lg -n 15 @args }
function gco { git checkout @args }
function gwt { git worktree @args }

# Safe PowerShell updater via WinGet (complies with Permission Rule N-06: no iwr | iex)
function Update-PowerShell {
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        winget upgrade --id Microsoft.PowerShell --exact --source winget
    } else {
        Write-Warning "winget is not available. Download the MSI installer from https://github.com/PowerShell/PowerShell/releases"
    }
}

# Reload profile
function Invoke-ProfileReload {
    . $PROFILE
    Write-Host "[+] PowerShell profile reloaded." -ForegroundColor Cyan
}
Set-Alias -Name reload -Value Invoke-ProfileReload -Force

# Resolve dotfiles repository root dynamically from symlink target or environment variable
$resolvedTarget = $null
if ($PSCommandPath) {
    try {
        $item = Get-Item -LiteralPath $PSCommandPath -Force -ErrorAction SilentlyContinue
        if ($item -and $item.Target) {
            $resolvedTarget = $item.Target | Select-Object -First 1
        }
    } catch {}
}
if ($env:DOTFILES_ROOT) {
    $global:DotfilesRoot = $env:DOTFILES_ROOT
} elseif ($resolvedTarget) {
    $global:DotfilesRoot = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $resolvedTarget))
} else {
    $global:DotfilesRoot = Join-Path $HOME "dotfiles"
}

function Invoke-DotfilesDoctor {
    $engineScript = Join-Path $global:DotfilesRoot (Join-Path "scripts" "dotfiles.py")
    if (Test-Path $engineScript) {
        python $engineScript doctor @args
    } else {
        Write-Warning "Dotfiles engine not found at $engineScript (set `$env:DOTFILES_ROOT to override)."
    }
}
Set-Alias -Name dotfiles-doctor -Value Invoke-DotfilesDoctor -Force

# ------------------------------------------------------------------------------
# 4. Lazy-Loaded CLI Tool Integrations (zoxide, mise) — Global Scope Safe
# ------------------------------------------------------------------------------
if (Get-Command zoxide -ErrorAction SilentlyContinue) {
    function global:Invoke-ZoxideLazyInit {
        Remove-Item Function:\z, Function:\zi -ErrorAction SilentlyContinue
        $initScript = (zoxide init powershell | Out-String) -replace '(?m)^(\s*)function\s+([A-Za-z0-9_-]+)', '$1function global:$2'
        Invoke-Expression $initScript
    }
    function global:z { Invoke-ZoxideLazyInit; z @args }
    function global:zi { Invoke-ZoxideLazyInit; zi @args }
}

if (Get-Command mise -ErrorAction SilentlyContinue) {
    function global:Invoke-MiseLazyInit {
        Remove-Item Function:\mise -ErrorAction SilentlyContinue
        $initScript = ((& mise activate pwsh) | Out-String) -replace '(?m)^(\s*)function\s+([A-Za-z0-9_-]+)', '$1function global:$2'
        Invoke-Expression $initScript
    }
    function global:mise { Invoke-MiseLazyInit; mise @args }
}

# ------------------------------------------------------------------------------
# 5. Prompt Initialization (Starship with Dark 2026 Native Fallback)
# ------------------------------------------------------------------------------
if (Get-Command starship -ErrorAction SilentlyContinue) {
    Invoke-Expression (& starship init powershell)
} else {
    function global:prompt {
        $lastSuccess = $?
        $rawPath = (Get-Location).Path
        $cwd = if ($rawPath.StartsWith($HOME, [System.StringComparison]::OrdinalIgnoreCase)) {
            "~" + $rawPath.Substring($HOME.Length)
        } else {
            $rawPath
        }
        $gitBranch = ""
        if (Get-Command git -ErrorAction SilentlyContinue) {
            $branch = git rev-parse --abbrev-ref HEAD 2>$null
            if ($LASTEXITCODE -eq 0 -and $branch) {
                $gitBranch = " ($branch)"
            }
        }
        Write-Host ""
        Write-Host "$cwd" -NoNewline -ForegroundColor Cyan
        if ($gitBranch) {
            Write-Host "$gitBranch" -NoNewline -ForegroundColor Magenta
        }
        Write-Host ""
        $symbolColor = if ($lastSuccess) { "Yellow" } else { "Red" }
        Write-Host "❯" -NoNewline -ForegroundColor $symbolColor
        return " "
    }
}

# ------------------------------------------------------------------------------
# 6. Machine-Local Private Overrides (~/.powershell.local.ps1)
# ------------------------------------------------------------------------------
$localProfile = Join-Path $HOME ".powershell.local.ps1"
if (Test-Path $localProfile) {
    . $localProfile
}

$global:DotfilesProfileTimer.Stop()
if ($env:DOTFILES_PROFILE_TIMING -eq "1") {
    Write-Host ("[dotfiles] Profile loaded in {0}ms" -f $global:DotfilesProfileTimer.ElapsedMilliseconds) -ForegroundColor DarkGray
}
