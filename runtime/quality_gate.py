#!/usr/bin/env python3
"""Deterministic repository quality and attribution policy checks."""

from __future__ import annotations

import pathlib
import json
import re
import shutil
import subprocess
import sys

ROOT = pathlib.Path.cwd()
SOURCE_SUFFIXES = {
    ".c",
    ".cc",
    ".cpp",
    ".cs",
    ".go",
    ".java",
    ".js",
    ".jsx",
    ".kt",
    ".php",
    ".py",
    ".rb",
    ".rs",
    ".scala",
    ".sh",
    ".ts",
    ".tsx",
}
TEST_MARKERS = ("/test/", "/tests/", ".test.", ".spec.", "_test.", "test_")
ATTRIBUTION_PATTERNS = (
    re.compile(r"generated (?:by|with) (?:ai|chatgpt|claude|copilot)", re.I),
    re.compile(
        r"(?:created|written|assisted) (?:by|with) (?:ai|chatgpt|claude|copilot)", re.I
    ),
    re.compile(r"co-authored-by:.*(?:chatgpt|claude|copilot|openai|anthropic)", re.I),
    re.compile(r"(?:ai|llm)[ -]assisted", re.I),
    re.compile(r"(?:ai|llm)[ -]generated", re.I),
)


def run(command: list[str], *, optional: bool = False) -> None:
    if optional and shutil.which(command[0]) is None:
        print(f"[skip] {' '.join(command)} ({command[0]} not installed)")
        return
    print(f"[run] {' '.join(command)}")
    subprocess.run(command, cwd=ROOT, check=True)


def changed_files() -> list[str]:
    paths: set[str] = set()
    commands = (
        ["git", "diff", "--name-only", "HEAD"],
        ["git", "diff", "--cached", "--name-only"],
        ["git", "ls-files", "--others", "--exclude-standard"],
    )
    for command in commands:
        process = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
        if process.returncode == 0:
            paths.update(filter(None, process.stdout.splitlines()))
    return sorted(paths)


def check_tdd(paths: list[str]) -> None:
    source_changes = [
        path
        for path in paths
        if pathlib.Path(path).suffix in SOURCE_SUFFIXES
        and ".agentic-loop/" not in path
        and not any(marker in f"/{path.lower()}" for marker in TEST_MARKERS)
    ]
    test_changes = [
        path
        for path in paths
        if any(marker in f"/{path.lower()}" for marker in TEST_MARKERS)
    ]
    if source_changes and not test_changes:
        raise RuntimeError(
            "TDD gate failed: source changed without a changed test file. "
            f"Source changes: {', '.join(source_changes)}"
        )


def check_attribution(paths: list[str]) -> None:
    for relative in paths:
        if relative.startswith((".agentic-loop/", "openspec/")):
            continue
        path = ROOT / relative
        if not path.is_file() or path.stat().st_size > 2_000_000:
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for pattern in ATTRIBUTION_PATTERNS:
            if pattern.search(content):
                raise RuntimeError(
                    f"AI attribution policy failed: prohibited attribution text in {relative}"
                )


def project_checks() -> None:
    if (ROOT / "pyproject.toml").exists():
        run(["ruff", "format", "--check", "."])
        run(["ruff", "check", "."])
        run(["ruff", "check", "--select", "I", "."])
        run(["pytest"])
    if (ROOT / "package.json").exists():
        package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
        scripts = package.get("scripts", {})
        required = {"test", "lint", "format:check"}
        missing = sorted(required - scripts.keys())
        if missing:
            raise RuntimeError(
                "Node quality gate requires package.json scripts: " + ", ".join(missing)
            )
        run(["npm", "test"])
        run(["npm", "run", "lint"])
        run(["npm", "run", "format:check"])
        if "typecheck" in scripts:
            run(["npm", "run", "typecheck"])
    if (ROOT / "go.mod").exists():
        output = subprocess.run(
            ["gofmt", "-l", "."], cwd=ROOT, text=True, capture_output=True, check=True
        ).stdout.strip()
        if output:
            raise RuntimeError(f"gofmt required for: {output}")
        run(["go", "vet", "./..."])
        run(["go", "test", "./..."])
    if (ROOT / "Cargo.toml").exists():
        run(["cargo", "fmt", "--all", "--", "--check"])
        run(
            [
                "cargo",
                "clippy",
                "--all-targets",
                "--all-features",
                "--",
                "-D",
                "warnings",
            ]
        )
        run(["cargo", "test", "--all-targets"])


def main() -> int:
    try:
        paths = changed_files()
        check_tdd(paths)
        check_attribution(paths)
        project_checks()
        print("[ok] TDD, attribution, lint, format, sort, and project checks")
        return 0
    except (RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"quality gate failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
