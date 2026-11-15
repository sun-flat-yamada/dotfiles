#!/usr/bin/env python3
"""
tests/test-sync-permissions.py
==============================================================================
Unit tests for scripts/sync-permissions.py and the canonical permission
definition (.agents/permissions/permission-policy.json).

Run directly (the hyphenated file name is not importable by unittest discovery):

    python tests/test-sync-permissions.py -v
"""

from __future__ import annotations

import importlib.util
import io
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
POLICY_DOC = REPO_ROOT / ".agents" / "rules" / "permission-rules-general.md"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


sync = load_module("sync_permissions", REPO_ROOT / "scripts" / "sync-permissions.py")
guard = load_module("permission_guard_for_sync", REPO_ROOT / ".claude" / "hooks" / "permission-guard.py")


def rule(**fields):
    return dict({"id": "N-01", "effect": "deny"}, **fields)


class CanonicalDefinitionTest(unittest.TestCase):
    def setUp(self):
        self.rules = sync.load_policy()

    def test_every_rule_id_exists_in_the_prose_policy(self):
        prose = POLICY_DOC.read_text(encoding="utf-8")
        for canonical in self.rules:
            self.assertRegex(prose, rf"\b{re.escape(canonical['id'])}\b")

    def test_every_never_tier_rule_has_a_canonical_entry(self):
        prose_ids = set(re.findall(r"^\| (N-\d{2}) \|", POLICY_DOC.read_text(encoding="utf-8"), re.M))
        canonical_ids = {canonical["id"] for canonical in self.rules}
        # N-02 (secret leakage into text) is enforced by secret scanning, not by a pattern rule.
        self.assertEqual(prose_ids - canonical_ids, {"N-02"})

    def test_never_tier_rules_never_allow(self):
        for canonical in self.rules:
            if canonical["id"].startswith("N-"):
                self.assertNotEqual(canonical["effect"], "allow", canonical["id"])

    def test_invalid_definitions_are_rejected(self):
        self.assertTrue(sync.rule_errors(rule(effect="maybe")))
        self.assertTrue(sync.rule_errors(rule(id="X-1")))
        self.assertTrue(sync.rule_errors(rule(shell="sudo *")))
        self.assertTrue(sync.rule_errors(rule(command_regex=["("])))
        self.assertTrue(sync.rule_errors(rule(typo=[])))
        self.assertEqual(sync.rule_errors(rule(shell=["sudo *"])), [])


class GeneratedFilesTest(unittest.TestCase):
    def test_generated_files_match_the_canonical_definition(self):
        for tool, (path, current, rendered, _) in sync.render_all(sync.load_policy()).items():
            self.assertEqual(current, rendered, f"{tool}: run python scripts/sync-permissions.py --write")

    def test_rendering_is_stable(self):
        rules = sync.load_policy()
        first = {tool: result[2] for tool, result in sync.render_all(rules).items()}
        second = {tool: result[2] for tool, result in sync.render_all(rules).items()}
        self.assertEqual(first, second)

    def test_unexpressed_entries_are_reported_not_dropped(self):
        results = sync.render_all(sync.load_policy())
        self.assertTrue(any(field == "command_regex" for _, field, _, _ in results["claude"][3]))
        self.assertTrue(any(field == "read" for _, field, _, _ in results["antigravity"][3]))


class PatternHelperTest(unittest.TestCase):
    def matches(self, glob: str, command: str) -> bool:
        return re.fullmatch(sync.glob_to_regex(glob), command) is not None

    def test_glob_to_regex_keeps_the_glob_meaning(self):
        self.assertTrue(self.matches("git push *", "git push"))
        self.assertTrue(self.matches("git push *", "git push origin main"))
        self.assertFalse(self.matches("git push *", "git pushx"))
        self.assertTrue(self.matches("mkfs*", "mkfs.ext4 /dev/sda"))
        self.assertTrue(self.matches("* --yolo*", "gemini --yolo"))
        self.assertFalse(self.matches("bash", "bash script.sh"))
        self.assertTrue(self.matches("git -c core.fsmonitor=*", "git -c core.fsmonitor=x status"))
        self.assertFalse(self.matches("git -c core.fsmonitor=*", "git -c coreXfsmonitor=x"))

    def test_command_prefix(self):
        self.assertEqual(sync.command_prefix("sudo *"), "sudo")
        self.assertEqual(sync.command_prefix("gh pr merge*"), "gh pr merge")
        self.assertIsNone(sync.command_prefix("bash"))
        self.assertIsNone(sync.command_prefix("git push * --force*"))

    def test_path_scope(self):
        self.assertEqual(sync.path_scope("~/.ssh/**"), ("home", ".ssh/**"))
        self.assertEqual(sync.path_scope("/etc/**"), ("absolute", "etc/**"))
        self.assertEqual(sync.path_scope("**/.env"), ("anywhere", ".env"))
        self.assertEqual(sync.path_scope("./**"), ("workspace", "**"))
        self.assertEqual(sync.path_scope(".claude/**"), ("workspace", ".claude/**"))


class AdapterTest(unittest.TestCase):
    def test_claude_rules(self):
        rendered = sync.claude_rules(
            rule(shell=["sudo *"], powershell=["gsudo *"], read=["~/.ssh/**", "/proc/*/environ"],
                 write=[".claude/**", "**/.mcp.json"], domains=["webhook.site"])
        )
        self.assertEqual(
            rendered,
            ["Bash(sudo *)", "PowerShell(gsudo *)", "Read(~/.ssh/**)", "Read(//proc/*/environ)",
             "Edit(/.claude/**)", "Edit(**/.mcp.json)", "WebFetch(domain:webhook.site)"],
        )

    def test_vscode_terminal_rules_require_approval(self):
        terminal = sync.vscode_terminal([rule(shell=["sudo *", "dd *"], command_regex=["^su\\b"])])
        self.assertEqual(terminal, {"/^su\\b/": False, "/^(?:sudo(?:\\s.*)?|dd(?:\\s.*)?)$/": False})

    def test_vscode_edits_skip_paths_outside_the_workspace(self):
        skips = []
        edits = sync.vscode_edits([rule(write=["~/.bashrc", ".github/**"], read=["**/.env"])], skips)
        self.assertEqual(edits, {"**/.github/**": False, "**/.env": False})
        self.assertEqual([skipped[2] for skipped in skips], ["~/.bashrc"])

    def test_copilot_cli_denies_whole_programs_only(self):
        self.assertEqual(sync.copilot_cli_tool("sudo *"), "shell(sudo)")
        self.assertEqual(sync.copilot_cli_tool("gh secret *"), "shell(gh secret)")
        self.assertIsNone(sync.copilot_cli_tool("bash"))
        self.assertIsNone(sync.copilot_cli_tool("docker push*"))
        self.assertIsNone(sync.copilot_cli_tool("gh pr merge*"))
        text = sync.render_copilot_cli([rule(shell=["sudo *"], domains=["webhook.site", "*.ngrok.io"])], "", [])
        self.assertEqual(text, "--deny-tool=shell(sudo)\n--deny-url=webhook.site\n")

    def test_copilot_cli_never_emits_allow_flags(self):
        text = sync.render_all(sync.load_policy())["copilot-cli"][2]
        self.assertNotIn("--allow", text)
        self.assertNotIn("--yolo", text)

    def test_kiro_yaml(self):
        text = sync.render_kiro([rule(summary="Secret access", read=["**/.env.*"], read_except=["**/.env.example"])], "", [])
        self.assertIn(
            '  # N-01 Secret access\n  - capability: filesystem\n    match:\n      - "**/.env.*"\n'
            '    exclude:\n      - "**/.env.example"\n    effect: deny\n',
            text,
        )

    def test_kiro_does_not_allow_workspace_wide_writes(self):
        skips = []
        entries = sync.kiro_entries({"id": "A-03", "effect": "allow", "write": ["./**"]}, skips)
        self.assertEqual(entries, [])
        self.assertEqual(len(skips), 1)

    def test_antigravity_rules(self):
        skips = []
        rendered = sync.antigravity_rules(
            rule(shell=["sudo *", "git push * --force*"], command_regex=["^su\\b"], read=["~/.ssh/**", "**/*.pem"],
                 write=["/etc/**"], domains=["*.ngrok.io"]),
            skips,
        )
        self.assertEqual(
            rendered,
            ["command(sudo)", "command(regex:^git push .* --force.*$)", "command(regex:^su\\b)",
             "read_file(~/.ssh)", "write_file(/etc)", "read_url(ngrok.io)"],
        )
        self.assertEqual([skipped[2] for skipped in skips], ["**/*.pem"])

    def test_codex_groups_prefix_globs_by_their_last_word(self):
        skips = []
        patterns = sync.codex_patterns(["sudo *", "su *", "git clone *", "git submodule add *", "* --yolo*"], rule(), skips)
        self.assertEqual(patterns, [[["sudo", "su"]], ["git", "clone"], ["git", "submodule", "add"]])
        self.assertEqual([skipped[2] for skipped in skips], ["* --yolo*"])

    def test_codex_rules_carry_a_self_check_and_never_allow(self):
        text = sync.render_codex([rule(summary="Secret access", shell=["op read *"]),
                                  {"id": "A-02", "effect": "allow", "shell": ["ls *"]}], "", [])
        self.assertIn('pattern = ["op", "read"]', text)
        self.assertIn('decision = "forbidden"', text)
        self.assertIn('match = ["op read"]', text)
        self.assertNotIn('decision = "allow"', text)

    def test_codex_native_rules_keep_their_examples(self):
        native = {"codex": [{"pattern": ["git", "push", ["-f"]], "match": ["git push -f"], "not_match": ["git push"]}]}
        text = sync.render_codex([rule(id="N-05", summary="Irreversible destruction", native=native)], "", [])
        self.assertIn('not_match = ["git push"]', text)

    def gemini_matches(self, regex: str, command: str) -> bool:
        encoded = json.dumps({"command": command}, separators=(",", ":"))
        return re.search('"command":"' + regex, encoded) is not None

    def test_gemini_command_regex_keeps_the_glob_meaning(self):
        exact = sync.gemini_command_regex("bash")
        self.assertTrue(self.gemini_matches(exact, "bash"))
        self.assertFalse(self.gemini_matches(exact, "bash script.sh"))
        middle = sync.gemini_command_regex("git push * --force*")
        self.assertTrue(self.gemini_matches(middle, "git push origin --force-with-lease"))
        self.assertFalse(self.gemini_matches(middle, "git push origin feat/x"))
        optional = sync.gemini_command_regex("* --yolo *")
        self.assertTrue(self.gemini_matches(optional, "gemini --yolo"))
        self.assertIsNone(sync.GEMINI_UNSAFE_QUANTIFIER.search(optional))

    def test_gemini_regex_atoms(self):
        self.assertEqual(sync.gemini_regex_atom("^su\\b"), "su\\b")
        self.assertEqual(sync.gemini_regex_atom("--no-verify\\b|core\\.hooksPath"), ".*(--no-verify\\b|core\\.hooksPath)")
        self.assertIsNone(sync.gemini_regex_atom("^a(b)?c"))
        self.assertIsNone(sync.gemini_regex_atom("HISTFILE=|^history -c"))
        self.assertIsNone(sync.gemini_regex_atom("x[\"']y"))

    def test_gemini_file_pattern_honours_exceptions(self):
        pattern = sync.gemini_file_pattern(["**/.env.*", "~/.ssh/**"], ["**/.env.example"])
        check = lambda path: re.search(pattern, json.dumps({"file_path": path}, separators=(",", ":"))) is not None
        self.assertTrue(check("app/.env.local"))
        self.assertFalse(check("app/.env.example"))
        self.assertTrue(check("/home/dev/.ssh/id_ed25519"))
        self.assertFalse(check("src/main.py"))

    def test_gemini_uses_word_prefixes_only_for_whole_words(self):
        tables = sync.gemini_tables(rule(shell=["sudo *", "npm publish*"]), [])
        self.assertEqual(tables[0]["commandPrefix"], ["sudo"])
        self.assertEqual(tables[1]["commandRegex"], "npm publish")

    def test_cursor_rules(self):
        self.assertEqual(sync.cursor_shell("sudo *"), "Shell(sudo)")
        self.assertEqual(sync.cursor_shell("git push --force*"), "Shell(git:push --force*)")
        self.assertEqual(sync.cursor_shell("mkfs*"), "Shell(mkfs*)")
        self.assertIsNone(sync.cursor_shell("* --yolo*"))
        self.assertEqual(sync.cursor_path("~/.ssh/**"), "**/.ssh/**")
        self.assertEqual(sync.cursor_path(".claude/**"), ".claude/**")
        self.assertIsNone(sync.cursor_path("/etc/**"))

    def test_cursor_denies_configuration_writes_it_cannot_ask_about(self):
        rules = [{"id": "C-HITL-05", "effect": "ask", "write": [".claude/**"], "shell": ["gh *"]},
                 {"id": "C-HITL-02", "effect": "ask", "write": ["**/package.json"]}]
        permissions = json.loads(sync.render_cursor(rules, "{}", []))["permissions"]
        self.assertEqual(permissions, {"allow": [], "deny": ["Write(.claude/**)"]})

    def test_install_antigravity_keeps_other_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            fragment = home / "fragment.json"
            fragment.write_text(json.dumps({"permissions": {"deny": ["read_file(~/.ssh)", "command(sudo)"]}}))
            settings = home / "cli" / "settings.json"
            settings.parent.mkdir()
            settings.write_text(json.dumps({"agentMode": "plan", "permissions": {"allow": ["command(*)"]}}))
            self.assertEqual(sync.install_antigravity(settings, fragment, home), 0)
            written = json.loads(settings.read_text())
            self.assertEqual(written["agentMode"], "plan")
            self.assertEqual(written["permissions"], {"deny": [f"read_file({home.as_posix()}/.ssh)", "command(sudo)"]})
            self.assertTrue((settings.parent / "settings.json.bak").exists())


class GuardHookFormatsTest(unittest.TestCase):
    """The same guard serves Copilot CLI and Antigravity through --format."""

    def run_guard(self, event, *argv):
        stdout = io.StringIO()
        guard.main(io.StringIO(json.dumps(event)), stdout, argv)
        return json.loads(stdout.getvalue()) if stdout.getvalue() else None

    def test_copilot_payload_and_output(self):
        event = {"toolName": "bash", "toolArgs": json.dumps({"command": "sudo rm -rf /"})}
        output = self.run_guard(event, "--format", "copilot")
        self.assertEqual(output["permissionDecision"], "deny")
        self.assertTrue(output["permissionDecisionReason"].startswith("[N-"))
        self.assertIsNone(self.run_guard({"toolName": "bash", "toolArgs": "{\"command\": \"ls\"}"}, "--format=copilot"))

    def test_copilot_file_edit(self):
        event = {"toolName": "edit", "toolArgs": {"path": ".git/hooks/pre-commit", "new_str": "true"}}
        self.assertEqual(self.run_guard(event, "--format", "copilot")["permissionDecision"], "ask")

    def test_antigravity_payload_and_output(self):
        event = {"toolCall": {"name": "run_command", "args": {"CommandLine": "git push --force origin main"}}}
        output = self.run_guard(event, "--format", "antigravity")
        self.assertEqual(output["decision"], "deny")
        self.assertTrue(output["reason"].startswith("[N-"))

    def test_antigravity_ask_ignores_cached_grants(self):
        event = {"toolCall": {"name": "write_to_file", "args": {"TargetFile": ".git/hooks/pre-commit", "CodeContent": "true"}}}
        self.assertEqual(self.run_guard(event, "--format", "antigravity")["decision"], "force_ask")

    def test_default_output_stays_claude_shaped(self):
        output = self.run_guard({"tool_input": {"command": "sudo ls"}})
        self.assertEqual(output["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_hook_files_call_the_guard_with_the_matching_format(self):
        copilot = json.loads((REPO_ROOT / ".github" / "hooks" / "permission-guard.json").read_text(encoding="utf-8"))
        for handler in copilot["hooks"]["preToolUse"]:
            self.assertIn("permission-guard.py --format copilot", handler["bash"])
            self.assertIn("permission-guard.py --format copilot", handler["powershell"])
        antigravity = json.loads((REPO_ROOT / ".agents" / "hooks.json").read_text(encoding="utf-8"))
        handler = antigravity["permission-guard"]["PreToolUse"][0]["hooks"][0]
        self.assertIn("permission-guard.py --format antigravity", handler["command"])


if __name__ == "__main__":
    unittest.main()
