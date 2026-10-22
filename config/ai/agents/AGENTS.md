---
title: "Universal Multi-AI Agent Global Instructions (AGENTS.md)"
description: "Single Source of Truth for global language, security, permission tiers, and engineering discipline across Claude Code, Google Antigravity, Gemini CLI, OpenAI Codex CLI, and GitHub Copilot."
category: "ai-governance"
type: "instruction"
status: "active"
date: 2026-10-22
updated: 2026-10-22
lang: "ja"
tags: ["ai-agents", "claude-code", "antigravity", "gemini-cli", "codex", "copilot"]
---

# グローバル AI エージェント共通規約 (AGENTS.md)

## 1. 言語ポリシー (Language Policy)

私は日本語で読み書きする。
私に向けて書くものは、セッションの最初から最後まで日本語で書く。
英語の返答は私の手間を増やし、読み違いの元になる。

- 対象は、チャットの返答、作業の途中経過、質問、最終報告のすべてである。
- 長い作業の途中でも日本語を続ける。ツールの結果、エラー、参照した資料、バックグラウンドの処理の通知が英語であっても、それに引きずられて英語で書かない。
- 返答を送る前に、地の文が日本語になっているかを確かめる。英語で書いていたら、日本語に書き直してから送る。
- 英語のままにするのは、コード、識別子、コマンド、ファイルパス、エラーメッセージ、英語の固有名詞と技術用語だけである。
- 私以外に向けたものは、次のとおりに書き分ける。リポジトリの `CLAUDE.md` / `AGENTS.md` に指定があれば、そちらに従う。
  - Issue、PR のタイトルと本文、PR へのレビューの返信: 日本語
  - コミットメッセージ: リポジトリの慣習に従う（既定は英語の Conventional Commits）
  - コード、識別子、コードのコメント: リポジトリの既存の慣習に従う（既定は英語）

## 2. セキュリティ・機密保護 (Zero-Secret Principle)

- API キー、トークン（`ghp_*`, `gho_*`, `sk-ant-*`, `AIza*` 等）、秘密鍵（`*.pem`, `*.key`）、個人認証情報を絶対にハードコード・出力・コミットしない。
- 環境固有の機密設定は常に `.env.local`、`~/.gitconfig.local`、`~/.powershell.local.ps1`、`~/.zshrc.local` に分離する。

## 3. 権限 3 分類 (Permission Tiers: A / C / N)

- **Tier A (Always Allow)**: ファイル読取、静的解析、ローカルテスト、構文検証（`git status`, `git diff`, `pytest`, `validate-*`）。
- **Tier C (Conditional Allow)**: ファイル編集、通常の `git commit` / `git push`（保護ブランチ外）、依存パッケージ追加。
- **Tier N (Never Allow)**: 破壊的コマンド（`rm -rf /`, `git push --force main`）、シークレットファイルの外部送信、ガードフックのバイパス。
