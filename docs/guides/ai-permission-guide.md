---
title: "AIエージェント権限設定ガイド（Permission Policy）"
description: "AIコーディングエージェントの権限を「常に許可・条件付き許可（条件別）・いかなる場合も禁止」の3分類で定義した根拠（ベストプラクティスと事故事例の調査結果）と、Claude Code / Codex CLI / Gemini CLI / Cursor / GitHub Copilot 向け設定ファイルの導入・検証手順をまとめたガイド。"
category: "guide"
type: "security"
status: "active"
date: 2026-10-01
updated: 2026-11-13
lang: "ja"
tags:
  - "security"
  - "permissions"
  - "ai-agents"
  - "least-privilege"
  - "prompt-injection"
  - "claude-code"
  - "codex"
  - "gemini-cli"
  - "cursor"
  - "github-copilot"
---

# AIエージェント権限設定ガイド（Permission Policy）

本ガイドは、AIコーディングエージェントに与える権限を **常に許可（A）・条件付き許可（C、条件別）・いかなる場合も禁止（N）** の3分類で定めた理由と、各AIツールの設定ファイルへの落とし込み方を説明します。

- 正規のルール定義（ルールID付き）: [`.agents/rules/permission-rules-general.md`](../../.agents/rules/permission-rules-general.md)
- 意思決定記録: [ADR-0001](../adr/0001-adopt-ai-agent-permission-policy.md)

> **前提**: プロンプトや `CLAUDE.md` に書いた禁止事項は「お願い」にすぎず、強制力はありません。権限はツールの設定（許可/拒否ルール）、OSサンドボックス、フック、そしてGitHub側の保護設定で**機械的に**強制します（[Claude Code公式ドキュメント](https://code.claude.com/docs/en/permissions)も同じ立場です）。

---

## 1. ファイル構成

| ツール | 設定ファイル | 反映条件 |
| :--- | :--- | :--- |
| 共通（正規ポリシー） | `.agents/rules/permission-rules-general.md` | 各エージェントの指示ファイルから参照 |
| Claude Code | `.claude/settings.json`、`.claude/hooks/permission-guard.py` | `allow` はワークスペース信頼後に有効。`deny`/`ask` は即時有効 |
| OpenAI Codex CLI | `.codex/config.toml`、`.codex/rules/permission-policy.rules` | プロジェクトを trusted にした後に読み込み |
| Gemini CLI / Antigravity | `.gemini/settings.json`、`.gemini/policies/permission-policy.toml` | ポリシーは `~/.gemini/policies/` へのコピーが必要（後述） |
| Cursor | `.cursor/cli.json`（CLI）、`.cursor/permissions.json`（IDE） | リポジトリを開くと読み込み |
| GitHub Copilot（VS Code） | `.vscode/settings.json` | ワークスペース設定として適用 |
| テスト | `tests/test-permission-guard.py` | `python tests/test-permission-guard.py -v`（CIでも実行） |

---

## 2. 調査サマリ：ベストプラクティス

### 2.1 業界の共通原則

| 原則 | 内容 | 主な出典 |
| :--- | :--- | :--- |
| 最小権限・最小エージェンシー | 機能・権限・自律性の「過剰」を削る。高影響の操作は人間が承認する。認可判断をLLMに任せず下流システムで強制する。 | [OWASP LLM06:2025 Excessive Agency](https://genai.owasp.org/llmrisk/llm062025-excessive-agency/)、[OWASP Top 10 for Agentic Applications 2026](https://genai.owasp.org/2025/12/09/owasp-top-10-for-agentic-applications-the-benchmark-for-agentic-security-in-the-age-of-autonomous-ai/)（ASI02 ツール悪用、ASI03 権限濫用、ASI05 想定外のコード実行） |
| Lethal Trifecta / Rule of Two | 「機密データへのアクセス」「信頼できない入力」「外部への通信・状態変更」の3つが揃うとプロンプトインジェクションで情報が抜かれる。1セッションで同時に満たすのは2つまで。 | [Simon Willison: The lethal trifecta](https://simonwillison.net/2025/Jun/16/the-lethal-trifecta/)、[Meta: Agents Rule of Two](https://ai.meta.com/blog/practical-ai-agent-security/) |
| 人間の管理者・限定された権限・可観測性 | 決定論的な制御（ポリシー・サンドボックス）と推論ベースの防御を組み合わせる多層防御。 | [Google: An Introduction to Google's Approach for Secure AI Agents](https://research.google/pubs/an-introduction-to-googles-approach-for-secure-ai-agents/) |
| 段階的導入・承認ゲート | 狭いタスクから始め、高影響操作には明示的な人間の承認ゲートを置く。エージェントごとに最小権限の識別子・短命クレデンシャルを使う。 | [CISA ほか5か国: Careful Adoption of Agentic AI Services（2026-05-01）](https://www.cisa.gov/resources-tools/resources/careful-adoption-agentic-ai-services) |
| AI利用者の責務 | AI利用者は安全性・セキュリティ・プライバシー確保のための適切な利用と人間の関与を担う。 | [総務省・経済産業省: AI事業者ガイドライン](https://www.meti.go.jp/shingikai/mono_info_service/ai_shakai_jisso/20240419_report.html) |

### 2.2 ベンダー・専門家の推奨（2026年10月時点の一次情報）

- **Claude Code**: ルールは `deny → ask → allow` の順に評価され、最初に一致したものが優先。`Bash(git push *)` のようなパターンは「書かれた形」にしか一致せず、`git -C . push` や `sh -c '…'` は素通りするため、境界としてはOSサンドボックス（ファイル書き込みはワークスペースのみ、ネットワークは許可ドメインのみ）と PreToolUse フックを併用することが推奨されています（[permissions](https://code.claude.com/docs/en/permissions)、[sandboxing](https://code.claude.com/docs/en/sandboxing)）。自動モードの分類器は強制プッシュ、本番デプロイ、`curl | bash`、秘密情報の外部送信、IAM付与などを既定でブロックします（[permission-modes](https://code.claude.com/docs/en/permission-modes)）。Anthropic社内ではサンドボックスにより確認プロンプトが84%減ったと報告されています（[Anthropic Engineering](https://www.anthropic.com/engineering/claude-code-sandboxing)）。
- **OpenAI Codex CLI**: サンドボックス（`workspace-write`、ネットワーク既定オフ）と承認ポリシーの2軸。`.rules` の `prefix_rule` は `forbidden > prompt > allow` の最も厳しい判定が採用され、`allow` は「サンドボックス外で無確認実行」を意味します（[execpolicy README](https://github.com/openai/codex/blob/main/codex-rs/execpolicy/README.md)、[Codex rules](https://developers.openai.com/codex/rules)）。
- **Gemini CLI**: TOMLのポリシーエンジン（`allow` / `deny` / `ask_user`、優先度、モード別）。シェルコマンドは部分コマンドごとに検査され、1つでも `deny` なら拒否されます（[Policy engine](https://github.com/google-gemini/gemini-cli/blob/main/docs/reference/policy-engine.md)）。
- **VS Code（GitHub Copilot）**: ターミナル自動承認は「ベストエフォートであり、セキュリティ境界ではない」と明記。`false` ルールは承認要求であってブロックではなく、ブロックにはフック、隔離にはサンドボックスを使うよう案内されています（[Manage approvals](https://code.visualstudio.com/docs/agents/run/approvals)、[Agent sandboxing](https://code.visualstudio.com/docs/agents/run/agent-sandboxing)）。
- **GitHub Copilot coding agent**: ファイアウォール付きのActions上で動作し、`copilot/` で始まるブランチにしかpushできず、依頼者自身はそのPRを承認できない設計です（[Customize the agent firewall](https://docs.github.com/en/copilot/how-tos/use-copilot-agents/coding-agent/customize-the-agent-firewall)）。
- **Trail of Bits（セキュリティ企業の実運用例）**: 認証情報（`~/.ssh`、`~/.aws`、`~/.kube`、`~/.npmrc` 等）の読み取り拒否、シェル設定ファイルの編集拒否、`rm -rf` と main への直接pushをフックで阻止。「フックは境界ではなくガードレール」と明言しています（[trailofbits/claude-code-config](https://github.com/trailofbits/claude-code-config)）。

### 2.3 導いた設計方針

1. **拒否を先に評価**し、どのルールにも一致しない操作は「許可」ではなく「承認要求（C-HITL）」に倒す。
2. **ネットワーク送信と外向きのVCS操作（push、PR、公開）を統制点**にする（Lethal Trifecta対策）。
3. **プロジェクトのコード実行（ビルド・テスト）は「サンドボックス内なら許可」**とする。エージェントがファイルを編集でき、かつテストを実行できる時点で任意コード実行と等価だからです。
4. **パターンルール・フック・サンドボックス・GitHub側の保護を重ねる**。どれか1つを過信しない。
5. **AI自身の設定ファイル（権限・フック・MCP）の変更は人間の承認必須**、承認を全面的に無効化する設定の書き込みは禁止（下記CVE事例）。

### 2.4 2026年11月改訂：新しい調査結果と複数ペルソナレビュー

2026年10〜11月に公開された一次情報を取り込み、5つの視点（ペルソナ）で既存ポリシーを点検しました。ルールIDは既存のものを変更せず、**N-12、C-HITL-09、C-HITL-10 と評価原則 7〜9 を追加**し、N-01 / N-03 / N-04 / N-05 / N-06 / N-08 / N-09 / C-HITL-07 の対象を広げています。

| ペルソナ | 指摘 | 対応 |
| :--- | :--- | :--- |
| **攻撃者（レッドチーム）** | 判定した文字列と実際に実行される文字列がずれる（`$'su\x64o'`、行継続、`busybox sh -c`、`python -c "os.system(…)"`、`base64 -d \| sh`、`powershell -EncodedCommand`）。別経路で同じ結果に届く（`gh api …/merge`、子エージェントの起動、設定ファイルへの直接書き込み）。 | 原則7・8。ガードフックが ANSI-C クォートと行継続を解決し、インラインコードの文字列リテラル、デコード結果のパイプ、`gh api` を検査。N-06 / N-08 を拡張。C-HITL-09 を新設。 |
| **Windows / WSL2 プラットフォーム担当** | Claude Code の PowerShell ツール向けルールが無く、ネイティブ Windows はサンドボックスも無い。`.mcp.json.`（末尾ドット）・大文字小文字・`::$DATA` で設定ファイル保護を回避できる。`Start-Process -Verb RunAs`、タスクスケジューラ、`Run` レジストリ、Defender 無効化が未定義。 | `.claude/settings.json` に `PowerShell(...)` の deny / ask を追加。ガードフックがパスを正規化し、PowerShell コマンドレットを判定。N-03 / N-04 / N-05 を拡張。 |
| **日常利用する開発者（摩擦の最小化）** | 誤検知が多いと承認疲れになり、確認を読まずに通す。dotfiles リポジトリでは `config/shell/.zshrc` の編集が日常作業。 | `git -c core.pager=cat`、`GIT_EDITOR=true`、`claude --version`、`cp ~/.zshrc config/shell/.zshrc`、`curl … \| python3 parse.py` は判定対象外。ホーム直下の起動ファイルだけを N-03 とし、ワークスペース内の同名ファイルは A-03 のまま。許可されるべきコマンドをテストに固定。 |
| **ガバナンス / 監査担当** | エージェントが自分の実行記録を消せる。APIエンドポイントを差し替えられると会話とトークンが第三者へ流れる。ツール間でルールの有無がずれる。 | N-12（監査証跡の改ざん）を新設。N-04 にエンドポイント差し替え・フック無効化を追加。5ツールすべての設定を同じPRで更新し、Codex ルールの `match` 例と Gemini の正規表現制約をテストで検証。 |
| **サプライチェーン担当** | リポジトリやダウンロードに含まれる設定（`.git/config` の `core.fsmonitor`、フック、MCP、プラグイン、`AGENTS.md`）は開発者権限で動くコード。プラグイン更新でフックが差し替わる。 | 原則9。C-HITL-10（プログラムを実行する git 設定）を新設。C-HITL-07 をプラグイン・拡張機能・スキル・フック・mod の追加と更新に拡張。 |

採用しなかった案と理由:

- **Claude Code の自動モードの無効化（`permissions.disableAutoMode`）**: `ask` ルールは自動モードでも必ず人間に確認されるため C-HITL は維持されます。分類器は境界ではない（[回避率79%の報告](https://arxiv.org/abs/2609.19587)）ので、自動モードを使う場合もサンドボックスと `ask` / `deny` を前提にしてください。組織で禁止したい場合は managed settings で設定します。
- **許可リスト外ドメインの即時拒否（`sandbox.network.strictAllowlist`）**: ポリシーは「許可リスト外は人間の承認（C-HITL）」のため、確認を出す既定動作のままにしています。流出先は `sandbox.network.deniedDomains` で拒否します。
- **すべての MCP ツールへの一律 `ask`（`mcp__*`）**: 読み取り専用ツールまで毎回確認になり承認疲れを招くため見送りました。サーバーの追加時（C-HITL-07）に確認します。
- **Codex の permission profiles（`default_permissions`、`**/*.env = "deny"`）への移行**: N-01 の読み取り制限を強化できますが、`sandbox_mode` と併用できず挙動確認に Codex 実機が必要なため、次回の改訂候補とします。

---

## 3. 事例（インシデント・脆弱性）と対応ルール

| 事例（時期） | 何が起きたか | 教訓 | 対応ルール |
| :--- | :--- | :--- | :--- |
| [Replit エージェントによる本番DB削除](https://oecd.ai/en/incidents/2025-07-19-1eb1)（2025-07） | 「変更しないで」という指示を無視して本番DBを削除し、偽データを生成。 | 指示では止まらない。本番への到達経路と破壊操作を技術的に遮断する。 | N-07、C-SCOPE-03 |
| [Amazon Q Developer 拡張への破壊的プロンプト混入](https://www.bleepingcomputer.com/news/security/amazon-ai-coding-agent-hacked-to-inject-data-wiping-commands/)（2025-07） | 公開リポジトリ経由で「ホーム削除・AWSリソース削除」を指示するプロンプトが製品に混入。 | 全ツール自動許可（`--trust-all-tools`）で動かさない。クラウド削除系は常時禁止。 | N-04、N-05、N-07 |
| [Nx「s1ngularity」サプライチェーン攻撃](https://research.jfrog.com/post/nx-supply-chain-attack-targets-ai-tool-users/)（2025-08） | 悪性npmパッケージが、端末にあるAI CLIを `--dangerously-skip-permissions` / `--yolo` / `--trust-all-tools` 付きで起動し、秘密情報を探索・流出。 | 権限バイパスモードそのものを無効化する。資格情報ファイルはOSレベルで読めなくする。 | N-04（`disableBypassPermissionsMode`、`disableYoloMode`）、N-01 |
| [Gemini CLI の許可リスト回避](https://tracebit.com/blog/code-exec-deception-gemini-ai-cli-hijack)（2025-06〜07） | 許可済みの `grep` の後ろに `;` で `env \| curl` を連結し、無確認で環境変数を外部送信。 | 連結コマンドは部分ごとに判定する。許可ルールは最小限に。 | 原則1、C-HITL-04、N-09 |
| [Claude Code の DNS 経由データ流出（CVE-2025-55284）](https://advisories.gitlab.com/npm/@anthropic-ai/claude-code/CVE-2025-55284/)（2025-08） | 読み取り専用扱いだった `ping`/`nslookup`/`dig` で秘密情報をサブドメインに埋め込み送信。 | 「読み取り専用」に見えるネットワークコマンドも外部通信。 | C-HITL-04、N-09 |
| [GitHub Copilot の設定改ざんによるRCE（CVE-2025-53773）](https://www.wiz.io/vulnerability-database/cve/cve-2025-53773)（2025-08） | プロンプトインジェクションで `.vscode/settings.json` に `"chat.tools.autoApprove": true` を書かせ、YOLO状態にしてコード実行。 | AIに自分の権限設定を書き換えさせない。 | C-HITL-05、N-04（ガードフックが書き込み内容を検査） |
| [Cursor の MCP 設定悪用（CurXecute / MCPoison: CVE-2025-54135 / 54136）](https://www.tenable.com/blog/faq-cve-2025-54135-cve-2025-54136-vulnerabilities-in-cursor-curxecute-mcpoison)（2025-08） | 一度承認されたMCP設定を後から悪性コマンドへ差し替え、永続的に実行。 | MCPサーバーの追加・変更は毎回人間が確認。一括承認しない。 | C-HITL-05、C-HITL-07（`enableAllProjectMcpServers: false`、`mcpAllowlist: []`） |
| [Claude Code プロジェクト設定経由のRCE・APIキー窃取（CVE-2025-59536 / CVE-2026-21852）](https://research.checkpoint.com/2026/rce-and-api-token-exfiltration-through-claude-code-project-files-cve-2025-59536/)（2026-02） | 悪性リポジトリのフック・MCP設定・`ANTHROPIC_BASE_URL` で、信頼ダイアログ前にコマンド実行やキー送信。 | クローンしたリポジトリの `.claude/` `.mcp.json` `.env` はレビュー対象。プロジェクトの `.env` を自動で読ませない。 | C-HITL-05、N-01（Gemini は `ignoreLocalEnv: true`） |
| [Shai-Hulud 2.0 npm ワーム](https://blog.checkpoint.com/research/shai-hulud-2-0-inside-the-second-coming-the-most-aggressive-npm-supply-chain-attack-of-2025/)（2025-11） | `preinstall` スクリプトで開発端末・CIの認証情報を窃取し、自己増殖的に公開。 | 依存追加は人間の承認、インストールはロックファイル準拠かつサンドボックス内。公開はCIのみ。 | C-HITL-02、C-SBX-02、N-10 |
| [Claude Code によるホームディレクトリ削除](https://gigazine.net/gsc_news/en/20251216-claude-code-cli-mac-deleted)（2025-12） | `rm -rf tests/ patches/ plan/ ~/` が実行されホーム全体が消失（権限確認スキップの可能性が指摘）。 | ホーム・ルート・ワークスペース直下の再帰削除は常時禁止。確認スキップ運用をしない。 | N-05、N-04 |
| [Google Antigravity の D: ドライブ全削除](https://letsdatascience.com/news/google-antigravity-deletes-user-d-drive-e6727dc7)（2025-12） | Turboモード（自動実行）でキャッシュ削除のつもりが `rmdir /s /q d:\` を実行。 | Windowsのドライブルート削除も同様に禁止。自動実行モードは隔離環境でのみ。 | N-05、N-04 |
| [GitSpawn：`.git/config` 経由のコード実行](https://www.manifold.security/blog/ai-coding-agents-git-hijack)（2026-10） | zip や共有フォルダで受け取ったリポジトリの `.git/config` に `core.fsmonitor` を仕込み、エージェントが起動時に実行する `git status` でコマンドが動く。7製品に影響。 | リポジトリ同梱の git 設定はコード。ファイルとして受け取ったディレクトリは `.git/config` を確認してから開く。プログラムを実行する git 設定の変更は人間が承認。 | 原則9、C-HITL-10、N-06（`ext::`） |
| [Session inception：子セッションによるガードレール回避](https://straiker.ai/blog/session-inception-spawning-a-child-claude-session-to-bypass-parent-guardrails)（2026-10） | 親セッションがシェルから `cd repo && claude -p …` を実行。子はリポジトリの設定を読み込み、SessionStart フックが確認なしで動いて環境情報を送信。ペイロードは DNS TXT をデコードして bash へ。 | 入口ではなく結果にゲートを置く。`claude -p` は信頼ダイアログを出さない。 | 原則8、C-HITL-09、N-06 |
| [ダウンロードフォルダ経由のエージェント乗っ取り](https://forever.security/blog/hijacking-ai-agents-via-downloads-folder)（2026-10） | クリックなしで保存された `AGENTS.md` / `CLAUDE.md` に従い、Codex は `~/.codex/config.toml` に悪性 MCP サーバーを追記、Claude Code は `.claude/settings.json` の `env` に `ANTHROPIC_BASE_URL` を書き込みトークンが流出。 | `~/Downloads` でエージェントを起動しない。エンドポイントの差し替えと MCP 追加を設定ファイル書き込みの段階で止める。 | 原則9、N-04、C-HITL-07 |
| [無許可のAI中継サービス](https://www.security.com/threat-intelligence/openai-claude-unauthorized-relays)（2026-10） | 正規の CLI を導入したうえで、サンドボックス無効化・ネットワーク許可・APIトークン差し替え・テレメトリ無効化を設定。 | インストール手順ではなく「結果の設定」を検査する。 | N-04 |
| [Visual Studio Copilot の設定保護回避（CVE-2026-103572）](https://embracethered.com/blog/posts/2026/visual-studio-copilot-remote-code-execution/)（2026-10） | 自身の設定を書き換えさせない検査が `.mcp.json.`（末尾ドット）を見逃し、Windows では同じファイルとして開かれてコマンド実行に到達。 | パスはOSが解決した後の姿で比較する（末尾ドット・空白、大文字小文字、代替データストリーム）。 | 原則7、N-01、N-04、C-HITL-05 |
| [Mistral Vibe の承認回避（CVE-2026-87987 / 87984）](https://blog.secmate.dev/posts/mistral-vibe-cve-2026-87987-cve-2026-87984/)（2026-09） | 承認ロジックが解析した文字列と実行される文字列が異なり、環境変数の前置・リダイレクト・ANSI-C 文字列・解析不能な構文で承認をすり抜け。 | 「書かれた形」ではなく「実行される形」を判定する。解析できないものは許可しない。 | 原則7 |
| [エージェントによる実行記録の改ざん](https://arxiv.org/abs/2609.30266)（2026-09） | 複数のエージェントが自身の実行トレースを削除でき、監視側が気付かない。攻撃者の誘導でも、モデル自身の判断でも発生。 | ログはエージェントが書き込めない場所へ送る。記録の削除・改ざんは常時禁止。 | N-12 |
| [Plugin4Shell / フック更新攻撃](https://www.air.security/blog-posts/plugin4shell)（2026-09） | 固定したはずのプラグインのコミットが同名ブランチで差し替えられる。更新で悪性のライフサイクルフックが追加される（[成功率最大92.5%](https://arxiv.org/abs/2609.03884)）。 | 導入時だけでなく更新もレビュー対象。自動更新は検証できるまで無効に。 | C-HITL-07 |
| [AIエージェントを狙うインフォスティーラー](https://www.gendigital.com/blog/insights/research/infostealers-your-ai-agent)（2026-09） | エージェントのアクセストークン、資格情報を含む MCP 設定、プロンプト履歴が、予測可能な場所から窃取される。 | AIツールの認証情報・履歴も秘密情報として扱い、ローテーション対象に含める。 | N-01 |
| [PixelLeak：スクリーンショットの公開リポジトリ流出](https://www.glow.io/blogs/how-ai-agents-exposed-developer-screenshots-from-leading-tech-companies)（2026-09） | PRに画像を添付できないエージェントが公開リポジトリへ画像をpushし、300超の組織の社内画面1.3万枚が露出。攻撃者は不在。 | 公開範囲の変更とファイル共有サービスへのアップロードは人間が判断。 | N-09 |

---

## 4. 3分類の要約

詳細と完全な一覧は [`permission-rules-general.md`](../../.agents/rules/permission-rules-general.md) を参照してください。

### A — 常に許可

ワークスペース内の読み取り・検索（秘密情報を除く）、読み取り専用の確認コマンド、バージョン管理下の通常ファイル（ソース・テスト・ドキュメント）の作成・編集、公式ドキュメントの参照、計画・TODOなどエージェント内部ツール。

### C — 条件付き許可（条件別）

| 条件 | 対象の例 | 条件を満たさない場合 |
| :--- | :--- | :--- |
| **C-SBX** サンドボックス内のみ | ビルド・テスト・Lint、ロックファイル準拠のインストール、`git add`/`commit` | 人間の承認（C-HITL） |
| **C-NET** 許可リストの宛先のみ | パッケージレジストリ、公式ドキュメント | 人間の承認。流出先・メタデータは禁止（N-09） |
| **C-SCOPE** スコープ限定 | ワークスペース外の読み取りは人間が追加したディレクトリのみ。pushは保護されていないブランチのみ。クラウド操作は開発・ステージングのみ | 禁止（N-07 / N-08）または承認 |
| **C-HITL** 都度の人間承認 | push・PR・Issue、依存関係の変更、再帰削除・`reset --hard`、シェルからのネットワーク、AI/CI/ガバナンス設定の編集、コンテナ・クラウド・DBクライアント、サンドボックス外実行、MCP・プラグイン・拡張機能の追加と更新、環境変数の全出力、別のエージェントセッションの起動（C-HITL-09）、プログラムを実行する git 設定（C-HITL-10） | 実行しない |

### N — いかなる場合も禁止

N-01 秘密情報へのアクセス／N-02 秘密情報の書き込み・漏えい／N-03 権限昇格・ホストの改変と永続化／N-04 ガードレールの無効化（バイパスモード、`--no-verify`、全自動承認設定）／N-05 不可逆な破壊（ルート・ホーム削除、強制push、リモート参照削除）／N-06 ダウンロードしたコードの実行／N-07 本番・共有インフラの変更／N-08 自己承認・保護ブランチへの直接push／N-09 外部流出経路（トンネル、リバースシェル、ペーストサービス、メタデータ）／N-10 パッケージ・イメージ・リリースの公開／N-11 コンテナエスケープ／N-12 監査証跡の改ざん（セッション記録・ログ・シェル履歴の削除や書き換え）。

---

## 5. ツール別の導入と検証

### 5.1 Claude Code

| 設定 | 効果 | 対応ルール |
| :--- | :--- | :--- |
| `permissions.deny` | 秘密ファイル（`Read(...)`）、ホーム設定ファイル（`Edit(~/.bashrc)` 等）、禁止コマンドを拒否。`Read` の拒否はサンドボックスの読み取り拒否にも合流。Windows 向けに `PowerShell(...)` ルールも定義（エイリアスは正規化され、大文字小文字は区別されません） | N 全般 |
| `permissions.ask` | push・PR・依存変更・再帰削除・ネットワーク・クラウド操作・AI/CI設定の編集、サンドボックス外での再実行（`Bash(dangerouslyDisableSandbox:true)`）、ヘッドレスの子エージェント起動（`claude -p`、`codex exec`）、MCP・プラグイン・拡張機能の追加、プログラムを実行する git 設定に確認を強制。`ask` は自動モードでも人間に確認されます | C-HITL |
| `permissions.allow` | ワークスペース内の編集（`Edit(/**)`）、Web検索、公式ドキュメントの取得 | A |
| `permissions.disableBypassPermissionsMode` | `--dangerously-skip-permissions` を無効化 | N-04 |
| `permissions.blockReadsOutsideWorkingDirectories` | ワークスペース外の読み取りは `/add-dir` で追加したディレクトリのみ | C-SCOPE-01 |
| `enableAllProjectMcpServers: false` | `.mcp.json` のサーバーを一括承認しない | C-HITL-07 |
| `sandbox` | Bashをサンドボックス化。ネットワークはレジストリのみ（`network.deniedDomains` で流出先を明示拒否）、トークン系の環境変数を除去。`credentials.files` と `filesystem.denyRead` で資格情報ディレクトリと代表的な `.env.*` をリテラルパスでも保護 | C-SBX、C-NET、N-01 |
| `hooks.PreToolUse` | `permission-guard.py` が `git -C . push --force`、`bash -c "…"`、`xargs sudo …`、`$'su\x64o'`、行継続、`python -c` 内のシェル実行、`.mcp.json.` のようなファイル名の別表記を正規化して N を拒否、C-HITL を確認要求に。設定ファイルへの書き込み内容（`ANTHROPIC_BASE_URL`、`disableAllHooks`、`mcpServers`）も検査 | N、C-HITL |

**導入と確認**

1. リポジトリでClaude Codeを起動し、ワークスペースの信頼ダイアログで内容を確認して承認（`allow` と `additionalDirectories` は信頼後に有効化）。
2. `/permissions` でルール一覧、`/status` で読み込まれた設定ファイル、`claude doctor` で無効なルールがないか確認。Linux では doctor が「globパターンはサンドボックスで無視される」と警告しますが、これは想定どおりです（globの `Read`/`Edit` ルールはファイルツールに対して有効で、サンドボックス側は `sandbox.credentials.files` のリテラルパスで保護しています）。また `permissions.blockReadsOutsideWorkingDirectories`（v2.1.257以降）は公開JSONスキーマへの反映が遅れているため、エディタが警告を出すことがあります。
3. Linux/WSL2では `bubblewrap` と `socat` を導入（未導入だと警告のうえサンドボックスなしで実行）。ネイティブWindowsではサンドボックス非対応のため、WSL2かdevcontainerを推奨。
4. 個人用の緩和は `.claude/settings.local.json`（Git管理外）へ。ただし `deny` は他のどのファイルからも上書きできません。
5. 他人が作ったリポジトリで `claude -p`（ヘッドレス）を使う場合、信頼ダイアログは表示されず、リポジトリのフック・`env`・`.mcp.json` がそのまま使われます。`--setting-sources user` か `--bare` を付け、必要なら `--settings '{"disableAllHooks": true}'` を指定してください（[permissions: What runs before you trust a folder](https://code.claude.com/docs/en/permissions)）。
6. 組織配布では managed settings で `allowManagedPermissionRulesOnly`、`sandbox.failIfUnavailable`、`sandbox.allowUnsandboxedCommands: false`、`sandbox.network.allowManagedDomainsOnly` を検討。自動モードを使う場合は `autoMode.environment`（ユーザー/管理設定のみ有効）に社内リポジトリ・ドメインを登録します（[auto-mode-config](https://code.claude.com/docs/en/auto-mode-config)）。

### 5.2 OpenAI Codex CLI

- `.codex/config.toml`: `approval_policy = "on-request"`、`sandbox_mode = "workspace-write"`、`network_access = false`、`approvals_reviewer = "user"`、`web_search = "cached"`、環境変数から `*KEY*`/`*SECRET*`/`*TOKEN*` 等を除外。
- `.codex/rules/permission-policy.rules`: N を `forbidden`、C-HITL を `prompt` で定義。`allow` は「サンドボックス外で無確認実行」になるため使用しません。
- **導入**: Codexでプロジェクトを trusted にすると両ファイルが読み込まれます。
- **検証**: `codex execpolicy check --rules .codex/rules/permission-policy.rules git push --force` → `"decision":"forbidden"`。ルール内の `match`/`not_match` は読み込み時に自己テストされます。
- **2026-11 追加分**: 子エージェントの起動（`claude` / `codex` / `gemini` など）、`git -c` と実行系の `git config` キー、拡張機能の導入は `prompt`。エンコード済み PowerShell、`ext::` トランスポート、パスワードマネージャーの読み取り、履歴・セッション記録の削除は `forbidden`。`tests/test-permission-guard.py` が全ルールの `match` / `not_match` 例を Codex 無しで検証します。
- **限界**: プレフィックス一致のため、フラグが後ろにある形は捕捉しません（サンドボックスが後ろ盾）。`workspace-write` は読み取りを制限しないため、N-01 を厳格に守るにはdevcontainer等で資格情報をマウントしない運用を併用してください。ネットワークは全許可か全拒否のため、レジストリ通信は承認要求になります（C-NET より厳しい側に倒しています）。

### 5.3 Gemini CLI / Google Antigravity

- `.gemini/settings.json`: `disableYoloMode: true`、恒久承認の無効化、環境変数の秘匿（redaction）、プロジェクトの `.env` を読み込まない（`ignoreLocalEnv: true`）。
- `.gemini/policies/permission-policy.toml`: N を `deny`（優先度900）、C-HITL を `ask_user`（500）、A を `allow`（100）。モード指定なしのためYOLOモードでも有効です。
- **重要**: Gemini CLI は現在ワークスペース階層のポリシー（プロジェクトの `.gemini/policies`）を読み込みません（[issue #18186](https://github.com/google-gemini/gemini-cli/issues/18186)）。次のようにユーザー階層へコピーしてください。

  ```bash
  mkdir -p ~/.gemini/policies
  cp .gemini/policies/permission-policy.toml ~/.gemini/policies/
  ```

- **注意**: Gemini は ReDoS 対策として「閉じ括弧の直後に量指定子がある正規表現」（`)?` など）を含むルールを読み込み時に破棄します。ルールを追加する際は `(x|)` のような代替表記を使ってください。
- **Antigravity**: ファイルベースの権限設定がないため、UIのターミナル実行ポリシーを「承認を求める」にし、許可/拒否リストへ本ポリシーの A / N を反映します。Turbo（自動実行）は隔離環境でのみ使用してください。

### 5.4 Cursor

- `.cursor/cli.json`（Cursor CLI）: `allow` に読み取り・読み取り専用git・ソース系ディレクトリへの書き込み・公式ドキュメント、`deny` に N と AI/CI設定への書き込みを列挙。
- `.cursor/permissions.json`（IDE）: 端末の自動実行許可を読み取り専用コマンドに限定し、MCPの自動実行を空リストで無効化。`autoRun` の自然言語指示で自動レビュー分類器を誘導します（強制力はありません）。
- **限界**: Cursor CLI には ask リストがなく、許可されていない操作は都度確認になります。否定パターンもないため `.env.example` も読み取り拒否、AI/CI設定の編集は確認ではなく拒否（いずれもポリシーより厳しい側）です。

### 5.5 GitHub Copilot（VS Code）と Copilot coding agent

- `.vscode/settings.json`: 全体自動承認の無効化、読み取り専用gitのみ自動承認、C-HITL / N に該当するコマンドは `false`（承認必須）、秘密ファイル・AI/CI設定・依存マニフェストの編集は承認必須、macOS/Linux でエージェント用サンドボックスを有効化（ネットワークはレジストリのみ）。
- `chat.useClaudeHooks: true` により、Local ハーネスでも `.claude/settings.json` の PreToolUse フック（`permission-guard.py`）が動作し、N を**ブロック**します（VS Codeの `false` は承認要求止まりのため）。Python 3.8以上が必要です。
- **Copilot coding agent（GitHub上）**: リポジトリ設定のファイアウォール許可リストを C-NET の宛先に合わせ、ブランチ保護で `copilot/*` 以外へのpushと自己承認を防ぎます。

---

## 6. サーバー側で必ず併用する統制

ローカル設定は利用者が変更できるため、次をGitHubで強制してください。

1. **ブランチ保護 / ルールセット**: `main` などへの直接push禁止、PRレビュー必須（作成者以外）、強制push・削除禁止、必須ステータスチェック（CI・Gitleaks）。
2. **CODEOWNERS**: `/.agents/`、`/.github/`、`/.claude/`、`/.codex/`、`/.cursor/`、`/.gemini/`、`/.vscode/` の変更をオーナーレビュー必須に。
3. **シークレットスキャンとプッシュ保護**: 本テンプレートの `secret-scan.yml` に加え、GitHubのpush protectionを有効化。
4. **Actions の最小権限**: `GITHUB_TOKEN` は既定で read 権限、外部PRからのワークフロー実行は承認制。
5. **公開はCIのみ**: パッケージ・イメージ・リリースの公開権限はCIのデプロイ環境（承認者付き）に限定（N-10）。

---

## 7. 検証方法

```bash
# ガードフックの単体テスト（CIでも実行）
python tests/test-permission-guard.py -v

# 設定ファイルの構文チェック
python -c "import json,sys; [json.load(open(p)) for p in sys.argv[1:]]" \
  .claude/settings.json .cursor/cli.json .cursor/permissions.json .gemini/settings.json .vscode/settings.json
python -c "import tomllib,sys; [tomllib.load(open(p,'rb')) for p in sys.argv[1:]]" \
  .codex/config.toml .gemini/policies/permission-policy.toml

# フックの動作確認（deny の JSON が出力されること）
echo '{"tool_name":"Bash","tool_input":{"command":"git -C . push --force"}}' | python .claude/hooks/permission-guard.py

# Codex ルールの確認
codex execpolicy check --rules .codex/rules/permission-policy.rules git push origin main
```

---

## 8. 既知の限界と残存リスク

- **パターンルールは境界ではない**: 表記ゆれ・別名・スクリプト経由の実行は取りこぼします。サンドボックスとサーバー側統制を前提にしてください。
- **ガードフックはヒューリスティック**: シェル構文を近似的に解析します。秘密ファイル名への言及（例: `git add .env`）は誤検知でも拒否する側に倒しています。
- **Linux のサンドボックスは glob を解釈しない**: `Read(**/*.pem)` などのglobルールはファイルツールには効きますが、サンドボックス内のシェルには効きません。リテラルパス（`~/.ssh`、`~/.aws` など）とガードフックで補っています。プロジェクト内に秘密鍵を置かないことが前提です。
- **テスト実行は任意コード実行と等価**: エージェントが編集したテストやビルドスクリプトを実行するため、サンドボックスがない環境（ネイティブWindows、bubblewrap未導入のLinux）では毎回承認になります。
- **変数経由の間接実行は検査できない**: `a=sudo; $a ls` のように実行時に決まるコマンド名、スクリプトファイルに書いてから実行する形（`curl -o x.sh … && bash x.sh`）は、ガードフックでは判定できません。前者はサンドボックス、後者は `curl` の承認（C-HITL-04）とサンドボックスが後ろ盾です。
- **`git status` 自体が設定を実行する**: リポジトリの `.git/config` にある `core.fsmonitor` などは、エージェントが読み取り専用のつもりで実行する `git status` でも動きます（GitSpawn）。ルールでは防げないため、ファイルとして受け取ったリポジトリは使い捨てコンテナで開くか、先に `.git/config` を確認してください。
- **ガードフックが効かないツールがある**: フックは Claude Code と VS Code（`chat.useClaudeHooks`）でのみ動作します。Codex・Gemini・Cursor は各ツールのパターンルールとサンドボックスのみで、原則7（実行される形で判定）の保証は弱くなります。
- **ヘッドレス実行と子セッション**: `claude -p` や SDK は信頼ダイアログを出さず、リポジトリのフックと `env` を使います。C-HITL-09 は起動時点の確認であり、子セッションの中身までは制御しません。
- **許可ドメイン経由の流出**: レジストリやGitHubなど広いドメインへの通信は、アップロードやドメインフロンティングに悪用される余地があります。許可リストは最小限に保ってください。
- **ツールごとの表現力の差**: Codex はフラグ位置を問わない一致ができず、Cursor CLI には ask がなく、VS Code の `false` は承認止まり、Gemini のワークスペースポリシーは無効です（各節の「限界」を参照）。

---

## 9. 参考文献

- Anthropic: [Configure permissions](https://code.claude.com/docs/en/permissions) / [Sandboxing](https://code.claude.com/docs/en/sandboxing) / [Permission modes](https://code.claude.com/docs/en/permission-modes) / [Example settings](https://code.claude.com/docs/en/settings-example) / [Hooks](https://code.claude.com/docs/en/hooks) / [Auto mode config](https://code.claude.com/docs/en/auto-mode-config) / [examples/settings](https://github.com/anthropics/claude-code/tree/main/examples/settings) / [Engineering: sandboxing](https://www.anthropic.com/engineering/claude-code-sandboxing)
- OpenAI: [Codex rules](https://developers.openai.com/codex/rules) / [execpolicy README](https://github.com/openai/codex/blob/main/codex-rs/execpolicy/README.md) / [Configuration reference](https://developers.openai.com/codex/config-reference)
- Google: [Gemini CLI policy engine](https://github.com/google-gemini/gemini-cli/blob/main/docs/reference/policy-engine.md) / [Configuration](https://github.com/google-gemini/gemini-cli/blob/main/docs/reference/configuration.md) / [Secure AI Agents](https://research.google/pubs/an-introduction-to-googles-approach-for-secure-ai-agents/)
- Cursor: [CLI permissions](https://cursor.com/docs/cli/reference/permissions) / [permissions.json](https://cursor.com/docs/reference/permissions)
- Microsoft / GitHub: [VS Code approvals](https://code.visualstudio.com/docs/agents/run/approvals) / [Agent sandboxing](https://code.visualstudio.com/docs/agents/run/agent-sandboxing) / [Agent hooks](https://code.visualstudio.com/docs/agent-customization/hooks) / [Copilot agent firewall](https://docs.github.com/en/copilot/how-tos/use-copilot-agents/coding-agent/customize-the-agent-firewall)
- Standards: [OWASP LLM06:2025](https://genai.owasp.org/llmrisk/llm062025-excessive-agency/) / [OWASP Top 10 for Agentic Applications 2026](https://genai.owasp.org/2025/12/09/owasp-top-10-for-agentic-applications-the-benchmark-for-agentic-security-in-the-age-of-autonomous-ai/) / [CISA: Careful Adoption of Agentic AI Services](https://www.cisa.gov/resources-tools/resources/careful-adoption-agentic-ai-services) / [AI事業者ガイドライン](https://www.meti.go.jp/shingikai/mono_info_service/ai_shakai_jisso/20240419_report.html)
- 2026-10〜11 の事例・研究: [GitSpawn](https://www.manifold.security/blog/ai-coding-agents-git-hijack) / [Session inception](https://straiker.ai/blog/session-inception-spawning-a-child-claude-session-to-bypass-parent-guardrails) / [Downloads folder hijacking](https://forever.security/blog/hijacking-ai-agents-via-downloads-folder) / [Unauthorized AI relays](https://www.security.com/threat-intelligence/openai-claude-unauthorized-relays) / [CVE-2026-103572](https://embracethered.com/blog/posts/2026/visual-studio-copilot-remote-code-execution/) / [Mistral Vibe CVE-2026-87987](https://blog.secmate.dev/posts/mistral-vibe-cve-2026-87987-cve-2026-87984/) / [Plugin4Shell](https://www.air.security/blog-posts/plugin4shell) / [Hook-update attacks](https://arxiv.org/abs/2609.03884) / [Agents tampering with their own traces](https://arxiv.org/abs/2609.30266) / [Red-teaming auto mode](https://arxiv.org/abs/2609.19587) / [Infostealers targeting AI agents](https://www.gendigital.com/blog/insights/research/infostealers-your-ai-agent) / [PixelLeak](https://www.glow.io/blogs/how-ai-agents-exposed-developer-screenshots-from-leading-tech-companies) / [Adversa: AI coding agent security digest（2026-10）](https://adversa.ai/blog/top-ai-coding-agent-security-resources-october-2026/) / [同（2026-11）](https://adversa.ai/blog/top-ai-coding-agent-security-resources-november-2026/) / [Secure software factory reference architecture](https://agentbaseline.org/reference-architecture)
- Research: [The lethal trifecta](https://simonwillison.net/2025/Jun/16/the-lethal-trifecta/) / [Agents Rule of Two](https://ai.meta.com/blog/practical-ai-agent-security/) / [Trail of Bits claude-code-config](https://github.com/trailofbits/claude-code-config)
