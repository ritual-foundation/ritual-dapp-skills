#!/usr/bin/env python3
"""Sync Ritual dApp Skills into agent-specific skill paths.

The README advertises that skills can be synced into Hermes Agent via this
script (and dropped directly into Claude Code, Cursor, and OpenClaw paths).
This utility makes that one command.

Supported harnesses:
  - claude-code  -> <target>/.claude/skills/ritual-dapp-skills/
  - cursor       -> <target>/.cursor/rules/ritual-dapp-skills/
  - openclaw     -> <target>/.openclaw/skills/ritual-dapp-skills/
  - hermes       -> <target>/skills/blockchain/ritual/

Default target is the user's home directory. Override with --target.

By default this is a non-destructive copy: SKILL.md and any sibling assets
are read from this repo and written into the harness-specific location,
preserving subdirectory structure. Existing files are overwritten only when
their content differs. Re-running is idempotent.

Frontmatter transforms are intentionally NOT applied: the YAML frontmatter
(`name`, `description`, optional `user_invocable`) is the same across the
harnesses we support today. A pluggable transform hook is reserved for
future harnesses with divergent frontmatter requirements.

Usage:
    # Sync all skills to Claude Code (default harness, default target)
    python3 scripts/skills_sync.py

    # Sync to Hermes Agent
    python3 scripts/skills_sync.py --harness hermes

    # Sync to Hermes with a custom target root
    python3 scripts/skills_sync.py --harness hermes --target ~/dev/hermes

    # Sync only the meta skills (filter by prefix)
    python3 scripts/skills_sync.py --filter 'ritual-meta-*'

    # Preview what would be written without touching disk
    python3 scripts/skills_sync.py --harness hermes --dry-run

    # Remove a previous sync (only files this script would have written)
    python3 scripts/skills_sync.py --harness hermes --uninstall
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

# ---------------------------------------------------------------------------
# Harness registry
# ---------------------------------------------------------------------------

# Relative subpath inside <target> where this harness expects skill bundles.
# Add a new harness by appending to this dict; the rest of the script picks
# it up automatically (CLI choices, target resolution, README docs).
HARNESS_PATHS: dict[str, str] = {
    "claude-code": ".claude/skills/ritual-dapp-skills",
    "cursor": ".cursor/rules/ritual-dapp-skills",
    "openclaw": ".openclaw/skills/ritual-dapp-skills",
    "hermes": "skills/blockchain/ritual",
}

# Hook for future per-harness frontmatter transforms. Current harnesses all
# accept the upstream SKILL.md frontmatter unmodified, so identity is the
# safe default. To add a transform: implement `def _transform_<harness>(text)`
# below and register it here.
FRONTMATTER_TRANSFORMS: dict[str, Callable[[str], str]] = {
    "claude-code": lambda s: s,
    "cursor": lambda s: s,
    "openclaw": lambda s: s,
    "hermes": lambda s: s,
}

DEFAULT_HARNESS = "claude-code"

# Subdirectories under the repo root to sync. Order matters only for
# readable dry-run output.
SYNC_DIRS: tuple[str, ...] = ("skills", "agents", "examples", "templates")


# ---------------------------------------------------------------------------
# Filesystem helpers
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FileOp:
    """A single sync action. `kind` is one of write / skip / remove."""

    kind: str
    src: Path | None
    root: Path
    dst: Path
    reason: str


def _repo_root() -> Path:
    """Resolve the repo root from this script's location.

    `scripts/skills_sync.py` lives one level below the repo root, mirroring
    the layout of the existing `scripts/pull_contracts.py`.
    """
    return Path(__file__).resolve().parent.parent


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _bytes_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _iter_source_files(root: Path, sync_dirs: Iterable[str]) -> Iterable[Path]:
    for sub in sync_dirs:
        d = root / sub
        if not d.exists():
            continue
        for p in sorted(d.rglob("*")):
            if p.is_file() and not _is_ignored(p):
                yield p


def _is_ignored(path: Path) -> bool:
    """Skip files that should never be synced into agent skill paths."""
    parts = set(path.parts)
    if any(seg.startswith(".") for seg in parts if seg not in {".", ".."}):
        return True
    if "__pycache__" in parts or "node_modules" in parts:
        return True
    if path.suffix in {".pyc", ".pyo"}:
        return True
    return False


def _filter_matches(rel: Path, patterns: list[str]) -> bool:
    if not patterns:
        return True
    posix = rel.as_posix()
    # Pattern matches against the top-level skill/agent/example/template name,
    # OR against the full relative posix path. This lets the user pass either
    # `ritual-dapp-llm` or `skills/ritual-dapp-llm/SKILL.md`.
    top_level = rel.parts[1] if len(rel.parts) > 1 else rel.parts[0]
    return any(
        fnmatch.fnmatch(posix, pat) or fnmatch.fnmatch(top_level, pat)
        for pat in patterns
    )


# ---------------------------------------------------------------------------
# Planning
# ---------------------------------------------------------------------------


def plan_sync(
    repo: Path,
    target_root: Path,
    harness: str,
    patterns: list[str],
) -> list[FileOp]:
    """Build the list of file operations needed to sync, without executing."""
    if harness not in HARNESS_PATHS:
        raise ValueError(f"unknown harness: {harness!r}")

    harness_root = target_root / HARNESS_PATHS[harness]
    transform = FRONTMATTER_TRANSFORMS[harness]
    ops: list[FileOp] = []

    for src in _iter_source_files(repo, SYNC_DIRS):
        rel = src.relative_to(repo)
        if not _filter_matches(rel, patterns):
            continue
        dst = harness_root / rel
        new_bytes = _maybe_transform(src, transform)
        if dst.exists() and _file_hash(dst) == _bytes_hash(new_bytes):
            ops.append(FileOp("skip", src, harness_root, dst, "identical content"))
        else:
            reason = "new file" if not dst.exists() else "content differs"
            ops.append(FileOp("write", src, harness_root, dst, reason))

    return ops


def plan_uninstall(
    repo: Path,
    target_root: Path,
    harness: str,
) -> list[FileOp]:
    """List files under the harness root that this script's source tree
    knows about, plus empty directories left behind."""
    if harness not in HARNESS_PATHS:
        raise ValueError(f"unknown harness: {harness!r}")

    harness_root = target_root / HARNESS_PATHS[harness]
    ops: list[FileOp] = []

    if not harness_root.exists():
        return ops

    # Files this script could have written: those whose relative path under
    # harness_root exists under repo as well. This prevents removing user
    # additions placed under the same directory.
    known_rel: set[Path] = set()
    for src in _iter_source_files(repo, SYNC_DIRS):
        known_rel.add(src.relative_to(repo))

    for dst in sorted(harness_root.rglob("*")):
        if not dst.is_file():
            continue
        rel = dst.relative_to(harness_root)
        if rel in known_rel:
            ops.append(FileOp("remove", None, harness_root, dst, "known-source file"))

    return ops


def _maybe_transform(src: Path, transform: Callable[[str], str]) -> bytes:
    """Apply harness-specific transform if the file is a SKILL.md.

    For everything else (assets, JSON, .py, templates), bytes pass through
    untouched.
    """
    if src.name == "SKILL.md":
        text = src.read_text(encoding="utf-8")
        return transform(text).encode("utf-8")
    return src.read_bytes()


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------


def apply_ops(ops: list[FileOp], harness: str) -> tuple[int, int]:
    """Execute a planned op list. Returns (written, removed)."""
    transform = FRONTMATTER_TRANSFORMS[harness]
    written = 0
    removed = 0

    for op in ops:
        if op.kind == "write":
            assert op.src is not None
            op.dst.parent.mkdir(parents=True, exist_ok=True)
            op.dst.write_bytes(_maybe_transform(op.src, transform))
            written += 1
        elif op.kind == "remove":
            op.dst.unlink()
            # Walk up and remove any now-empty parent dirs, but never remove
            # the harness root itself.
            parent = op.dst.parent
            while parent != op.root and parent.is_dir() and not any(parent.iterdir()):
                try:
                    parent.rmdir()
                except OSError:
                    break
                parent = parent.parent
            removed += 1
        # `skip` is a no-op.

    return written, removed


def print_plan(
    all_ops: list[FileOp],
    visible_ops: list[FileOp],
    target_root: Path,
    harness: str,
) -> None:
    """Print the plan. Summary counts reflect *all* ops; only `visible_ops`
    are listed line by line (caller controls verbosity).
    """
    counts = {"write": 0, "skip": 0, "remove": 0}
    for op in all_ops:
        counts[op.kind] += 1

    print(f"harness:     {harness}")
    print(f"target root: {target_root}")
    print(f"sync path:   {target_root / HARNESS_PATHS[harness]}")
    print()
    print(
        f"plan:  write={counts['write']}  "
        f"skip={counts['skip']}  remove={counts['remove']}"
    )
    print()

    for op in visible_ops:
        if op.kind == "write":
            marker = "+"
        elif op.kind == "remove":
            marker = "-"
        else:
            marker = "="
        rel = op.dst
        try:
            rel = op.dst.relative_to(target_root)
        except ValueError:
            pass
        print(f"  {marker} {rel}  ({op.reason})")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--harness",
        choices=sorted(HARNESS_PATHS),
        default=DEFAULT_HARNESS,
        help=f"target harness (default: {DEFAULT_HARNESS})",
    )
    parser.add_argument(
        "--target",
        type=Path,
        default=Path.home(),
        help="root under which the harness-specific subpath is created "
        "(default: $HOME)",
    )
    parser.add_argument(
        "--filter",
        action="append",
        default=[],
        metavar="PATTERN",
        help="only sync skills/agents/examples matching this fnmatch "
        "pattern; may be passed multiple times (e.g. 'ritual-meta-*' or "
        "'skills/ritual-dapp-llm/*')",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print planned writes without touching disk",
    )
    parser.add_argument(
        "--uninstall",
        action="store_true",
        help="remove previously synced files (only files known to this repo)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="include skipped files in the plan output",
    )
    args = parser.parse_args(argv)

    repo = _repo_root()
    target = args.target.expanduser().resolve()

    if args.uninstall:
        ops = plan_uninstall(repo, target, args.harness)
        action = "uninstall"
    else:
        ops = plan_sync(repo, target, args.harness, args.filter)
        action = "sync"

    # Filter skips out of the printed lines unless --verbose. Summary still
    # reflects all ops.
    visible_ops = ops if args.verbose else [o for o in ops if o.kind != "skip"]
    print_plan(ops, visible_ops, target, args.harness)

    if args.dry_run:
        print()
        print("dry-run: no changes written")
        return 0

    if not ops or all(o.kind == "skip" for o in ops):
        print()
        print(f"{action}: nothing to do")
        return 0

    written, removed = apply_ops(ops, args.harness)
    print()
    print(f"{action}: wrote {written} file(s), removed {removed} file(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
