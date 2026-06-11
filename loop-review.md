# Code review: agentic-loop-bundle

Scope: code quality and functionality of `runtime/loopctl.py`, `runtime/quality_gate.py`,
`install.sh`, templates (prompts, bin scripts, CI workflows), and tests.
Baseline: `make test` passes on the current tree (smoke, quality-gate, and Jira tests).

Instructions for the implementer: fix the findings below in order (H = high, M = medium,
L = low). Line numbers refer to the current tree and will shift as you edit — locate code
by the quoted snippets, not only by line number. After each fix, run `make verify` and
`make test` from the repository root; both must pass. Do not change behavior that the
smoke test asserts (non-zero exit on failure, run artifacts under `.agentic-loop/runs/`,
the policy-tamper rejection) unless a finding says so.

---

## H1. `{{VERIFICATION}}` placeholder is never populated — retries get no failure feedback

**Files:** `runtime/loopctl.py` (`render_prompt` line 451, `run_verification` lines 560–577, `command_run` lines 813–818, 860–865, 925–929)

`render_prompt` fills `{{VERIFICATION}}` from `run_dir / "verification.txt"`:

```python
verification = read_optional(run_dir / "verification.txt")
```

But no code ever writes `verification.txt`. All verification output goes to
`slice-{n}-baseline-tests.txt`, `slice-{n}-red-result.txt`, and
`slice-{n}-verification-{attempt}.txt`. Consequence: the implementer prompt section
"Previous verification output, if any:" is always empty, so retry attempts 2..N have no
idea why attempt 1 failed (the retry loop is nearly useless), and the reviewer prompt's
"Verification:" section is also always empty.

**Fix:** in `command_run`, after the per-attempt verification call:

```python
verify_result = run_verification(
    telemetry,
    verification_command,
    run_dir / f"slice-{slice_number}-verification-{attempt}.txt",
    verify_timeout,
)
```

add a copy of that output into the file `render_prompt` reads:

```python
write_text(
    run_dir / "verification.txt",
    read_optional(run_dir / f"slice-{slice_number}-verification-{attempt}.txt"),
)
```

Also reset it at the start of each slice (right after `current_task = remaining[0]`) so a
new slice does not see stale output from the previous slice:

```python
write_text(run_dir / "verification.txt", "")
```

Verification: in `tests/smoke.sh` the fake loop still passes; additionally assert after a
successful run that `.agentic-loop/runs/$run_id/verification.txt` exists.

---

## H2. RuntimeError and TimeoutExpired escape `main()` as raw tracebacks

**File:** `runtime/loopctl.py` lines 1118–1124

```python
def main() -> int:
    args = build_parser().parse_args()
    try:
        return args.handler(args)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
```

`RuntimeError` is the primary error type raised throughout the module
(`validate_change_name`, `detect_agent_command`, `openspec_command`, all preconditions in
`command_propose` and `command_run`, Jira helpers), yet `main()` does not catch it.
Confirmed empirically: `loopctl propose` outside an installed repo prints a full Python
traceback instead of a clean error. `subprocess.TimeoutExpired` from the propose stage
also escapes uncaught.

Related: in `command_run` the except clause is
`except (RuntimeError, subprocess.TimeoutExpired)`. Any other exception (e.g.
`urllib.error.URLError` from the Jira start comment, a `FileNotFoundError` reading a
prompt template) bypasses the handler, so `state.json` is left stuck at
`"status": "running"` and no `loop.outcome` failure event is emitted.

**Fix (two parts):**

1. In `main()`, broaden the handler:

```python
    except (RuntimeError, subprocess.TimeoutExpired, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
```

(`json.JSONDecodeError` is a `ValueError` subclass; keeping just `ValueError` is fine.)

2. In `command_run`, change `except (RuntimeError, subprocess.TimeoutExpired) as exc:` to
`except Exception as exc:` so any failure marks the run state failed, emits the
`loop.outcome` event, and posts the Jira failure comment. Keep the `return 1`.

Verification: run `python3 runtime/loopctl.py propose --change x --task y` in an empty
temp git dir — expect a one-line `error: not installed: ...` and exit code 2, no
traceback. `make test` must still pass (smoke.sh relies on non-zero exit for the tamper
case, which both 1 and 2 satisfy).

---

## H3. GitHub workflow "no changes" check misses untracked files

**File:** `templates/github/.github/workflows/agentic-loop.yml`, step "Publish pull request"

```bash
if git diff --quiet && git diff --cached --quiet; then
  echo "Agent produced no changes" >&2
  exit 1
fi
```

`git diff` ignores untracked files. A run in which the agent only *adds* files (new
tests, new modules, plus the always-new `openspec/changes/<change>/` directory) makes
both diffs quiet, so the workflow incorrectly fails with "Agent produced no changes"
even though there is work to publish. The GitLab template already does this correctly
(`test -n "$(git status --porcelain)"`).

**Fix:** replace the condition with:

```bash
if [[ -z "$(git status --porcelain)" ]]; then
  echo "Agent produced no changes" >&2
  exit 1
fi
```

---

## H4. Reviewer read-only guard cannot detect edits to already-dirty files

**File:** `runtime/loopctl.py` lines 976–990 (review stage) and `workspace_status` lines 482–490

The review stage guards against the reviewer modifying the tree by comparing
`git status --porcelain` output before and after:

```python
status_before_review = workspace_status()
...
if workspace_status() != status_before_review:
    raise RuntimeError("reviewer modified the working tree during a read-only stage")
```

`git status --porcelain` lists *paths and states*, not content. After the implement
stages, every file the loop touched is already listed as modified or untracked — so the
reviewer can freely edit any of those files without changing the status output. The
guard only catches edits to files the loop never touched. This defeats the purpose of
the check (the policy digest covers `.agentic-loop/` files, but nothing else).

**Fix:** use content hashes, the same mechanism already used for the propose and test
stages:

```python
hashes_before_review = workspace_hashes()
review_result = run_agent(...)
if review_result and deep_get(config, "review.required", False):
    raise RuntimeError("reviewer agent failed")
if workspace_hashes() != hashes_before_review:
    raise RuntimeError("reviewer modified the working tree during a read-only stage")
```

Delete `workspace_status()` if nothing else uses it afterwards. (Apply M2 first so the
hash walk is cheap and stable.)

---

## M1. `is_test_path` substring matching misclassifies production files as tests

**Files:** `runtime/loopctl.py` lines 507–510; `runtime/quality_gate.py` lines 33, 67–79

```python
markers = ("/test/", "/tests/", ".test.", ".spec.", "_test.", "test_")
return any(marker in lowered for marker in markers)
```

Confirmed empirically: `src/latest_news.py` → `True`, `src/contest_rules.py` → `True`
(`"test_"` is a substring of `latest_` and `contest_`). Consequences: in the red stage
the agent may modify production files whose names happen to contain `test_`/`_test.`
without tripping the "red stage changed non-test files" guard, and `check_tdd` in the
quality gate counts such files as test changes, silently satisfying the TDD gate.

**Fix:** match on path segments and filename prefixes/suffixes instead of raw
substrings. In `runtime/loopctl.py` replace `is_test_path` with:

```python
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
```

In `runtime/quality_gate.py`, delete `TEST_MARKERS` and the two
`any(marker in f"/{path.lower()}" ...)` expressions in `check_tdd`, and use the same
`is_test_path` function (copy it into quality_gate.py — the two scripts are installed as
standalone files and must not import each other).

Add cases to `tests/quality-gate.sh`: a repo where only `latest_news.py` changed must
*fail* the TDD gate (it previously passed because the file was misread as a test).

---

## M2. `workspace_hashes` walks vendored trees, virtualenvs, and caches

**File:** `runtime/loopctl.py` lines 493–504

`workspace_hashes()` hashes every file under the repo except `.git` and
`.agentic-loop/runs`. The CI workflows create `.agentic-loop/python` (a full venv) and
`.agentic-loop/tools` (node_modules) *before* `loopctl run`, and projects routinely have
`node_modules`, `__pycache__`, `.pytest_cache`, `.ruff_cache`. Problems: (a) hashing
thousands of irrelevant files happens 4+ times per slice — slow; (b) cache churn (e.g. a
regenerated `.pyc`, npm metadata) shows up as a changed path and aborts the run with
"red stage changed non-test files" or "proposal stage changed files outside its OpenSpec
change" — false positives unrelated to agent behavior.

**Fix:** skip well-known generated directories. Replace the body's filter section:

```python
SKIP_DIR_NAMES = {
    ".git", "node_modules", "__pycache__", ".pytest_cache", ".ruff_cache",
    ".mypy_cache", ".tox", ".venv", "venv",
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
```

(`.agentic-loop/state.json` must be excluded because `ctx.update()` writes it between
stages.)

---

## M3. Implementer/reviewer prompts duplicate the full spec context twice

**File:** `runtime/loopctl.py` lines 730–732 and 942–943

```python
spec_context = openspec_context(change)
task = spec_context
```

In `command_run`, `task` is set to the entire spec context, and the implementer/reviewer
templates substitute both `{{TASK}}` and `{{SPEC_CONTEXT}}` — so every implement and
review prompt contains the complete proposal/specs/design/tasks **twice**. This wastes a
large fraction of the agent's context window for zero information gain.

**Fix:** make `{{TASK}}` a short statement instead of a duplicate. At line 732:

```python
task = f"Implement the OpenSpec change `{change}` as specified in the context below."
```

and delete the re-assignment `task = spec_context` after a slice completes (line 943 —
keep the `spec_context = openspec_context(change)` refresh on the previous line). The
`write_text(run_dir / "task.md", ...)` at line 742 should keep writing `spec_context`
(rename the variable used there accordingly) so the run artifact still records the full
input.

---

## M4. `loopctl doctor` does not check Docker, but the default verify path requires it

**Files:** `runtime/loopctl.py` `command_doctor` lines 1022–1053; `templates/common/.agentic-loop/bin/verify.sh`; `templates/common/.agentic-loop/bin/smoke.sh`

The default `verify.sh` unconditionally `exec`s `smoke.sh` outside a container, and
`smoke.sh` exits 1 if `docker` is missing — so every slice verification fails on a
machine without Docker, yet `doctor` reports all-ok.

**Fix:** add a check in `command_doctor` after the verification-script check:

```python
checks.append(
    (
        "docker",
        shutil.which("docker") is not None,
        "required by the default per-slice smoke gate (bin/smoke.sh)",
    )
)
```

Keep it fatal (it is required by the default configuration). `shutil` is already
imported.

---

## M5. quality_gate crashes with a traceback when a required tool is missing

**File:** `runtime/quality_gate.py` lines 45–50, 105–146, 149–159

`run()` takes an `optional` keyword that no caller uses (dead parameter), and when e.g.
`pyproject.toml` exists but `ruff` is not on PATH, `subprocess.run` raises
`FileNotFoundError`, which is not in `main()`'s except tuple
(`(RuntimeError, subprocess.CalledProcessError)`) — the gate dies with a raw traceback
instead of the "quality gate failed: ..." message.

**Fix:** in `run()`, remove the `optional` parameter and raise a clean error when the
tool is absent:

```python
def run(command: list[str]) -> None:
    if shutil.which(command[0]) is None:
        raise RuntimeError(f"required tool is not installed: {command[0]}")
    print(f"[run] {' '.join(command)}")
    subprocess.run(command, cwd=ROOT, check=True)
```

The `gofmt` call at line 126–128 uses `subprocess.run` directly with `check=True`; guard
it the same way (`if shutil.which("gofmt") is None: raise RuntimeError(...)`).

---

## M6. Test command is hardcoded while the verify command is configurable

**File:** `runtime/loopctl.py` line 791; `templates/common/.agentic-loop/loop.json`

```python
verification_command = deep_get(config, "verification.command", "./.agentic-loop/bin/verify.sh")
...
test_command = "./.agentic-loop/bin/test.sh"
```

The baseline/red checks always run the bundled `test.sh` with no override, while the
green verification honors `loop.json`. Repos with a nonstandard test entrypoint can
configure verification but not the red gate.

**Fix:** read it from config with the current value as default:

```python
test_command = deep_get(config, "verification.test_command", "./.agentic-loop/bin/test.sh")
```

and add `"test_command": "./.agentic-loop/bin/test.sh"` to the `verification` object in
`templates/common/.agentic-loop/loop.json`.

---

## M7. Transient Jira failures abort otherwise-healthy runs

**File:** `runtime/loopctl.py` lines 796–800 (start comment), 995–1000 (success comment), 699–704 (propose success comment)

The progress/success Jira comments are called bare, so a Jira outage or bad credential:
(a) aborts `command_run` before any work starts, and (b) at lines 995–1000 fails the run
*after* all slices and review have passed (state already marked succeeded, then the
exception flips it to failed). Only the failure-path comments are wrapped in
`contextlib.suppress`.

**Fix:** make the informational comments best-effort. Wrap each of the three call sites:

```python
with contextlib.suppress(Exception):
    jira_comment(...)
```

and emit a telemetry event when suppression happens if you want visibility, e.g.
`telemetry.event("jira.comment_failed", {"agentic_loop.jira.issue": jira_issue})` inside
an `except Exception` instead of plain suppress. Keep `command_jira_comment` (the
explicit CLI subcommand) strict.

---

## M8. verify.sh runs the full test suite 4+ times per verification

**File:** `templates/common/.agentic-loop/bin/verify.sh`

Host path: `quality_gate.py` (which itself runs the project test suite via
`pytest`/`npm test`/`go test`/`cargo test`) → `test.sh` (runs the suite again) → `exec
smoke.sh` → container runs `verify.sh` again with `LOOP_IN_CONTAINER=1`, repeating
`quality_gate.py` + `test.sh` + the project verifier. That is at least four full suite
executions per verification, and verification runs once per implement attempt. The
container is the authoritative environment; the host pre-runs add time, not signal.

**Fix:** in `verify.sh`, when not in the container, delegate to the container
immediately:

```bash
#!/usr/bin/env bash
set -euo pipefail

if [[ "${LOOP_IN_CONTAINER:-0}" != "1" ]]; then
  exec .agentic-loop/bin/smoke.sh
fi

python3 .agentic-loop/bin/quality_gate.py
./.agentic-loop/bin/test.sh
...
```

This also removes the duplicate suite run inside the container (quality_gate already
runs the suite; `test.sh` runs it again). Pick one: keep `quality_gate.py` (lint +
format + TDD + attribution + suite) and drop the separate `./.agentic-loop/bin/test.sh`
line from `verify.sh`, since `loopctl` invokes `test.sh` directly for the baseline/red
gates. Update `tests/docker-smoke.sh` expectations if needed and re-run
`make test-docker`.

---

## L1. Placeholder injection in `render_prompt`

**File:** `runtime/loopctl.py` lines 438–462

Chained `.replace()` calls mean substituted *content* is scanned by later replacements:
if the task text or a spec file contains the literal string `{{VERIFICATION}}` or
`{{SPEC_CONTEXT}}`, it gets expanded too. Single-pass substitution fixes it:

```python
import re

def render_prompt(...) -> str:
    ...
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
```

Note: `{{PLAN}}` is read from `run_dir / "plan.md"` but no shipped prompt template uses
it. Either delete the `plan` plumbing and the `write_text(run_dir / "plan.md", ...)`
call in `command_run`, or leave it — but do not leave it half-wired silently; add a
one-line comment in `render_prompt` stating it is available to user-customized prompts.

## L2. Red gate misreports environment errors as "test did not fail as expected"

**File:** `runtime/loopctl.py` lines 860–869

`test.sh` exits 2 when no test command is detected or pytest is missing. `red_result !=
1` then raises "new test did not fail as expected", which sends the operator hunting a
test problem instead of an environment problem. Fix:

```python
if red_result == 0:
    raise RuntimeError(
        f"new test did not fail as expected for slice '{current_task}'"
    )
if red_result != 1:
    raise RuntimeError(
        f"test command errored (exit {red_result}) during the red stage; "
        f"see slice-{slice_number}-red-result.txt"
    )
```

## L3. `command_telemetry_test` run dir is not 0700

**File:** `runtime/loopctl.py` line 1059. Other run dirs use `mkdir(parents=True,
mode=0o700)`; this one uses the default mode. Change to
`run_dir.mkdir(parents=True, mode=0o700)` for consistency with the artifact-permission
policy elsewhere (0600 files, 0700 dirs).

## L4. install.sh ref heuristic breaks branches that look like versions

**File:** `install.sh` lines 94–97. A branch named `v2-experiments` or `1.x-maintenance`
is fetched from `refs/tags/` and 404s. Fix: try the heads URL first and fall back:

```bash
url_heads="https://github.com/$REPOSITORY/archive/refs/heads/$REF.tar.gz"
url_tags="https://github.com/$REPOSITORY/archive/refs/tags/$REF.tar.gz"
curl -fsSL "$url_heads" -o "$archive" || curl -fsSL "$url_tags" -o "$archive" \
  || die "could not download $REPOSITORY at $REF"
```

## L5. smoke.sh Docker tag can be invalid

**File:** `templates/common/.agentic-loop/bin/smoke.sh` line 9. `basename "$PWD" | tr
-cs ...` leaves a trailing `-` (tr converts the trailing newline) and produces an
invalid tag when the directory name starts with `.` or `-`. Fix:

```bash
slug="$(basename "$PWD" | tr -c '[:alnum:]_.-' '-' | sed -e 's/-*$//' -e 's/^[.-]*//')"
image="agentic-loop-smoke:${slug:-repo}"
```

## L6. JSONL trace_id is not hex

**File:** `runtime/loopctl.py` lines 77, 106. `self.run_id.replace("-", "")[:32]` yields
strings like `proposalfixturechange3f2a...` — not a valid 32-hex trace id, which breaks
downstream correlation if the JSONL is ever ingested. Fix: derive it once in
`JsonlTelemetry.__init__`:

```python
self.trace_id = hashlib.sha256(run_id.encode()).hexdigest()[:32]
```

and use `self.trace_id` in both `span` and `event`. (`hashlib` is already imported in
loopctl.py.)

## L7. Failed-attempt rollback is partial — document it

**File:** `runtime/loopctl.py` line 959. On a failed attempt only `tasks.md` is restored
(`tasks_path.write_text(tasks_before_slice, ...)`); production-code changes from the
failed attempt remain in the working tree for the next attempt. That may be intentional
(let attempt N+1 build on partial progress), but it is undocumented and surprising next
to a line that *does* roll back. Add a brief comment at the rollback site stating that
working-tree changes are deliberately retained and only the task checklist is reset, so
a future maintainer does not "fix" it blindly — or, if full rollback is desired, use
`git stash`/`git checkout` semantics (bigger change; not required).

## L8. README prompt table omits the tester

**File:** `README.md`, "What gets installed" table: `.agentic-loop/prompts/` says
"Proposer, implementer, and reviewer contracts" — the directory also ships
`tester.md`, which drives the red stage. Update the row to "Proposer, tester,
implementer, and reviewer contracts".

---

## Verification checklist after all fixes

1. `make verify` — bash syntax, py_compile, ruff (if installed) all pass.
2. `make test` — smoke, quality-gate, and Jira tests pass.
3. `make test-docker` — Docker slice smoke passes (needed for M8).
4. New negative test from M1 (TDD gate rejects `latest_news.py`-only change) passes.
5. `python3 runtime/loopctl.py propose --change x --task y` in a bare temp git repo
   prints a single-line `error: ...` (H2), no traceback.
