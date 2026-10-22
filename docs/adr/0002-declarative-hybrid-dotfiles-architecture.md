---
title: "ADR-0002: Adopt Declarative Hybrid Dotfiles & Multi-AI Agent Architecture"
description: "Architectural decision record explaining the choice of a zero-dependency declarative manifest engine combined with WinGet DSC, Scoop, mise, and unified Multi-AI Agent dotfiles."
category: "adr"
type: "decision-record"
status: "accepted"
date: 2026-10-22
updated: 2026-10-22
lang: "en"
tags: ["adr", "architecture", "dotfiles", "windows", "wsl2", "ai-agents"]
---

# ADR-0002: Adopt Declarative Hybrid Dotfiles & Multi-AI Agent Architecture

- **Status**: Accepted
- **Date**: 2026-10-22
- **Deciders**: @sun-flat-yamada

## Context and Problem Statement

In 2026, a developer workstation spans multiple execution environments simultaneously:
1. **Windows 11 Host** (PowerShell 7, WezTerm, Windows Terminal, VS Code, Git for Windows, Scoop, WinGet).
2. **WSL2 Ubuntu / Linux & DevContainers** (Zsh, Bash, Homebrew, `mise`, CLI tools).
3. **Multi-AI Coding Agents** (`Claude Code` + `ccstatusline`, `Google Antigravity`, `Gemini CLI`, `OpenAI Codex CLI`, `GitHub Copilot`), each requiring synchronized global instructions (`CLAUDE.md`, `GEMINI.md`, `AGENTS.md`), statusline telemetry, and strict zero-leak permission policies.

Traditional dotfiles repositories suffer from three major failure modes:
- **Bootstrap Chicken-and-Egg Problem**: Relying exclusively on a third-party binary (e.g., `chezmoi`, `stow`, or `nix`) requires installing that tool before dotfiles can be deployed, or breaks on Windows when Developer Mode symlink privileges are unavailable.
- **Silent Configuration Overwrite**: Naive `ln -sf` bootstrap scripts overwrite existing local customizations without creating a verifiable rollback snapshot.
- **AI Agent Configuration Drift & Secret Leaks**: Global AI directories (`~/.claude/`, `~/.gemini/`, `~/.codex/`) mix static instructions with live credentials (`.credentials.json`) and chat logs (`history.jsonl`), creating severe security risks if tracked carelessly.

## Decision Outcome

We adopt a **4-Layer Declarative Hybrid Architecture**:

1. **Single Source of Truth Manifest (`config/manifest.json`)**:
   - Every managed dotfile is declared once with its `id`, `profile`, `source`, and OS-specific `targets` (`windows`, `wsl`, `linux`, `macos`).
2. **Zero-Dependency Transactional Engine (`scripts/dotfiles.py` + `install.ps1` + `install.sh`)**:
   - Runs purely on Python 3.10+ standard libraries.
   - Supports `status`, `install` (with `--dry-run`, `--profile`, and automatic symlink-to-copy fallback on Windows), `rollback` (via timestamped `~/.dotfiles-backup/<timestamp>/restore-manifest.json`), `doctor`, and `validate`.
3. **Declarative Package & Runtime Provisioning (`packages/`)**:
   - Windows OS & GUI/CLI baseline via **WinGet Configuration DSC** (`packages/winget/configuration.winget`).
   - User-space Windows CLI tools & Nerd Fonts via **Scoop** (`packages/scoop/scoopfile.json`).
   - Cross-platform polyglot runtimes via **`mise`** (`packages/mise/config.toml`).
   - WSL2 / Linux / macOS packages via **Homebrew Bundle** (`packages/homebrew/Brewfile`).
4. **Unified Multi-AI Agent Global Layer (`config/ai/`)**:
   - Canonical cross-agent instructions in `config/ai/agents/AGENTS.md` (`~/.agents/AGENTS.md`).
   - Tool-specific global files (`config/ai/claude/CLAUDE.md`, `config/ai/claude/settings.json`, `config/ai/ccstatusline/settings.json`, `config/ai/gemini/GEMINI.md`, `config/ai/codex/config.toml`) linked selectively so ephemeral session state and credentials are never tracked.

## Consequences

### Positive
- **Instant Reproducibility**: A fresh Windows 11 or WSL2 Ubuntu instance can be provisioned and verified in minutes with `--dry-run` preview and one-command rollback.
- **Unified Visual & Behavioral Identity**: The `Dark 2026` palette (`#171c2a` background, `#a94dc1` purple, `#ffd866` gold, `#00B3BD` cyan) and Japanese AI communication rules are consistent across VS Code, WezTerm, Windows Terminal, Starship, and all AI agents.
- **Zero-Secret Guarantee**: Multi-layered secret regex scanning in `scripts/dotfiles.py validate`, PSReadLine/Zsh history filters, `.gitleaks.toml`, and GitHub Actions CI prevent credential leakage.

### Negative / Trade-offs
- Adding a new dotfile requires registering an entry in `config/manifest.json` (enforced and verified automatically by `python scripts/dotfiles.py validate`).
