#!/usr/bin/env python3
"""
tests/test-dotfiles.py
==============================================================================
Automated Unit & Integration Tests for scripts/dotfiles.py and config/*
==============================================================================
Covers manifest integrity, OS/profile filtering, idempotent installation
(copy, symlink, and auto fallback), broken symlink detection, drift backup,
action-journal rollback (including removal of newly created files), dry-run
safety, JSON CLI output schemas, and secret/portability/traversal scanners.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
DOTFILES_SCRIPT = REPO_ROOT / "scripts" / "dotfiles.py"

spec = importlib.util.spec_from_file_location("dotfiles_engine", DOTFILES_SCRIPT)
assert spec is not None and spec.loader is not None
dotfiles_engine = importlib.util.module_from_spec(spec)
sys.modules["dotfiles_engine"] = dotfiles_engine
spec.loader.exec_module(dotfiles_engine)


class TestDotfilesEngine(unittest.TestCase):
    def setUp(self) -> None:
        self.manifest = dotfiles_engine.load_manifest()

    def test_validate_repository_passes(self) -> None:
        """Full repository validation (manifest, JSON/TOML/YAML/Lua syntax, LF endings, zero secrets) must pass."""
        rc = dotfiles_engine.cmd_validate(REPO_ROOT)
        self.assertEqual(rc, 0)

    def test_profiles_and_platforms_resolution(self) -> None:
        """Every supported OS must resolve a non-empty set of items for 'core' and 'full' profiles."""
        for os_name in dotfiles_engine.SUPPORTED_PLATFORMS:
            core_items = dotfiles_engine.resolve_items_for_profile(self.manifest, "core", os_name)
            full_items = dotfiles_engine.resolve_items_for_profile(self.manifest, "full", os_name)
            self.assertGreater(len(core_items), 0, f"Expected core items for {os_name}")
            self.assertGreaterEqual(len(full_items), len(core_items), f"Expected full >= core for {os_name}")

    def test_dry_run_makes_no_disk_changes(self) -> None:
        """Running install with dry_run=True must not create any files in target_home."""
        with tempfile.TemporaryDirectory() as tmp:
            target_home = Path(tmp) / "home"
            target_home.mkdir(parents=True, exist_ok=True)
            rc = dotfiles_engine.cmd_install(
                manifest=self.manifest,
                os_name="linux",
                profile="core",
                method="copy",
                target_home=target_home,
                backup_root=None,
                dry_run=True,
            )
            self.assertEqual(rc, 0)
            self.assertEqual(list(target_home.iterdir()), [])

    def test_install_idempotency_drift_backup_and_rollback(self) -> None:
        """Verify install -> idempotent re-run -> drift -> backup on re-install -> rollback."""
        with tempfile.TemporaryDirectory() as tmp:
            target_home = Path(tmp) / "home"
            backup_dir_initial = Path(tmp) / "backup-initial"
            backup_dir_drift = Path(tmp) / "backup-drift"
            target_home.mkdir(parents=True, exist_ok=True)

            # 1. Initial install into empty home (records 'remove' actions in journal)
            rc1 = dotfiles_engine.cmd_install(
                manifest=self.manifest,
                os_name="windows",
                profile="git",
                method="copy",
                target_home=target_home,
                backup_root=backup_dir_initial,
                dry_run=False,
            )
            self.assertEqual(rc1, 0)

            gitconfig_target = target_home / ".gitconfig"
            self.assertTrue(gitconfig_target.is_file())
            original_content = gitconfig_target.read_text(encoding="utf-8")

            # 2. Check state is IDENTICAL
            git_src = REPO_ROOT / "config" / "git" / ".gitconfig"
            self.assertEqual(
                dotfiles_engine.inspect_item_state(git_src, gitconfig_target),
                "IDENTICAL",
            )

            # 3. Introduce drift
            drifted_content = original_content + "\n# custom local drift test\n"
            gitconfig_target.write_text(drifted_content, encoding="utf-8")
            self.assertEqual(
                dotfiles_engine.inspect_item_state(git_src, gitconfig_target),
                "DRIFTED",
            )

            # 4. Re-install: must back up drifted file and restore canonical version
            rc2 = dotfiles_engine.cmd_install(
                manifest=self.manifest,
                os_name="windows",
                profile="git",
                method="copy",
                target_home=target_home,
                backup_root=backup_dir_drift,
                dry_run=False,
            )
            self.assertEqual(rc2, 0)
            self.assertEqual(gitconfig_target.read_text(encoding="utf-8"), original_content)

            restore_manifest = backup_dir_drift / "restore-manifest.json"
            self.assertTrue(restore_manifest.is_file())
            manifest_data = json.loads(restore_manifest.read_text(encoding="utf-8"))
            self.assertEqual(len(manifest_data["backups"]), 1)
            self.assertEqual(manifest_data["backups"][0]["action"], "restore_file")

            # 5. Rollback drift backup: must restore drifted content
            rc3 = dotfiles_engine.cmd_rollback(backup_dir=backup_dir_drift, dry_run=False)
            self.assertEqual(rc3, 0)
            self.assertEqual(gitconfig_target.read_text(encoding="utf-8"), drifted_content)

            # 6. Rollback initial install: must remove newly created files
            rc4 = dotfiles_engine.cmd_rollback(backup_dir=backup_dir_initial, dry_run=False)
            self.assertEqual(rc4, 0)
            self.assertFalse(gitconfig_target.exists())

    def test_auto_mode_idempotency_when_symlink_unavailable(self) -> None:
        """When method='auto' falls back to copy, a second run must treat IDENTICAL files as up-to-date without creating a backup."""
        with tempfile.TemporaryDirectory() as tmp:
            target_home = Path(tmp) / "home"
            backup_dir_1 = Path(tmp) / "backup1"
            backup_dir_2 = Path(tmp) / "backup2"
            target_home.mkdir(parents=True, exist_ok=True)

            with mock.patch.object(dotfiles_engine, "try_create_symlink", return_value=False):
                rc1 = dotfiles_engine.cmd_install(
                    manifest=self.manifest,
                    os_name="linux",
                    profile="git",
                    method="auto",
                    target_home=target_home,
                    backup_root=backup_dir_1,
                    dry_run=False,
                )
                self.assertEqual(rc1, 0)
                self.assertTrue((target_home / ".gitconfig").is_file())

                # Second run in auto mode with symlinks unavailable must skip all IDENTICAL files and NOT create backup_dir_2
                rc2 = dotfiles_engine.cmd_install(
                    manifest=self.manifest,
                    os_name="linux",
                    profile="git",
                    method="auto",
                    target_home=target_home,
                    backup_root=backup_dir_2,
                    dry_run=False,
                )
                self.assertEqual(rc2, 0)
                self.assertFalse(
                    (backup_dir_2 / "restore-manifest.json").exists(),
                    "Expected no redundant backup on second auto-mode run when files are IDENTICAL",
                )

    def test_status_and_doctor_json_output(self) -> None:
        """CLI status --json and doctor --json must emit valid, schema-compliant JSON."""
        with tempfile.TemporaryDirectory() as tmp:
            buf_status = io.StringIO()
            with contextlib.redirect_stdout(buf_status):
                rc_s = dotfiles_engine.main(["status", "--os", "linux", "--profile", "core", "--target-home", tmp, "--json"])
            self.assertEqual(rc_s, 0)
            status_payload = json.loads(buf_status.getvalue())
            self.assertEqual(status_payload["os"], "linux")
            self.assertEqual(status_payload["profile"], "core")
            self.assertGreater(len(status_payload["items"]), 0)

            buf_doc = io.StringIO()
            with contextlib.redirect_stdout(buf_doc):
                rc_d = dotfiles_engine.main(["doctor", "--json"])
            self.assertEqual(rc_d, 0)
            doc_payload = json.loads(buf_doc.getvalue())
            self.assertIn("os", doc_payload)
            self.assertGreater(len(doc_payload["checks"]), 0)

    def test_path_traversal_and_invalid_targets_rejected(self) -> None:
        """resolve_target_path must reject paths without '~/' or containing '..' traversal."""
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            with self.assertRaises(ValueError):
                dotfiles_engine.resolve_target_path("/etc/passwd", home)
            with self.assertRaises(ValueError):
                dotfiles_engine.resolve_target_path("~/../../etc/passwd", home)
            with self.assertRaises(ValueError):
                dotfiles_engine.resolve_target_path("~/", home)

    def test_secret_and_portability_detectors(self) -> None:
        """Secret and hardcoded path regexes must detect synthetic violations."""
        fake_gh_token = "ghp_" + ("A1b2C3d4E5" * 4)
        fake_openai_proj = "sk-proj-" + ("A1b2C3d4_E5-" * 3)
        self.assertTrue(any(p.search(fake_gh_token) for _, p in dotfiles_engine.SECRET_PATTERNS))
        self.assertTrue(any(p.search(fake_openai_proj) for _, p in dotfiles_engine.SECRET_PATTERNS))

        hardcoded_user = r"C:\Users\sun_flat\.vscode\extensions"
        hardcoded_drive = r"V:\repos\sun.flat.yamada\dotfiles"
        self.assertTrue(any(p.search(hardcoded_user) for _, p in dotfiles_engine.PORTABILITY_PATTERNS))
        self.assertTrue(any(p.search(hardcoded_drive) for _, p in dotfiles_engine.PORTABILITY_PATTERNS))


if __name__ == "__main__":
    unittest.main()
