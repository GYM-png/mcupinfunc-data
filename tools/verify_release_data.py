#!/usr/bin/env python3
"""Verify generated McuPinFunc remote release data before publishing."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Iterable


def _read_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _duplicates(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    duplicates: list[str] = []
    for value in values:
        key = value.lower()
        if key in seen and value not in duplicates:
            duplicates.append(value)
            continue
        seen.add(key)
    return duplicates


def _verify_index(root: Path) -> list[str]:
    errors: list[str] = []
    index_path = root / "index.json"
    if not index_path.is_file():
        return [f"missing {index_path}"]

    payload = _read_json(index_path)
    if not isinstance(payload, dict):
        return ["index.json must contain an object"]

    chips = payload.get("chips")
    if not isinstance(chips, list):
        return ["index.json chips must be an array"]

    for chip in chips:
        if not isinstance(chip, dict):
            errors.append("index chip entry must be an object")
            continue

        chip_id = str(chip.get("id") or "<unknown>")
        packages = chip.get("packages")
        if isinstance(packages, list):
            for package_name in _duplicates([str(package_name) for package_name in packages]):
                errors.append(f"index chip {chip_id} has duplicate package {package_name}")

        source_files = chip.get("sourceFiles")
        if isinstance(source_files, list):
            for source_file in source_files:
                if not isinstance(source_file, dict):
                    continue
                url = str(source_file.get("url") or "")
                if "/staging/" in url:
                    package_name = source_file.get("package") or source_file.get("type") or "<unknown>"
                    errors.append(f"index chip {chip_id} source file URL points at staging: {package_name}")

    return errors


def _verify_chip_json_files(root: Path) -> list[str]:
    errors: list[str] = []
    for chip_path in sorted((root / "chips").glob("**/chip.json")):
        payload = _read_json(chip_path)
        if not isinstance(payload, dict):
            errors.append(f"{chip_path.relative_to(root).as_posix()} must contain an object")
            continue

        chip_id = str(payload.get("id") or chip_path.parent.name)
        packages = payload.get("packages")
        if not isinstance(packages, list):
            continue

        package_names: list[str] = []
        for package_layout in packages:
            if isinstance(package_layout, dict):
                package_name = package_layout.get("packageName")
                if package_name:
                    package_names.append(str(package_name))

        for package_name in _duplicates(package_names):
            errors.append(f"chip.json {chip_id} has duplicate package {package_name}")

    return errors


def verify_release_data(root: Path) -> list[str]:
    root = root.resolve()
    return [*_verify_index(root), *_verify_chip_json_files(root)]


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify generated McuPinFunc remote release data.")
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    errors = verify_release_data(args.repo_root)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1

    print("Release data verification passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
