# agentic-loop-bundle

Install a specification-first, bounded, observable coding-agent loop into an
existing GitHub or GitLab repository.

The bundle turns reviewed intent into an OpenSpec proposal, behavioral
specifications, small implementation slices, cumulative verification,
independent review, and a pull or merge request. Jira can mirror the work and
evidence without becoming a second technical source of truth.

![Agentic loop architecture](docs/images/loop-architecture.png)

![OpenSpec-centered loops](docs/images/specification-loop.png)

## Quick start

Run from the repository you want to configure:

```bash
# GitHub
curl -fsSL https://raw.githubusercontent.com/mwigge/agentic-loop-bundle/main/install.sh \
  | bash -s -- --github --with-signoz --install-deps

# GitLab
curl -fsSL https://raw.githubusercontent.com/mwigge/agentic-loop-bundle/main/install.sh \
  | bash -s -- --gitlab --with-signoz --install-deps
```

Check the setup:

```bash
./loopctl doctor
./loopctl telemetry-test
```

The installer is idempotent and conservative. Changed managed files stop
installation unless `--force` is supplied; replaced files are backed up beneath
`.agentic-loop/backups/`.

## What gets installed

| Path | Purpose |
|---|---|
| `.agentic-loop/loop.json` | Retry, timeout, review, OpenSpec, and telemetry policy |
| `.agentic-loop/prompts/` | Proposer, tester, implementer, and reviewer contracts |
| `.agentic-loop/bin/` | Loop runtime, quality gate, verifier, and Docker smoke runner |
| `.agentic-loop/docker/` | Repository-customizable smoke-test image |
| `loopctl` | Repository-local command |
| `.github/` | GitHub issue template and Actions workflow |
| `.gitlab-ci.agentic-loop.yml` | GitLab loop job |
| `.agentic-loop/observability/signoz/` | Optional standalone SigNoz setup |

OpenSpec changes are checked-in content under `openspec/changes/`. Runtime
evidence is private local state under `.agentic-loop/runs/` and is ignored by
Git.

## Runner requirements

Use a dedicated self-hosted runner labeled or tagged `agentic-loop` with:

- Python 3.10 or newer;
- Node.js 20 or newer;
- Docker with Compose;
- Git;
- Codex, Claude Code, or OpenCode;
- the repository's normal build and test tools.

`--install-deps` installs OpenSpec `1.4.1` repository-locally and the optional
OpenTelemetry and AgentOps Python packages.

The runtime detects Codex, Claude Code, then OpenCode. Override the agent command
when required:

```bash
export LOOP_AGENT_COMMAND='codex exec --full-auto -'
```

## OpenSpec is the work envelope

Free-form implementation runs are not accepted. First create an apply-ready
OpenSpec change:

```bash
./loopctl propose \
  --change add-parser-guard \
  --task "Reject malformed parser input and cover the behavior with tests"

./loopctl run --change add-parser-guard
```

The proposal stage creates and validates:

- `proposal.md`: intent, scope, and impact;
- `specs/*/spec.md`: requirements and scenarios;
- `design.md`: target architecture, shared contracts, migration path, and final acceptance;
- `tasks.md`: ordered, independently verifiable implementation slices.

Large work can create a linked specification subloop:

```bash
./loopctl propose \
  --change add-parser-fuzzing \
  --parent-change add-parser-guard \
  --task "Specify and add bounded parser fuzz testing"
```

The parent relationship is recorded in metadata and telemetry.

## Slice-by-slice without tunnel vision

The runtime selects one unchecked OpenSpec task at a time. Every slice receives
the complete proposal, all specs, the design, the full task graph, prior work,
and the cumulative working-tree diff.

Before changing code, the implementer must explain how the slice advances the
target architecture and which later tasks depend on its contracts. A slice only
advances when:

1. Its test is added or changed first.
2. The smallest cohesive implementation is made.
3. Formatting, import sorting, linting, and tests pass.
4. The complete working tree passes in a disposable Docker container.
5. The OpenSpec task is marked complete.

Verification is cumulative. The loop does not test a slice in isolation and
does not allow locally convenient interfaces that contradict the final design.

## One pull or merge request per slice

Each implemented task slice is published as its own pull or merge request,
reviewed and merged independently before the next slice runs. This keeps
AI-generated diffs small (the proposer targets roughly 200 changed lines per
slice; `publication.max_pr_lines` in `loop.json`, default 400, flags larger
slices on the resulting pull request) and gives a human a merge gate at every
step instead of one large diff at the end.

```text
issue + agent:ready
  -> propose job: opens a spec-only pull request (proposal, specs, design, tasks)
     -> label agent:spec-review
     -> human merges the spec pull request
  -> slice job (runs on merge of any agent/issue-* pull request):
     -> implements the next unchecked task (loopctl run --max-slices 1)
     -> opens a pull request for that slice
     -> remaining slices > 0: label agent:review; merging starts the next slice
     -> remaining slices == 0: holistic review runs; label agent:done
```

| Label | Meaning |
|---|---|
| `agent:queued` | Task proposed for an agent loop |
| `agent:ready` | Approved by a maintainer; starts the propose job |
| `agent:running` | A propose or slice job is active |
| `agent:spec-review` | Spec pull request needs review; merging starts slice 1 |
| `agent:review` | A slice pull request needs review; merging starts the next slice |
| `agent:done` | All slices implemented and published |
| `agent:failed` | Loop needs human attention |

**Recovery from a mid-change failure.** Earlier slices are already merged,
reviewed independently, and verified on their own — the default branch is not
broken. To resume: fix the issue manually and re-run the slice job (push to the
default branch again, or re-trigger), or `./loopctl propose` a new change for
the remaining `tasks.md` items.

Set `"review": {"per_slice": true}` in `loop.json` to run the independent
reviewer on every slice pull request instead of only the final one.

## Example: rate limit for a public API

The same change — add a per-IP rate limit to a public `/search` endpoint,
returning `429 Too Many Requests` with `Retry-After` when exceeded — walked
through end to end for three setups: GitHub with Jira, GitLab with Jira, and a
plain local loop with neither.

In all three, the proposal stage produces a `tasks.md` such as:

```markdown
## 1. Add a token-bucket rate limiter for /search
- [ ] Add a failing test asserting the 11th request within a second from one
      IP returns 429 with a Retry-After header
- [ ] Add a RateLimiter middleware backed by an in-memory token bucket and
      wire it into the /search route
- [ ] Add RATE_LIMIT_PER_SECOND to configuration (default 10)

## 2. Return a structured 429 response body
- [ ] Add a failing test asserting the 429 body matches
      {"error": "rate_limited", "retry_after": <int>}
- [ ] Implement the structured error body and Retry-After header

## 3. Document the limit and add an end-to-end smoke test
- [ ] Add a failing end-to-end test that sends 11 requests to /search and
      checks the 11th response
- [ ] Document RATE_LIMIT_PER_SECOND in docs/api.md
```

### GitHub + Jira

1. A product owner files Jira issue `ENG-742`, "Add a rate limit to the public
   `/search` endpoint", with the description above as the task.
2. A maintainer opens a GitHub **Agent loop task** issue #742 referencing
   `ENG-742` and applies `agent:ready` (or starts the `propose` job directly
   via `workflow_dispatch` with `jira_issue=ENG-742`).
3. The `propose` job runs
   `./loopctl propose --change issue-742 --jira ENG-742` — with no `--task`,
   it pulls the summary and description straight from `ENG-742`. It pushes
   `openspec/changes/issue-742/` on `agent/issue-742-spec`, opens **PR #743**
   "Agent spec: issue #742" labeled `agent:spec-review`, and comments on
   `ENG-742`: "Agentic loop opened GitHub pull request `.../pull/743` for
   OpenSpec change `issue-742` (spec review)."
4. A maintainer reviews the proposal, specs, design, and the `tasks.md` above,
   then merges #743.
5. The `slice` job runs `./loopctl run --change issue-742 --max-slices 1` and
   opens **PR #744** "Agent slice 1/3: Add a token-bucket rate limiter for
   /search (#742)" (~85 changed lines, `agent:review`), commenting on
   `ENG-742`: "Agentic loop opened pull request `.../pull/744` for OpenSpec
   change `issue-742` (slice 1/3, 2 remaining)."
6. Merging #744 starts slice 2: **PR #745** "Agent slice 2/3: Return a
   structured 429 response body (#742)" (~40 changed lines, `agent:review`),
   with a matching Jira comment ("slice 2/3, 1 remaining").
7. Merging #745 starts the final slice. `remaining` reaches `0`, so the
   holistic reviewer runs across the cumulative diff before **PR #746** "Agent
   slice 3/3: Document the limit and add an end-to-end smoke test (#742)"
   (~30 changed lines) is opened. The Jira comment reads "Agentic loop opened
   the final pull request `.../pull/746` for OpenSpec change `issue-742`."
8. Merging #746 labels issue #742 `agent:done`; the maintainer resolves
   `ENG-742`.

### GitLab + Jira

1. A product owner files Jira issue `ENG-900` with the description above.
2. A maintainer starts a pipeline with `LOOP_ISSUE_IID=58` and
   `LOOP_JIRA_ISSUE=ENG-900` set (GitLab issue `#58` tracks the same work).
3. `agentic-loop-propose` runs
   `./loopctl propose --change issue-58 --jira ENG-900`, pulling the task from
   `ENG-900`. It pushes `openspec/changes/issue-58/` on `agent/issue-58-spec`,
   opens **MR !59** "Agent spec: issue #58" labeled `agent:spec-review`, and
   comments on `ENG-900`: "Agentic loop opened GitLab merge request
   `.../merge_requests/59` for OpenSpec change `issue-58` (spec review)."
4. A maintainer reviews the proposal, specs, design, and `tasks.md`, then
   merges `!59` with a merge commit (not fast-forward).
5. `agentic-loop-slice` runs on that push to the default branch, resolves the
   merged commit back to `!59`, confirms its source branch matches
   `agent/issue-58-*`, runs `./loopctl run --change issue-58 --max-slices 1`,
   and opens **MR !60** "Agent slice 1/3: Add a token-bucket rate limiter for
   /search (#58)" (~85 changed lines, `agent:review`), commenting on `ENG-900`:
   "...opened merge request `.../merge_requests/60` for OpenSpec change
   `issue-58` (slice 1/3, 2 remaining)."
6. Merging `!60` (again as a merge commit) triggers **MR !61** "Agent slice
   2/3: Return a structured 429 response body (#58)" (~40 changed lines,
   `agent:review`), with a matching Jira comment ("slice 2/3, 1 remaining").
7. Merging `!61` triggers the final slice. `remaining` reaches `0`, the
   holistic reviewer runs, and **MR !62** "Agent slice 3/3: Document the limit
   and add an end-to-end smoke test (#58)" (~30 changed lines) is opened.
   Merging it labels issue `#58` `agent:done`, and the Jira comment reads
   "Agentic loop opened the final merge request `.../merge_requests/62` for
   OpenSpec change `issue-58`."

### Local only, no GitHub, GitLab, or Jira

The same `tasks.md` can be worked through from any shell, with no issue
tracker, CI, or Jira involved:

```bash
./loopctl propose \
  --change add-rate-limit \
  --task "Add a per-IP rate limit to /search, returning 429 with Retry-After"

./loopctl run --change add-rate-limit --max-slices 1
# 3f9a7b2e-1c4d-4f8a-9e2b-7d6c5a4b3c21
# remaining=2

./loopctl status --change add-rate-limit --json
# {
#   "change": "add-rate-limit",
#   "pending_tasks": [
#     "Return a structured 429 response body",
#     "Document the limit and add an end-to-end smoke test"
#   ],
#   "remaining": 2,
#   "is_complete": false
# }

./loopctl run --change add-rate-limit --max-slices 1
./loopctl run --change add-rate-limit --max-slices 1
# remaining=0
```

Commit and open a pull or merge request after each `--max-slices 1` run if the
slice-per-PR workflow is wanted, or omit `--max-slices` to let one run
implement every remaining task before review.

## Required engineering policy

The generated gate enforces:

- TDD evidence for source changes;
- SOLID design and cohesive, readable code through proposer and review contracts;
- project linting, formatting, import sorting, type checks, and tests where detected;
- a Docker smoke build and run after every task slice;
- independent review against the full OpenSpec end state;
- no AI attribution, generated-by notices, model names, or AI co-author lines.

Customize `.agentic-loop/docker/Dockerfile` with the project's compilers,
services, and dependency installation. Extend
`.agentic-loop/bin/verify.sh` for repository-specific checks. These policy files
are hashed before implementation; an agent cannot weaken them during a run.

## GitHub workflow

1. Install with `--github --configure-remote`.
2. Register a self-hosted runner labeled `agentic-loop`.
3. Add model credentials as Actions secrets.
4. Create an **Agent loop task** issue.
5. A trusted maintainer applies `agent:ready`.

The `propose` job authorizes the trigger, creates `openspec/changes/issue-<number>`
on `agent/issue-<number>-spec`, and opens a spec-only pull request labeled
`agent:spec-review`. It never merges or pushes to the default branch.

The `slice` job runs whenever a human merges a pull request whose head branch
starts with `agent/issue-`. It implements the next unchecked task
(`loopctl run --max-slices 1`) on a new `agent/issue-<number>-slice-<n>` branch
and opens a pull request for that slice. See
[One pull or merge request per slice](#one-pull-or-merge-request-per-slice) for
the full lifecycle and labels.

## GitLab workflow

If `.gitlab-ci.yml` already exists, include:

```yaml
include:
  - local: .gitlab-ci.agentic-loop.yml
```

Register a runner tagged `agentic-loop`, add a protected `GITLAB_TOKEN`, and
start a manual, scheduled, or API pipeline with:

```text
LOOP_ISSUE_IID=123
```

The `agentic-loop-propose` job creates `openspec/changes/issue-123` on
`agent/issue-123-spec` and opens a spec-only merge request labeled
`agent:spec-review`.

The `agentic-loop-slice` job runs on every default-branch push. It checks
whether the new commit belongs to a merged merge request from an
`agent/issue-*` branch; if not, it is a no-op. When it matches, it implements
the next unchecked task (`loopctl run --max-slices 1`) on a new
`agent/issue-123-slice-<n>` branch and opens a merge request for that slice.
This requires a merge method that produces a merge commit (not fast-forward),
so the merged commit can be resolved back to its merge request via the GitLab
API. See
[One pull or merge request per slice](#one-pull-or-merge-request-per-slice) for
the full lifecycle and labels.

## Jira synchronization

Jira is optional but first-class for documenting loop work. OpenSpec remains the
checked-in technical authority.

Configure:

```bash
export JIRA_BASE_URL="https://example.atlassian.net"
export JIRA_EMAIL="developer@example.com"
export JIRA_API_TOKEN="..."
```

Link a loop:

```bash
./loopctl propose --change add-parser-guard --jira ENG-123
./loopctl run --change add-parser-guard --jira ENG-123
```

When no `--task` is supplied, the proposal fetches the Jira summary and
description as intake. The loop comments proposal readiness, run start, success
or failure, and the final PR/MR URL. GitHub workflow dispatch accepts
`jira_issue`; GitLab accepts `LOOP_JIRA_ISSUE`.

## Observability

![Loop observability flow](docs/images/observability-flow.png)

Every run writes private JSONL evidence. With telemetry dependencies installed,
it also emits GenAI OpenTelemetry spans:

```text
loop.propose
loop.run
├── loop.slice.start
├── gen_ai.client.operation
├── loop.verify
├── loop.slice.complete
├── loop.retry
└── gen_ai.client.operation  (review)
```

Attributes correlate repository, platform, OpenSpec change, parent change, Jira
issue, Git issue, commit, task slice, attempt, model system, status, and
duration. Prompt and response bodies are not exported.

Set `AGENTOPS_API_KEY` for optional AgentOps session outcomes. OpenTelemetry
remains the canonical signal.

### Standalone SigNoz

```bash
./.agentic-loop/observability/signoz/signoz.sh up
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318
./loopctl telemetry-test
```

Open `http://localhost:8080`. Suggested panels are documented in
[`dashboards/signoz-queries.md`](dashboards/signoz-queries.md).

## Safety

- Trusted maintainers start repository loops.
- Work stays on review branches with human merge gates.
- Attempts, task slices, and execution time are bounded.
- OpenSpec and verification policy are protected from agent edits.
- Docker smoke tests use the cumulative working tree.
- Concurrent work on one issue is prevented.
- Telemetry excludes prompt and response content by default.
- Dedicated runners and credentials should have minimal permissions.

Do not expose an agent-enabled self-hosted runner to untrusted pull-request
workflows.

## Development

```bash
make verify
```

The suite checks both installers, idempotency, conflicts, proposal-first
execution, multi-slice progress, policy tamper rejection, OpenSpec compatibility,
and local telemetry.

## License

Apache License 2.0.
