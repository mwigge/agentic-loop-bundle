# SigNoz dashboard queries

Create a dashboard named **Agentic Loops** and add panels using these trace
attributes. Keeping the queries here makes the dashboard reproducible while
remaining compatible with SigNoz dashboard schema changes.

| Panel | Aggregation | Filter / group |
|---|---|---|
| Loop runs | count | `name = loop.run` |
| Proposals | count | `name = loop.propose` |
| Completed task slices | count | `event = loop.slice.complete` |
| Successful outcomes | count | `event = loop.outcome`, `agentic_loop.outcome = succeeded` |
| Failed outcomes | count | `event = loop.outcome`, `agentic_loop.outcome = failed` |
| Run latency | p50, p95, p99 duration | `name = loop.run` |
| Model operations | count | `name = gen_ai.client.operation`, group by `gen_ai.system` |
| Stage latency | p95 duration | group by `gen_ai.operation.name` |
| Verification failures | count | `name = loop.verify` and error status |
| Retries | count | `event = loop.retry`, group by `agentic_loop.reason` |
| Repositories | count | group by `agentic_loop.repository` |
| OpenSpec changes | count | group by `agentic_loop.change` |
| Jira issues | count | group by `agentic_loop.jira.issue` |

Useful trace-table columns:

- `agentic_loop.run.id`
- `agentic_loop.repository`
- `agentic_loop.platform`
- `agentic_loop.issue.id`
- `agentic_loop.change`
- `agentic_loop.parent_change`
- `agentic_loop.jira.issue`
- `agentic_loop.slice`
- `agentic_loop.task`
- `gen_ai.system`
- `gen_ai.request.model`
- `agentic_loop.attempt`
- duration and status
