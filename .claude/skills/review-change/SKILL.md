---
name: review-change
description: Review code and documentation changes for actionable defects, regressions, security or compatibility risks, and validation gaps without modifying files. Use when asked to review a working tree, diff, commit, branch, pull request, patch, or completed implementation; verify claims against repository instructions and relevant code, prioritize findings by severity, and report file-and-line evidence. Also use when asked to review a change for over-engineering or unnecessary complexity. Do not use for requests to implement or fix changes unless review is the requested first phase.
---

# Review Change

Review the requested change as an evidence-backed reviewer. Focus on problems introduced or exposed by the change, not on rewriting it to match personal preferences.

## Workflow

1. Read the repository instructions and determine the requested review scope, comparison base, and changed files. If the base is ambiguous and cannot be inferred safely, ask before drawing conclusions. If the requested target cannot be inspected, report the review as blocked; never substitute another accessible branch, pull request, commit, repository, or remote target. Accessing the same requested target through another reference is allowed only after verifying that the reference identifies that exact target and does not change the review scope.
2. Inspect the complete diff and enough surrounding code, tests, configuration, and documentation to understand the intended behavior and existing invariants.
3. Trace affected callers, data flows, failure paths, and compatibility boundaries when the change can influence behavior outside the edited lines.
4. Look for correctness defects, regressions, security or privacy risks, unsafe error handling, concurrency or state problems, compatibility breaks, and missing validation that could allow those problems through.
5. Verify each candidate finding against concrete code or test evidence. Exclude speculation, unchanged pre-existing problems, and purely stylistic preferences unless they create a material maintenance or correctness risk.
6. Run the narrowest useful read-only checks when practical. Do not modify files, dependencies, remote state, or the pull request unless the user separately authorizes changes.
7. Within the repository-required report structure, place actionable findings at the earliest permitted position and order them by severity. If no actionable findings remain, say so explicitly and describe any validation gaps or residual risks.

## Optional Complexity Review

When the user asks whether the scoped change is over-engineered or could be
simpler, also inspect duplicate implementations, unnecessary dependencies,
speculative extension points, and abstractions without a demonstrated purpose.
Keep ordinary reviews focused on actionable defects; do not add a complexity
pass to every review or expand a diff review into a repository-wide audit.

For each simplification suggestion, cite the code and an existing alternative,
explain the maintenance benefit, and check that required behavior, compatibility,
and validation survive. A single caller or implementation alone does not prove
an abstraction is unnecessary. Preserve purposeful boundaries, security checks,
error handling, and tests; fewer lines alone are not a benefit.

Separate optional suggestions from severity-ranked defects and leave them
unrated unless a concrete defect is demonstrated. Complexity review complements
correctness and security review; it never establishes that a change is safe to
merge. If the user requests only complexity review, state that coverage limit.
Propose changes without applying them, and do not invent suggestions when the
scoped code has no supported simplification opportunity.

## Severity

- **P0 — Critical**: Causes widespread data loss, security compromise, or an unusable release and requires immediate action.
- **P1 — High**: Likely causes incorrect behavior, a serious regression, or a meaningful security or compatibility failure in normal use.
- **P2 — Medium**: Causes a bounded defect or reliability problem under realistic conditions but does not broadly block use.
- **P3 — Low**: Creates a small but concrete correctness, operability, or maintainability risk worth fixing.

Do not assign a severity to suggestions that are optional improvements rather than defects.

<!-- review-severity-policy: require-repository-evidence -->

Calibrate severity to evidence in the reviewed repository, not to a hypothetical deployment. Never assign P0 based only on a function name, the magnitude of an incorrect value, a failing unit test, or imagined callers. P0 requires direct repository evidence that the changed path reaches production or release-critical behavior and that its impact is widespread. Without that evidence, choose P1 or lower based on the behavior demonstrated in the reviewed scope and state material uncertainty about reach.

## Finding Quality

For each finding:

- Use a concise, imperative title that identifies the problem.
- Cite the narrowest relevant file and line or diff location.
- Explain the triggering condition and user or system impact.
- State why the current tests or safeguards do not prevent it.
- Recommend the smallest direction for correction without implementing it.
- Keep separate root causes in separate findings; combine duplicate symptoms of the same cause.

## Guardrails

<!-- review-scope-policy: do-not-substitute-unverified-target -->

- Stay in Review Mode. Do not turn a review request into an implementation task.
- If the requested diff or target is unavailable, stop with a validation gap. Do not review a different remote branch or pull request merely because it is accessible.
- Treat user-provided claims, commit messages, and PR descriptions as hypotheses to verify, not proof.
- Do not report a finding solely because validation was not run; describe that as a validation gap unless a concrete defect follows from the omission.
- Do not hide uncertainty. Label assumptions and unresolved questions that materially affect the review.
- When the repository requires Summary before Findings, keep Summary factual: state the finding count, highest severity, and review disposition without praising or extensively recapping the change.

## Report

<!-- skill-report-policy: honor-repository-format -->

Honor the repository's required final report structure and do not replace, rename, or combine required top-level sections. When the repository permits additional sections between Changes and Validation, place `## Findings` there.

In `## Findings`, list findings from P0 to P3 using this form:

```text
- [P1] Prevent stale authorization from being reused — path/to/file.py:42
  - Impact: [what fails and under which conditions]
  - Evidence: [specific code path, behavior, or check]
  - Recommendation: [smallest correction direction]
```

If there are no actionable findings, write `No actionable findings.` Include assumptions, validation gaps, and residual risks in the repository's required sections or concise additional subsections.
