#!/usr/bin/env python3
"""Repository-local agent loop runner with optional OpenTelemetry export."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import pathlib
import re
import shlex
import shutil
import subprocess
import sys
import time
import urllib.request
import urllib.error
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterator

ROOT = pathlib.Path.cwd()
LOOP_DIR = ROOT / ".agentic-loop"
RUNS_DIR = LOOP_DIR / "runs"
CONFIG_PATH = LOOP_DIR / "loop.json"
OPENSPEC_VERSION = "1.4.1"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(path: pathlib.Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: pathlib.Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    temporary.chmod(0o600)
    temporary.replace(path)


def write_text(path: pathlib.Path, value: str) -> None:
    path.write_text(value, encoding="utf-8")
    path.chmod(0o600)


def deep_get(value: dict[str, Any], path: str, default: Any = None) -> Any:
    current: Any = value
    for key in path.split("."):
        if not isinstance(current, dict) or key not in current:
            return default
        current = current[key]
    return current


class JsonlTelemetry:
    def __init__(self, run_id: str, run_dir: pathlib.Path, attributes: dict[str, Any]):
        self.run_id = run_id
        self.trace_id = hashlib.sha256(run_id.encode()).hexdigest()[:32]
        self.path = run_dir / "telemetry.jsonl"
        self.attributes = attributes

    @contextlib.contextmanager
    def span(
        self, name: str, attributes: dict[str, Any] | None = None
    ) -> Iterator[None]:
        span_id = uuid.uuid4().hex[:16]
        started = time.monotonic()
        record = {
            "timestamp": now(),
            "event": "span.start",
            "trace_id": self.trace_id,
            "span_id": span_id,
            "name": name,
            "attributes": {**self.attributes, **(attributes or {})},
        }
        self._emit(record)
        error = ""
        try:
            yield
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            self._emit(
                {
                    **record,
                    "timestamp": now(),
                    "event": "span.end",
                    "duration_ms": round((time.monotonic() - started) * 1000, 2),
                    "status": "error" if error else "ok",
                    "error": error or None,
                }
            )

    def event(self, name: str, attributes: dict[str, Any] | None = None) -> None:
        self._emit(
            {
                "timestamp": now(),
                "event": name,
                "trace_id": self.trace_id,
                "attributes": {**self.attributes, **(attributes or {})},
            }
        )

    def _emit(self, record: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, separators=(",", ":")) + "\n")
        self.path.chmod(0o600)


class OpenTelemetry:
    """Optional OTel SDK bridge. JSONL remains available regardless of SDK state."""

    def __init__(self, fallback: JsonlTelemetry, service_name: str):
        self.fallback = fallback
        self.tracer = None
        self.provider = None
        endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip()
        if not endpoint:
            return
        try:
            from opentelemetry import trace
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                OTLPSpanExporter,
            )
            from opentelemetry.sdk.resources import Resource
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import BatchSpanProcessor

            provider = TracerProvider(
                resource=Resource.create(
                    {
                        "service.name": service_name,
                        "service.version": "0.2.0",
                    }
                )
            )
            exporter = OTLPSpanExporter(endpoint=endpoint.rstrip("/") + "/v1/traces")
            provider.add_span_processor(BatchSpanProcessor(exporter))
            trace.set_tracer_provider(provider)
            self.provider = provider
            self.tracer = trace.get_tracer("agentic-loop-bundle")
        except Exception as exc:
            print(f"warning: OpenTelemetry export disabled: {exc}", file=sys.stderr)

    @contextlib.contextmanager
    def span(
        self, name: str, attributes: dict[str, Any] | None = None
    ) -> Iterator[None]:
        attrs = attributes or {}
        with self.fallback.span(name, attrs):
            if self.tracer is None:
                yield
                return
            with self.tracer.start_as_current_span(
                name, attributes=clean_attributes(attrs)
            ):
                yield

    def event(self, name: str, attributes: dict[str, Any] | None = None) -> None:
        self.fallback.event(name, attributes)

    def subprocess_environment(self, service_name: str) -> dict[str, str]:
        environment = dict(os.environ)
        environment.setdefault("OTEL_SERVICE_NAME", service_name)
        if self.tracer is None:
            return environment
        try:
            from opentelemetry import trace

            context = trace.get_current_span().get_span_context()
            if context.is_valid:
                sampled = "01" if context.trace_flags.sampled else "00"
                environment["TRACEPARENT"] = (
                    f"00-{context.trace_id:032x}-{context.span_id:016x}-{sampled}"
                )
        except Exception:
            pass
        return environment

    def close(self) -> None:
        if self.provider is not None:
            self.provider.force_flush(timeout_millis=5000)
            self.provider.shutdown()


def clean_attributes(attributes: dict[str, Any]) -> dict[str, Any]:
    allowed = (bool, str, int, float)
    return {
        key: value for key, value in attributes.items() if isinstance(value, allowed)
    }


def init_agentops(run_id: str, tags: list[str]) -> Any:
    if not os.environ.get("AGENTOPS_API_KEY"):
        return None
    try:
        import agentops

        agentops.init(
            default_tags=tags,
            trace_name=f"agentic-loop-{run_id}",
            auto_start_session=False,
            fail_safe=True,
        )
        return agentops.start_trace(f"agentic-loop-{run_id}", tags=tags)
    except Exception as exc:
        print(f"warning: AgentOps disabled: {exc}", file=sys.stderr)
        return None


def end_agentops(session: Any, success: bool) -> None:
    if session is None:
        return
    try:
        import agentops

        agentops.end_trace(session, end_state="Success" if success else "Fail")
    except Exception:
        try:
            import agentops

            agentops.end_session("Success" if success else "Fail")
        except Exception:
            pass


def detect_agent_command() -> str:
    configured = os.environ.get("LOOP_AGENT_COMMAND", "").strip()
    if configured:
        return configured
    candidates = (
        ("codex", "codex exec --full-auto -"),
        ("claude", "claude -p --dangerously-skip-permissions"),
        ("opencode", "opencode run"),
    )
    for binary, command in candidates:
        if shutil.which(binary):
            return command
    raise RuntimeError(
        "no supported agent CLI found; install codex, claude, or opencode, "
        "or set LOOP_AGENT_COMMAND"
    )


def openspec_command() -> list[str]:
    configured = os.environ.get("OPENSPEC_COMMAND", "").strip()
    if configured:
        return shlex.split(configured)
    local_binary = LOOP_DIR / "tools" / "node_modules" / ".bin" / "openspec"
    if local_binary.is_file():
        return [str(local_binary)]
    binary = shutil.which("openspec")
    if binary:
        return [binary]
    raise RuntimeError(
        f"OpenSpec is required; install @fission-ai/openspec@{OPENSPEC_VERSION} "
        "or set OPENSPEC_COMMAND"
    )


def run_openspec(*arguments: str, json_output: bool = False) -> Any:
    command = [*openspec_command(), *arguments]
    process = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        capture_output=True,
        env={**os.environ, "OPENSPEC_TELEMETRY": "0"},
    )
    if process.returncode:
        raise RuntimeError(
            f"OpenSpec command failed ({' '.join(command)}): "
            f"{(process.stderr or process.stdout).strip()}"
        )
    if json_output:
        return json.loads(process.stdout)
    return process.stdout


def validate_change_name(change: str) -> str:
    if not change or any(
        character not in "abcdefghijklmnopqrstuvwxyz0123456789-" for character in change
    ):
        raise RuntimeError("change name must use lowercase kebab-case")
    return change


def openspec_change_dir(change: str) -> pathlib.Path:
    return ROOT / "openspec" / "changes" / validate_change_name(change)


def openspec_context(change: str) -> str:
    instructions = run_openspec(
        "instructions", "apply", "--change", change, "--json", json_output=True
    )
    files = instructions.get("contextFiles", [])
    sections = []
    for value in files:
        path = pathlib.Path(value)
        if not path.is_absolute():
            path = ROOT / path
        if path.is_file():
            sections.append(
                f"# {path.relative_to(ROOT)}\n\n{path.read_text(encoding='utf-8')}"
            )
    if not sections:
        change_dir = openspec_change_dir(change)
        for name in ("proposal.md", "design.md", "tasks.md"):
            path = change_dir / name
            if path.is_file():
                sections.append(
                    f"# {path.relative_to(ROOT)}\n\n{path.read_text(encoding='utf-8')}"
                )
        for path in sorted((change_dir / "specs").glob("**/*.md")):
            sections.append(
                f"# {path.relative_to(ROOT)}\n\n{path.read_text(encoding='utf-8')}"
            )
    return "\n\n".join(sections)


def pending_tasks(change: str) -> list[str]:
    tasks_path = openspec_change_dir(change) / "tasks.md"
    if not tasks_path.is_file():
        raise RuntimeError(f"OpenSpec tasks are missing for change: {change}")
    tasks = []
    for line in tasks_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("- [ ] "):
            tasks.append(stripped[6:].strip())
    return tasks


def jira_comment(issue_key: str, text: str) -> None:
    if not issue_key or any(
        character not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-"
        for character in issue_key
    ):
        raise RuntimeError(
            "Jira issue key must use uppercase letters, digits, and hyphens"
        )
    base_url = os.environ.get("JIRA_BASE_URL", "").rstrip("/")
    email = os.environ.get("JIRA_EMAIL", "")
    token = os.environ.get("JIRA_API_TOKEN", "")
    if not all((base_url, email, token)):
        raise RuntimeError(
            "Jira sync requires JIRA_BASE_URL, JIRA_EMAIL, and JIRA_API_TOKEN"
        )
    import base64

    body = {
        "body": {
            "type": "doc",
            "version": 1,
            "content": [
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": text[:30000]}],
                }
            ],
        }
    }
    request = urllib.request.Request(
        f"{base_url}/rest/api/3/issue/{issue_key}/comment",
        data=json.dumps(body).encode(),
        method="POST",
        headers={
            "Authorization": "Basic "
            + base64.b64encode(f"{email}:{token}".encode()).decode(),
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30):
            return
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        raise RuntimeError(f"Jira comment failed ({exc.code}): {detail}") from exc


def adf_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(filter(None, (adf_text(item) for item in value)))
    if isinstance(value, dict):
        text = value.get("text", "")
        children = adf_text(value.get("content", []))
        return "\n".join(part for part in (text, children) if part)
    return ""


def jira_issue_text(issue_key: str) -> str:
    if not issue_key or any(
        character not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-"
        for character in issue_key
    ):
        raise RuntimeError(
            "Jira issue key must use uppercase letters, digits, and hyphens"
        )
    base_url = os.environ.get("JIRA_BASE_URL", "").rstrip("/")
    email = os.environ.get("JIRA_EMAIL", "")
    token = os.environ.get("JIRA_API_TOKEN", "")
    if not all((base_url, email, token)):
        raise RuntimeError(
            "Jira intake requires JIRA_BASE_URL, JIRA_EMAIL, and JIRA_API_TOKEN"
        )
    import base64

    request = urllib.request.Request(
        f"{base_url}/rest/api/3/issue/{issue_key}?fields=summary,description",
        headers={
            "Authorization": "Basic "
            + base64.b64encode(f"{email}:{token}".encode()).decode(),
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            issue = json.load(response)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        raise RuntimeError(f"Jira issue fetch failed ({exc.code}): {detail}") from exc
    fields = issue.get("fields", {})
    summary = fields.get("summary", issue_key)
    description = adf_text(fields.get("description")) or "No Jira description supplied."
    return f"# {issue_key}: {summary}\n\n{description}\n"


def render_prompt(
    stage: str,
    task: str,
    run_dir: pathlib.Path,
    attempt: int,
    change: str = "",
    spec_context: str = "",
    parent_change: str = "",
    current_task: str = "",
) -> str:
    prompt_path = LOOP_DIR / "prompts" / f"{stage}.md"
    template = prompt_path.read_text(encoding="utf-8")
    # plan.md is written each run for user-customized prompts; no shipped
    # template currently substitutes {{PLAN}}.
    plan = read_optional(run_dir / "plan.md")
    verification = read_optional(run_dir / "verification.txt")
    values = {
        "TASK": task,
        "PLAN": plan,
        "VERIFICATION": verification,
        "ATTEMPT": str(attempt),
        "RUN_ID": run_dir.name,
        "CHANGE": change,
        "SPEC_CONTEXT": spec_context,
        "PARENT_CHANGE": parent_change,
        "CURRENT_TASK": current_task,
    }
    return re.sub(
        r"\{\{(" + "|".join(values) + r")\}\}",
        lambda match: values[match.group(1)],
        template,
    )


def read_optional(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def policy_digest() -> str:
    digest = hashlib.sha256()
    protected = [LOOP_DIR / "loop.json"]
    for directory in (LOOP_DIR / "bin", LOOP_DIR / "prompts", LOOP_DIR / "docker"):
        protected.extend(path for path in directory.glob("**/*") if path.is_file())
    for path in sorted(protected):
        digest.update(str(path.relative_to(ROOT)).encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


SKIP_DIR_NAMES = {
    ".git",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    ".tox",
    ".venv",
    "venv",
}


def workspace_hashes() -> dict[str, str]:
    values: dict[str, str] = {}
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(ROOT)
        if any(part in SKIP_DIR_NAMES for part in relative.parts):
            continue
        if relative.parts[:2] in (
            (".agentic-loop", "runs"),
            (".agentic-loop", "python"),
            (".agentic-loop", "tools"),
            (".agentic-loop", "backups"),
        ):
            continue
        if relative.parts == (".agentic-loop", "state.json"):
            continue
        values[str(relative)] = hashlib.sha256(path.read_bytes()).hexdigest()
    return values


def is_test_path(path: str) -> bool:
    parts = pathlib.PurePosixPath(path.lower()).parts
    if any(part in ("test", "tests", "__tests__") for part in parts[:-1]):
        return True
    name = parts[-1] if parts else ""
    stem = name.split(".")[0]
    return (
        stem.startswith("test_")
        or stem.endswith("_test")
        or ".test." in name
        or ".spec." in name
    )


def run_agent(
    telemetry: OpenTelemetry,
    command: str,
    stage: str,
    prompt: str,
    output_path: pathlib.Path,
    timeout_seconds: int,
) -> int:
    prompt_hash = hashlib.sha256(prompt.encode()).hexdigest()
    attributes = {
        "gen_ai.operation.name": stage,
        "gen_ai.request.model": os.environ.get("LOOP_MODEL", "cli-default"),
        "gen_ai.system": command.split()[0],
        "agentic_loop.prompt_sha256": prompt_hash,
        "agentic_loop.prompt_bytes": len(prompt.encode()),
    }
    started = time.monotonic()
    with telemetry.span("gen_ai.client.operation", attributes):
        process = subprocess.run(
            command,
            cwd=ROOT,
            input=prompt,
            text=True,
            shell=True,
            executable="/bin/bash",
            capture_output=True,
            timeout=timeout_seconds,
            env={
                **telemetry.subprocess_environment(f"agentic-loop-{stage}"),
                "AGENTIC_LOOP_STAGE": stage,
            },
        )
    write_text(output_path, process.stdout)
    if process.stderr:
        write_text(output_path.with_suffix(".stderr.txt"), process.stderr)
    telemetry.event(
        "agent.completed",
        {
            "agentic_loop.stage": stage,
            "agentic_loop.exit_code": process.returncode,
            "agentic_loop.duration_ms": round((time.monotonic() - started) * 1000, 2),
            "agentic_loop.output_bytes": len(process.stdout.encode()),
        },
    )
    return process.returncode


def run_verification(
    telemetry: OpenTelemetry,
    command: str,
    output_path: pathlib.Path,
    timeout_seconds: int,
) -> int:
    with telemetry.span("loop.verify", {"agentic_loop.verify.command": command}):
        process = subprocess.run(
            command,
            cwd=ROOT,
            text=True,
            shell=True,
            executable="/bin/bash",
            capture_output=True,
            timeout=timeout_seconds,
        )
    write_text(output_path, process.stdout + process.stderr)
    return process.returncode


@dataclass
class RunContext:
    run_id: str
    run_dir: pathlib.Path
    config: dict[str, Any]
    state: dict[str, Any]
    telemetry: OpenTelemetry

    def update(self, **values: Any) -> None:
        self.state.update(values)
        self.state["updated_at"] = now()
        write_json(self.run_dir / "state.json", self.state)
        write_json(LOOP_DIR / "state.json", self.state)


def command_propose(args: argparse.Namespace) -> int:
    if not CONFIG_PATH.exists():
        raise RuntimeError("not installed: .agentic-loop/loop.json is missing")
    change = validate_change_name(args.change)
    if args.task_file:
        task = pathlib.Path(args.task_file).read_text(encoding="utf-8")
    elif args.task:
        task = args.task
    elif args.jira:
        task = jira_issue_text(args.jira)
    else:
        task = ""
    if not task.strip():
        raise RuntimeError("task is empty")
    if not (ROOT / "openspec").exists():
        run_openspec("init", "--tools", "none")
    if args.parent_change:
        parent_change = validate_change_name(args.parent_change)
        if not openspec_change_dir(parent_change).is_dir():
            raise RuntimeError(
                f"parent OpenSpec change does not exist: {parent_change}"
            )
    change_dir = openspec_change_dir(change)
    if change_dir.exists():
        raise RuntimeError(f"OpenSpec change already exists: {change}")
    run_openspec("new", "change", change, "--description", task.strip())
    metadata = {
        "change": change,
        "parent_change": args.parent_change or "",
        "jira_issue": args.jira or "",
        "issue": os.environ.get("LOOP_ISSUE_ID", ""),
        "created_at": now(),
    }
    write_json(change_dir / "agentic-loop.json", metadata)

    run_id = f"proposal-{change}-{uuid.uuid4()}"
    run_dir = RUNS_DIR / run_id
    run_dir.mkdir(parents=True, mode=0o700)
    run_dir.chmod(0o700)
    write_text(run_dir / "task.md", task.rstrip() + "\n")
    telemetry = OpenTelemetry(
        JsonlTelemetry(
            run_id,
            run_dir,
            {
                "agentic_loop.run.id": run_id,
                "agentic_loop.change": change,
                "agentic_loop.parent_change": args.parent_change or "",
                "agentic_loop.jira.issue": args.jira or "",
            },
        ),
        "agentic-loop-proposal",
    )
    command = detect_agent_command()
    timeout_seconds = int(
        deep_get(load_json(CONFIG_PATH), "limits.agent_timeout_seconds", 1800)
    )
    proposal_policy_digest = policy_digest()
    hashes_before_proposal = workspace_hashes()
    prompt = render_prompt(
        "proposer",
        task,
        run_dir,
        1,
        change=change,
        parent_change=args.parent_change or "",
    )
    try:
        with telemetry.span("loop.propose", {"agentic_loop.change": change}):
            if run_agent(
                telemetry,
                command,
                "propose",
                prompt,
                run_dir / "proposal-agent.txt",
                timeout_seconds,
            ):
                raise RuntimeError("proposal agent failed")
            if policy_digest() != proposal_policy_digest:
                raise RuntimeError("proposal agent modified protected loop policy")
            hashes_after_proposal = workspace_hashes()
            changed_by_proposal = {
                path
                for path in hashes_before_proposal.keys() | hashes_after_proposal.keys()
                if hashes_before_proposal.get(path) != hashes_after_proposal.get(path)
            }
            allowed_prefix = f"openspec/changes/{change}/"
            invalid_proposal_changes = {
                path
                for path in changed_by_proposal
                if not path.startswith(allowed_prefix)
            }
            if invalid_proposal_changes:
                raise RuntimeError(
                    "proposal stage changed files outside its OpenSpec change: "
                    + ", ".join(sorted(invalid_proposal_changes))
                )
            status = run_openspec(
                "status", "--change", change, "--json", json_output=True
            )
            if not status.get("isComplete"):
                raise RuntimeError(
                    f"OpenSpec change is not apply-ready: {status.get('nextSteps', [])}"
                )
            run_openspec("validate", change)
        if args.jira:
            with contextlib.suppress(Exception):
                jira_comment(
                    args.jira,
                    f"Agentic loop proposal `{change}` is apply-ready. "
                    f"Artifacts: openspec/changes/{change}/",
                )
        print(change)
        return 0
    except Exception:
        if args.jira:
            with contextlib.suppress(Exception):
                jira_comment(args.jira, f"Agentic loop proposal `{change}` failed.")
        raise
    finally:
        telemetry.close()


def command_run(args: argparse.Namespace) -> int:
    if not CONFIG_PATH.exists():
        raise RuntimeError("not installed: .agentic-loop/loop.json is missing")
    config = load_json(CONFIG_PATH)
    change = validate_change_name(args.change)
    change_dir = openspec_change_dir(change)
    if not change_dir.is_dir():
        raise RuntimeError(f"OpenSpec change does not exist: {change}")
    status = run_openspec("status", "--change", change, "--json", json_output=True)
    if not status.get("isComplete"):
        raise RuntimeError(
            f"OpenSpec change is not apply-ready: {status.get('nextSteps', [])}"
        )
    run_openspec("validate", change)
    spec_context = openspec_context(change)
    task = f"Implement the OpenSpec change `{change}` as specified in the context below."
    change_metadata_path = change_dir / "agentic-loop.json"
    change_metadata = (
        load_json(change_metadata_path) if change_metadata_path.exists() else {}
    )
    jira_issue = args.jira or change_metadata.get("jira_issue", "")

    run_id = os.environ.get("LOOP_RUN_ID", str(uuid.uuid4()))
    run_dir = RUNS_DIR / run_id
    run_dir.mkdir(parents=True, mode=0o700, exist_ok=False)
    run_dir.chmod(0o700)
    write_text(run_dir / "task.md", spec_context.rstrip() + "\n")
    repo = (
        os.environ.get("CI_PROJECT_PATH")
        or os.environ.get("GITHUB_REPOSITORY")
        or ROOT.name
    )
    platform = (
        "gitlab"
        if os.environ.get("GITLAB_CI")
        else "github"
        if os.environ.get("GITHUB_ACTIONS")
        else "local"
    )
    base_attributes = {
        "agentic_loop.run.id": run_id,
        "agentic_loop.repository": repo,
        "agentic_loop.platform": platform,
        "agentic_loop.change": change,
        "agentic_loop.parent_change": change_metadata.get("parent_change", ""),
        "agentic_loop.jira.issue": jira_issue,
        "agentic_loop.issue.id": os.environ.get("LOOP_ISSUE_ID", ""),
        "agentic_loop.commit.sha": os.environ.get("CI_COMMIT_SHA")
        or os.environ.get("GITHUB_SHA", ""),
    }
    fallback = JsonlTelemetry(run_id, run_dir, base_attributes)
    telemetry = OpenTelemetry(
        fallback, deep_get(config, "telemetry.service_name", "agentic-loop")
    )
    state = {
        "run_id": run_id,
        "status": "running",
        "stage": "starting",
        "attempt": 0,
        "created_at": now(),
        **base_attributes,
    }
    ctx = RunContext(run_id, run_dir, config, state, telemetry)
    ctx.update()
    agentops_session = init_agentops(run_id, [platform, repo])
    success = False

    command = detect_agent_command()
    timeout_seconds = int(deep_get(config, "limits.agent_timeout_seconds", 1800))
    verify_timeout = int(deep_get(config, "limits.verify_timeout_seconds", 900))
    max_attempts = int(deep_get(config, "limits.max_attempts", 3))
    verification_command = deep_get(
        config, "verification.command", "./.agentic-loop/bin/verify.sh"
    )
    test_command = deep_get(
        config, "verification.test_command", "./.agentic-loop/bin/test.sh"
    )
    initial_policy_digest = policy_digest()

    try:
        with telemetry.span("loop.run", {"agentic_loop.max_attempts": max_attempts}):
            write_text(run_dir / "plan.md", spec_context)
            if jira_issue:
                with contextlib.suppress(Exception):
                    jira_comment(
                        jira_issue,
                        f"Agentic loop `{run_id}` started for OpenSpec change `{change}`.",
                    )

            slice_number = 0
            while True:
                remaining = pending_tasks(change)
                if not remaining:
                    break
                slice_number += 1
                current_task = remaining[0]
                tasks_path = openspec_change_dir(change) / "tasks.md"
                tasks_before_slice = tasks_path.read_text(encoding="utf-8")
                tasks_mode = tasks_path.stat().st_mode
                write_text(run_dir / "verification.txt", "")
                ctx.update(stage="test", slice=slice_number, current_task=current_task)
                baseline_result = run_verification(
                    telemetry,
                    test_command,
                    run_dir / f"slice-{slice_number}-baseline-tests.txt",
                    verify_timeout,
                )
                if baseline_result != 0:
                    raise RuntimeError(
                        f"tests were not green before slice '{current_task}'"
                    )
                hashes_before_test = workspace_hashes()
                test_prompt = render_prompt(
                    "tester",
                    task,
                    run_dir,
                    1,
                    change=change,
                    spec_context=spec_context,
                    current_task=current_task,
                )
                if run_agent(
                    telemetry,
                    command,
                    "test",
                    test_prompt,
                    run_dir / f"slice-{slice_number}-red-test.txt",
                    timeout_seconds,
                ):
                    raise RuntimeError(f"test author failed for slice '{current_task}'")
                if policy_digest() != initial_policy_digest:
                    raise RuntimeError("test author modified protected loop policy")
                hashes_after_test = workspace_hashes()
                changed_by_test = {
                    path
                    for path in hashes_before_test.keys() | hashes_after_test.keys()
                    if hashes_before_test.get(path) != hashes_after_test.get(path)
                }
                invalid_test_changes = {
                    path for path in changed_by_test if not is_test_path(path)
                }
                if invalid_test_changes:
                    raise RuntimeError(
                        "red stage changed non-test files: "
                        + ", ".join(sorted(invalid_test_changes))
                    )
                if not any(is_test_path(path) for path in changed_by_test):
                    raise RuntimeError("red stage did not add or change a test")
                red_result = run_verification(
                    telemetry,
                    test_command,
                    run_dir / f"slice-{slice_number}-red-result.txt",
                    verify_timeout,
                )
                if red_result == 0:
                    raise RuntimeError(
                        f"new test did not fail as expected for slice '{current_task}'"
                    )
                if red_result != 1:
                    raise RuntimeError(
                        f"test command errored (exit {red_result}) during the red "
                        f"stage; see slice-{slice_number}-red-result.txt"
                    )
                slice_succeeded = False
                for attempt in range(1, max_attempts + 1):
                    ctx.update(
                        stage="implement",
                        attempt=attempt,
                        slice=slice_number,
                        current_task=current_task,
                        remaining_tasks=len(remaining),
                    )
                    implement_prompt = render_prompt(
                        "implementer",
                        task,
                        run_dir,
                        attempt,
                        change=change,
                        spec_context=spec_context,
                        current_task=current_task,
                    )
                    telemetry.event(
                        "loop.slice.start",
                        {
                            "agentic_loop.change": change,
                            "agentic_loop.slice": slice_number,
                            "agentic_loop.task": current_task,
                            "agentic_loop.attempt": attempt,
                            "agentic_loop.context_scope": "full-spec-and-working-tree",
                        },
                    )
                    if run_agent(
                        telemetry,
                        command,
                        "implement",
                        implement_prompt,
                        run_dir / f"slice-{slice_number}-attempt-{attempt}.txt",
                        timeout_seconds,
                    ):
                        telemetry.event(
                            "loop.retry", {"agentic_loop.reason": "implementer_failed"}
                        )
                        continue
                    if policy_digest() != initial_policy_digest:
                        raise RuntimeError(
                            "agent modified protected loop policy, prompts, runtime, or verification files"
                        )
                    remaining_after_implementation = pending_tasks(change)
                    completed_out_of_order = set(remaining[1:]) - set(
                        remaining_after_implementation
                    )
                    if completed_out_of_order:
                        raise RuntimeError(
                            "agent marked later OpenSpec tasks complete out of order: "
                            + ", ".join(sorted(completed_out_of_order))
                        )

                    ctx.update(stage="verify")
                    verification_output_path = (
                        run_dir / f"slice-{slice_number}-verification-{attempt}.txt"
                    )
                    verify_result = run_verification(
                        telemetry,
                        verification_command,
                        verification_output_path,
                        verify_timeout,
                    )
                    write_text(
                        run_dir / "verification.txt",
                        read_optional(verification_output_path),
                    )
                    if (
                        verify_result == 0
                        and current_task not in remaining_after_implementation
                    ):
                        telemetry.event(
                            "loop.slice.complete",
                            {
                                "agentic_loop.slice": slice_number,
                                "agentic_loop.task": current_task,
                            },
                        )
                        spec_context = openspec_context(change)
                        slice_succeeded = True
                        break
                    reason = (
                        "task_not_marked_complete"
                        if verify_result == 0
                        else "verification_failed"
                    )
                    telemetry.event(
                        "loop.retry",
                        {
                            "agentic_loop.reason": reason,
                            "agentic_loop.attempt": attempt,
                            "agentic_loop.slice": slice_number,
                        },
                    )
                    # Only the task checklist is reset between attempts; working-tree
                    # code changes from the failed attempt are deliberately retained
                    # so the next attempt can build on partial progress.
                    tasks_path.write_text(tasks_before_slice, encoding="utf-8")
                    tasks_path.chmod(tasks_mode)
                if not slice_succeeded:
                    raise RuntimeError(
                        f"slice '{current_task}' failed after {max_attempts} attempts"
                    )
                if args.max_slices and slice_number >= args.max_slices:
                    break

            remaining_tasks = len(pending_tasks(change))
            is_complete = remaining_tasks == 0
            review_enabled = deep_get(config, "review.enabled", True)
            per_slice_review = deep_get(config, "review.per_slice", False)
            if review_enabled and (is_complete or per_slice_review):
                ctx.update(stage="review")
                review_prompt = render_prompt(
                    "reviewer",
                    task,
                    run_dir,
                    ctx.state["attempt"],
                    change=change,
                    spec_context=spec_context,
                )
                hashes_before_review = workspace_hashes()
                review_result = run_agent(
                    telemetry,
                    command,
                    "review",
                    review_prompt,
                    run_dir / "review.md",
                    timeout_seconds,
                )
                if review_result and deep_get(config, "review.required", False):
                    raise RuntimeError("reviewer agent failed")
                if workspace_hashes() != hashes_before_review:
                    raise RuntimeError(
                        "reviewer modified the working tree during a read-only stage"
                    )

            ctx.update(
                stage="complete", status="succeeded", remaining_tasks=remaining_tasks
            )
            telemetry.event(
                "loop.outcome",
                {
                    "agentic_loop.outcome": "succeeded",
                    "agentic_loop.remaining_tasks": remaining_tasks,
                },
            )
            success = True
            if jira_issue:
                with contextlib.suppress(Exception):
                    if is_complete:
                        jira_comment(
                            jira_issue,
                            f"Agentic loop `{run_id}` completed for OpenSpec change `{change}`. "
                            "Verification passed; review branch publication follows in the repository workflow.",
                        )
                    else:
                        jira_comment(
                            jira_issue,
                            f"Agentic loop `{run_id}` completed slice {slice_number} for "
                            f"OpenSpec change `{change}`. {remaining_tasks} task(s) remain.",
                        )
            print(run_id)
            print(f"remaining={remaining_tasks}")
            return 0
    except Exception as exc:
        ctx.update(stage="failed", status="failed", error=str(exc))
        telemetry.event(
            "loop.outcome",
            {"agentic_loop.outcome": "failed", "error.type": type(exc).__name__},
        )
        if jira_issue:
            with contextlib.suppress(Exception):
                jira_comment(
                    jira_issue,
                    f"Agentic loop `{run_id}` failed for OpenSpec change `{change}`: {exc}",
                )
        print(f"loop failed: {exc}", file=sys.stderr)
        return 1
    finally:
        end_agentops(agentops_session, success)
        telemetry.close()


def command_doctor(_: argparse.Namespace) -> int:
    checks: list[tuple[str, bool, str]] = []
    checks.append(("configuration", CONFIG_PATH.exists(), str(CONFIG_PATH)))
    checks.append(("git repository", (ROOT / ".git").exists(), str(ROOT)))
    try:
        command = detect_agent_command()
        checks.append(("agent command", True, command))
    except RuntimeError as exc:
        checks.append(("agent command", False, str(exc)))
    try:
        command = " ".join(openspec_command())
        checks.append(("OpenSpec", True, command))
    except RuntimeError as exc:
        checks.append(("OpenSpec", False, str(exc)))
    verify = LOOP_DIR / "bin" / "verify.sh"
    checks.append(
        (
            "verification script",
            verify.is_file() and os.access(verify, os.X_OK),
            str(verify),
        )
    )
    checks.append(
        (
            "docker",
            shutil.which("docker") is not None,
            "required by the default per-slice smoke gate (bin/smoke.sh)",
        )
    )
    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "")
    checks.append(
        ("OTLP endpoint", bool(endpoint), endpoint or "optional; JSONL fallback active")
    )
    failed = False
    for name, ok, detail in checks:
        print(f"[{'ok' if ok else '!!'}] {name}: {detail}")
        if name not in {"OTLP endpoint"} and not ok:
            failed = True
    return 1 if failed else 0


def command_telemetry_test(_: argparse.Namespace) -> int:
    run_id = f"telemetry-{uuid.uuid4()}"
    run_dir = RUNS_DIR / run_id
    run_dir.mkdir(parents=True, mode=0o700)
    run_dir.chmod(0o700)
    fallback = JsonlTelemetry(run_id, run_dir, {"agentic_loop.test": True})
    telemetry = OpenTelemetry(fallback, "agentic-loop-telemetry-test")
    with telemetry.span("loop.telemetry.test"):
        time.sleep(0.05)
    telemetry.close()
    print(f"wrote {run_dir / 'telemetry.jsonl'}")
    return 0


def command_status(args: argparse.Namespace) -> int:
    if args.change:
        change = validate_change_name(args.change)
        tasks = pending_tasks(change)
        payload = {
            "change": change,
            "pending_tasks": tasks,
            "remaining": len(tasks),
            "is_complete": not tasks,
        }
        print(json.dumps(payload, indent=2))
        return 0
    state_path = LOOP_DIR / "state.json"
    if not state_path.exists():
        print("no loop runs recorded")
        return 0
    print(json.dumps(load_json(state_path), indent=2))
    return 0


def command_jira_comment(args: argparse.Namespace) -> int:
    jira_comment(args.issue, args.text)
    print(f"commented on {args.issue}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="loopctl")
    subparsers = parser.add_subparsers(dest="command", required=True)
    propose_parser = subparsers.add_parser(
        "propose", help="create and validate an apply-ready OpenSpec change"
    )
    propose_parser.add_argument("--change", required=True)
    task_group = propose_parser.add_mutually_exclusive_group()
    task_group.add_argument("--task")
    task_group.add_argument("--task-file")
    propose_parser.add_argument("--parent-change")
    propose_parser.add_argument("--jira")
    propose_parser.set_defaults(handler=command_propose)
    run_parser = subparsers.add_parser("run", help="run a bounded OpenSpec change")
    run_parser.add_argument("--change", required=True)
    run_parser.add_argument("--jira")
    run_parser.add_argument(
        "--max-slices",
        type=int,
        default=0,
        help="stop after N task slices (0 = unlimited)",
    )
    run_parser.set_defaults(handler=command_run)
    doctor_parser = subparsers.add_parser(
        "doctor", help="check installation and runtime"
    )
    doctor_parser.set_defaults(handler=command_doctor)
    telemetry_parser = subparsers.add_parser("telemetry-test", help="emit a test trace")
    telemetry_parser.set_defaults(handler=command_telemetry_test)
    status_parser = subparsers.add_parser("status", help="show the latest run state")
    status_parser.add_argument("--change")
    status_parser.add_argument("--json", action="store_true")
    status_parser.set_defaults(handler=command_status)
    jira_parser = subparsers.add_parser(
        "jira-comment", help="append loop evidence to a Jira issue"
    )
    jira_parser.add_argument("--issue", required=True)
    jira_parser.add_argument("--text", required=True)
    jira_parser.set_defaults(handler=command_jira_comment)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        return args.handler(args)
    except (RuntimeError, subprocess.TimeoutExpired, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
