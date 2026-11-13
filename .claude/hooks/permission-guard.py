#!/usr/bin/env python3
"""
.claude/hooks/permission-guard.py
==============================================================================
PreToolUse guard hook for the AI agent permission policy.

Enforces the never-allow tier (N-*) and normalizes a few conditional (C-HITL-*)
actions of .agents/rules/permission-rules-general.md for command forms that
pattern-based permission rules miss (wrappers such as `bash -c`, `env`, `xargs`,
git global options like `git -C <dir> push`, flag permutations, heredocs, ANSI-C
quoting, line continuations, Windows file-name variants, PowerShell cmdlets).

Input : a hook event as JSON on stdin (`tool_name`, `tool_input`).
Output: a PreToolUse decision as JSON on stdout, or nothing to defer to the
        normal permission flow. The exit code is always 0.

This hook is a guardrail, not a security boundary: keep the OS sandbox and the
deny rules in .claude/settings.json enabled. Zero dependencies (Python 3.8+).
"""

from __future__ import annotations

import json
import re
import shlex
import sys
from typing import Callable, Dict, List, Optional, Sequence, TextIO, Tuple

Decision = Tuple[str, str]  # (permission decision, reason starting with "[RULE-ID]")

DENY = "deny"
ASK = "ask"
POLICY_FILE = ".agents/rules/permission-rules-general.md"
MAX_NESTING_DEPTH = 4

OPERATOR_CHARS = frozenset("();<>|&\n`")
REDIRECT_OPERATORS = frozenset({"<", ">", ">>", ">&", "<&", "&>", "&>>", ">|", "<>", "<<", "<<-", "<<<"})
PIPE_OPERATORS = frozenset({"|", "|&"})
SUBSTITUTION_OPERATORS = frozenset({"(", "<(", ">("})
ENV_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
HEREDOC_START = re.compile(r"(?<!<)<<(?!<)(-?)\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\2")

SHELLS = frozenset({"sh", "bash", "zsh", "dash", "ksh", "ash", "fish"})
INTERPRETERS = SHELLS | {
    "python", "python3", "node", "perl", "ruby", "php", "pwsh", "powershell",
    "iex", "invoke-expression", "source", ".", "eval",
}
DOWNLOADERS = frozenset({
    "curl", "wget", "iwr", "irm", "invoke-webrequest", "invoke-restmethod", "aria2c", "certutil", "bitsadmin",
    "start-bitstransfer",
})
PRIVILEGE_COMMANDS = frozenset({"sudo", "su", "doas", "pkexec", "runas", "gsudo"})
SIMPLE_WRAPPERS = frozenset({
    "command", "builtin", "exec", "nohup", "time", "noglob", "setsid", "chronic", "unbuffer", "caffeinate",
    "busybox", "toybox",
})
VALUE_WRAPPERS = {  # wrapper -> options that consume the next token
    "env": {"-u", "--unset", "-C", "--chdir", "-S", "--split-string"},
    "nice": {"-n", "--adjustment"},
    "ionice": {"-c", "-n", "-p", "-t"},
    "stdbuf": {"-i", "-o", "-e"},
    "timeout": {"-s", "--signal", "-k", "--kill-after"},
    "xargs": {"-n", "-I", "-L", "-d", "-P", "-s", "-E", "-a", "--max-args", "--delimiter", "--max-procs", "--arg-file"},
    "watch": {"-n", "--interval", "-d"},
    "flock": {"-w", "--timeout", "-E", "--conflict-exit-code"},
}
WRAPPERS_WITH_OPERAND = {"timeout": 1, "flock": 1}  # positional operands before the wrapped command
RUNNERS = {  # runner -> (subcommands that run the next command, or () for the runner itself; options taking a value)
    "uv": ({"run"}, {"--with", "--python", "-p", "--project", "--directory", "--package", "--extra", "--group", "--env-file", "--index"}),
    "uvx": ((), {"--with", "--from", "--python", "-p", "--index"}),
    "poetry": ({"run"}, {"--directory", "-C", "--project", "-P"}),
    "pdm": ({"run"}, {"--project", "-p"}),
    "hatch": ({"run"}, set()),
    "pipx": ({"run"}, {"--spec", "--python", "--index-url", "-i"}),
    "conda": ({"run"}, {"--name", "-n", "--prefix", "-p"}),
    "npx": ((), {"--package", "-p"}),
    "pnpx": ((), {"--package", "-p"}),
    "bunx": ((), {"--package", "-p"}),
    "npm": ({"exec", "x"}, {"--package", "-p", "--workspace", "-w"}),
    "pnpm": ({"exec", "dlx"}, {"--package", "--dir", "-C", "--filter", "-F"}),
    "yarn": ({"exec", "dlx"}, {"--package", "-p"}),
    "bun": ({"x"}, {"--package", "-p"}),
}
PYTHON_PROGRAM = re.compile(r"^(python[0-9.]*|py)$")
EXECUTABLE_SUFFIX = re.compile(r"\.(exe|cmd|bat)$")
ANSI_C_QUOTE = re.compile(r"\$'((?:[^'\\]|\\.)*)'")
ANSI_C_ESCAPE = re.compile(r"\\(x[0-9A-Fa-f]{1,2}|u[0-9A-Fa-f]{1,4}|[0-7]{1,3}|.)", re.DOTALL)
ANSI_C_SIMPLE_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "a": "\a", "b": "\b", "e": "\x1b", "f": "\f", "v": "\v"}
INLINE_CODE_FLAGS = {  # interpreter -> flags whose value is program text
    "python": {"-c"}, "node": {"-e", "--eval", "-p", "--print"}, "deno": {"eval"}, "bun": {"-e", "--eval"},
    "perl": {"-e", "-E"}, "ruby": {"-e"}, "php": {"-r"},
}
INLINE_EXEC_MARKER = re.compile(r"system|popen|subprocess|child_process|exec|spawn|shell|%x|`", re.IGNORECASE)
STRING_LITERAL = re.compile(r"'((?:[^'\\]|\\.)+)'|\"((?:[^\"\\]|\\.)+)\"")

AGENT_BYPASS_FLAGS = frozenset({
    "--dangerously-skip-permissions", "--allow-dangerously-skip-permissions",
    "--dangerously-bypass-approvals-and-sandbox", "--yolo", "--trust-all-tools",
    "--allow-all-tools", "danger-full-access",
})
AGENT_BYPASS_OPTION_VALUES = {"--permission-mode": "bypasspermissions", "--approval-mode": "yolo", "--sandbox": "danger-full-access"}
AGENT_CLIS = frozenset({  # agent CLIs, including the package names a runner such as npx resolves to
    "claude", "claude-code", "codex", "gemini", "gemini-cli", "copilot", "cursor-agent", "qwen", "goose",
    "opencode", "aider",
})
AGENT_INFO_ARGUMENTS = frozenset({"--version", "-v", "-V", "--help", "-h", "doctor", "help", "version"})
AGENT_EXTENSION_GROUPS = frozenset({"mcp", "plugin", "plugins", "extension", "extensions", "skill", "skills"})
AGENT_EXTENSION_READ_ACTIONS = frozenset({"list", "ls", "get", "show", "status", "info", "validate"})
EDITOR_CLIS = frozenset({"code", "code-insiders", "codium", "cursor", "windsurf"})
AGENT_ENDPOINT_VARIABLES = frozenset({
    "ANTHROPIC_BASE_URL", "ANTHROPIC_BEDROCK_BASE_URL", "ANTHROPIC_VERTEX_BASE_URL", "OPENAI_BASE_URL",
    "OPENAI_API_BASE", "GOOGLE_GEMINI_BASE_URL", "CODE_ASSIST_ENDPOINT",
})

PROTECTED_BRANCHES = frozenset({"main", "master", "trunk", "production", "prod"})
RELEASE_BRANCH = re.compile(r"^release([/-]v?\d|/|$)")
GIT_GLOBAL_VALUE_OPTIONS = frozenset({
    "-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path", "--config-env", "--super-prefix",
})
GIT_PUSH_VALUE_OPTIONS = frozenset({"-o", "--push-option", "--repo", "--receive-pack", "--exec"})
GIT_COMMIT_VALUE_SHORT = frozenset("mFcCt")
GIT_CONFIG_READ_ACTIONS = frozenset({"--get", "--get-all", "--get-regexp", "get", "--list", "-l", "list"})
GIT_CONFIG_UNSET_ACTIONS = frozenset({"--unset", "--unset-all", "unset"})
GIT_CONFIG_VALUE_OPTIONS = frozenset({"-f", "--file", "--blob", "--type", "--default", "--comment"})
GIT_CONFIG_ACTION_WORDS = frozenset({"set", "get", "unset", "list", "add"})
GIT_EXECUTING_KEY = re.compile(  # configuration keys whose value names a program git will run
    r"^(core\.(fsmonitor|sshcommand|pager|editor|gitproxy|askpass)|sequence\.editor|diff\.external"
    r"|diff\..+\.(textconv|command)|merge\..+\.driver|filter\..+\.(clean|smudge|process)|alias\..+"
    r"|credential(\..+)?\.helper|gpg(\..+)?\.program|pager\..+|url\..+\.(insteadof|pushinsteadof)"
    r"|protocol\.ext\.allow|uploadpack\.packobjectshook|include(if\..+)?\.path|init\.templatedir"
    r"|remote\..+\.(uploadpack|receivepack|vcs|proxy)|http(\..+)?\.proxy)$"
)
GIT_BENIGN_PROGRAM_VALUES = frozenset({"", "cat", "less", "more", "true", "false", ":", "0", "1", "never"})
GIT_EXECUTING_VARIABLES = frozenset({
    "GIT_SSH_COMMAND", "GIT_SSH", "GIT_EXTERNAL_DIFF", "GIT_ASKPASS", "GIT_PROXY_COMMAND", "GIT_CONFIG_GLOBAL",
    "GIT_CONFIG_SYSTEM", "GIT_CONFIG_COUNT", "GIT_CONFIG_PARAMETERS", "GIT_EXEC_PATH", "GIT_TEMPLATE_DIR",
})
GIT_EXECUTING_OPTIONS = ("--upload-pack", "--receive-pack", "--exec")
GIT_INTERNAL_EXEC_PATH = re.compile(r"(^|/)\.git/(config|hooks(/|$)|info/attributes$)", re.IGNORECASE)

ENV_EXAMPLE_SUFFIXES = frozenset({"example", "sample", "template"})
ALTERNATE_DATA_STREAM = re.compile(r"(?<=[^/:]{2}):[^/]*$")  # NTFS `file::$DATA` opens the same file
SECRET_PATH_PATTERNS = tuple(re.compile(pattern, re.IGNORECASE) for pattern in (
    r"(^|/)\.ssh(/|$)", r"(^|/)id_(rsa|dsa|ecdsa|ed25519)$", r"(^|/)\.gnupg(/|$)",
    r"(^|/)\.aws(/|$)", r"(^|/)\.azure(/|$)", r"(^|/)\.config/gcloud(/|$)", r"(^|/)\.kube(/|$)",
    r"(^|/)\.docker/config\.json$", r"(^|/)\.config/gh(/|$)", r"(^|/)\.git-credentials$",
    r"(^|/)[._]netrc$", r"(^|/)\.npmrc$", r"(^|/)\.pypirc$", r"(^|/)\.gem/credentials$",
    r"(^|/)\.cargo/credentials(\.toml)?$", r"(^|/)\.claude/\.credentials\.json$",
    r"(^|/)\.codex/auth\.json$", r"(^|/)\.gemini/oauth_creds\.json$", r"(^|/)\.claude\.json$",
    r"(^|/)\.(claude|codex)/history\.jsonl$", r"(^|/)\.config/github-copilot(/|$)",
    r"(^|/)\.local/share/opencode/auth\.json$", r"(^|/)\.config/op(/|$)", r"(^|/)\.vault-token$",
    r"(^|/)\.terraform\.d/credentials\.tfrc\.json$", r"(^|/)\.terraformrc$",
    r"(^|/)\.config/rclone/rclone\.conf$", r"(^|/)\.m2/settings(-security)?\.xml$",
    r"(^|/)kubeconfig(\.ya?ml)?$", r"(^|/)(Login Data|key4\.db|logins\.json)$",
    r"(^|/)Library/Keychains(/|$)", r"\.keychain(-db)?$",
    r"\.(pem|key|p12|pfx|jks|keystore|kdbx|ppk|ovpn)$", r"\.tfstate(\.backup)?$",
    r"(^|/)(credentials|client_secret[^/]*|service[-_]account[^/]*)\.json$",
    r"(^|/)\.?(bash|zsh|sh)_history$", r"(^|/)ConsoleHost_history\.txt$",
    r"(^|/)\.(gitconfig|zshrc|bashrc)\.local$", r"(^|/)\.powershell\.local\.ps1$",
    r"(^|/)\.secrets$", r"^/proc/[^/]+/environ$",
))
PATTERN_FIRST_PROGRAMS = frozenset({"grep", "egrep", "fgrep", "rg", "ag", "ack"})
LITERAL_PRINTERS = frozenset({"echo", "printf"})

AGENT_CONFIG_PATH = re.compile(
    r"(^|/)(\.claude/settings(\.local)?\.json|managed-settings\.json|\.claude\.json"
    r"|\.vscode/(settings|mcp)\.json|User/settings\.json|\.cursor/(cli|cli-config|permissions|mcp)\.json"
    r"|\.gemini/settings\.json|\.codex/(config|requirements)\.toml|\.mcp\.json)$",
    re.IGNORECASE,
)
MCP_SERVER_DEFINITION = re.compile(r'"mcpServers"\s*:|\[mcp_servers\.')
MCP_CONFIG_PATH = re.compile(r"(^|/)(\.mcp\.json|\.(vscode|cursor)/mcp\.json)$", re.IGNORECASE)
HOME_PREFIX = r"^(~|\$HOME|\$\{HOME\}|\$env:USERPROFILE|/home/[^/]+|/Users/[^/]+|/root|[A-Za-z]:/Users/[^/]+)/"
STARTUP_FILE_PATH = re.compile(  # files the host runs on login or shell start (N-03)
    HOME_PREFIX + r"(\.(bashrc|bash_profile|bash_login|bash_logout|zshrc|zprofile|zshenv|zlogin|profile)"
    r"|\.config/fish/config\.fish|(\.config/powershell|Documents/(Windows)?PowerShell)/.*profile\.ps1"
    r"|Library/LaunchAgents/.+|\.config/(systemd/user|autostart)/.+"
    r"|AppData/Roaming/Microsoft/Windows/Start Menu/Programs/Startup/.+)$",
    re.IGNORECASE,
)
AUDIT_TRAIL_PATTERNS = tuple(re.compile(pattern, re.IGNORECASE) for pattern in (  # N-12
    r"(^|/)\.claude/(projects|logs|file-history|shell-snapshots)(/|$)",
    r"(^|/)\.codex/(sessions|log)(/|$)", r"(^|/)\.gemini/(tmp|history)(/|$)", r"^/var/log(/|$)",
))
AUDIT_DESTROYERS = frozenset({
    "rm", "shred", "truncate", "unlink", "mv", "del", "erase", "remove-item", "ri", "clear-content", "clc",
})
HISTORY_ERASERS = frozenset({"clear-history", "clear-eventlog", "wevtutil"})
HISTORY_DISABLING = re.compile(r"^(HISTFILE=(/dev/null)?|HISTSIZE=0|HISTFILESIZE=0)$")
DESTINATION_LAST_WRITERS = frozenset({"cp", "mv", "install", "ln", "rsync", "copy-item", "move-item", "copy", "move"})
ANY_OPERAND_WRITERS = frozenset({"tee", "add-content", "set-content", "out-file", "ac", "sc"})
GUARDRAIL_DISABLING_SETTINGS = tuple(re.compile(pattern) for pattern in (
    r'"chat\.tools\.(global\.)?autoApprove"\s*:\s*true',
    r'"chat\.tools\.terminal\.ignoreDefaultAutoApproveRules"\s*:\s*true',
    r'"defaultMode"\s*:\s*"bypassPermissions"',
    r'"enableAllProjectMcpServers"\s*:\s*true',
    r'"skipDangerousModePermissionPrompt"\s*:\s*true',
    r'"disableYoloMode"\s*:\s*false',
    r'"defaultApprovalMode"\s*:\s*"yolo"',
    r'"disableAllHooks"\s*:\s*true',
    r'"sandbox"\s*:\s*\{\s*"enabled"\s*:\s*false',
    r'"apiKeyHelper"\s*:',
    r'"(' + "|".join(sorted(AGENT_ENDPOINT_VARIABLES)) + r')"\s*:',  # JSON `env` block
    r"\b(" + "|".join(sorted(AGENT_ENDPOINT_VARIABLES)) + r")\s*=\s*[\"']?\w",  # TOML or shell assignment
    r'\b(openai_base_url|chatgpt_base_url)\s*=',
    r'sandbox_mode\s*=\s*"danger-full-access"',
    r'approval_policy\s*=\s*"never"',
    r'approvals_reviewer\s*=\s*"auto_review"',
    r'\bnetwork_access\s*=\s*true',
    r'\bdangerously_allow_\w+\s*=\s*true',
))

EXFIL_HOSTS = (
    "169.254.169.254", "metadata.google.internal", "webhook.site", "pastebin.com", "paste.ee",
    "hastebin.com", "transfer.sh", "0x0.st", "termbin.com", "requestbin", "pipedream.net",
    "ngrok.io", "ngrok-free.app", "ngrok.app", "trycloudflare.com", "interact.sh", "oast.fun",
    "oast.pro", "oast.live", "burpcollaborator.net", "oastify.com", "requestcatcher.com", "beeceptor.com",
    "canarytokens.com", "ngrok.dev", "localhost.run", "serveo.net", "loca.lt", "file.io", "gofile.io",
    "tmpfiles.org", "catbox.moe", "bashupload.com", "dpaste.com", "api.imgur.com",
    "discord.com/api/webhooks", "discordapp.com/api/webhooks", "hooks.slack.com", "api.telegram.org",
)
NETWORK_TOOLS = DOWNLOADERS | {
    "http", "https", "xh", "nc", "ncat", "netcat", "socat", "ssh", "scp", "sftp", "rsync", "ftp",
    "telnet", "ping", "dig", "nslookup", "host",
}
EXFIL_HOST_PATTERN = re.compile(  # a host or one of its subdomains, not a longer name that merely ends the same way
    r"(?<![a-z0-9-])(" + "|".join(re.escape(host) for host in EXFIL_HOSTS) + r")"
)
REMOTE_SOURCES = NETWORK_TOOLS - {"ping"}  # programs whose output is attacker-controlled when piped onward
DECODERS = {  # program -> flags that turn an encoded payload back into text
    "base64": {"-d", "-D", "--decode"}, "base32": {"-d", "-D", "--decode"}, "xxd": {"-r"},
    "openssl": {"-d"}, "uudecode": set(), "certutil": {"-decode", "-decodehex"},
}
POWERSHELL_PROGRAMS = frozenset({"powershell", "pwsh"})
POWERSHELL_ENCODED_FLAG = re.compile(r"^-(e|ec|en|enc|enco[a-z]*)$", re.IGNORECASE)
TUNNEL_PROGRAMS = frozenset({"ngrok", "localtunnel", "lt", "bore"})
PUBLISH_SUBCOMMANDS = {
    "npm": {"publish", "unpublish", "deprecate", "dist-tag", "owner", "token", "adduser", "login"},
    "pnpm": {"publish"}, "bun": {"publish"}, "twine": {"upload"}, "uv": {"publish"},
    "poetry": {"publish"}, "cargo": {"publish", "yank", "owner", "login"}, "nuget": {"push", "delete"},
    "gem": {"push", "yank", "owner"}, "docker": {"push", "login"}, "podman": {"push", "login"},
    "mvn": {"deploy"}, "gradle": {"publish"},
}
PUBLISH_SUBCOMMAND_PAIRS = {
    "yarn": {("publish",), ("npm", "publish"), ("npm", "login")}, "dotnet": {("nuget", "push"), ("nuget", "delete")},
    "dart": {("pub", "publish")}, "flutter": {("pub", "publish")},
}
DESTRUCTIVE_SQL = re.compile(r"\b(drop\s+(database|schema|table)|truncate\s+(table\s+)?\w|dropdatabase\s*\()", re.IGNORECASE)
SQL_CLIENTS = frozenset({"psql", "mysql", "mariadb", "sqlcmd", "sqlite3", "mongosh", "mongo", "cockroach"})
CLOUD_DELETE_PREFIXES = ("delete-", "terminate-", "deregister-", "remove-")
IAM_GRANT_PREFIXES = ("create-", "attach-", "put-", "update-", "add-")
CONTAINER_ESCAPE_FLAGS = frozenset({
    "--privileged", "--pid=host", "--net=host", "--network=host", "--ipc=host", "--userns=host",
    "--cap-add=all", "--cap-add=sys_admin",
})
CONTAINER_HOST_NAMESPACE_OPTIONS = {"--pid": "host", "--net": "host", "--network": "host", "--ipc": "host", "--cap-add": "all"}
SYSTEM_DIRS_ANY_DEPTH = re.compile(r"^/(bin|boot|dev|etc|lib|lib32|lib64|proc|sbin|sys|usr|System|Library)(/|$)")
SHALLOW_ROOT_PATH = re.compile(r"^/[^/]+(/[^/]+)?$")
SHALLOW_ROOT_DIRS = frozenset({"home", "Users", "var", "opt", "srv", "root", "mnt", "media", "Volumes", "private"})
CRITICAL_TARGETS = frozenset({
    "/", "/*", "~", "~/*", "$HOME", "${HOME}", "$HOME/*", "${HOME}/*", ".", "./*", "*", "..", "../*",
})
WINDOWS_CRITICAL_VARIABLES = frozenset({
    "$env:userprofile", "$env:homepath", "$env:systemroot", "$env:systemdrive", "$env:programfiles", "$env:windir",
})
WINDOWS_DESTROYERS = frozenset({  # disk, boot, backup, and power tools with no safe agent use (N-05)
    "format-volume", "clear-disk", "initialize-disk", "remove-partition", "diskpart", "bcdedit", "vssadmin",
    "wbadmin", "stop-computer", "restart-computer",
})
WINDOWS_SWITCH = re.compile(r"^/[A-Za-z]$")  # cmd.exe switches such as /s and /q
WINDOWS_RECURSE_FLAG = re.compile(r"^-r(e(c(u(r(se?)?)?)?)?)?$", re.IGNORECASE)  # PowerShell accepts any prefix
WINDOWS_RECURSIVE_DELETERS = frozenset({"remove-item", "ri", "rmdir", "rd", "del", "erase"})
WINDOWS_PERSISTENCE = frozenset({"register-scheduledtask", "new-scheduledtask", "new-service", "set-scheduledtask"})
REGISTRY_WRITERS = frozenset({"reg", "new-itemproperty", "set-itemproperty", "sp"})
WINDOWS_RUN_KEY = re.compile(r"currentversion[\\/]*(run|runonce)\b", re.IGNORECASE)  # shlex drops backslashes
VARIABLE_GLOB = re.compile(r"^\$\{?[A-Za-z0-9_@*]+\}?/\*?$")  # "$DIR/*" expands to "/*" when DIR is empty
WINDOWS_CRITICAL = re.compile(r"^[A-Za-z]:[\\/]?(\*|(Windows|Users|Program Files[^\\/]*)[\\/]?)?$", re.IGNORECASE)
DOWNLOADER_SUBSTITUTION = re.compile(r"(\$\(|`)\s*(curl|wget|iwr|irm)\b", re.IGNORECASE)


class Segment:
    """One simple command: its words, redirect targets, and the operator before it."""

    def __init__(self, op_before: str) -> None:
        self.op_before = op_before
        self.words: List[str] = []
        self.redirect_targets: List[str] = []


def finding(decision: str, rule_id: str, message: str) -> Decision:
    return decision, f"[{rule_id}] {message} Policy: " + POLICY_FILE


def strongest(results: Sequence[Optional[Decision]]) -> Optional[Decision]:
    """Return the first deny, else the first ask, else None."""
    for wanted in (DENY, ASK):
        for result in results:
            if result and result[0] == wanted:
                return result
    return None


# ----------------------------------------------------------------------------
# Tokenizing
# ----------------------------------------------------------------------------
def is_operator(token: str) -> bool:
    return bool(token) and all(char in OPERATOR_CHARS for char in token)


def decode_ansi_c(match: "re.Match[str]") -> str:
    """Rewrite bash `$'...'` quoting (which can hide `$'su\\x64o'`) as a plain quoted word."""
    def decode_escape(escape: "re.Match[str]") -> str:
        body = escape.group(1)
        if body[0] in "xu" and len(body) > 1:
            return chr(int(body[1:], 16))
        if body[0] in "01234567":
            return chr(int(body, 8))
        return ANSI_C_SIMPLE_ESCAPES.get(body, body)
    return shlex.quote(ANSI_C_ESCAPE.sub(decode_escape, match.group(1)))


def canonical_command(command: str) -> str:
    """Undo spellings the shell resolves before running: line continuations and ANSI-C quotes."""
    return ANSI_C_QUOTE.sub(decode_ansi_c, command.replace("\\\n", ""))


def tokenize(command: str) -> List[str]:
    lexer = shlex.shlex(command, posix=True, punctuation_chars="();<>|&\n`")
    lexer.whitespace_split = True
    lexer.whitespace = " \t\r"
    lexer.commenters = ""
    try:
        return list(lexer)
    except ValueError:  # unbalanced quotes: fall back to a coarse split
        return re.findall(r"[;&|\n()`<>]+|[^\s;&|\n()`<>]+", command)


def outside_quotes(line: str, position: int) -> bool:
    quote = ""
    escaped = False
    for char in line[:position]:
        if escaped:
            escaped = False
        elif char == "\\" and quote != "'":
            escaped = True
        elif quote:
            quote = "" if char == quote else quote
        elif char in "'\"":
            quote = char
    return not quote


def receives_shell(prefix: str) -> bool:
    words = strip_privilege(strip_wrappers(re.split(r"[;&|]", prefix)[-1].split()))
    return bool(words) and program_name(words[0]) in SHELLS


def extract_heredocs(command: str) -> Tuple[str, List[str]]:
    """Drop heredoc bodies; return bodies fed to a shell for separate inspection."""
    lines = command.split("\n")
    kept: List[str] = []
    shell_bodies: List[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        kept.append(line)
        index += 1
        for match in HEREDOC_START.finditer(line):
            if not outside_quotes(line, match.start()):
                continue
            body, end = read_heredoc_body(lines, index, match.group(3), match.group(1) == "-")
            if end is None:
                continue  # unterminated: keep analysing the following lines as commands
            index = end
            if receives_shell(line[: match.start()]):
                shell_bodies.append("\n".join(body))
    return "\n".join(kept), shell_bodies


def read_heredoc_body(lines: List[str], start: int, delimiter: str, strip_tabs: bool) -> Tuple[List[str], Optional[int]]:
    for index in range(start, len(lines)):
        candidate = lines[index].lstrip("\t") if strip_tabs else lines[index]
        if candidate == delimiter:
            return lines[start:index], index + 1
    return [], None


def split_segments(tokens: Sequence[str]) -> List[Segment]:
    segments = [Segment("start")]
    expecting_redirect_target = False
    for token in tokens:
        current = segments[-1]
        if expecting_redirect_target and not is_operator(token):
            current.redirect_targets.append(token)
            expecting_redirect_target = False
        elif token in REDIRECT_OPERATORS:
            if current.words and current.words[-1].isdigit():
                current.words.pop()  # file descriptor such as the 2 in 2>&1
            expecting_redirect_target = True
        elif is_operator(token):
            segments.append(Segment(classify_separator(token)))
            expecting_redirect_target = False
        else:
            current.words.append(token)
    return [segment for segment in segments if segment.words or segment.redirect_targets]


def classify_separator(token: str) -> str:
    if token in PIPE_OPERATORS:
        return "pipe"
    if token in SUBSTITUTION_OPERATORS or token == "`":
        return "substitution"
    return "sequence"


# ----------------------------------------------------------------------------
# Command normalization
# ----------------------------------------------------------------------------
def program_name(word: str) -> str:
    return EXECUTABLE_SUFFIX.sub("", word.replace("\\", "/").rsplit("/", 1)[-1].lower())


def skip_options(words: List[str], value_options: Sequence[str]) -> List[str]:
    index = 0
    while index < len(words) and words[index].startswith("-") and words[index] != "-":
        consumes_value = words[index] in value_options
        index += 2 if consumes_value else 1
        if words[index - (2 if consumes_value else 1)] == "--":
            break
    return words[index:]


def strip_runner(name: str, words: Sequence[str]) -> Optional[List[str]]:
    """Return the command a runner such as `uv run` or `npx` executes, or None."""
    subcommands, value_options = RUNNERS[name]
    rest = list(words[1:])
    if subcommands:
        if not rest or rest[0] not in subcommands:
            return None
        rest = rest[1:]
    return skip_options(rest, tuple(value_options))


def strip_wrappers(words: Sequence[str]) -> List[str]:
    """Remove env assignments, exec wrappers (env, timeout, xargs, ...), and runners (uv run, npx, ...)."""
    remaining = list(words)
    while remaining:
        name = program_name(remaining[0])
        if ENV_ASSIGNMENT.match(remaining[0]):
            remaining = remaining[1:]
        elif name in SIMPLE_WRAPPERS:
            remaining = skip_options(remaining[1:], ())
        elif name in VALUE_WRAPPERS:
            remaining = skip_options(remaining[1:], tuple(VALUE_WRAPPERS[name]))
            remaining = remaining[WRAPPERS_WITH_OPERAND.get(name, 0):]
        elif name in RUNNERS:
            executed = strip_runner(name, remaining)
            if executed is None:
                break
            remaining = executed
        else:
            break
    return remaining


def python_module(prog: str, args: List[str]) -> Tuple[str, List[str]]:
    """Treat `python -m <module> <args>` as `<module> <args>`."""
    if not PYTHON_PROGRAM.match(prog):
        return prog, args
    for index, arg in enumerate(args):
        if arg == "-m" and index + 1 < len(args):
            return program_name(args[index + 1]), args[index + 2:]
        if not arg.startswith("-"):
            break
    return prog, args


def strip_privilege(words: Sequence[str]) -> List[str]:
    remaining = list(words)
    while remaining and program_name(remaining[0]) in PRIVILEGE_COMMANDS:
        remaining = strip_wrappers(skip_options(remaining[1:], ("-u", "-g", "-C", "-p")))
    return remaining


def positional(args: Sequence[str]) -> List[str]:
    return [arg for arg in args if not arg.startswith("-")]


def short_flags(arg: str) -> str:
    return arg[1:] if re.match(r"^-[A-Za-z]+$", arg) else ""


def has_short_flag(args: Sequence[str], letter: str) -> bool:
    return any(letter in short_flags(arg) for arg in args)


# ----------------------------------------------------------------------------
# Path classification
# ----------------------------------------------------------------------------
def normalize_path(path: str) -> str:
    """Canonical spelling of a path: Windows opens `x.json.`, `x.json ` and `x.json::$DATA` as `x.json`."""
    unified = ALTERNATE_DATA_STREAM.sub("", path.strip("'\"").replace("\\", "/"))
    return "/".join(segment.rstrip(". ") or segment for segment in unified.split("/"))


def is_secret_path(path: str) -> bool:
    normalized = normalize_path(path)
    basename = normalized.rstrip("/").rsplit("/", 1)[-1].lower()
    if basename == ".env" or (basename.endswith(".env") and len(basename) > len(".env")):
        return True
    if basename.startswith(".env.") and basename[len(".env."):] not in ENV_EXAMPLE_SUFFIXES:
        return True
    return any(pattern.search(normalized) for pattern in SECRET_PATH_PATTERNS)


def is_startup_file(path: str) -> bool:
    return path.lower() == "$profile" or bool(STARTUP_FILE_PATH.match(normalize_path(path)))


def is_audit_trail(path: str) -> bool:
    normalized = normalize_path(path)
    return any(pattern.search(normalized) for pattern in AUDIT_TRAIL_PATTERNS)


def is_critical_target(target: str) -> bool:
    if target.strip("'\"").rstrip("\\/*").lower() in WINDOWS_CRITICAL_VARIABLES:
        return True
    normalized = normalize_path(target)
    trimmed = normalized.rstrip("/") or "/"
    if normalized in CRITICAL_TARGETS or trimmed in CRITICAL_TARGETS or VARIABLE_GLOB.match(normalized):
        return True
    if WINDOWS_CRITICAL.match(target) or SYSTEM_DIRS_ANY_DEPTH.match(trimmed):
        return True
    shallow = SHALLOW_ROOT_PATH.match(trimmed)
    return bool(shallow) and (trimmed.count("/") == 1 or trimmed.split("/")[1] in SHALLOW_ROOT_DIRS)


# ----------------------------------------------------------------------------
# Segment checks: each returns a Decision or None
# ----------------------------------------------------------------------------
def check_privilege(prog: str, args: List[str], tokens: List[str]) -> Optional[Decision]:
    if prog in PRIVILEGE_COMMANDS:
        return finding(DENY, "N-03", f"Privilege escalation via `{prog}` is never allowed.")
    launch_agent = prog == "launchctl" and positional(args)[:1] in (["load"], ["bootstrap"], ["submit"], ["enable"])
    lowered = [arg.lower() for arg in args]
    elevated = prog in ("start-process", "saps", "start") and "runas" in lowered
    if elevated:
        return finding(DENY, "N-03", "Privilege escalation via `-Verb RunAs` is never allowed.")
    scheduled = prog in ("schtasks", "sc") and lowered[:1] in (["/create"], ["create"])
    run_key = prog in REGISTRY_WRITERS and any(WINDOWS_RUN_KEY.search(arg) for arg in args)
    persistence = prog == "crontab" or launch_agent or prog in WINDOWS_PERSISTENCE or scheduled or run_key
    if persistence or (prog == "systemctl" and "enable" in args):
        return finding(DENY, "N-03", "Installing persistence on the host is never allowed.")
    return None


def written_operands(prog: str, args: List[str], redirect_targets: List[str]) -> List[str]:
    """Paths a command writes: redirect targets, copy destinations, and `tee`-style operands."""
    operands = positional(args)
    written = list(redirect_targets)
    if prog in DESTINATION_LAST_WRITERS and len(operands) > 1:
        written.append(operands[-1])
    elif prog in ANY_OPERAND_WRITERS or (prog == "sed" and any(a.startswith(("-i", "--in-place")) for a in args)):
        written.extend(operands)
    return written


def check_host_files(prog: str, args: List[str], redirect_targets: List[str]) -> Optional[Decision]:
    """N-03 for shell startup files and N-12 for the audit trail, whichever tool touches them."""
    if any(is_startup_file(path) for path in written_operands(prog, args, redirect_targets)):
        return finding(DENY, "N-03", "Writing shell startup or autostart files is never allowed.")
    if erases_audit_trail(prog, args) or any(is_audit_trail(target) for target in redirect_targets):
        return finding(DENY, "N-12", "Deleting or rewriting session transcripts, logs, or shell history is never allowed.")
    return None


def erases_audit_trail(prog: str, args: List[str]) -> bool:
    erases_history = prog in HISTORY_ERASERS or (prog == "history" and any(a in ("-c", "-w", "-d") for a in args))
    disables_history = (prog == "unset" and "HISTFILE" in args) or (prog == "set" and args[:2] == ["+o", "history"])
    return erases_history or disables_history or (prog in AUDIT_DESTROYERS and any(is_audit_trail(a) for a in args))


def check_environment(words: Sequence[str]) -> Optional[Decision]:
    """Inspect `NAME=value` words (leading assignments, `env`, `export`) before they are stripped."""
    for word in words:
        if not ENV_ASSIGNMENT.match(word):
            continue
        name, value = word.split("=", 1)
        if name in AGENT_ENDPOINT_VARIABLES:
            return finding(DENY, "N-04", "Repointing an agent's API endpoint is never allowed.")
        if HISTORY_DISABLING.match(word):
            return finding(DENY, "N-12", "Disabling shell history is never allowed.")
        if name in GIT_EXECUTING_VARIABLES and value.lower() not in GIT_BENIGN_PROGRAM_VALUES:
            return finding(ASK, "C-HITL-10", f"`{name}` makes git run a program and requires human approval.")
    return None


def check_agent_cli(prog: str, args: List[str], tokens: List[str]) -> Optional[Decision]:
    """C-HITL-07 for installing extensions; C-HITL-09 for starting another agent session."""
    if prog in EDITOR_CLIS:
        installs = any(arg.startswith("--install-extension") for arg in args)
        return finding(ASK, "C-HITL-07", "Installing an editor extension requires human approval.") if installs else None
    if prog not in AGENT_CLIS or not args or args[0] in AGENT_INFO_ARGUMENTS:
        return None
    words = positional(args)
    if words[:1] and words[0] in AGENT_EXTENSION_GROUPS:
        if words[1:2] and words[1] in AGENT_EXTENSION_READ_ACTIONS:
            return None
        return finding(ASK, "C-HITL-07", "Adding MCP servers, plugins, extensions, or skills requires human approval.")
    return finding(ASK, "C-HITL-09", f"Starting a nested `{prog}` agent session requires human approval.")


def check_agent_bypass(prog: str, args: List[str], tokens: List[str]) -> Optional[Decision]:
    lowered = [token.lower() for token in tokens]
    flagged = any(token in AGENT_BYPASS_FLAGS for token in lowered)
    for option, value in AGENT_BYPASS_OPTION_VALUES.items():
        pairs = zip(lowered, lowered[1:] + [""])
        flagged = flagged or any(t == f"{option}={value}" or (t == option and n == value) for t, n in pairs)
    if prog == "cursor-agent" and ("--force" in args or "-f" in args):
        flagged = True
    if flagged:
        return finding(DENY, "N-04", "Running an agent with approvals or sandbox disabled is never allowed.")
    if weakens_host_protection(prog, lowered):
        return finding(DENY, "N-04", "Weakening host protection (Defender, execution policy) is never allowed.")
    return None


def weakens_host_protection(prog: str, lowered: List[str]) -> bool:
    """Defender exclusions or switches, and a machine- or user-wide unrestricted execution policy."""
    if prog in ("set-mppreference", "add-mppreference"):
        return any(arg.startswith(("-disable", "-exclusion")) for arg in lowered)
    unrestricted = any(arg in ("bypass", "unrestricted") for arg in lowered)
    return prog == "set-executionpolicy" and unrestricted and "process" not in lowered


def secret_candidates(prog: str, args: List[str], redirect_targets: List[str]) -> List[str]:
    operands = [] if prog in LITERAL_PRINTERS else list(args)
    if prog in PATTERN_FIRST_PROGRAMS and not any(a in ("-e", "--regexp", "-f", "--file") for a in operands):
        first = next((i for i, a in enumerate(operands) if not a.startswith("-")), None)
        operands = operands if first is None else operands[:first] + operands[first + 1:]
    parts: List[str] = []
    for token in operands + list(redirect_targets):
        parts.extend(part.lstrip("@") for part in re.split(r"[=,]", token) if part)
    return parts


def check_secret_access(prog: str, args: List[str], redirect_targets: List[str]) -> Optional[Decision]:
    if any(is_secret_path(candidate) for candidate in secret_candidates(prog, args, redirect_targets)):
        return finding(DENY, "N-01", "Reading, writing, or copying secret files is never allowed.")
    return None


def git_subcommand(args: List[str]) -> Tuple[str, List[str], List[str]]:
    """Split `git <global options> <subcommand> <args>`; also return `-c` values."""
    configs: List[str] = []
    index = 0
    while index < len(args) and args[index].startswith("-"):
        option = args[index]
        if option in GIT_GLOBAL_VALUE_OPTIONS and index + 1 < len(args):
            if option == "-c":
                configs.append(args[index + 1])
            index += 2
        else:
            index += 1
    if index >= len(args):
        return "", [], configs
    return args[index].lower(), args[index + 1:], configs


def push_refspecs(args: List[str]) -> List[str]:
    remaining = skip_options(list(args), tuple(GIT_PUSH_VALUE_OPTIONS))
    operands = [arg for arg in remaining if not arg.startswith("-")]
    return operands[1:]  # the first operand is the remote


def is_protected_ref(refspec: str) -> bool:
    destination = refspec.lstrip("+").rsplit(":", 1)[-1]
    if destination.startswith("refs/heads/"):
        destination = destination[len("refs/heads/"):]
    return destination in PROTECTED_BRANCHES or bool(RELEASE_BRANCH.match(destination))


def check_git_push(args: List[str]) -> Decision:
    force = {"--force", "-f", "--force-with-lease", "--force-if-includes", "--mirror", "--delete", "-d", "--prune"}
    refspecs = push_refspecs(args)
    rewrites_remote = any(a in force or a.startswith("--force-with-lease=") for a in args)
    rewrites_remote = rewrites_remote or has_short_flag(args, "f") or has_short_flag(args, "d")
    if rewrites_remote or any(ref.startswith(("+", ":")) for ref in refspecs):
        return finding(DENY, "N-05", "Force push and remote ref deletion are never allowed.")
    if any(is_protected_ref(ref) for ref in refspecs):
        return finding(DENY, "N-08", "Pushing directly to a protected branch is never allowed; open a pull request.")
    return finding(ASK, "C-HITL-01", "`git push` requires human approval.")


def commit_skips_hooks(args: List[str]) -> bool:
    index = 0
    while index < len(args):
        arg = args[index]
        letters = short_flags(arg)
        if arg == "--no-verify" or "n" in letters:
            return True
        index += 2 if letters and letters[-1] in GIT_COMMIT_VALUE_SHORT else 1
    return False


def check_git_local(subcommand: str, args: List[str]) -> Optional[Decision]:
    destructive = (
        (subcommand == "reset" and "--hard" in args)
        or (subcommand == "clean" and ("--force" in args or has_short_flag(args, "f")))
        or (subcommand == "branch" and has_short_flag(args, "D"))
        or (subcommand == "stash" and positional(args)[:1] in (["drop"], ["clear"]))
        or subcommand in ("filter-branch", "filter-repo")
        or (subcommand == "reflog" and positional(args)[:1] in (["expire"], ["delete"]))
        or (subcommand == "gc" and any(arg.startswith("--prune=now") for arg in args))
        or (subcommand == "update-ref" and "-d" in args)
    )
    if destructive:
        return finding(ASK, "C-HITL-03", f"Destructive `git {subcommand}` requires human approval.")
    return None


def changes_hooks_path(config_args: List[str]) -> bool:
    """True when `git config <config_args>` sets or unsets core.hooksPath; reading it is fine."""
    lowered = [arg.lower() for arg in config_args]
    if "core.hookspath" not in lowered:
        return False
    index = lowered.index("core.hookspath")
    before = set(lowered[:index])
    if before & GIT_CONFIG_READ_ACTIONS:
        return False
    return bool(before & GIT_CONFIG_UNSET_ACTIONS) or index + 1 < len(lowered)


def config_assignment(config_args: List[str]) -> Optional[Tuple[str, str]]:
    """Return (key, value) when `git config <config_args>` writes a value, else None."""
    if set(arg.lower() for arg in config_args) & (GIT_CONFIG_READ_ACTIONS | GIT_CONFIG_UNSET_ACTIONS):
        return None
    operands: List[str] = []
    skip_next = False
    for arg in config_args:
        if skip_next or arg.startswith("-"):
            skip_next = not skip_next and arg in GIT_CONFIG_VALUE_OPTIONS
            continue
        operands.append(arg)
    if operands[:1] and operands[0] in GIT_CONFIG_ACTION_WORDS:
        operands = operands[1:]
    return (operands[0], operands[1]) if len(operands) >= 2 else None


def runs_program(key: str, value: str) -> bool:
    """True when setting git config `key` to `value` makes git execute something."""
    lowered = key.lower()
    if not GIT_EXECUTING_KEY.match(lowered) or value.lower() in GIT_BENIGN_PROGRAM_VALUES:
        return False
    return not lowered.startswith("alias.") or value.lstrip().startswith("!")


def check_git_execution(subcommand: str, sub_args: List[str], configs: List[str], args: List[str]) -> Optional[Decision]:
    """N-06 for the `ext::` transport; C-HITL-10 for configuration that makes git run a program."""
    if any(arg.startswith("ext::") for arg in sub_args):
        return finding(DENY, "N-06", "The git `ext::` transport executes arbitrary commands and is never allowed.")
    assignments = [tuple(config.split("=", 1)) for config in configs if "=" in config]
    if subcommand == "config" and config_assignment(sub_args):
        assignments.append(config_assignment(sub_args))
    indirect = any(arg.startswith("--config-env") for arg in args)
    helper = any(arg.startswith(GIT_EXECUTING_OPTIONS) for arg in sub_args)
    if indirect or helper or any(runs_program(key, value) for key, value in assignments):
        return finding(ASK, "C-HITL-10", "Git configuration that executes a program requires human approval.")
    return None


def check_git(prog: str, args: List[str], tokens: List[str]) -> Optional[Decision]:
    if prog != "git":
        return None
    subcommand, sub_args, configs = git_subcommand(args)
    hooks_overridden = any(config.lower().startswith("core.hookspath") for config in configs)
    if hooks_overridden or (subcommand == "config" and changes_hooks_path(sub_args)):
        return finding(DENY, "N-04", "Overriding git hooks is never allowed.")
    if subcommand == "credential" and positional(sub_args)[:1] == ["fill"]:
        return finding(DENY, "N-01", "Printing stored git credentials is never allowed.")
    executes = check_git_execution(subcommand, sub_args, configs, args)
    if executes:
        return executes
    skips_hooks = "--no-verify" in sub_args or (subcommand == "commit" and commit_skips_hooks(sub_args))
    if skips_hooks and subcommand in ("commit", "push", "merge", "rebase", "am", "cherry-pick"):
        return finding(DENY, "N-04", "Bypassing git hooks with --no-verify is never allowed.")
    if subcommand == "push":
        return check_git_push(sub_args)
    return check_git_local(subcommand, sub_args)


def check_github_cli(prog: str, args: List[str], tokens: List[str]) -> Optional[Decision]:
    if prog != "gh":
        return None
    words = positional(args)
    pair = tuple(words[:2])
    if pair == ("pr", "merge") or (pair == ("pr", "review") and any(a in ("--approve", "-a") for a in args)):
        return finding(DENY, "N-08", "Merging or approving pull requests is a human decision.")
    if words[:1] == ["api"]:
        return check_github_api(words, args)
    widens_access = pair in (("ssh-key", "add"), ("gpg-key", "add"), ("auth", "login"), ("auth", "refresh"))
    if widens_access or tuple(words[:3]) == ("repo", "deploy-key", "add"):
        return finding(DENY, "N-08", "Adding keys or widening the agent's own GitHub access is never allowed.")
    lowered = [arg.lower() for arg in args]
    goes_public = bool({"--public", "--visibility=public"} & set(lowered)) or ("--visibility" in lowered and "public" in lowered)
    if words[:1] == ["repo"] and words[1:2] in (["create"], ["edit"]) and goes_public:
        return finding(DENY, "N-09", "Making a repository public is a human decision.")
    if pair == ("auth", "token") or (pair == ("auth", "status") and any(a in ("--show-token", "-t") for a in args)):
        return finding(DENY, "N-01", "Printing credentials is never allowed.")
    if pair == ("repo", "delete") or words[:1] in (["secret"], ["variable"]):
        return finding(DENY, "N-07", "Deleting repositories or managing secrets is never allowed.")
    if pair == ("gist", "create"):
        return finding(DENY, "N-09", "Uploading content to gists is never allowed.")
    if words[:1] == ["release"] and pair[1:] in (("create",), ("upload",), ("delete",), ("edit",)):
        return finding(DENY, "N-10", "Publishing releases is done by CI, never by an agent.")
    return None


def check_github_api(words: List[str], args: List[str]) -> Optional[Decision]:
    """`gh api` reaches the same endpoints as the subcommands denied above."""
    endpoint = " ".join(words[1:]).lower()
    joined = " ".join(args).lower()
    mutates = any(method in joined for method in ("put", "post", "patch", "delete")) or "-f" in args or "-F" in args
    approves = "/reviews" in endpoint and "approve" in joined
    if re.search(r"/pulls/\d+/merge|/merges\b", endpoint) or approves:
        return finding(DENY, "N-08", "Merging or approving pull requests is a human decision.")
    if mutates and re.search(r"/(protection|rulesets|collaborators|keys|hooks)\b", endpoint):
        return finding(DENY, "N-08", "Changing branch protection or repository access is never allowed.")
    if re.search(r"/(actions|codespaces|dependabot)/secrets\b", endpoint):
        return finding(DENY, "N-07", "Managing repository secrets is never allowed.")
    return None


def check_recursive_delete(prog: str, args: List[str], tokens: List[str]) -> Optional[Decision]:
    slash_recursive = any(a.lower() == "/s" for a in args)
    cmdlet_recursive = any(WINDOWS_RECURSE_FLAG.match(a) for a in args)
    if prog in WINDOWS_RECURSIVE_DELETERS and (slash_recursive or cmdlet_recursive):
        targets = [a for a in args if not a.startswith("-") and not WINDOWS_SWITCH.match(a)]
        if any(is_critical_target(t) for t in targets):
            return finding(DENY, "N-05", "Recursive deletion of a drive or system directory is never allowed.")
        return finding(ASK, "C-HITL-03", "Recursive deletion requires human approval.")
    if prog != "rm" or not ("--recursive" in args or has_short_flag(args, "r") or has_short_flag(args, "R")):
        return None
    if any(is_critical_target(target) for target in positional(args)):
        return finding(DENY, "N-05", "Recursive deletion of root, home, workspace, or system paths is never allowed.")
    return finding(ASK, "C-HITL-03", "Recursive deletion requires human approval.")


def check_system_destruction(prog: str, args: List[str], tokens: List[str]) -> Optional[Decision]:
    disk_tool = prog.startswith("mkfs") or prog in ("fdisk", "sfdisk", "parted", "wipefs")
    disk_tool = disk_tool or (prog == "dd" and any(a.startswith("of=/dev/") for a in args))
    disk_tool = disk_tool or (prog == "diskutil" and any(a.lower() in ("erasedisk", "partitiondisk", "zerodisk") for a in args))
    disk_tool = disk_tool or prog in WINDOWS_DESTROYERS
    disk_tool = disk_tool or (prog == "cipher" and any(a.lower().startswith("/w") for a in args))
    power = prog in ("shutdown", "reboot", "halt", "poweroff") or (prog == "init" and args[:1] in (["0"], ["6"]))
    recursive_mode = prog in ("chmod", "chown", "chgrp") and ("-R" in args or "--recursive" in args)
    if disk_tool or power or (recursive_mode and any(is_critical_target(t) for t in positional(args)[1:])):
        return finding(DENY, "N-05", f"Irreversible system operation `{prog}` is never allowed.")
    return None


def check_publish(prog: str, args: List[str], tokens: List[str]) -> Optional[Decision]:
    words = positional(args)
    published = prog in PUBLISH_SUBCOMMANDS and words[:1] and words[0] in PUBLISH_SUBCOMMANDS[prog]
    pairs = PUBLISH_SUBCOMMAND_PAIRS.get(prog, set())
    published = published or any(tuple(words[: len(pair)]) == pair for pair in pairs)
    if published:
        return finding(DENY, "N-10", "Publishing packages or managing registry credentials is done by CI, never by an agent.")
    return None


def check_exfiltration(prog: str, args: List[str], tokens: List[str]) -> Optional[Decision]:
    lowered = [token.lower() for token in tokens]
    tunnel = prog in TUNNEL_PROGRAMS or (prog == "cloudflared" and "tunnel" in lowered)
    tunnel = tunnel or (prog == "ssh" and any(a.startswith("-R") for a in args))
    reverse_shell = prog in ("nc", "ncat", "netcat") and any(a in ("-e", "-c", "--exec", "--sh-exec") for a in args)
    reverse_shell = reverse_shell or (prog == "socat" and any(m in t for t in lowered for m in ("exec:", "system:")))
    reverse_shell = reverse_shell or any("/dev/tcp/" in t or "/dev/udp/" in t for t in lowered)
    exfil_host = prog in NETWORK_TOOLS and any(EXFIL_HOST_PATTERN.search(token) for token in lowered)
    if tunnel or reverse_shell or exfil_host:
        return finding(DENY, "N-09", "Tunnels, reverse shells, and exfiltration endpoints are never allowed.")
    return None


AWS_TOKEN_SUBCOMMANDS = (
    "secretsmanager get-secret-value", "configure get", "configure export-credentials", "ecr get-login-password",
    "sts get-session-token", "codeartifact get-authorization-token",
)
SECRET_READ_SUBCOMMANDS = {  # program -> subcommand prefixes that print secrets or tokens
    "aws": AWS_TOKEN_SUBCOMMANDS,
    "gcloud": ("auth print-", "secrets versions access"),
    "az": ("keyvault secret show", "keyvault secret download", "account get-access-token"),
    "op": ("read", "item get", "inject", "run"), "vault": ("kv get", "read", "print token"),
    "pass": ("show",), "bw": ("get", "export"), "secret-tool": ("lookup", "search"),
    "security": ("find-generic-password", "find-internet-password", "dump-keychain", "export"),
    "doppler": ("secrets", "run"), "heroku": ("auth:token",), "flyctl": ("auth token",), "fly": ("auth token",),
    "glab": ("auth token",),
}


def reads_cloud_secret(prog: str, words: List[str], args: List[str]) -> bool:
    joined = " ".join(words[:3])
    if prog.startswith("docker-credential-"):
        return True
    if prog == "kubectl" and words[:2] == ["config", "view"]:
        return "--raw" in args or "--flatten" in args
    if prog == "kubectl":
        return words[:1] == ["get"] and len(words) > 1 and words[1].startswith("secret")
    if prog == "aws" and words[:1] == ["ssm"] and "--with-decryption" in args:
        return True
    return joined.startswith(SECRET_READ_SUBCOMMANDS.get(prog, ()))


def destroys_iac(prog: str, first: List[str], args: List[str]) -> bool:
    if prog in ("terraform", "tofu", "terragrunt"):
        unattended = any(a in ("-destroy", "-auto-approve", "--auto-approve") for a in args)
        return first == ["destroy"] or (first == ["apply"] and unattended)
    if prog == "pulumi" and first == ["up"]:
        return "--yes" in args or "-y" in args
    return prog in ("pulumi", "cdk") and first == ["destroy"]


def destroys_cloud_resources(prog: str, words: List[str], args: List[str]) -> bool:
    if prog == "kubectl":
        namespace = words[1:2] in (["namespace"], ["namespaces"], ["ns"])
        return words[:1] == ["delete"] and (namespace or any(a in ("--all", "-A", "--all-namespaces") for a in args))
    if prog == "aws":
        bucket = words[:2] == ["s3", "rb"] or (words[:2] == ["s3", "rm"] and "--recursive" in args)
        iam_grant = words[:1] == ["iam"] and any(w.startswith(IAM_GRANT_PREFIXES) for w in words[1:2])
        return bucket or iam_grant or any(w.startswith(CLOUD_DELETE_PREFIXES) for w in words)
    if prog in ("gcloud", "az"):
        return "delete" in words or "add-iam-policy-binding" in words or words[:3] == ["role", "assignment", "create"]
    return False


def destroys_data(prog: str, args: List[str]) -> bool:
    if prog == "redis-cli":
        return any(a.upper() in ("FLUSHALL", "FLUSHDB") for a in args)
    return prog == "dropdb" or (prog in SQL_CLIENTS and bool(DESTRUCTIVE_SQL.search(" ".join(args))))


def check_infrastructure(prog: str, args: List[str], tokens: List[str]) -> Optional[Decision]:
    words = positional(args)
    if reads_cloud_secret(prog, words, args):
        return finding(DENY, "N-01", "Reading secrets from secret managers or printing tokens is never allowed.")
    if destroys_iac(prog, words[:1], args) or destroys_cloud_resources(prog, words, args) or destroys_data(prog, args):
        return finding(DENY, "N-07", "Destroying infrastructure or data, or granting IAM permissions, is never allowed.")
    return None


def mount_specs(args: List[str]) -> List[str]:
    specs = []
    for option, value in zip(args, args[1:] + [""]):
        if option in ("-v", "--volume", "--mount"):
            specs.append(value)
        elif option.startswith(("--volume=", "--mount=")):
            specs.append(option.split("=", 1)[1])
    return specs


def mounts_host_root(args: List[str]) -> bool:
    for spec in mount_specs(args):
        source = spec.split(":", 1)[0].replace("source=", "").replace("src=", "")
        if source == "/" or "docker.sock" in spec:
            return True
    return False


def check_container_escape(prog: str, args: List[str], tokens: List[str]) -> Optional[Decision]:
    if prog not in ("docker", "podman", "nerdctl") or positional(args)[:1] not in (["run"], ["create"]):
        return None
    lowered = [a.lower() for a in args]
    pairs = zip(lowered, lowered[1:] + [""])
    escape = any(a in CONTAINER_ESCAPE_FLAGS for a in lowered)
    escape = escape or any(CONTAINER_HOST_NAMESPACE_OPTIONS.get(a) == n for a, n in pairs) or mounts_host_root(args)
    if escape:
        return finding(DENY, "N-11", "Privileged containers and host mounts are never allowed.")
    return None


def check_nested_scripts(prog: str, args: List[str], depth: int) -> Optional[Decision]:
    script = ""
    if prog in SHELLS:
        flag_index = next((i for i, a in enumerate(args) if "c" in short_flags(a)), None)
        if flag_index is not None and flag_index + 1 < len(args):
            script = args[flag_index + 1]
    elif prog == "eval":
        script = " ".join(args)
    if prog in POWERSHELL_PROGRAMS and any(POWERSHELL_ENCODED_FLAG.match(arg) for arg in args):
        return finding(DENY, "N-06", "Running an encoded PowerShell command is never allowed.")
    if not script:
        return check_inline_code(prog, args, depth)
    if DOWNLOADER_SUBSTITUTION.search(script):
        return finding(DENY, "N-06", "Executing downloaded code is never allowed.")
    return evaluate_command(script, depth + 1)


def check_inline_code(prog: str, args: List[str], depth: int) -> Optional[Decision]:
    """Inspect string literals of `python -c` / `node -e` code that shells out."""
    family = "python" if PYTHON_PROGRAM.match(prog) else prog
    flags = INLINE_CODE_FLAGS.get(family, set())
    code = next((value for flag, value in zip(args, args[1:]) if flag in flags), "")
    if not code or not INLINE_EXEC_MARKER.search(code):
        return None
    literals = [single or double for single, double in STRING_LITERAL.findall(code)]
    return strongest([evaluate_command(literal, depth + 1) for literal in literals])


SEGMENT_CHECKS: Tuple[Callable[[str, List[str], List[str]], Optional[Decision]], ...] = (
    check_privilege, check_agent_bypass, check_git, check_github_cli, check_recursive_delete,
    check_system_destruction, check_publish, check_exfiltration, check_infrastructure, check_container_escape,
    check_agent_cli,
)


def evaluate_segment(segment: Segment, depth: int) -> Optional[Decision]:
    words = strip_wrappers(segment.words)
    literal = bool(words) and program_name(words[0]) in LITERAL_PRINTERS
    environment = None if literal else check_environment(segment.words)
    if not words:
        targets = segment.redirect_targets
        return strongest([environment, check_secret_access("", [], targets), check_host_files("", [], targets)])
    prog, args = python_module(program_name(words[0]), words[1:])
    tokens = words + segment.redirect_targets
    results: List[Optional[Decision]] = [check_privilege(prog, args, tokens), check_agent_bypass(prog, args, tokens)]
    results.extend([environment, check_host_files(prog, args, segment.redirect_targets)])
    results.append(check_secret_access(prog, args, segment.redirect_targets))
    results.extend(check(prog, args, tokens) for check in SEGMENT_CHECKS[2:])
    results.append(check_nested_scripts(prog, args, depth))
    return strongest(results)


def check_remote_execution(segments: Sequence[Segment]) -> Optional[Decision]:
    """Deny downloader output piped or substituted into an interpreter."""
    untrusted_in_pipeline = False
    previous_program = ""
    for segment in segments:
        words = strip_privilege(strip_wrappers(segment.words))
        prog = program_name(words[0]) if words else ""
        if segment.op_before != "pipe":
            untrusted_in_pipeline = False
        piped_into_interpreter = segment.op_before == "pipe" and untrusted_in_pipeline and runs_stdin(prog, words[1:])
        substituted = segment.op_before == "substitution" and prog in DOWNLOADERS and previous_program in INTERPRETERS
        if piped_into_interpreter or substituted:
            return finding(DENY, "N-06", "Executing downloaded or decoded code is never allowed.")
        untrusted_in_pipeline = untrusted_in_pipeline or prog in REMOTE_SOURCES or decodes_payload(prog, words[1:])
        previous_program = prog
    return None


def runs_stdin(prog: str, args: Sequence[str]) -> bool:
    """True when an interpreter executes its standard input (`| sh`, `| bash -s`, `| python3 -`)."""
    if prog not in INTERPRETERS:
        return False
    operands = positional(args)
    return not operands or operands[0] in ("-", "/dev/stdin") or "-s" in args


def decodes_payload(prog: str, args: Sequence[str]) -> bool:
    """True for `base64 -d`, `xxd -r`, `openssl enc -d`: an opaque payload becoming text."""
    if prog not in DECODERS:
        return False
    return not DECODERS[prog] or any(arg in DECODERS[prog] for arg in args)


# ----------------------------------------------------------------------------
# Public entry points
# ----------------------------------------------------------------------------
def evaluate_command(command: str, depth: int = 0) -> Optional[Decision]:
    """Evaluate a shell command line against the N-tier and C-HITL rules."""
    if depth > MAX_NESTING_DEPTH or not command.strip():
        return None
    command, shell_bodies = extract_heredocs(canonical_command(command))
    segments = split_segments(tokenize(command))
    results: List[Optional[Decision]] = [check_remote_execution(segments)]
    results.extend(evaluate_segment(segment, depth) for segment in segments)
    results.extend(evaluate_command(body, depth + 1) for body in shell_bodies)
    return strongest(results)


def evaluate_file_write(path: str, content: str) -> Optional[Decision]:
    """Evaluate a file path (and the text written to it) for N-01, N-03, N-04, N-12, and C-HITL."""
    normalized = normalize_path(path)
    if is_secret_path(path):
        return finding(DENY, "N-01", "Reading or writing secret files is never allowed.")
    if is_startup_file(path):
        return finding(DENY, "N-03", "Writing shell startup or autostart files is never allowed.")
    if is_audit_trail(path):
        return finding(DENY, "N-12", "Rewriting session transcripts or logs is never allowed.")
    agent_config = bool(AGENT_CONFIG_PATH.search(normalized))
    if agent_config and any(p.search(content) for p in GUARDRAIL_DISABLING_SETTINGS):
        return finding(DENY, "N-04", "Writing settings that disable guardrails or repoint the agent is never allowed.")
    if MCP_CONFIG_PATH.search(normalized) or (agent_config and MCP_SERVER_DEFINITION.search(content)):
        return finding(ASK, "C-HITL-07", "Adding or changing MCP servers requires human approval.")
    if GIT_INTERNAL_EXEC_PATH.search(normalized):
        return finding(ASK, "C-HITL-10", "Editing git configuration or hooks directly requires human approval.")
    return None


def written_text(tool_input: Dict[str, object]) -> str:
    texts = [tool_input.get(key) for key in ("content", "new_string", "newString", "code", "new_source", "text")]
    edits = tool_input.get("edits")
    if isinstance(edits, list):
        texts.extend(edit.get("new_string") for edit in edits if isinstance(edit, dict))
    return "\n".join(text for text in texts if isinstance(text, str))


def evaluate_event(event: Dict[str, object]) -> Optional[Decision]:
    tool_input = event.get("tool_input")
    if not isinstance(tool_input, dict):
        return None
    command = tool_input.get("command")
    if isinstance(command, str):
        return evaluate_command(command)
    path_keys = ("file_path", "filePath", "notebook_path", "path")
    path = next((tool_input[key] for key in path_keys if isinstance(tool_input.get(key), str)), None)
    return evaluate_file_write(path, written_text(tool_input)) if path else None


def main(stdin: TextIO = sys.stdin, stdout: TextIO = sys.stdout) -> int:
    try:
        event = json.load(stdin)
    except (ValueError, OSError):
        return 0
    result = evaluate_event(event) if isinstance(event, dict) else None
    if result:
        decision, reason = result
        output = {"hookEventName": "PreToolUse", "permissionDecision": decision, "permissionDecisionReason": reason}
        json.dump({"hookSpecificOutput": output}, stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
