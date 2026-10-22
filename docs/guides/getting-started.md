---
title: "Getting Started Guide — sun-flat-yamada/dotfiles"
description: "Step-by-step installation, profile selection, package provisioning, drift inspection, rollback, and keyboard/alias cheat sheet for Windows 11, WSL2, Linux, and macOS."
category: "guide"
type: "guide"
status: "active"
date: 2026-10-22
updated: 2026-10-22
lang: "en"
tags: ["guide", "getting-started", "installation", "windows", "wsl2", "cheatsheet"]
---

# 📖 Getting Started Guide

## 1. Prerequisites

- **Git** (`git`)
- **Python 3.10+** (`python` / `python3`)
- **Windows 11**: PowerShell 7 (`pwsh`) recommended (enable Windows Developer Mode for native non-admin symlinks, or let `dotfiles.py` automatically fall back to safe file copy). Note that `install.ps1` automatically detects redirected Windows `Documents` folders (`[Environment]::GetFolderPath('MyDocuments')`).
- **WSL2 / Linux / macOS**: `bash` or `zsh`.

---

## 2. Step-by-Step Installation

### Windows 11 (PowerShell 7)

```powershell
# 1. Clone the repository (into ~/dotfiles or your preferred workspace directory)
git clone https://github.com/sun-flat-yamada/dotfiles.git "$HOME\dotfiles"
cd "$HOME\dotfiles"

# 2. Preview changes without modifying any files (Dry-Run)
.\install.ps1 -DryRun

# 3. Inspect current drift status against your home directory
.\install.ps1 -Status

# 4. Apply all configurations (automatically backs up existing files to ~/.dotfiles-backup/<timestamp>/)
.\install.ps1 -Profile full

# 5. Run environment health diagnostics
.\install.ps1 -Doctor
```

### WSL2 (Ubuntu) / Linux / macOS

```bash
# 1. Clone the repository
git clone https://github.com/sun-flat-yamada/dotfiles.git ~/dotfiles
cd ~/dotfiles

# 2. Preview changes (Dry-Run)
./install.sh --dry-run

# 3. Apply configurations
./install.sh --profile full

# 4. Check environment health
./install.sh --doctor

# 5. (Optional, WSL2 only) Apply guest /etc/wsl.conf configuration
sudo cp config/wsl/wsl.conf /etc/wsl.conf
```

---

## 3. Selective Profile Deployment

You can deploy specific subsystems using `--profile` / `-Profile`:

| Profile | Included Configurations |
| :--- | :--- |
| `full` | All supported configurations for the current OS (24 items in manifest) |
| `core` | `git`, `shell`, `starship`, `ai` |
| `git` | `.gitconfig`, `.gitignore_global`, `.gitattributes_global` |
| `wsl` | `.wslconfig` (Windows host WSL2 tuning) |
| `terminal` | WezTerm (`wezterm.lua`, `keybinds.lua`) & Windows Terminal fragment |
| `shell` | PowerShell 7 profile (`Microsoft.PowerShell_profile.ps1`) or `.zshrc` / `.bashrc` / `.aliases` |
| `starship` | `starship.toml` |
| `editor` | VS Code `settings.json` & `keybindings.json` |
| `ai` | Global AI Agent instructions, policies & settings (`~/.agents`, `~/.claude`, `~/.gemini`, `~/.codex`, `ccstatusline`) |
| `packages` | Global `mise` configuration (`~/.config/mise/config.toml`) |

---

## 4. Provisioning Packages, Extensions & Runtimes

```powershell
# Windows: Declarative WinGet Configuration (OS Developer Mode + Core GUI/System Apps)
winget configure validate -f packages\winget\configuration.winget
winget configure -f packages\winget\configuration.winget

# Windows: Scoop Packages (User-Space CLI Tools & Nerd Fonts)
scoop import packages\scoop\scoopfile.json

# Cross-Platform: Polyglot Language Runtimes via mise
mise install

# VS Code: Install all recommended extensions from config/vscode/extensions.json
(Get-Content config\vscode\extensions.json | ConvertFrom-Json).recommendations | ForEach-Object { code --install-extension $_ }
```

```bash
# WSL2 / Linux / macOS: Homebrew Bundle
brew bundle --file=packages/homebrew/Brewfile
```

---

## 5. Rollback & Machine-Local Overrides

### Rolling Back a Deployment
Whenever `install` modifies or creates files, it writes an action journal (`restore-manifest.json`) in `~/.dotfiles-backup/<timestamp>/`:

```powershell
# Windows PowerShell
.\install.ps1 -RollbackBackupDir "$HOME\.dotfiles-backup\20261022T143000Z"
```

```bash
# WSL2 / Linux / macOS
./install.sh --rollback --backup-dir ~/.dotfiles-backup/20261022T143000Z
```

### Adding Machine-Local Customizations (Never Committed)
- **Git**: Create `~/.gitconfig.local` (see [`config/git/.gitconfig.local.example`](../../config/git/.gitconfig.local.example)).
- **PowerShell 7**: Create `~/.powershell.local.ps1`.
- **Zsh / Bash**: Create `~/.zshrc.local` or `~/.bashrc.local`.

---

## 6. Keyboard & Alias Ergonomics Cheat Sheet

### WezTerm Multiplexer (`Leader = Ctrl + q`)

| Shortcut | Action |
| :--- | :--- |
| `Ctrl+q` then `-` | Split pane vertically (top / bottom) |
| `Ctrl+q` then `\|` or `\` | Split pane horizontally (left / right) |
| `Ctrl+q` then `h` / `j` / `k` / `l` | Navigate panes (Left / Down / Up / Right) |
| `Ctrl+q` then `z` | Toggle pane zoom |
| `Ctrl+q` then `x` | Close current pane (with confirmation) |
| `Ctrl+q` then `c` / `n` / `p` | New tab / Next tab / Previous tab |
| `Ctrl+q` then `w` | Fuzzy workspace, tab & launch-menu switcher |
| `Ctrl+q` then `[` / `Space` | Enter Copy Mode / QuickSelect |

### VS Code Keybindings

| Shortcut | Action |
| :--- | :--- |
| `Shift + Enter` (in AI Chat input) | Submit AI Chat prompt (`Enter` alone safely inserts a newline) |
| `Ctrl + Shift + \`` | Open new integrated terminal |
| `Ctrl + Alt + R` | Reload VS Code window |

### Cross-Shell Aliases (PowerShell 7 & Zsh / Bash)

| Alias / Function | Command |
| :--- | :--- |
| `ll` / `la` / `lt` | `eza` long / all / tree view with Git status & icons (falls back to `Get-ChildItem` / `ls`) |
| `g` / `gs` / `gd` / `gl` | `git` / `git status -sb` / `git diff` / `git lg -n 15` |
| `gco` / `gwt` | `git checkout` / `git worktree` |
| `..` / `...` / `....` | Navigate up 1 / 2 / 3 parent directories |
| `mkcd <dir>` | Create directory and immediately `cd` into it |
| `z <query>` / `zi` | Smart directory jump via `zoxide` (lazy-loaded on first invocation) |
| `dotfiles-doctor` | Run `python scripts/dotfiles.py doctor` |
| `reload` (PowerShell) | Reload `$PROFILE` in current session |
