#!/usr/bin/env python3
"""Verify SVG assets are safe, valid, and renderable.

Usage:
  python3 scripts/verify_svgs.py
  python3 scripts/verify_svgs.py --assets-dir assets --readme README.md
  python3 scripts/verify_svgs.py --check-remote --repo ritual-foundation/ritual-dapp-skills --ref not/a-fix-at-all
"""

from __future__ import annotations

import base64
import argparse
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

FORBIDDEN_TAGS = {"script", "foreignObject", "iframe", "object", "embed"}
CTRL_ALLOW = {9, 10, 13}  # tab, LF, CR


def _strip_ns(tag: str) -> str:
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def check_utf8_and_controls(path: Path) -> list[str]:
    errors: list[str] = []
    raw = path.read_bytes()

    try:
        raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        errors.append(f"{path}: not valid UTF-8 ({exc})")
        return errors

    bad_ctrl = [(i, b) for i, b in enumerate(raw) if b < 32 and b not in CTRL_ALLOW]
    if bad_ctrl:
        sample = ", ".join(f"offset {i}: 0x{b:02x}" for i, b in bad_ctrl[:5])
        errors.append(f"{path}: contains forbidden control bytes ({sample})")
    return errors


def check_xml_structure(path: Path) -> list[str]:
    errors: list[str] = []
    content = path.read_text(encoding="utf-8")

    try:
        root = ET.fromstring(content)
    except ET.ParseError as exc:
        errors.append(f"{path}: XML parse error ({exc})")
        return errors

    errors.extend(check_svg_tree(root, str(path)))
    return errors


def check_svg_tree(root: ET.Element, label: str) -> list[str]:
    errors: list[str] = []

    if _strip_ns(root.tag) != "svg":
        errors.append(f"{label}: root element is not <svg>")

    for node in root.iter():
        tag = _strip_ns(node.tag)
        if tag in FORBIDDEN_TAGS:
            errors.append(f"{label}: forbidden tag <{tag}> found")

        for attr_name, attr_value in node.attrib.items():
            attr = _strip_ns(attr_name).lower()
            if attr not in {"href"}:
                continue

            v = attr_value.strip().lower()
            if v.startswith(("javascript:", "file:", "http://", "https://", "//")):
                errors.append(f"{label}: unsafe href attribute value '{attr_value}'")
    return errors


def parse_readme_svg_links(readme: Path) -> list[str]:
    content = readme.read_text(encoding="utf-8")
    # Markdown image syntax only.
    pattern = re.compile(r"!\[[^\]]*]\((assets/[A-Za-z0-9._/\-]+\.svg)\)")
    return pattern.findall(content)


def check_readme_links(repo_root: Path, readme: Path, svg_files: list[Path]) -> list[str]:
    errors: list[str] = []
    links = parse_readme_svg_links(readme)

    if not links:
        errors.append(f"{readme}: no markdown SVG image links found")
        return errors

    for rel in links:
        target = repo_root / rel
        if not target.exists():
            errors.append(f"{readme}: linked SVG does not exist ({rel})")

    svg_rel_set = {str(p.relative_to(repo_root)) for p in svg_files}
    link_set = set(links)
    missing_in_readme = sorted(svg_rel_set - link_set)
    if missing_in_readme:
        errors.append(
            f"{readme}: SVG files not referenced in README: {', '.join(missing_in_readme)}"
        )
    return errors


def fetch_remote_content(repo: str, ref: str, rel_path: str) -> bytes | None:
    cmd = [
        "gh",
        "api",
        f"repos/{repo}/contents/{rel_path}?ref={ref}",
        "--jq",
        ".content",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        return None
    try:
        return base64.b64decode(proc.stdout.strip())
    except Exception:
        return None


def check_remote_svg(repo: str, ref: str, rel_path: str) -> list[str]:
    errors: list[str] = []
    label = f"remote:{ref}:{rel_path}"
    raw = fetch_remote_content(repo, ref, rel_path)
    if raw is None:
        return [f"{label}: missing/unreadable via gh api"]

    try:
        content = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        return [f"{label}: not valid UTF-8 ({exc})"]

    bad_ctrl = [(i, b) for i, b in enumerate(raw) if b < 32 and b not in CTRL_ALLOW]
    if bad_ctrl:
        sample = ", ".join(f"offset {i}: 0x{b:02x}" for i, b in bad_ctrl[:5])
        errors.append(f"{label}: contains forbidden control bytes ({sample})")

    try:
        root = ET.fromstring(content)
        errors.extend(check_svg_tree(root, label))
    except ET.ParseError as exc:
        errors.append(f"{label}: XML parse error ({exc})")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify SVG assets and README links")
    parser.add_argument("--assets-dir", default="assets", help="SVG directory")
    parser.add_argument("--readme", default="README.md", help="README path")
    parser.add_argument(
        "--check-remote",
        action="store_true",
        help="Also verify files exist on GitHub via gh api",
    )
    parser.add_argument(
        "--repo",
        default="ritual-foundation/ritual-dapp-skills",
        help="GitHub repo for remote checks",
    )
    parser.add_argument(
        "--ref",
        default=None,
        help="Git ref for remote checks (defaults to current branch)",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent.parent
    assets_dir = (repo_root / args.assets_dir).resolve()
    readme = (repo_root / args.readme).resolve()

    if not assets_dir.exists():
        print(f"ERROR: assets directory not found: {assets_dir}")
        return 1
    if not readme.exists():
        print(f"ERROR: README not found: {readme}")
        return 1

    svg_files = sorted(assets_dir.glob("*.svg"))
    if not svg_files:
        print(f"ERROR: no SVG files found in {assets_dir}")
        return 1

    errors: list[str] = []

    for svg in svg_files:
        errors.extend(check_utf8_and_controls(svg))
        errors.extend(check_xml_structure(svg))

    errors.extend(check_readme_links(repo_root, readme, svg_files))

    if args.check_remote:
        ref = args.ref
        if not ref:
            branch_proc = subprocess.run(
                ["git", "branch", "--show-current"],
                cwd=repo_root,
                capture_output=True,
                text=True,
            )
            ref = branch_proc.stdout.strip() if branch_proc.returncode == 0 else None
        if not ref:
            errors.append("remote check requested but no git ref could be determined")
        else:
            for svg in svg_files:
                rel = str(svg.relative_to(repo_root))
                errors.extend(check_remote_svg(args.repo, ref, rel))

    if errors:
        print("SVG verification FAILED:")
        for err in errors:
            print(f" - {err}")
        return 1

    print("SVG verification PASSED:")
    print(f" - Checked {len(svg_files)} SVG file(s) in {assets_dir}")
    print(" - UTF-8 decode, control bytes, XML parse, and forbidden tags passed")
    print(" - README SVG links are valid and complete")
    if args.check_remote:
        print(" - Remote file existence check passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
