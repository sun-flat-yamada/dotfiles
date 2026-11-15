#!/usr/bin/env python3
"""
scripts/sync-permissions.py
==============================================================================
Canonical Permission Definition -> Tool-Specific Configuration Generator
==============================================================================
Reads the canonical permission definition
(.agents/permissions/permission-policy.json) and renders it into the native
format of each supported AI tool:

  claude        .claude/settings.json                (permissions, sandbox network)
  copilot       .vscode/settings.json                (GitHub Copilot in VS Code)
  copilot-cli   .agents/permissions/generated/copilot-cli-args.txt
  kiro          config/ai/kiro/permissions.yaml      (-> ~/.kiro/settings/)
  antigravity   .agents/permissions/generated/antigravity-permissions.json
  codex         .codex/rules/permission-policy.rules
  gemini        .gemini/policies/permission-policy.toml (-> ~/.gemini/policies/)
  cursor        .cursor/cli.json

Usage:
  python scripts/sync-permissions.py              # same as --check
  python scripts/sync-permissions.py --write      # regenerate every target
  python scripts/sync-permissions.py --report     # list what a tool cannot express
  python scripts/sync-permissions.py --install-antigravity [SETTINGS_PATH]

Zero external dependencies: runs purely on Python 3.8+ standard libraries.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import OrderedDict
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
CANONICAL_PATH = REPO_ROOT / ".agents" / "permissions" / "permission-policy.json"
GENERATED_DIR = REPO_ROOT / ".agents" / "permissions" / "generated"
ANTIGRAVITY_SETTINGS = Path("~/.gemini/antigravity-cli/settings.json")

EFFECTS = ("deny", "ask", "allow")
LIST_FIELDS = ("shell", "powershell", "command_regex", "read", "read_except", "write", "fetch", "network", "domains")
KNOWN_FIELDS = set(LIST_FIELDS) | {"id", "effect", "summary", "web_search", "native"}
RULE_ID_PATTERN = re.compile(r"^(A-\d{2}|C-(SBX|NET|SCOPE|HITL)-\d{2}|C-HITL|N-\d{2})$")
SUBCOMMAND_PROGRAMS = ("git", "gh")
REGEX_SPECIALS = set(".^$+?()[]{}|\\/")

Rule = Dict[str, object]
Skips = List[Tuple[str, str, str, str]]


# ----------------------------------------------------------------------------
# Canonical definition
# ----------------------------------------------------------------------------
def rule_errors(rule: Rule) -> List[str]:
    label = f"{rule.get('id')}/{rule.get('effect')}"
    errors = [f"{label}: unknown field '{key}'" for key in rule if key not in KNOWN_FIELDS]
    if not RULE_ID_PATTERN.match(str(rule.get("id"))):
        errors.append(f"{label}: malformed rule id")
    if rule.get("effect") not in EFFECTS:
        errors.append(label + ": effect must be one of " + ", ".join(EFFECTS))
    for field in LIST_FIELDS:
        values = rule.get(field, [])
        if not isinstance(values, list) or not all(isinstance(value, str) and value for value in values):
            errors.append(f"{label}: '{field}' must be a list of non-empty strings")
    for pattern in rule.get("command_regex", []) if isinstance(rule.get("command_regex"), list) else []:
        try:
            re.compile(pattern)
        except re.error as exc:
            errors.append(f"{label}: invalid command_regex {pattern!r}: {exc}")
    return errors


def load_policy(path: Path = CANONICAL_PATH) -> List[Rule]:
    document = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=OrderedDict)
    rules = document.get("rules")
    if not isinstance(rules, list):
        raise ValueError("canonical definition has no 'rules' list")
    errors = [error for rule in rules for error in rule_errors(rule)]
    seen = set()
    for rule in rules:
        key = (rule.get("id"), rule.get("effect"))
        if key in seen:
            errors.append(f"{key[0]}/{key[1]}: duplicate rule group")
        seen.add(key)
    if errors:
        raise ValueError("invalid canonical definition:\n  " + "\n  ".join(errors))
    return rules


def by_effect(rules: Sequence[Rule], effect: str) -> List[Rule]:
    return [rule for rule in rules if rule["effect"] == effect]


def values(rule: Rule, *fields: str) -> List[str]:
    return [value for field in fields for value in rule.get(field, [])]  # type: ignore[union-attr]


def native_rules(rule: Rule, tool: str) -> List:
    native = rule.get("native", {})
    return list(native.get(tool, [])) if isinstance(native, dict) else []


def unique(items: Iterable[str]) -> List[str]:
    return list(OrderedDict.fromkeys(items))


def skip(skips: Skips, rule: Rule, field: str, reason: str) -> None:
    for value in values(rule, field):
        skips.append((str(rule["id"]), field, value, reason))


# ----------------------------------------------------------------------------
# Pattern helpers
# ----------------------------------------------------------------------------
def glob_to_regex(glob: str) -> str:
    """Translate a command glob to an unanchored regex body with the same meaning."""
    optional_tail = glob.endswith(" *")
    body = glob[:-2] if optional_tail else glob
    parts = []
    for char in body:
        if char == "*":
            parts.append(".*")
        elif char in REGEX_SPECIALS:
            parts.append("\\" + char)
        else:
            parts.append(char)
    return "".join(parts) + ("(?:\\s.*)?" if optional_tail else "")


def command_prefix(glob: str) -> Optional[str]:
    """Return the literal words of a `words *` / `words*` glob, or None for any other shape."""
    if not glob.endswith("*"):
        return None
    prefix = glob[:-1].rstrip()
    return prefix if prefix and "*" not in prefix else None


def word_prefix(glob: str) -> Optional[str]:
    """Return the words of a `words *` glob: the only shape that equals a whole-word prefix match."""
    return command_prefix(glob) if glob.endswith(" *") else None


def path_scope(pattern: str) -> Tuple[str, str]:
    """Split a canonical path into (scope, rest): home, absolute, anywhere, or workspace."""
    if pattern.startswith("~/"):
        return "home", pattern[2:]
    if pattern.startswith("**/"):
        return "anywhere", pattern[3:]
    if pattern.startswith("/"):
        return "absolute", pattern[1:]
    return "workspace", pattern[2:] if pattern.startswith("./") else pattern


def dump_json(data: object) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


# ----------------------------------------------------------------------------
# Claude Code
# ----------------------------------------------------------------------------
def claude_path(pattern: str) -> str:
    scope, rest = path_scope(pattern)
    return {"home": "~/", "anywhere": "**/", "absolute": "//", "workspace": "/"}[scope] + rest


def claude_rules(rule: Rule) -> List[str]:
    rendered = native_rules(rule, "claude")
    rendered += [f"Bash({glob})" for glob in values(rule, "shell")]
    rendered += [f"PowerShell({glob})" for glob in values(rule, "powershell")]
    rendered += [f"Read({claude_path(path)})" for path in values(rule, "read")]
    rendered += [f"Edit({claude_path(path)})" for path in values(rule, "write")]
    rendered += ["WebSearch"] if rule.get("web_search") else []
    rendered += [f"WebFetch(domain:{host})" for host in values(rule, "fetch", "domains")]
    return rendered


def render_claude(rules: Sequence[Rule], current: str, skips: Skips) -> str:
    settings = json.loads(current, object_pairs_hook=OrderedDict)
    for effect in EFFECTS:
        settings["permissions"][effect] = unique(r for rule in by_effect(rules, effect) for r in claude_rules(rule))
    network = settings["sandbox"]["network"]
    network["allowedDomains"] = unique(h for rule in by_effect(rules, "allow") for h in values(rule, "network"))
    network["deniedDomains"] = unique(h for rule in by_effect(rules, "deny") for h in values(rule, "network", "domains"))
    for rule in rules:
        skip(skips, rule, "command_regex", "no regex rules; the PreToolUse guard hook covers these")
        skip(skips, rule, "read_except", "no exclusion syntax; the excepted files stay blocked")
    return dump_json(settings)


# ----------------------------------------------------------------------------
# GitHub Copilot (VS Code)
# ----------------------------------------------------------------------------
def vscode_glob(pattern: str) -> Optional[str]:
    scope, rest = path_scope(pattern)
    if scope in ("home", "absolute"):
        return None
    return "**/*" if rest == "**" else "**/" + rest


def vscode_terminal(rules: Sequence[Rule]) -> "OrderedDict[str, bool]":
    terminal: "OrderedDict[str, bool]" = OrderedDict()
    for effect in ("allow", "ask", "deny"):
        for rule in by_effect(rules, effect):
            for pattern in values(rule, "command_regex"):
                terminal[f"/{pattern}/"] = effect == "allow"
            globs = values(rule, "shell", "powershell") if effect != "allow" else []
            if globs:
                body = "|".join(unique(glob_to_regex(glob) for glob in globs))
                terminal[f"/^(?:{body})$/"] = False
    return terminal


def vscode_edits(rules: Sequence[Rule], skips: Skips) -> "OrderedDict[str, bool]":
    edits: "OrderedDict[str, bool]" = OrderedDict()
    for effect in ("allow", "ask", "deny"):
        for rule in by_effect(rules, effect):
            fields = ("write",) if effect == "allow" else ("write", "read")
            for field in fields:
                for pattern in values(rule, field):
                    glob = vscode_glob(pattern)
                    if glob:
                        edits[glob] = effect == "allow"
                    else:
                        skips.append((str(rule["id"]), field, pattern, "edit approvals only see workspace files"))
    return edits


def vscode_urls(rules: Sequence[Rule]) -> "OrderedDict[str, bool]":
    urls: "OrderedDict[str, bool]" = OrderedDict()
    for host in unique(h for rule in by_effect(rules, "allow") for h in values(rule, "fetch")):
        urls[f"https://{host}/*"] = True
    for host in unique(h for rule in by_effect(rules, "deny") for h in values(rule, "fetch", "domains")):
        urls[f"https://{host}/*"] = False
    return urls


def render_vscode(rules: Sequence[Rule], current: str, skips: Skips) -> str:
    settings = json.loads(current, object_pairs_hook=OrderedDict)
    settings["chat.tools.terminal.autoApprove"] = vscode_terminal(rules)
    settings["chat.tools.edits.autoApprove"] = vscode_edits(rules, skips)
    settings["chat.tools.urls.autoApprove"] = vscode_urls(rules)
    settings["chat.agent.allowedNetworkDomains"] = unique(
        h for rule in by_effect(rules, "allow") for h in values(rule, "network")
    )
    settings["chat.agent.deniedNetworkDomains"] = unique(
        h for rule in by_effect(rules, "deny") for h in values(rule, "network", "domains")
    )
    for rule in rules:
        skip(skips, rule, "read_except", "no exclusion syntax; the excepted files need approval")
    return dump_json(settings)


# ----------------------------------------------------------------------------
# GitHub Copilot CLI
# ----------------------------------------------------------------------------
def copilot_cli_tool(glob: str) -> Optional[str]:
    """Map a deny glob to `shell(program)` or `shell(git subcommand)` when it covers all of it."""
    prefix = command_prefix(glob)
    words = prefix.split() if prefix else []
    if len(words) == 1 or (len(words) == 2 and words[0] in SUBCOMMAND_PROGRAMS):
        return f"shell({' '.join(words)})"
    return None


def render_copilot_cli(rules: Sequence[Rule], current: str, skips: Skips) -> str:
    args: List[str] = []
    for rule in by_effect(rules, "deny"):
        for field in ("shell", "powershell"):
            for glob in values(rule, field):
                tool = copilot_cli_tool(glob)
                if tool:
                    args.append(f"--deny-tool={tool}")
                else:
                    skips.append((str(rule["id"]), field, glob, "flags match a program or a git/gh subcommand only"))
        for host in values(rule, "fetch", "domains"):
            if "*" in host:
                skips.append((str(rule["id"]), "domains", host, "wildcard hosts are not documented for --deny-url"))
            else:
                args.append(f"--deny-url={host}")
        for field in ("command_regex", "read", "write"):
            skip(skips, rule, field, "no flag form; the preToolUse guard hook covers these")
    for rule in by_effect(rules, "ask") + by_effect(rules, "allow"):
        for field in LIST_FIELDS:
            skip(skips, rule, field, "flags carry deny rules only; unlisted tools prompt by default")
    return "\n".join(unique(args)) + "\n"


# ----------------------------------------------------------------------------
# Kiro
# ----------------------------------------------------------------------------
def kiro_path(pattern: str) -> str:
    scope, rest = path_scope(pattern)
    return {"home": "~/", "anywhere": "**/", "absolute": "/", "workspace": ""}[scope] + rest


def kiro_entries(rule: Rule, skips: Skips) -> List[Tuple[str, List[str], List[str]]]:
    """Return (capability, match, exclude) triples for one canonical rule."""
    effect = rule["effect"]
    writes = [path for path in values(rule, "write") if path_scope(path) != ("workspace", "**")]
    if len(writes) != len(values(rule, "write")):
        skips.append((str(rule["id"]), "write", "./**", "a workspace-wide allow could reach outside the workspace"))
    hosts = values(rule, "fetch", "domains")
    url_suffix = "/*" if effect == "allow" else "*"
    entries = [
        ("shell", unique(values(rule, "shell", "powershell")), []),
        ("filesystem" if effect == "deny" else "fs_read", [kiro_path(p) for p in values(rule, "read")],
         [kiro_path(p) for p in values(rule, "read_except")]),
        ("fs_write", [kiro_path(p) for p in writes], []),
        ("web_search", ["*"] if rule.get("web_search") else [], []),
        ("web_fetch", [f"https://{host}{url_suffix}" for host in hosts], []),
        ("sandbox_network", values(rule, "network", "domains") if effect != "ask" else [], []),
    ]
    skip(skips, rule, "command_regex", "no regex rules; use the glob rules or a hook")
    return [entry for entry in entries if entry[1]]


def yaml_list(key: str, items: Sequence[str]) -> List[str]:
    return [f"    {key}:"] + [f"      - {json.dumps(item, ensure_ascii=False)}" for item in items]


def render_kiro(rules: Sequence[Rule], current: str, skips: Skips) -> str:
    lines = [
        "# Generated by scripts/sync-permissions.py from .agents/permissions/permission-policy.json.",
        "# Do not edit by hand: change the canonical definition and run the script with --write.",
        "rules:",
    ]
    for effect in EFFECTS:
        for rule in by_effect(rules, effect):
            for capability, match, exclude in kiro_entries(rule, skips):
                lines.append(f"  # {rule['id']} {rule.get('summary', '')}".rstrip())
                lines.append(f"  - capability: {capability}")
                lines += yaml_list("match", match)
                lines += yaml_list("exclude", exclude) if exclude else []
                lines.append(f"    effect: {effect}")
    return "\n".join(lines) + "\n"


# ----------------------------------------------------------------------------
# Antigravity
# ----------------------------------------------------------------------------
def antigravity_command(glob: str) -> str:
    prefix = word_prefix(glob)
    return f"command({prefix})" if prefix else f"command(regex:^{glob_to_regex(glob)}$)"


def antigravity_path(pattern: str) -> Optional[str]:
    """Antigravity takes plain files or directories (recursive), so only glob-free paths survive."""
    scope, rest = path_scope(pattern)
    rest = rest[:-3] if rest.endswith("/**") else rest
    if scope == "anywhere" or not rest or any(char in rest for char in "*?[{"):
        return None
    return {"home": "~/", "absolute": "/", "workspace": ""}[scope] + rest


def antigravity_rules(rule: Rule, skips: Skips) -> List[str]:
    rendered = [antigravity_command(glob) for glob in values(rule, "shell", "powershell")]
    rendered += [f"command(regex:{pattern})" for pattern in values(rule, "command_regex")]
    for field, action in (("read", "read_file"), ("write", "write_file")):
        for pattern in values(rule, field):
            path = antigravity_path(pattern)
            if path:
                rendered.append(f"{action}({path})")
            else:
                skips.append((str(rule["id"]), field, pattern, "path rules take no globs; the guard hook covers writes"))
    rendered += [f"read_url({host[2:] if host.startswith('*.') else host})" for host in values(rule, "fetch", "domains")]
    skip(skips, rule, "network", "no sandbox network allowlist in the permissions block")
    skip(skips, rule, "read_except", "no exclusion syntax")
    return rendered


def render_antigravity(rules: Sequence[Rule], current: str, skips: Skips) -> str:
    permissions = OrderedDict(
        (effect, unique(r for rule in by_effect(rules, effect) for r in antigravity_rules(rule, skips)))
        for effect in ("allow", "ask", "deny")
    )
    return dump_json(OrderedDict(permissions=permissions))


def expand_home(rule: str, home: Path) -> str:
    return re.sub(r"^(read_file|write_file)\(~/", lambda match: f"{match.group(1)}({home.as_posix()}/", rule)


def install_antigravity(settings_path: Path, fragment_path: Optional[Path] = None, home: Optional[Path] = None) -> int:
    """Merge the generated permissions block into the Antigravity CLI settings, keeping other keys."""
    fragment_path = fragment_path or GENERATED_DIR / "antigravity-permissions.json"
    home = home or Path.home()
    permissions = json.loads(fragment_path.read_text(encoding="utf-8"))["permissions"]
    settings = OrderedDict()
    if settings_path.exists():
        previous = settings_path.read_text(encoding="utf-8")
        settings = json.loads(previous, object_pairs_hook=OrderedDict)
        settings_path.with_name(settings_path.name + ".bak").write_text(previous, encoding="utf-8")
    settings["permissions"] = {effect: [expand_home(rule, home) for rule in rules] for effect, rules in permissions.items()}
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(dump_json(settings), encoding="utf-8")
    os.chmod(settings_path, 0o600)
    print(f"[+] Wrote the permissions block to {settings_path}")
    return 0


# ----------------------------------------------------------------------------
# OpenAI Codex CLI
# ----------------------------------------------------------------------------
CODEX_DECISIONS = {"deny": "forbidden", "ask": "prompt"}
CODEX_HEADER = """# Generated by scripts/sync-permissions.py from .agents/permissions/permission-policy.json.
# Do not edit by hand: change the canonical definition and run the script with --write.
#
# Codex CLI execution policy, loaded from <repo>/.codex/rules/ after the project is trusted.
# "forbidden" = tier N, "prompt" = tier C-HITL. The strictest matching rule wins.
# "allow" is unused on purpose: in Codex it runs a command outside the sandbox.
# Prefix rules match argv tokens from the start, so a flag in another position is
# not matched; the workspace-write sandbox in .codex/config.toml is the backstop.
"""


def codex_patterns(globs: Sequence[str], rule: Rule, skips: Skips) -> List[List[object]]:
    """Group prefix globs that differ only in their last word into one token pattern."""
    grouped: "OrderedDict[Tuple[str, ...], List[str]]" = OrderedDict()
    for glob in globs:
        prefix = command_prefix(glob)
        words = prefix.split() if prefix else []
        if not words or any(char in prefix for char in "\"'$|;&<>\\"):
            skips.append((str(rule["id"]), "shell", glob, "prefix rules match leading argv tokens only"))
            continue
        alternatives = grouped.setdefault(tuple(words[:-1]), [])
        if words[-1] not in alternatives:
            alternatives.append(words[-1])
    return [list(head) + [tail[0] if len(tail) == 1 else tail] for head, tail in grouped.items()]


def codex_rule_text(pattern: Sequence[object], decision: str, rule: Rule, extra: Optional[Dict[str, object]] = None) -> str:
    example = " ".join(token[0] if isinstance(token, list) else token for token in pattern)  # type: ignore[index,misc]
    fields: "OrderedDict[str, object]" = OrderedDict(
        pattern=list(pattern),
        decision=decision,
        justification=f"{rule['id']}: {rule.get('summary', '')}.",
        match=(extra or {}).get("match", [example]),
    )
    if (extra or {}).get("not_match"):
        fields["not_match"] = extra["not_match"]  # type: ignore[index]
    body = "".join(f"    {key} = {json.dumps(value, ensure_ascii=False)},\n" for key, value in fields.items())
    return f"prefix_rule(\n{body})\n"


def render_codex(rules: Sequence[Rule], current: str, skips: Skips) -> str:
    blocks = [CODEX_HEADER]
    for effect in ("deny", "ask"):
        for rule in by_effect(rules, effect):
            decision = CODEX_DECISIONS[effect]
            for pattern in codex_patterns(values(rule, "shell", "powershell"), rule, skips):
                blocks.append(codex_rule_text(pattern, decision, rule))
            for entry in native_rules(rule, "codex"):
                blocks.append(codex_rule_text(entry["pattern"], decision, rule, entry))
            for field in ("command_regex", "read", "write", "fetch", "network", "domains"):
                skip(skips, rule, field, "execution policy covers commands only; the sandbox covers files and network")
    for rule in by_effect(rules, "allow"):
        for field in LIST_FIELDS:
            skip(skips, rule, field, "allow rules would run commands outside the sandbox")
    return "\n".join(blocks)


# ----------------------------------------------------------------------------
# Gemini CLI
# ----------------------------------------------------------------------------
GEMINI_LEVELS = {"deny": ("deny", 900), "ask": ("ask_user", 500), "allow": ("allow", 100)}
GEMINI_HOME = '(~|/home/[^/"]+|/Users/[^/"]+|/root)/'
GEMINI_UNSAFE_QUANTIFIER = re.compile(r"\)[?*+{]")
GEMINI_HEADER = """# Generated by scripts/sync-permissions.py from .agents/permissions/permission-policy.json.
# Do not edit by hand: change the canonical definition and run the script with --write.
#
# Gemini CLI policy-engine rules. Gemini ignores the workspace policy tier
# (google-gemini/gemini-cli#18186), so install this file in the user tier:
#   mkdir -p ~/.gemini/policies && cp .gemini/policies/permission-policy.toml ~/.gemini/policies/
# Priorities: 900 = tier N (deny), 500 = tier C-HITL (ask_user), 100 = tier A (allow).
# commandRegex and argsPattern run against the JSON-encoded arguments, so a closing
# double quote marks the end of a value. Gemini drops any regex with a quantifier
# right after a closing parenthesis, so optional parts are written as (x|).
"""


def gemini_escape(text: str, star: str) -> str:
    return "".join(star if char == "*" else "\\" + char if char in REGEX_SPECIALS else char for char in text)


def gemini_command_regex(glob: str) -> str:
    """Translate a non-prefix command glob to a regex anchored at the start of the command."""
    if glob.endswith(" *"):
        return gemini_escape(glob[:-2], '[^"]*') + '(\\s[^"]*|)"'
    if glob.endswith("*"):
        return gemini_escape(glob[:-1], '[^"]*')
    return gemini_escape(glob, '[^"]*') + '"'


def has_top_level_alternation(pattern: str) -> bool:
    depth = 0
    for index, char in enumerate(pattern):
        escaped = index > 0 and pattern[index - 1] == "\\"
        depth += (char in "([") - (char in ")]") if not escaped else 0
        if char == "|" and depth == 0 and not escaped:
            return True
    return False


def gemini_regex_atom(pattern: str) -> Optional[str]:
    """Adapt a canonical command regex, or return None when Gemini would drop or misread it."""
    if GEMINI_UNSAFE_QUANTIFIER.search(pattern) or '"' in pattern or re.search(r"(?<!\\)\$", pattern):
        return None
    if has_top_level_alternation(pattern):
        pattern = f"({pattern})" if "^" not in pattern else ""
    if pattern.startswith("^"):
        pattern = pattern[1:]
    elif pattern:
        pattern = ".*" + pattern
    return pattern if pattern and "^" not in pattern.replace("[^", "") else None


def gemini_path_regex(pattern: str) -> str:
    scope, rest = path_scope(pattern)
    body = gemini_escape(rest.replace("**", "\0"), '[^"/]*').replace("\0", '[^"]*')
    return {"home": GEMINI_HOME, "absolute": "/", "anywhere": '([^"]*/|)', "workspace": '([^"]*/|)'}[scope] + body


def gemini_file_pattern(paths: Sequence[str], excepts: Sequence[str] = ()) -> str:
    guard = f'(?![^"]*({"|".join(gemini_path_regex(p) for p in excepts)})")' if excepts else ""
    return f'"file_path":"{guard}({"|".join(gemini_path_regex(p) for p in paths)})"'


def gemini_tables(rule: Rule, skips: Skips) -> List["OrderedDict[str, object]"]:
    """Return the Gemini rule tables (without decision and priority) for one canonical rule."""
    tables: List["OrderedDict[str, object]"] = []
    globs = unique(values(rule, "shell", "powershell"))
    prefixes = unique(p for p in map(word_prefix, globs) if p)
    regexes = [gemini_command_regex(glob) for glob in globs if not word_prefix(glob)]
    for pattern in values(rule, "command_regex"):
        atom = gemini_regex_atom(pattern)
        if atom:
            regexes.append(atom)
        else:
            skips.append((str(rule["id"]), "command_regex", pattern, "the regex loader would drop or misread it"))
    if prefixes:
        tables.append(OrderedDict(toolName="run_shell_command", commandPrefix=prefixes))
    tables += [OrderedDict(toolName="run_shell_command", commandRegex=regex) for regex in regexes]
    if values(rule, "read"):
        pattern = gemini_file_pattern(values(rule, "read"), values(rule, "read_except"))
        tables.append(OrderedDict(toolName=["read_file", "write_file", "replace"], argsPattern=pattern))
    if values(rule, "write"):
        tables.append(OrderedDict(toolName=["write_file", "replace"], argsPattern=gemini_file_pattern(values(rule, "write"))))
    hosts = [gemini_escape(host[2:] if host.startswith("*.") else host, "") for host in values(rule, "fetch", "domains")]
    if hosts:
        tables.append(OrderedDict(toolName="web_fetch", argsPattern=f'({"|".join(unique(hosts))})'))
    tables += [OrderedDict(entry) for entry in native_rules(rule, "gemini")]
    skip(skips, rule, "network", "no sandbox network allowlist in the policy engine")
    return tables


def toml_value(value: object) -> str:
    if isinstance(value, list):
        return "[" + ", ".join(toml_value(item) for item in value) + "]"
    if isinstance(value, str) and "'" not in value and "\\" in value:
        return f"'{value}'"
    return json.dumps(value, ensure_ascii=False)


def render_gemini(rules: Sequence[Rule], current: str, skips: Skips) -> str:
    blocks = [GEMINI_HEADER]
    for effect in EFFECTS:
        decision, priority = GEMINI_LEVELS[effect]
        for rule in by_effect(rules, effect):
            for table in gemini_tables(rule, skips):
                table.update(decision=decision, priority=priority)
                if effect == "deny":
                    table["denyMessage"] = f"{rule['id']}: {rule.get('summary', '')} is never allowed."
                lines = [f"# {rule['id']} {rule.get('summary', '')}".rstrip(), "[[rule]]"]
                lines += [f"{key} = {toml_value(value)}" for key, value in table.items()]
                blocks.append("\n".join(lines) + "\n")
    return "\n".join(blocks)


# ----------------------------------------------------------------------------
# Cursor CLI
# ----------------------------------------------------------------------------
# Cursor CLI has no ask list. Writes to agent and git configuration are denied instead.
CURSOR_ASK_WRITES_DENIED = ("C-HITL-05", "C-HITL-07", "C-HITL-10")


def cursor_shell(glob: str) -> Optional[str]:
    """Map a command glob to Shell(base) or Shell(base:argument glob)."""
    base, _, arguments = glob.partition(" ")
    if "*" in base.rstrip("*") or not base.rstrip("*"):
        return None
    if not arguments or arguments == "*":
        return f"Shell({base})"
    return f"Shell({base}:{arguments})"


def cursor_path(pattern: str) -> Optional[str]:
    scope, rest = path_scope(pattern)
    if scope == "absolute":
        return None
    return rest if scope == "workspace" else "**/" + rest


def cursor_rules(rule: Rule, skips: Skips, write_fields: Sequence[str]) -> List[str]:
    rendered = native_rules(rule, "cursor")
    for field, action in [("read", "Read")] + [(field, "Write") for field in write_fields]:
        for pattern in values(rule, field):
            path = cursor_path(pattern)
            if path:
                rendered.append(f"{action}({path})")
            else:
                skips.append((str(rule["id"]), field, pattern, "absolute paths are outside the CLI's path rules"))
    for field in ("shell", "powershell"):
        for glob in values(rule, field):
            shell = cursor_shell(glob)
            if shell:
                rendered.append(shell)
            else:
                skips.append((str(rule["id"]), field, glob, "Shell rules need a literal command name first"))
    rendered += [f"WebFetch({host})" for host in values(rule, "fetch", "domains")]
    return rendered


def render_cursor(rules: Sequence[Rule], current: str, skips: Skips) -> str:
    settings = json.loads(current or "{}", object_pairs_hook=OrderedDict)
    allow = [r for rule in by_effect(rules, "allow") for r in cursor_rules(rule, skips, ())]
    deny = [r for rule in by_effect(rules, "deny") for r in cursor_rules(rule, skips, ("write", "read"))]
    for rule in by_effect(rules, "ask"):
        if rule["id"] in CURSOR_ASK_WRITES_DENIED:
            deny += [f"Write({cursor_path(pattern)})" for pattern in values(rule, "write") if cursor_path(pattern)]
        else:
            skip(skips, rule, "write", "no ask list; unlisted writes prompt by default")
        for field in ("shell", "powershell", "command_regex"):
            skip(skips, rule, field, "no ask list; unlisted commands prompt by default")
    for rule in rules:
        skip(skips, rule, "read_except", "no exclusion syntax; the excepted files stay blocked")
        skip(skips, rule, "network", "no sandbox network allowlist in the CLI permissions")
        if rule["effect"] != "ask":
            skip(skips, rule, "command_regex", "no regex rules")
    settings["permissions"] = OrderedDict(allow=unique(allow), deny=unique(deny))
    return dump_json(settings)


# ----------------------------------------------------------------------------
# Targets and CLI
# ----------------------------------------------------------------------------
Renderer = Callable[[Sequence[Rule], str, Skips], str]
TARGETS: "OrderedDict[str, Tuple[Path, Renderer]]" = OrderedDict(
    [
        ("claude", (Path(".claude/settings.json"), render_claude)),
        ("copilot", (Path(".vscode/settings.json"), render_vscode)),
        ("copilot-cli", (Path(".agents/permissions/generated/copilot-cli-args.txt"), render_copilot_cli)),
        ("kiro", (Path("config/ai/kiro/permissions.yaml"), render_kiro)),
        ("antigravity", (Path(".agents/permissions/generated/antigravity-permissions.json"), render_antigravity)),
        ("codex", (Path(".codex/rules/permission-policy.rules"), render_codex)),
        ("gemini", (Path(".gemini/policies/permission-policy.toml"), render_gemini)),
        ("cursor", (Path(".cursor/cli.json"), render_cursor)),
    ]
)


def render_all(rules: Sequence[Rule], root: Path = REPO_ROOT) -> "OrderedDict[str, Tuple[Path, str, str, Skips]]":
    """Return {tool: (path, current text, rendered text, skipped atoms)}."""
    results: "OrderedDict[str, Tuple[Path, str, str, Skips]]" = OrderedDict()
    for tool, (relative, renderer) in TARGETS.items():
        path = root / relative
        current = path.read_text(encoding="utf-8") if path.exists() else ""
        skips: Skips = []
        results[tool] = (path, current, renderer(rules, current, skips), skips)
    return results


def cmd_sync(write: bool, root: Path = REPO_ROOT) -> int:
    stale = []
    for tool, (path, current, rendered, _) in render_all(load_policy(), root).items():
        if current == rendered:
            continue
        stale.append(tool)
        if write:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(rendered, encoding="utf-8", newline="\n")
            print(f"[+] Updated {path.relative_to(root)}")
    if stale and not write:
        print(f"[X] Out of date: {', '.join(stale)}. Run: python scripts/sync-permissions.py --write", file=sys.stderr)
        return 1
    print("[+] Every tool-specific permission file matches the canonical definition.")
    return 0


def cmd_report(root: Path = REPO_ROOT) -> int:
    for tool, (path, _, _, skips) in render_all(load_policy(), root).items():
        print(f"{tool} ({path.relative_to(root)}): {len(skips)} canonical entries not expressed")
        reasons: Dict[Tuple[str, str], List[str]] = OrderedDict()
        for rule_id, field, value, reason in skips:
            reasons.setdefault((field, reason), []).append(rule_id)
        for (field, reason), rule_ids in reasons.items():
            print(f"  - {field} x{len(rule_ids)} [{', '.join(unique(rule_ids))}]: {reason}")
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Render the canonical permission definition for every AI tool.")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--check", action="store_true", help="fail if a generated file is out of date (default)")
    group.add_argument("--write", action="store_true", help="regenerate every tool-specific file")
    group.add_argument("--report", action="store_true", help="list canonical entries a tool cannot express")
    group.add_argument(
        "--install-antigravity",
        nargs="?",
        const=str(ANTIGRAVITY_SETTINGS),
        metavar="SETTINGS_PATH",
        help="merge the permissions block into the Antigravity CLI settings file",
    )
    args = parser.parse_args(argv)
    if args.install_antigravity:
        return install_antigravity(Path(args.install_antigravity).expanduser())
    if args.report:
        return cmd_report()
    return cmd_sync(write=args.write)


if __name__ == "__main__":
    sys.exit(main())
