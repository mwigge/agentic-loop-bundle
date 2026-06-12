# OpenSpec proposal assignment

You are starting the root loop or a specification subloop for change `{{CHANGE}}`.

Parent change, when this is a subloop: `{{PARENT_CHANGE}}`

Requested outcome:

{{TASK}}

Use the installed OpenSpec CLI to make `openspec/changes/{{CHANGE}}` apply-ready.
Follow OpenSpec's artifact dependency order exactly:

1. Run `openspec status --change "{{CHANGE}}" --json`.
2. For each ready artifact, run
   `openspec instructions <artifact> --change "{{CHANGE}}" --json`.
3. Read dependency artifacts and relevant repository context.
4. Write the instructed artifact to its resolved output path.
5. Continue until `isComplete` is true.
6. Run `openspec validate "{{CHANGE}}"`.

Create proposal, behavioral specs, design, and actionable tasks. Every requirement
must include scenarios. Break work into the smallest independently verifiable task
slices. Every implementation slice must start with a failing test, then name lint,
format, import-sort, deterministic verification, and Docker smoke expectations.
Architecture must follow SOLID principles and keep code small, cohesive, and clear.
Add an integration and end-state section to the design: define the target architecture,
cross-task contracts, dependency order, migration path, compatibility constraints, and
final acceptance test. Tasks must reference those shared contracts rather than define
isolated local solutions.

Each task slice becomes its own pull or merge request, reviewed and merged on its
own before the next slice runs. Keep each slice to roughly 200 changed lines or
fewer, including its test, so the resulting diff stays easy to review. If the
requested outcome cannot be decomposed into slices of that size without leaving
incoherent intermediate states, create a parent change and one or more
specification subloops (`--parent-change`) instead of writing oversized tasks.

Do not modify implementation files. Do not archive the change.
