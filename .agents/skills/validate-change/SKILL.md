---
name: validate-change
description: Select and run focused validation for a current code, documentation, configuration, or build change, then report concrete evidence and remaining gaps without modifying the implementation. Use when asked to validate, test, verify, check, or perform pre-commit verification of an existing change; when an implementation request also requires validation after editing; or when validation commands and scope must be inferred from repository evidence. Do not use as the primary workflow for reviewing change quality or root-causing an unfixed bug.
---

# Validate Change

Validate the requested change with the smallest useful checks and preserve the
integrity of both the evidence and the worktree.

## Workflow

1. Read repository instructions and determine the exact change and validation
   scope. Inspect the diff or changed files when the scope is not explicit.
2. Record the initial worktree state so validation-created changes can be
   distinguished from the user's existing work.
3. Discover repository-provided validation commands from entrypoints,
   documentation, configuration, build files, CI, and nearby tests. Prefer
   documented commands over guesses.
4. Select the narrowest checks that cover the affected behavior. Start with
   changed-file checks or focused tests, then broaden only when risk or explicit
   repository guidance justifies it.
5. Prefer check-only modes. Do not run formatters, generators, snapshot updates,
   dependency installation, or other commands that intentionally rewrite files
   unless the user authorized those mutations.
6. Run commands with resource-safe settings. Use repository defaults when
   documented; otherwise avoid unbounded parallelism and split expensive suites
   into smaller steps.
7. Stop broadening validation after a relevant failure until its relationship
   to the change is understood. Distinguish product failures from environment,
   permission, dependency, and resource failures.
8. Compare the final worktree with the recorded initial state. Do not delete or
   revert unexpected artifacts without authorization; identify them and explain
   their likely source.
9. Report exact commands, outcomes, skipped checks, worktree effects, and the
   remaining confidence gap. Never imply that a broader suite passed when only
   a focused subset ran.

## Validation Selection

- Documentation-only changes: run documentation lint, link, spelling, or
  formatting checks when configured; otherwise use repository baseline checks.
- Code changes: run the closest affected tests and changed-file lint or type
  checks before package or repository-wide suites.
- Build or dependency changes: validate the smallest affected build or metadata
  surface, then expand to integration checks when practical.
- Configuration or CI changes: use native validators, dry runs, or syntax checks
  before commands that contact external services or mutate remote state.
- Every change: include `git diff --check` when Git is available and repository
  instructions do not provide an equivalent or stronger baseline.

## Guardrails

<!-- validate-scope-policy: execute-checks-without-review-substitution -->

- Keep validation read-only with respect to the implementation unless the user
  separately authorizes fixes or generated updates.
- Do not turn a validation request into a general code review. Report a concrete
  defect exposed by a check, but use `review-change` when the primary ask is to
  judge change quality, regressions, or risks.
- Do not use validation success as proof that an unresolved bug's root cause is
  known; use `investigate-bug` when diagnosis is the primary ask.
- Do not invent commands solely from ecosystem convention when repository
  evidence contradicts or does not support them. Label plausible but unverified
  commands as follow-up suggestions rather than executed repository commands.
- Do not weaken, skip, or rewrite failing tests to obtain a passing result.
- Do not install dependencies, access production systems, or mutate remote state
  merely to increase validation coverage without the required authorization.

## Report

<!-- skill-report-policy: honor-repository-format -->

Honor the repository's required final report structure when one exists. Include
the fields below within its Validation section; do not replace required
top-level sections. Otherwise, use this format:

```text
Validation:
- [x] Ran: [exact command] — [outcome]
- [ ] Not run: [command or check] because [reason]
- Scope: [changed files or behavior covered]
- Worktree: [unchanged, or artifacts/changes observed]
- Tests: [added, updated, not needed, or not added because]
- Documentation: [updated, not needed, or not updated because]
- Remaining gap: [unvalidated risk or none identified]
```
