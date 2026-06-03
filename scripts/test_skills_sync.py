#!/usr/bin/env python3
"""Tests for scripts/skills_sync.py.

Uses stdlib unittest + tmp_path fixtures; no third-party dependencies.

Run with:
    python3 scripts/test_skills_sync.py
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

# Import target. The script sits next to this test file.
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import skills_sync as ss  # noqa: E402


def _make_fixture_repo(root: Path) -> None:
    """Build a minimal fixture mirroring the real repo layout."""
    (root / "scripts").mkdir()
    (root / "scripts" / "skills_sync.py").write_text("# placeholder\n")

    # Two skills, one with sibling assets.
    (root / "skills" / "ritual-dapp-llm").mkdir(parents=True)
    (root / "skills" / "ritual-dapp-llm" / "SKILL.md").write_text(
        "---\nname: ritual-dapp-llm\ndescription: LLM patterns.\n---\n\nbody\n"
    )
    (root / "skills" / "ritual-dapp-llm" / "examples.md").write_text(
        "# Examples\n"
    )

    (root / "skills" / "ritual-meta-bootstrap").mkdir(parents=True)
    (root / "skills" / "ritual-meta-bootstrap" / "SKILL.md").write_text(
        "---\nname: ritual-meta-bootstrap\ndescription: Meta.\n---\n\nbody\n"
    )

    # One agent.
    (root / "agents").mkdir()
    (root / "agents" / "ritual-dapp-builder.md").write_text("# Builder\n")

    # One template.
    (root / "templates" / "starter").mkdir(parents=True)
    (root / "templates" / "starter" / "index.js").write_text("'use strict';\n")

    # Noise that must be ignored.
    (root / "skills" / "ritual-dapp-llm" / ".DS_Store").write_text("noise")
    (root / "skills" / "ritual-dapp-llm" / "__pycache__").mkdir()
    (root / "skills" / "ritual-dapp-llm" / "__pycache__" / "x.pyc").write_text(
        "noise"
    )


class TestSkillsSync(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="ritual_sync_test_")
        self.tmp = Path(self._tmp)
        self.repo = self.tmp / "repo"
        self.target = self.tmp / "target"
        self.repo.mkdir()
        self.target.mkdir()
        _make_fixture_repo(self.repo)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    # ------------------------------------------------------------------ tests

    def test_harnesses_registered_consistently(self) -> None:
        self.assertEqual(
            set(ss.HARNESS_PATHS),
            set(ss.FRONTMATTER_TRANSFORMS),
            "every harness needs a frontmatter transform entry",
        )

    def test_plan_lists_all_real_files_for_default_harness(self) -> None:
        ops = ss.plan_sync(self.repo, self.target, "claude-code", patterns=[])
        writes = [o for o in ops if o.kind == "write"]
        self.assertEqual(
            len(writes),
            5,  # 2 SKILL.md + 1 examples.md + 1 agent + 1 template
            f"unexpected plan: {[str(o.dst) for o in writes]}",
        )

    def test_ignored_files_excluded(self) -> None:
        ops = ss.plan_sync(self.repo, self.target, "hermes", patterns=[])
        for op in ops:
            self.assertNotIn(".DS_Store", op.dst.name)
            self.assertNotIn("__pycache__", op.dst.parts)
            self.assertFalse(op.dst.name.endswith(".pyc"))

    def test_apply_then_replan_is_idempotent(self) -> None:
        ops1 = ss.plan_sync(self.repo, self.target, "hermes", patterns=[])
        ss.apply_ops(ops1, "hermes")
        ops2 = ss.plan_sync(self.repo, self.target, "hermes", patterns=[])
        for op in ops2:
            self.assertEqual(
                op.kind, "skip", f"unexpected non-skip on re-run: {op}"
            )

    def test_modified_file_re_synced(self) -> None:
        ss.apply_ops(
            ss.plan_sync(self.repo, self.target, "hermes", []), "hermes"
        )
        skill = self.repo / "skills" / "ritual-meta-bootstrap" / "SKILL.md"
        skill.write_text(skill.read_text() + "\nEDITED\n")
        ops = ss.plan_sync(self.repo, self.target, "hermes", patterns=[])
        writes = [o for o in ops if o.kind == "write"]
        self.assertEqual(len(writes), 1)
        self.assertTrue(writes[0].dst.name == "SKILL.md")

    def test_harness_path_layout(self) -> None:
        ops = ss.plan_sync(self.repo, self.target, "hermes", patterns=[])
        ss.apply_ops(ops, "hermes")
        expected = self.target / "skills" / "blockchain" / "ritual"
        self.assertTrue(expected.is_dir())
        # And no Claude-Code path was created.
        self.assertFalse((self.target / ".claude").exists())

    def test_filter_matches_top_level_skill_name(self) -> None:
        ops = ss.plan_sync(
            self.repo, self.target, "hermes", patterns=["ritual-meta-*"]
        )
        # Only the meta skill should match. Agents/templates use different
        # top-level names and should be excluded.
        for op in ops:
            self.assertIn("ritual-meta-bootstrap", op.dst.parts)

    def test_filter_matches_relative_glob(self) -> None:
        ops = ss.plan_sync(
            self.repo, self.target, "hermes", patterns=["agents/*"]
        )
        self.assertEqual(len(ops), 1)
        self.assertEqual(ops[0].dst.name, "ritual-dapp-builder.md")

    def test_uninstall_removes_only_known_files(self) -> None:
        # Sync, then add a user-authored file in the harness root.
        ss.apply_ops(
            ss.plan_sync(self.repo, self.target, "hermes", []), "hermes"
        )
        user_file = (
            self.target / "skills" / "blockchain" / "ritual" / "USER_NOTES.md"
        )
        user_file.write_text("my notes\n")

        ops = ss.plan_uninstall(self.repo, self.target, "hermes")
        ss.apply_ops(ops, "hermes")

        self.assertTrue(user_file.exists(), "user file must be preserved")
        # All known sources gone.
        self.assertFalse(
            (
                self.target
                / "skills"
                / "blockchain"
                / "ritual"
                / "skills"
                / "ritual-meta-bootstrap"
                / "SKILL.md"
            ).exists()
        )

    def test_uninstall_preserves_harness_root_directory(self) -> None:
        ss.apply_ops(
            ss.plan_sync(self.repo, self.target, "hermes", []), "hermes"
        )
        harness_root = self.target / "skills" / "blockchain" / "ritual"

        ops = ss.plan_uninstall(self.repo, self.target, "hermes")
        ss.apply_ops(ops, "hermes")

        self.assertTrue(harness_root.is_dir())
        self.assertEqual(list(harness_root.iterdir()), [])

    def test_uninstall_on_missing_target_noop(self) -> None:
        ops = ss.plan_uninstall(self.repo, self.tmp / "nonexistent", "hermes")
        self.assertEqual(ops, [])

    def test_unknown_harness_raises(self) -> None:
        with self.assertRaises(ValueError):
            ss.plan_sync(self.repo, self.target, "made-up", patterns=[])

    def test_dry_run_writes_nothing(self) -> None:
        from unittest.mock import patch

        with patch.object(ss, "_repo_root", return_value=self.repo):
            rc = ss.main(
                [
                    "--harness",
                    "hermes",
                    "--target",
                    str(self.target),
                    "--dry-run",
                ]
            )
        self.assertEqual(rc, 0)
        self.assertFalse((self.target / "skills" / "blockchain").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
