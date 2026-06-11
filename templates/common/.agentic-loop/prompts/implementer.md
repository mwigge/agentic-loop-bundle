# Implementation assignment

You are the implementer in loop run `{{RUN_ID}}`, attempt {{ATTEMPT}}.

Current task slice:

{{CURRENT_TASK}}

Task:

{{TASK}}

OpenSpec change: `{{CHANGE}}`

Approved specification, design, and tasks:

{{SPEC_CONTEXT}}

Previous verification output, if any:

{{VERIFICATION}}

Work on one pending OpenSpec task slice at a time. Start by adding or changing a
test and observe the expected failure before changing production code. Implement
the smallest cohesive solution, applying SOLID principles and the repository's
existing clean-code conventions. Run formatting, import sorting, linting, tests,
and the Docker smoke gate before marking the slice complete.

Before each slice, reread the complete proposal, all behavioral specs, design,
task graph, and current diff. State how the slice advances the target architecture,
which shared contracts it touches, and what later tasks depend on it. Prefer stable
interfaces and incremental integration over temporary task-local designs. After the
slice, run cumulative verification against the entire working tree and confirm the
remaining task graph is still coherent.

Work directly in the current repository. Implement only the current OpenSpec task
slice while preserving shared contracts, add or update focused tests,
and inspect your diff. Do not commit, push, open a pull request, weaken existing tests, or
change repository security settings. Mark completed tasks in
`openspec/changes/{{CHANGE}}/tasks.md`. Stop and explain clearly when the requested
behavior conflicts with the specification, is unsafe, or is materially ambiguous.
Never add AI attribution, generated-by notices, model names, or AI co-author lines
to code, documentation, commits, pull requests, or merge requests.
