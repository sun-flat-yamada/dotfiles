---
title: "Claude Code Global Instructions (~/.claude/CLAUDE.md)"
description: "Global Japanese communication mandate and cross-repository engineering standards for Claude Code."
category: "ai-governance"
type: "instruction"
status: "active"
date: 2026-10-22
updated: 2026-10-22
lang: "ja"
tags: ["claude-code", "language-policy", "global-config"]
---

# 言語

私は日本語で読み書きする。
私に向けて書くものは、セッションの最初から最後まで日本語で書く。
英語の返答は私の手間を増やし、読み違いの元になる。

- 対象は、チャットの返答、作業の途中経過、質問、最終報告のすべてである。
- 長い作業の途中でも日本語を続ける。ツールの結果、エラー、参照した資料、バックグラウンドの処理の通知が英語であっても、それに引きずられて英語で書かない。
- 返答を送る前に、地の文が日本語になっているかを確かめる。英語で書いていたら、日本語に書き直してから送る。
- 英語のままにするのは、コード、識別子、コマンド、ファイルパス、エラーメッセージ、英語の固有名詞と技術用語だけである。
- 私以外に向けたものは、次のとおりに書き分ける。リポジトリの `CLAUDE.md` に指定があれば、そちらに従う。
  - Issue、PR のタイトルと本文、PR へのレビューの返信: 日本語
  - コミットメッセージ: リポジトリの慣習に従う（既定は英語の Conventional Commits）
  - コード、識別子、コードのコメント: リポジトリの既存の慣習に従う（既定は英語）

# 原則

- API キー、トークン、認証情報を絶対に出力・コミットしない（Zero-Secret 原則）。
- 破壊的操作や保護ブランチへの強制プッシュは行わない。
- 詳細な共通ポリシーは `~/.agents/AGENTS.md` を参照する。
