---
title: "Changelog — sun-flat-yamada/dotfiles"
description: "All notable changes to sun-flat-yamada/dotfiles following Keep a Changelog and Semantic Versioning."
category: "documentation"
type: "changelog"
status: "active"
date: 2026-10-22
updated: 2026-11-13
lang: "en"
tags: ["changelog", "release", "dotfiles"]
---

# Changelog

All notable changes to `sun-flat-yamada/dotfiles` will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **AI agent permission policy, November 2026 revision** (`.agents/rules/permission-rules-general.md`):
  - New rules `N-12` (audit trail tampering), `C-HITL-09` (starting a nested agent session such as `claude -p` or `codex exec`), and `C-HITL-10` (git configuration that runs a program, such as `core.fsmonitor` and `core.sshCommand`).
  - New evaluation principles 7 to 9: check what will run rather than what was written, give a second route the same gate, and treat repository-supplied configuration as code.
  - `N-01`, `N-03`, `N-04`, `N-05`, `N-06`, `N-08`, `N-09`, and `C-HITL-07` now cover AI tool credential stores, password managers, Windows elevation and persistence, agent API endpoint overrides (`ANTHROPIC_BASE_URL`), decoded payloads piped into an interpreter, `gh api` routes to merge and branch protection, making a repository public, and plugin or extension installs.
- **Guard hook** (`.claude/hooks/permission-guard.py`): resolves ANSI-C quoting and line continuations, inspects inline `python -c` / `node -e` code that shells out, compares paths the way Windows opens them (trailing dot, case, `::$DATA`), and recognizes PowerShell cmdlets.
- **Claude Code**: `PowerShell(...)` deny and ask rules, `sandbox.network.deniedDomains`, and more credential paths and variables hidden from the sandbox.
- **Tests**: Codex `match` / `not_match` examples and Gemini regex loader constraints are now checked in `tests/test-permission-guard.py`.

### Changed
- Codex, Gemini, Cursor, and VS Code enforcement files carry the same additions as the canonical policy.
- The global Claude Code settings (`config/ai/claude/settings.json`) deny reads of the same credential stores as the project policy.
- `docs/guides/ai-permission-guide.md` records the persona review, ten incidents from September to November 2026, and the options that were considered and not adopted.

## [1.0.0] - 2026-10-22

### Added
- **Declarative Cross-Platform Dotfiles Engine (`scripts/dotfiles.py` & `config/manifest.json`)**:
  - Supports `windows`, `wsl`, `linux`, and `macos` targets across modular profiles (`full`, `core`, `git`, `wsl`, `terminal`, `shell`, `starship`, `editor`, `ai`, `packages`).
  - Idempotent `install` with `--dry-run`, automatic backup of drifted files (`~/.dotfiles-backup/<timestamp>/restore-manifest.json`), symlink-to-copy fallback on Windows, `status`, `rollback`, `doctor`, and `validate` subcommands.
  - Native bootstrap entrypoints (`install.ps1` for PowerShell 7, `install.sh` for POSIX/WSL2).
- **2026 Terminal & Shell Configurations**:
  - **WezTerm** (`config/wezterm/wezterm.lua`, `config/wezterm/keybinds.lua`): WebGPU front-end, `Dark 2026` palette, Nerd Font fallback chain (`Hack Nerd Font Mono Regular`, `HackGen Console NF Regular`), custom powerline tab renderer, and multiplexer leader keybindings (`Ctrl+q`).
  - **Windows Terminal** (`config/windows-terminal/settings.fragment.json`): `Dark 2026` color scheme and PowerShell 7 profile fragment.
  - **PowerShell 7** (`config/powershell/Microsoft.PowerShell_profile.ps1`): Sub-50ms startup with lazy-loaded `zoxide`/`mise` stubs, PSReadLine predictive `ListView`, and secret-safe history filter blocking API keys/tokens from disk persistence.
  - **Zsh & Bash** (`config/shell/.zshrc`, `.bashrc`, `.aliases`): XDG base directory compliance, WSL2 clipboard/browser bridge (`clip.exe`, `wslview`), daily-cached completions, and secret-safe history filter.
  - **Starship** (`config/starship/starship.toml`): Cross-shell prompt styled in the `Dark 2026` palette (`#a94dc1`, `#ffd866`, `#00B3BD`, `#78e8c6`).
- **Git & WSL2 Configurations**:
  - **Git** (`config/git/.gitconfig`, `.gitignore_global`, `.gitattributes_global`, `.gitconfig.local.example`): 2026 Git best practices (`merge.conflictStyle = zdiff3`, `diff.algorithm = histogram`, `rebase.updateRefs = true`, `rerere.enabled = true`, `core.fsmonitor = true`, `branch.sort = -committerdate`).
  - **WSL2** (`config/wsl/.wslconfig`, `wsl.conf`): Mirrored networking mode, `dnsTunneling`, `autoMemoryReclaim=dropcache`, and `sparseVhd=true`.
- **Editor & Multi-AI Coding Agent Global Configurations**:
  - **VS Code** (`config/vscode/settings.json`, `keybindings.json`, `extensions.json`): `Dark 2026` workbench customizations, Japanese word segmenter, `Shift+Enter` chat submit protection, and AI hook bindings.
  - **Multi-AI Agents** (`config/ai/`): Unified global instructions (`~/.agents/AGENTS.md`, `~/.claude/CLAUDE.md`, `~/.claude/settings.json`, `~/.config/ccstatusline/settings.json`, `~/.gemini/GEMINI.md`, `~/.codex/config.toml`).
- **Declarative Package Manifests (`packages/`)**:
  - WinGet DSC (`packages/winget/configuration.winget`), Scoop (`packages/scoop/scoopfile.json`), `mise` (`packages/mise/config.toml`), and Homebrew (`packages/homebrew/Brewfile`).
- **Governance, Security & Cross-Platform CI**:
  - Dual-OS GitHub Actions workflow (`ubuntu-latest` + `windows-latest`), Gitleaks zero-leak scanning, AI Agent Permission Guard (`A/C/N` tiers), and unit/integration test suites (`tests/test-dotfiles.py`).
