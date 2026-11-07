---
name: investigate-bug
description: Investigate reported bugs and unexpected behavior before changing code. Use when an agent needs to reproduce or understand a defect, distinguish expected from actual behavior, identify the root cause, implement or recommend the smallest appropriate fix, and report focused validation and remaining gaps. Applies even when the same message also asks for unrelated work (a refactor, a new feature, cleanup) alongside the bug report — investigate the bug under this workflow first and keep other explicitly requested work as separate authorized stages.
---

# Investigate Bug

Follow an evidence-first workflow. Do not modify code until the expected behavior, actual behavior, and most likely cause are understood well enough to justify a focused change.

## Workflow

1. Read the repository instructions and relevant local conventions.
2. Restate the reported issue, expected behavior, and observed behavior.
3. Reproduce the issue when practical. If reproduction is unavailable, gather the strongest local evidence and state what is missing.
4. Trace the smallest relevant code, configuration, tests, and documentation surface.
5. Separate plausible causes across application logic, dependencies, configuration, environment, test design, and documentation.
6. Identify the root cause. Do not apply a broad workaround while the cause remains materially uncertain.
7. If the task authorizes a fix, make the smallest change that addresses the cause and preserves unrelated behavior. If the task only asks for diagnosis, stop before editing.
8. Add or update a focused regression test when behavior changes, unless a test is impractical; explain any omission.
9. Run the narrowest relevant validation first. Report commands and outcomes accurately.
10. Report the result using the format below while preserving any repository-required final report structure.

## Guardrails

<!-- investigate-scope-policy: preserve-requested-work-in-separate-stages -->

- Keep investigation and changes within the requested scope.
- When a request bundles a bug report with other explicitly requested work, investigate the bug first and keep its fix focused. Track the other work as separate authorized stages or commits; complete it within the agreed task unless blocked or the user requested diagnosis only. Do not silently drop it, require repeat approval merely because it is separate, or mix it into the bug fix. Unrequested cleanup remains out of scope.
- Preserve public APIs and user-visible behavior unless the requested fix requires a change.
- Do not hide failures by weakening tests, suppressing errors, or adding unexplained retries.
- Do not claim reproduction, validation, or root-cause certainty without evidence.
- Pause for clarification when multiple fixes have meaningfully different compatibility or product trade-offs.

## Report

<!-- skill-report-policy: honor-repository-format -->

Honor the repository's required final report structure when one exists. Include the fields below in a dedicated `Investigation` section or within the repository's required sections; do not replace required top-level sections. Otherwise, use this format:

```text
Investigation:
- Issue: [reported or observed problem]
- Expected: [expected behavior]
- Actual: [observed behavior]
- Root cause: [identified cause, or unknown with missing evidence]
- Affected area: [files, components, or behaviors]
- Fix approach: [change made or recommended, and why]
- Validation: [commands or checks and outcomes]
- Follow-up: [remaining gaps or deferred work]
```
