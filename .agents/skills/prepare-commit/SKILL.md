---
name: prepare-commit
description: Prepare a well-scoped, conventional commit for the current changes — review the diff, confirm scope, run lightweight pre-commit checks, and write a Conventional Commits message without committing unrelated work. Use when asked to commit, prepare or stage a commit, or write a commit message for existing changes. Do not use as the primary workflow for reviewing change quality, root-causing a bug, or running a full validation suite.
---

# Prepare Commit

Turn the current changes into one well-scoped, conventionally formatted commit
without sweeping in unrelated work.

## Workflow

1. Read repository instructions (commit conventions, hooks, required checks) and
   inspect the current changes with `git status` and `git diff` for both staged
   and unstaged work before composing anything.
2. Confirm the change is a single logical unit. If the working tree mixes
   unrelated changes, stage only the files that belong together and leave the
   rest for a separate commit; state what you excluded.
3. Run the narrowest relevant pre-commit checks, including `git diff --check`
   for whitespace and conflict markers. Prefer documented repository checks over
   guesses and keep them non-mutating.
4. Do not reformat, refactor, or edit code to "clean up" while committing.
   Commit the change as it is unless the user separately authorizes edits.
5. Write a Conventional Commits message of the form
   `<type>[optional scope]: <description>` in lowercase, imperative mood, with no
   trailing period. Use `!` or a `BREAKING CHANGE:` footer for compatibility
   breaks.
6. Verify the subject matches what actually changed; do not describe intended or
   unrelated work. Add a body only when the reason for the change is not obvious
   from the diff.
7. Stop and ask before committing when scope is ambiguous, the diff contains
   unexpected or unrelated changes, or a required check fails.

## Commit Message

- `type` is one of feat, fix, docs, test, refactor, style, perf, build, ci, or
  chore; choose the one that matches the actual change.
- Keep the subject concise and specific. Scope is optional and lowercase.
- Group related changes; never bundle unrelated changes into one commit.
- Do not claim validation, tests, or documentation that the commit does not
  actually include.

## Guardrails

<!-- prepare-commit-scope-policy: single-logical-change-conventional-message -->

- Commit only the requested logical change. Do not stage or commit unrelated
  edits, generated artifacts, or secrets that happen to be in the worktree.
- Do not amend, rebase, force-push, or rewrite existing history unless the user
  explicitly asks; prefer creating a new commit.
- Do not skip hooks or bypass signing (for example `--no-verify` or
  `--no-gpg-sign`) unless the user explicitly requests it; if a hook fails,
  report it rather than working around it.
- Do not turn commit preparation into a review or a full validation run. Run
  only lightweight pre-commit checks and use `review-change` or
  `validate-change` when deeper analysis is the primary ask.
- Do not invent a Conventional Commits type to look compliant; pick the type
  that matches the change.

## Report

<!-- skill-report-policy: honor-repository-format -->

Honor the repository's required final report structure when one exists; include
the fields below within it and do not replace required top-level sections.
Otherwise, use this format:

```text
Commit:
- Message: <type>[scope]: <subject>
- Staged: [files included in the commit]
- Excluded: [unrelated changes left out, or none]
- Checks: [pre-commit checks run and outcomes, e.g. git diff --check]
- Committed: [yes, or no — awaiting confirmation because ...]
```
