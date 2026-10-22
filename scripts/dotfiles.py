#!/usr/bin/env python3
"""
scripts/dotfiles.py
==============================================================================
Cross-Platform Declarative Dotfiles Manager & Health Diagnostics Engine
==============================================================================
Manages transactional installation (symlink / copy with action-journal backup),
drift status inspection, rollback, static validation, and environment health
checks across Windows 11, WSL2 (Ubuntu), Linux, and macOS.

Zero mandatory external dependencies: runs purely on Python 3.10+ stdlib
(uses tomllib on Python 3.11+, tomli fallback, and PyYAML when available).
"""

from __future__ import annotations

import argparse
import datetime
import filecmp
import json
import os
import platform
import re
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MANIFEST = REPO_ROOT / "config" / "manifest.json"

SUPPORTED_PLATFORMS = ("windows", "wsl", "linux", "macos")
ITEM_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+(?:\.[a-zA-Z0-9_-]+)+$")

# High-confidence secret patterns forbidden inside tracked repository files
SECRET_PATTERNS: List[Tuple[str, re.Pattern[str]]] = [
    ("GitHub Personal/OAuth Token", re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{36,255}\b")),
    ("GitHub Fine-Grained PAT", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{22,255}\b")),
    ("Anthropic API Key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,255}\b")),
    ("OpenAI API Key", re.compile(r"\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{32,255}\b")),
    ("Google Cloud / Gemini API Key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("AWS Access Key ID", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("Slack Token", re.compile(r"\bxox[baprs]-[0-9A-Za-z-]{10,255}\b")),
    ("HuggingFace Token", re.compile(r"\bhf_[A-Za-z0-9]{34,255}\b")),
    ("Private Key PEM Header", re.compile(r"-----BEGIN (?:RSA |OPENSSH |EC |DSA |PGP )?PRIVATE KEY(?: BLOCK)?-----")),
]

# Hardcoded local user paths that break fork/machine portability
PORTABILITY_PATTERNS: List[Tuple[str, re.Pattern[str]]] = [
    ("Hardcoded Windows User Path", re.compile(r"[Cc]:[/\\][Uu]sers[/\\](?:sun_flat|sunfl)[/\\]")),
    ("Hardcoded URL-Encoded Windows User Path", re.compile(r"file:///c%3A/Users/(?:sun_flat|sunfl)/", re.IGNORECASE)),
    ("Hardcoded Local Workspace Drive Path", re.compile(r"\b[Vv]:[/\\]repos[/\\]sun\.flat\.yamada", re.IGNORECASE)),
    ("Hardcoded POSIX User Home Path", re.compile(r"/(?:home|Users)/(?:sun_flat|sunfl)/")),
]


def detect_os() -> str:
    """Detect current operating system platform ('windows', 'wsl', 'linux', 'macos')."""
    sys_name = platform.system().lower()
    if sys_name == "windows":
        return "windows"
    if sys_name == "darwin":
        return "macos"
    if sys_name == "linux":
        try:
            proc_ver = Path("/proc/version").read_text(encoding="utf-8", errors="ignore").lower()
            if "microsoft" in proc_ver or "wsl" in proc_ver:
                return "wsl"
        except OSError:
            pass
        return "linux"
    return "linux"


def load_manifest(manifest_path: Path = DEFAULT_MANIFEST) -> Dict[str, Any]:
    """Load and parse config/manifest.json."""
    if not manifest_path.exists():
        raise FileNotFoundError(f"Manifest file not found: {manifest_path}")
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or "items" not in data or not isinstance(data["items"], list):
        raise ValueError("Invalid manifest structure: root object must contain an 'items' list.")
    return data


def get_windows_documents_dir(target_home: Path) -> Path:
    """
    Resolve Windows 'Documents' folder when operating on the real user home,
    supporting Known Folder redirection (e.g., V:\\home\\sun_flat\\documents).
    When a custom target_home is used (e.g. unit tests / CI), returns target_home / 'Documents'.
    """
    try:
        is_real_home = target_home.resolve() == Path.home().resolve()
    except OSError:
        is_real_home = False

    if is_real_home:
        env_docs = os.environ.get("DOTFILES_DOCUMENTS_DIR")
        if env_docs:
            return Path(env_docs).resolve()
        if os.name == "nt":
            try:
                import winreg  # type: ignore
                with winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER,
                    r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders",
                ) as key:
                    val, _ = winreg.QueryValueEx(key, "Personal")
                    if isinstance(val, str) and val.strip():
                        return Path(os.path.expandvars(val)).resolve()
            except OSError:
                pass
    return target_home.resolve() / "Documents"


def resolve_target_path(raw_target: str, target_home: Path, os_name: Optional[str] = None) -> Path:
    """
    Resolve '~/' path templates safely relative to target_home.
    Prevents path traversal ('..') and handles Windows Documents folder redirection.
    """
    if not isinstance(raw_target, str) or not (raw_target.startswith("~/") or raw_target.startswith("~\\")):
        raise ValueError(f"Target path must start with '~/': {raw_target!r}")

    rel_str = raw_target[2:].replace("\\", "/").strip("/")
    if not rel_str:
        raise ValueError(f"Target path cannot point to home root itself: {raw_target!r}")

    rel_path = Path(rel_str)
    if ".." in rel_path.parts:
        raise ValueError(f"Path traversal ('..') is forbidden in target path: {raw_target!r}")

    base_home = target_home.resolve()
    if os_name == "windows" and (rel_str == "Documents" or rel_str.startswith("Documents/")):
        docs_root = get_windows_documents_dir(base_home)
        sub_str = rel_str[len("Documents") :].lstrip("/")
        resolved = docs_root / Path(sub_str) if sub_str else docs_root
        if not resolved.resolve().is_relative_to(docs_root.resolve()) if not resolved.is_symlink() else False:
            raise ValueError(f"Target path escapes Documents root: {raw_target!r}")
        return resolved

    candidate = base_home / rel_path
    check_parent = candidate.parent.resolve()
    if not check_parent.is_relative_to(base_home):
        raise ValueError(f"Target path '{raw_target}' escapes target home '{base_home}'")
    return candidate


def resolve_items_for_profile(
    manifest: Dict[str, Any],
    profile: str,
    os_name: str,
) -> List[Dict[str, Any]]:
    """Filter manifest items matching the requested profile and target OS."""
    profiles_map: Dict[str, List[str]] = manifest.get("profiles", {})
    if profile in ("all", "full"):
        allowed_profiles: Optional[set[str]] = None
    elif profile in profiles_map:
        allowed_profiles = set(profiles_map[profile])
    else:
        allowed_profiles = {profile}

    selected: List[Dict[str, Any]] = []
    for item in manifest.get("items", []):
        item_profile = item.get("profile", "")
        if allowed_profiles is not None and item_profile not in allowed_profiles:
            continue
        targets = item.get("targets", {})
        if os_name in targets:
            selected.append(item)
    return selected


def inspect_item_state(source_path: Path, target_path: Path) -> str:
    """
    Determine synchronization state between source_path and target_path.
    Returns one of: 'LINKED', 'IDENTICAL', 'DRIFTED', 'MISSING', 'SOURCE_MISSING'.
    """
    if not source_path.exists():
        return "SOURCE_MISSING"
    if not target_path.exists() and not target_path.is_symlink():
        return "MISSING"

    if target_path.is_symlink():
        if not target_path.exists():
            return "DRIFTED"  # Broken symlink
        try:
            if os.path.samefile(str(source_path), str(target_path)):
                return "LINKED"
        except OSError:
            pass
        return "DRIFTED"

    if target_path.is_file():
        try:
            if filecmp.cmp(str(source_path), str(target_path), shallow=False):
                return "IDENTICAL"
        except OSError:
            pass
    return "DRIFTED"


def cmd_status(
    manifest: Dict[str, Any],
    os_name: str,
    profile: str,
    target_home: Path,
    as_json: bool = False,
) -> int:
    """Report current status of all managed dotfiles."""
    items = resolve_items_for_profile(manifest, profile=profile, os_name=os_name)
    records: List[Dict[str, str]] = []

    for item in items:
        src = REPO_ROOT / item["source"]
        dst = resolve_target_path(item["targets"][os_name], target_home, os_name=os_name)
        state = inspect_item_state(src, dst)
        records.append(
            {
                "id": item["id"],
                "profile": item["profile"],
                "state": state,
                "source": item["source"],
                "target": str(dst),
            }
        )

    if as_json:
        print(json.dumps({"os": os_name, "profile": profile, "items": records}, indent=2))
        return 0

    print(f"[*] Dotfiles Status (OS: {os_name} | Profile: {profile} | Home: {target_home})")
    print("-" * 88)
    print(f"{'ID':<28} {'PROFILE':<10} {'STATE':<14} {'TARGET'}")
    print("-" * 88)
    for rec in records:
        print(f"{rec['id']:<28} {rec['profile']:<10} {rec['state']:<14} {rec['target']}")
    print("-" * 88)
    return 0


def try_create_symlink(source_path: Path, target_path: Path) -> bool:
    """
    Atomically create or replace a symbolic link using a temporary sibling link.
    Never deletes an existing target file if symlink creation is denied by OS permissions.
    """
    tmp_link = target_path.with_name(f".{target_path.name}.dotfiles-tmp-{os.getpid()}")
    try:
        if tmp_link.exists() or tmp_link.is_symlink():
            tmp_link.unlink()
        tmp_link.symlink_to(source_path)
        os.replace(str(tmp_link), str(target_path))
        return True
    except OSError:
        try:
            if tmp_link.exists() or tmp_link.is_symlink():
                tmp_link.unlink()
        except OSError:
            pass
        return False


def cmd_install(
    manifest: Dict[str, Any],
    os_name: str,
    profile: str,
    method: str,
    target_home: Path,
    backup_root: Optional[Path],
    dry_run: bool = False,
) -> int:
    """Install/apply dotfiles transactionally with action-journal backup of changes."""
    items = resolve_items_for_profile(manifest, profile=profile, os_name=os_name)
    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_dir = (backup_root or (target_home / ".dotfiles-backup" / timestamp)).resolve()
    journal_records: List[Dict[str, Any]] = []

    # Pre-flight validation before modifying any file on disk
    resolved_plan: List[Tuple[Dict[str, Any], Path, Path, str]] = []
    for item in items:
        item_id = item["id"]
        if not ITEM_ID_PATTERN.match(item_id):
            print(f"  [!] Invalid item ID '{item_id}'", file=sys.stderr)
            return 1
        src = (REPO_ROOT / item["source"]).resolve()
        if not src.is_relative_to(REPO_ROOT.resolve()) or not src.is_file():
            print(f"  [!] {item_id}: Source missing or outside repository: {src}", file=sys.stderr)
            return 1
        try:
            dst = resolve_target_path(item["targets"][os_name], target_home, os_name=os_name)
        except ValueError as exc:
            print(f"  [!] {item_id}: {exc}", file=sys.stderr)
            return 1
        if dst.exists() and not dst.is_symlink() and dst.is_dir():
            print(f"  [!] {item_id}: Target path is an existing directory, refusing to overwrite: {dst}", file=sys.stderr)
            return 1
        state = inspect_item_state(src, dst)
        resolved_plan.append((item, src, dst, state))

    mode_str = "DRY-RUN" if dry_run else f"APPLY ({method})"
    print(f"[*] Installing {len(resolved_plan)} dotfile item(s) [{mode_str}] for OS '{os_name}'...")

    applied_count = 0
    skipped_count = 0

    try:
        for item, src, dst, state in resolved_plan:
            item_id = item["id"]

            # 1. Check if already in desired state
            if (state == "LINKED" and method in ("auto", "symlink")) or (state == "IDENTICAL" and method == "copy"):
                print(f"  [=] {item_id}: Already up to date ({state})")
                skipped_count += 1
                continue

            # 2. In 'auto' mode, if target is already IDENTICAL (copied previously due to no symlink privilege),
            # try upgrading to symlink silently without creating a redundant backup; if symlink is disallowed, skip!
            if state == "IDENTICAL" and method == "auto":
                if dry_run:
                    print(f"  [=] {item_id}: Already up to date (IDENTICAL)")
                    skipped_count += 1
                    continue
                if try_create_symlink(src, dst):
                    print(f"  [+] {item_id}: Upgraded identical copy to symlink -> {dst}")
                    applied_count += 1
                else:
                    print(f"  [=] {item_id}: Already up to date (IDENTICAL)")
                    skipped_count += 1
                continue

            if dry_run:
                action = "Backup & Update" if state == "DRIFTED" else "Install"
                print(f"  [DRY-RUN] {item_id}: Would {action} -> {dst}")
                applied_count += 1
                continue

            dst.parent.mkdir(parents=True, exist_ok=True)

            # 3. Prepare rollback journal entry (only back up content if DRIFTED)
            pending_record: Optional[Dict[str, Any]] = None
            if state == "MISSING":
                pending_record = {
                    "id": item_id,
                    "action": "remove",
                    "original_path": str(dst),
                }
            elif state == "DRIFTED":
                if dst.is_symlink():
                    link_target = str(os.readlink(dst))
                    pending_record = {
                        "id": item_id,
                        "action": "restore_symlink",
                        "original_path": str(dst),
                        "link_target": link_target,
                    }
                elif dst.exists():
                    backup_file = backup_dir / item_id.replace(".", "_") / dst.name
                    backup_file.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(str(dst), str(backup_file))
                    pending_record = {
                        "id": item_id,
                        "action": "restore_file",
                        "original_path": str(dst),
                        "backup_path": str(backup_file),
                    }
                    print(f"  [B] {item_id}: Backed up existing file to {backup_file}")

            # 4. Perform installation
            if method == "symlink":
                if not try_create_symlink(src, dst):
                    print(
                        f"  [!] {item_id}: Failed to create symlink at {dst} (Enable Windows Developer Mode or use --method auto/copy)",
                        file=sys.stderr,
                    )
                    return 1
                print(f"  [+] {item_id}: Linked -> {dst}")
            elif method == "copy":
                if dst.is_symlink():
                    dst.unlink()
                shutil.copy2(str(src), str(dst))
                print(f"  [+] {item_id}: Copied -> {dst}")
            else:  # auto
                if try_create_symlink(src, dst):
                    print(f"  [+] {item_id}: Linked -> {dst}")
                else:
                    if dst.is_symlink():
                        dst.unlink()
                    shutil.copy2(str(src), str(dst))
                    print(f"  [+] {item_id}: Copied (symlink fallback) -> {dst}")

            if pending_record is not None:
                journal_records.append(pending_record)
            applied_count += 1
    finally:
        if journal_records and not dry_run:
            backup_dir.mkdir(parents=True, exist_ok=True)
            manifest_out = backup_dir / "restore-manifest.json"
            manifest_out.write_text(
                json.dumps({"timestamp": timestamp, "os": os_name, "backups": journal_records}, indent=2),
                encoding="utf-8",
            )
            print(f"[*] Saved rollback manifest to: {manifest_out}")

    print(f"[+] Completed: {applied_count} applied, {skipped_count} already up-to-date.")
    return 0


def cmd_rollback(backup_dir: Path, dry_run: bool = False) -> int:
    """Restore or remove files from an action-journal backup directory created during install."""
    resolved_backup_dir = backup_dir.resolve()
    manifest_file = resolved_backup_dir / "restore-manifest.json"
    if not manifest_file.exists():
        print(f"[!] Restore manifest not found: {manifest_file}", file=sys.stderr)
        return 1

    data = json.loads(manifest_file.read_text(encoding="utf-8"))
    backups = data.get("backups", [])
    print(f"[*] Rolling back {len(backups)} item(s) from {resolved_backup_dir}...")

    for entry in backups:
        action = entry.get("action", "restore_file")
        orig = Path(entry["original_path"])

        if action == "remove":
            if dry_run:
                print(f"  [DRY-RUN] Would remove newly installed item {orig}")
            else:
                if orig.exists() or orig.is_symlink():
                    orig.unlink()
                print(f"  [-] Removed newly installed item {orig}")
        elif action == "restore_symlink":
            link_target = entry.get("link_target", "")
            if dry_run:
                print(f"  [DRY-RUN] Would restore symlink {orig} -> {link_target}")
            else:
                orig.parent.mkdir(parents=True, exist_ok=True)
                if orig.exists() or orig.is_symlink():
                    orig.unlink()
                orig.symlink_to(Path(link_target))
                print(f"  [+] Restored symlink {orig} -> {link_target}")
        else:  # restore_file
            bkp = Path(entry["backup_path"]).resolve()
            if not bkp.is_relative_to(resolved_backup_dir):
                print(f"  [!] Refusing to restore backup path outside backup directory: {bkp}", file=sys.stderr)
                return 1
            if not bkp.is_file():
                print(f"  [!] Missing backup file: {bkp}", file=sys.stderr)
                return 1
            if dry_run:
                print(f"  [DRY-RUN] Would restore {bkp} -> {orig}")
            else:
                orig.parent.mkdir(parents=True, exist_ok=True)
                if orig.is_symlink():
                    orig.unlink()
                shutil.copy2(str(bkp), str(orig))
                print(f"  [+] Restored {orig}")

    return 0


def validate_toml_text(content: str, path: Path) -> List[str]:
    """Validate TOML syntax using tomllib (3.11+), tomli fallback, or structural parser."""
    errors: List[str] = []
    toml_loader = None
    try:
        import tomllib  # type: ignore
        toml_loader = tomllib.loads
    except ImportError:
        try:
            import tomli  # type: ignore
            toml_loader = tomli.loads
        except ImportError:
            toml_loader = None

    if toml_loader is not None:
        try:
            toml_loader(content)
        except Exception as exc:
            errors.append(f"{path}: TOML syntax error: {exc}")
        return errors

    # Fallback structural validation for Python 3.10 without tomli installed
    in_multiline = False
    bracket_depth = 0
    for lineno, raw_line in enumerate(content.splitlines(), start=1):
        line = raw_line.strip()
        if '"""' in line or "'''" in line:
            delim = '"""' if '"""' in line else "'''"
            if line.count(delim) % 2 == 1:
                in_multiline = not in_multiline
            continue
        if in_multiline or not line or line.startswith("#"):
            continue
        if line.startswith("[") and bracket_depth == 0:
            if not (line.endswith("]") or "#" in line):
                errors.append(f"{path}:{lineno}: Unclosed TOML section header: {line}")
            continue
        bracket_depth += line.count("[") - line.count("]")
        if bracket_depth == 0 and "=" not in line and not line.endswith("]"):
            errors.append(f"{path}:{lineno}: Invalid TOML statement (missing '='): {line}")
    if in_multiline:
        errors.append(f"{path}: Unclosed multiline string in TOML file")
    if bracket_depth != 0:
        errors.append(f"{path}: Unbalanced brackets in TOML file")
    return errors


def validate_yaml_text(content: str, path: Path) -> List[str]:
    """Validate YAML syntax using PyYAML when installed."""
    errors: List[str] = []
    try:
        import yaml  # type: ignore
        yaml.safe_load(content)
    except ImportError:
        pass
    except Exception as exc:
        errors.append(f"{path}: YAML syntax error: {exc}")
    return errors


def validate_lua_balance(content: str, path: Path) -> List[str]:
    """Perform structural and domain-specific checks on Lua configuration files."""
    errors: List[str] = []
    if "return config" not in content and "return M" not in content:
        errors.append(f"{path}: Lua module should return a configuration table ('return config' or 'return M').")
    if "SOLID_RIGHT_ARROW" in content:
        defined = re.search(r"^\s*local\s+SOLID_RIGHT_ARROW\s*=", content, re.MULTILINE)
        if not defined:
            errors.append(f"{path}: 'SOLID_RIGHT_ARROW' is referenced but not defined as a local variable.")
    return errors


def cmd_validate(repo_root: Path = REPO_ROOT) -> int:
    """Validate manifest integrity, config syntax, LF line endings, portability, and secret hygiene."""
    errors: List[str] = []
    resolved_root = repo_root.resolve()
    manifest_path = resolved_root / "config" / "manifest.json"

    try:
        manifest = load_manifest(manifest_path)
    except Exception as exc:
        print(f"[X] Failed to load manifest: {exc}", file=sys.stderr)
        return 1

    items = manifest.get("items", [])
    seen_ids: set[str] = set()

    for item in items:
        item_id = item.get("id", "")
        if not item_id or not ITEM_ID_PATTERN.match(str(item_id)):
            errors.append(f"Invalid or missing manifest item id: {item_id!r}")
            continue
        if item_id in seen_ids:
            errors.append(f"Duplicate manifest item id: '{item_id}'")
        seen_ids.add(item_id)

        rel_source = item.get("source", "")
        src_path = (resolved_root / rel_source).resolve()
        if not src_path.is_relative_to(resolved_root):
            errors.append(f"Manifest item '{item_id}' source escapes repository root: '{rel_source}'")
        elif not src_path.is_file():
            errors.append(f"Manifest item '{item_id}' points to missing file: '{rel_source}'")

        targets = item.get("targets", {})
        if not isinstance(targets, dict) or not targets:
            errors.append(f"Manifest item '{item_id}' has no valid targets")
        else:
            for plat, tpath in targets.items():
                if plat not in SUPPORTED_PLATFORMS:
                    errors.append(f"Manifest item '{item_id}' uses unsupported OS key '{plat}'")
                try:
                    resolve_target_path(str(tpath), resolved_root / "_dummy_home", os_name=plat)
                except ValueError as exc:
                    errors.append(f"Manifest item '{item_id}' has invalid target '{tpath}': {exc}")

    # Enforce LF line endings on POSIX shell scripts and hooks
    lf_required_globs = [
        "install.sh",
        "config/shell/*",
        "config/wsl/wsl.conf",
        ".githooks/*",
    ]
    for pattern in lf_required_globs:
        for fpath in resolved_root.glob(pattern):
            if fpath.is_file():
                raw_bytes = fpath.read_bytes()
                if b"\r\n" in raw_bytes:
                    errors.append(f"{fpath.relative_to(resolved_root)}: Contains CRLF (\\r\\n); POSIX scripts/hooks require LF")

    # Scan configuration and governance directories for syntax, portability, and secrets
    scan_roots = [
        resolved_root / "config",
        resolved_root / "packages",
        resolved_root / ".claude",
        resolved_root / ".codex",
        resolved_root / ".cursor",
        resolved_root / ".gemini",
        resolved_root / ".vscode",
    ]
    scanned_files = 0
    for sroot in scan_roots:
        if not sroot.exists():
            continue
        for fpath in sroot.rglob("*"):
            if not fpath.is_file() or "__pycache__" in fpath.parts:
                continue
            scanned_files += 1
            rel = fpath.relative_to(resolved_root)
            try:
                text = fpath.read_text(encoding="utf-8")
            except Exception as exc:
                errors.append(f"{rel}: UTF-8 decode error: {exc}")
                continue

            suffix = fpath.suffix.lower()
            if suffix == ".json":
                try:
                    json.loads(text)
                except Exception as exc:
                    errors.append(f"{rel}: JSON syntax error: {exc}")
            elif suffix == ".toml":
                errors.extend(validate_toml_text(text, rel))
            elif suffix in (".yml", ".yaml", ".winget"):
                errors.extend(validate_yaml_text(text, rel))
            elif suffix == ".lua":
                errors.extend(validate_lua_balance(text, rel))

            for label, secret_re in SECRET_PATTERNS:
                if secret_re.search(text):
                    errors.append(f"{rel}: Potential secret detected ({label})")

            for label, port_re in PORTABILITY_PATTERNS:
                if port_re.search(text):
                    errors.append(f"{rel}: Non-portable path detected ({label})")

    if errors:
        print(f"[X] Dotfiles validation failed with {len(errors)} error(s):", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    print(
        f"[+] Dotfiles validation passed: {len(items)} manifest items and {scanned_files} configuration/governance files verified."
    )
    return 0


def cmd_doctor(as_json: bool = False) -> int:
    """Run non-destructive environment health diagnostics."""
    os_name = detect_os()
    checks: List[Dict[str, Any]] = []

    essential_tools = ["git", "python"]
    recommended_tools = ["gh", "pwsh", "wezterm", "code", "starship", "zoxide", "rg", "fd", "bat", "eza", "fzf", "uv", "mise"]
    ai_tools = ["claude", "gemini", "codex"]

    for tool in essential_tools:
        path = (shutil.which("python") or shutil.which("python3")) if tool == "python" else shutil.which(tool)
        checks.append({"category": "essential", "name": tool, "installed": bool(path), "path": path or ""})

    for tool in recommended_tools:
        path = shutil.which(tool)
        checks.append({"category": "recommended", "name": tool, "installed": bool(path), "path": path or ""})

    for tool in ai_tools:
        path = shutil.which(tool)
        checks.append({"category": "ai-agent", "name": tool, "installed": bool(path), "path": path or ""})

    if as_json:
        print(json.dumps({"os": os_name, "checks": checks}, indent=2))
        return 0

    print(f"[*] Dotfiles Environment Doctor (Detected OS: {os_name})")
    print("-" * 78)
    print(f"{'CATEGORY':<15} {'TOOL':<14} {'STATUS':<12} {'LOCATION'}")
    print("-" * 78)
    for chk in checks:
        status_label = "INSTALLED" if chk["installed"] else "MISSING"
        print(f"{chk['category']:<15} {chk['name']:<14} {status_label:<12} {chk['path']}")
    print("-" * 78)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Declarative Cross-Platform Dotfiles Manager (sun-flat-yamada/dotfiles)"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # status
    p_status = sub.add_parser("status", help="Inspect current synchronization status of dotfiles")
    p_status.add_argument("--os", choices=SUPPORTED_PLATFORMS, default=detect_os(), help="Target OS platform")
    p_status.add_argument("--profile", default="full", help="Profile filter (full, core, git, shell, terminal, editor, ai, wsl, packages)")
    p_status.add_argument("--target-home", type=Path, default=Path.home(), help="Override target home directory")
    p_status.add_argument("--json", action="store_true", help="Output status in JSON format")

    # install
    p_install = sub.add_parser("install", help="Install or update dotfiles idempotently with automatic backup")
    p_install.add_argument("--os", choices=SUPPORTED_PLATFORMS, default=detect_os(), help="Target OS platform")
    p_install.add_argument("--profile", default="full", help="Profile to install (default: full)")
    p_install.add_argument("--method", choices=("auto", "symlink", "copy"), default="auto", help="Deployment method (default: auto)")
    p_install.add_argument("--target-home", type=Path, default=Path.home(), help="Override target home directory")
    p_install.add_argument("--backup-dir", type=Path, default=None, help="Custom directory for backups")
    p_install.add_argument("--dry-run", action="store_true", help="Preview changes without modifying disk")

    # rollback
    p_rollback = sub.add_parser("rollback", help="Restore dotfiles from a previous backup snapshot")
    p_rollback.add_argument("--backup-dir", type=Path, required=True, help="Backup directory containing restore-manifest.json")
    p_rollback.add_argument("--dry-run", action="store_true", help="Preview rollback without modifying disk")

    # validate
    sub.add_parser("validate", help="Validate manifest, config syntax, portability, and zero-secret rules")

    # doctor
    p_doctor = sub.add_parser("doctor", help="Run environment and tool diagnostics")
    p_doctor.add_argument("--json", action="store_true", help="Output diagnostics in JSON format")

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "validate":
        return cmd_validate(REPO_ROOT)
    if args.command == "doctor":
        return cmd_doctor(as_json=args.json)
    if args.command == "rollback":
        return cmd_rollback(backup_dir=args.backup_dir.resolve(), dry_run=args.dry_run)

    manifest = load_manifest(DEFAULT_MANIFEST)
    if args.command == "status":
        return cmd_status(
            manifest=manifest,
            os_name=args.os,
            profile=args.profile,
            target_home=args.target_home.resolve(),
            as_json=args.json,
        )
    if args.command == "install":
        return cmd_install(
            manifest=manifest,
            os_name=args.os,
            profile=args.profile,
            method=args.method,
            target_home=args.target_home.resolve(),
            backup_root=args.backup_dir.resolve() if args.backup_dir else None,
            dry_run=args.dry_run,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
