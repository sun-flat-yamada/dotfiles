---
title: "Claude Code Configuration for dotfiles"
description: "Context rules, command shortcuts, and operational directives for Claude Code and AI assistant workflows in sun-flat-yamada/dotfiles."
category: "meta"
type: "configuration"
status: "active"
date: 2026-10-22
updated: 2026-10-22
lang: "en"
tags:
  - "claude-code"
  - "ai"
  - "agent"
  - "dotfiles"
---

# Claude Code Configuration for dotfiles

## Global Rules & Context
@.agents/rules/coding-rules-general.md
@.agents/rules/naming-rules-general.md
@.agents/rules/security-rules-general.md
@.agents/rules/git-rules-commit.md
@.agents/rules/permission-rules-general.md

## Commands
- `/status`: Run `python scripts/dotfiles.py status` and `git status -sb`.
- `/validate`: Run `python scripts/dotfiles.py validate`, `python scripts/validate-frontmatter.py`, and `python scripts/validate-filenames.py`.
- `/test`: Run `python tests/test-dotfiles.py -v` and `python tests/test-permission-guard.py -v`.
- `/doctor`: Run `python scripts/dotfiles.py doctor`.
- `/review`: Evaluate current branch against `.agents/agents/code-review.agent.md`.

## Directives
- **Manifest Single Source of Truth**: Every managed dotfile under `config/` or `packages/` MUST be registered in `config/manifest.json` using portable `~/` target paths.
- **Naming Rule Enforcement**: Adhere strictly to `.agents/rules/naming-rules-general.md`. Agent definition files MUST use the suffix `*.agent.md` and MUST NEVER use the `agent-` prefix.
- **Zero Secrets & Portability**: Never commit API keys, tokens, `.credentials.json`, `history.jsonl`, or hardcoded user paths (`C:\Users\...`). Verify with `python scripts/dotfiles.py validate`.
- **Permission Tiers**: Follow `.agents/rules/permission-rules-general.md` (A: always allow, C: conditional, N: never).
- **Output Language**: Reply to the user and write PR titles/descriptions in Japanese; commit messages, code, identifiers, and comments stay in English.
