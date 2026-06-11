#!/usr/bin/env python3
"""Minimal OpenSpec CLI contract used by offline smoke tests."""

from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path.cwd()
args = sys.argv[1:]


def option(name: str) -> str:
    return args[args.index(name) + 1]


if args[:1] == ["--version"]:
    print("1.4.1")
elif args[:1] == ["init"]:
    (ROOT / "openspec" / "specs").mkdir(parents=True, exist_ok=True)
    (ROOT / "openspec" / "changes" / "archive").mkdir(parents=True, exist_ok=True)
elif args[:2] == ["new", "change"]:
    change = args[2]
    directory = ROOT / "openspec" / "changes" / change
    directory.mkdir(parents=True)
    (directory / ".openspec.yaml").write_text("schema: spec-driven\n", encoding="utf-8")
    description = option("--description") if "--description" in args else change
    (directory / "README.md").write_text(
        f"# {change}\n\n{description}\n", encoding="utf-8"
    )
    if "--json" in args:
        print(json.dumps({"change": {"id": change, "path": str(directory)}}))
elif args[:1] == ["status"]:
    change = option("--change")
    directory = ROOT / "openspec" / "changes" / change
    required = [
        directory / "proposal.md",
        directory / "design.md",
        directory / "tasks.md",
    ]
    specs = list((directory / "specs").glob("**/*.md"))
    complete = all(path.is_file() for path in required) and bool(specs)
    payload = {
        "changeName": change,
        "isComplete": complete,
        "nextSteps": [] if complete else ["Create proposal, specs, design, and tasks"],
    }
    print(
        json.dumps(payload)
        if "--json" in args
        else f"{change}: {'complete' if complete else 'incomplete'}"
    )
elif args[:2] == ["instructions", "apply"]:
    change = option("--change")
    directory = ROOT / "openspec" / "changes" / change
    files = [
        directory / "proposal.md",
        *sorted((directory / "specs").glob("**/*.md")),
        directory / "design.md",
        directory / "tasks.md",
    ]
    print(json.dumps({"contextFiles": [str(path) for path in files]}))
elif args[:1] == ["validate"]:
    change = args[1]
    directory = ROOT / "openspec" / "changes" / change
    if not (directory / "tasks.md").is_file():
        raise SystemExit(1)
    print(f"Change '{change}' is valid")
else:
    print(f"unsupported fake openspec command: {args}", file=sys.stderr)
    raise SystemExit(2)
