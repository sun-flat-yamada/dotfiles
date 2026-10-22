---
title: "Universal AI Agent Instructions for sun-flat-yamada/dotfiles"
description: "Repository-level entry point for OpenAI Codex CLI, Google Antigravity, Gemini CLI, Claude Code, and GitHub Copilot."
category: "meta"
type: "instruction"
status: "active"
date: 2026-10-22
updated: 2026-10-22
lang: "ja"
tags: ["agents", "governance", "dotfiles", "security"]
---

# AGENTS.md — `sun-flat-yamada/dotfiles`

## 1. 言語・コミュニケーション規約

- ユーザーへのチャット返答、経過報告、質問、Issue、PR タイトル・本文、レビューコメントは**すべて日本語**で記述する。
- コミットメッセージは英語の Conventional Commits（`feat:`, `fix:`, `docs:`, `test:`, `ci:`, `chore:` 等）に従う。
- コード、識別子、設定キー、ファイルパスは英語のまま維持する。

## 2. コア設計・検証ルール

- **Single Source of Truth (`config/manifest.json`)**: 管理対象のすべての dotfile は `config/manifest.json` に登録し、ターゲットパスはポータブルな `~/` 記法を使用する。
- **検証コマンドの必須実行**: 変更後は必ず以下の検証スイートを実行し、すべてパスすることを確認する。
  - `python scripts/dotfiles.py validate`
  - `python tests/test-dotfiles.py -v`
  - `python tests/test-permission-guard.py -v`
  - `python scripts/validate-frontmatter.py`
  - `python scripts/validate-filenames.py`
- **Zero-Secret & Portability**: API キー、トークン、認証ファイル（`.credentials.json`, `auth.json`, `oauth_creds.json`）、会話履歴（`history.jsonl`）、およびローカル固有の絶対パス（`C:\Users\...` や `V:\repos\...`）を絶対にコミットしない。
- **権限ポリシー (Tier A / C / N)**: `.agents/rules/permission-rules-general.md` に従う。
