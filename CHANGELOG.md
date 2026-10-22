---
title: "Changelog — sun-flat-yamada/dotfiles"
description: "All notable changes to sun-flat-yamada/dotfiles following Keep a Changelog and Semantic Versioning."
category: "documentation"
type: "changelog"
status: "active"
date: 2026-10-22
updated: 2026-10-22
lang: "en"
tags: ["changelog", "release", "dotfiles"]
---

# Changelog

All notable changes to `sun-flat-yamada/dotfiles` will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
