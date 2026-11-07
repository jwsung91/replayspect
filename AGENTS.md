# AGENTS.md

<!-- agent-rules:
source=https://github.com/jwsung91/agent-rules
profile=codex
source_ref=main
source_commit=172c789ae3202badd6ede69aaeca59d1b2003c9d
generated_at=2026-11-07T03:44:20+00:00
managed_block=true
-->

<!-- agent-rules-managed:start -->

This repository follows the shared agent rules from:

- https://github.com/jwsung91/agent-rules

Use this file as the repository-local instruction entrypoint.

If internet access is available, agents may consult the shared rules repository for detailed guidance. The rules below are the local summary that must be followed even when external links are not available.

## Agent Usage Model

Use agent roles as execution modes, not fixed tool identities.

- Primary Mode: implementation, documentation update, investigation, or refactoring.
- Review Mode: cross-check, review, risk analysis, and validation gap review.

Use the mode requested by the task.

## Core Rules

- Investigate existing code, documentation, and behavior before editing.
- Keep changes scoped to the requested task.
- Preserve the agreed objective, authorized scope, and completion criteria across follow-ups. A status question does not cancel ongoing work; a short continuation resumes the agreed next step without expanding authorization.
- Separate explicitly requested additional work into stages or commits and keep it in the task; do not silently discard it as scope creep. Unrequested work stays out.
- For long-running work, retain a compact checkpoint of the repository, branch, execution environment, decisions, remaining steps, and latest evidence. Verify it against current state before resuming.
- Before performance experiments, define the baseline, target, allowed regressions, and experiment budget; stop or reassess when the budget is spent or evidence rejects the hypothesis.
- Before publishing a PR or release, inspect the destination repository's template and required submission procedure. Before merging, verify the intended head, required checks, and merge result.
- Never bypass commit signing, hooks, or required checks merely to make progress. Use an authorized working path or report the blocker; bypass requires an explicit user request.
- Do not refactor unrelated files, or rename public APIs, files, directories, or user-facing concepts, unless explicitly requested.
- Prefer simple, explicit, maintainable changes.
- After understanding the problem, prefer existing code, standard libraries, native platform features, and installed dependencies before new code, when they satisfy the required behavior and project conventions.
- Simplify implementation without dropping agreed requirements, compatibility, safety controls, or risk-appropriate validation; readable code matters more than minimum line counts.
- Preserve existing structure, naming, and documentation tone.
- Avoid new dependencies unless they have a clear, task-specific justification.
- Follow repository-local formatter, linter, test, PR template, and verification conventions.
- Consider risks, compatibility concerns, and validation gaps appropriate to the task.
- Respond to the user in the language of their latest message. Write commit messages, PR titles and descriptions, code comments, and repository docs in English unless the repository's conventions or PR template use another language. Keep code, commands, identifiers, and required report headings unchanged.
- Ask for clarification before proceeding when scope is ambiguous, instructions conflict, or a destructive action lacks explicit authorization.

## Commit Messages

Use Conventional Commits:

```text
<type>[optional scope]: <description>
```

Common types: `feat`, `fix`, `docs`, `test`, `refactor`, `style`, `perf`, `build`, `ci`, `chore`.

Use `!` or a `BREAKING CHANGE:` footer for compatibility-breaking changes.
Keep the subject concise, lowercase, imperative mood, no trailing period.

## Shared Skills

- This repository installs shared skills under `.agents/skills/`: `investigate-bug`, `review-change`, `validate-change`, `prepare-commit`.
- When a message reports a bug or unexpected behavior, invoke the `investigate-bug` skill before planning any fix — even when the same message also requests unrelated work such as refactoring, new tests, or cleanup. Investigate the bug first and keep its fix focused. Preserve other explicitly requested work as separate authorized stages or commits; do not silently drop it or ask for repeated approval merely because it is separate. Unrequested work remains out of scope.
- When asked to review code, documentation, a diff, working tree, commit, branch, patch, pull request, or completed implementation, invoke the `review-change` skill before reporting findings. Stay in Review Mode and do not modify files unless the user separately authorizes changes. If the requested review target cannot be inspected, report the review as blocked; never substitute a different accessible branch, pull request, commit, repository, or remote target.
- When asked to validate, test, verify, check, or perform pre-commit verification of an existing change, invoke the `validate-change` skill before running checks. Keep validation focused and non-mutating, record the initial worktree state, report exact commands and outcomes, and identify any validation-created changes without deleting or reverting them unless separately authorized.
- When asked to commit, prepare or stage a commit, or write a commit message for the current changes, invoke the `prepare-commit` skill before committing. Review the diff, commit only the requested logical change, run lightweight pre-commit checks including `git diff --check`, and write a Conventional Commits message. Do not amend or rewrite history, reformat code, or include unrelated changes unless separately authorized. Never bypass signing, hooks, or required checks without an explicit user request.
- When a request could match more than one shared skill's trigger (for example, reviewing a pull request that fixes a bug), prioritize `review-change` if the primary ask is judging the quality of an existing change, diff, or pull request; use `investigate-bug` if the primary ask is reproducing or root-causing a defect that has no fix yet; use `validate-change` if the primary ask is executing checks and reporting validation evidence for an existing change; use `prepare-commit` if the primary ask is composing a commit for the current changes. Report defects found while reviewing within `review-change`'s structure unless the user separately asks for a fix. Validation may support either workflow without replacing its primary purpose, and prepare-commit's lightweight pre-commit checks do not replace a full `validate-change` or `review-change` pass.

<!-- agent-rules-managed:end -->

## Repository-specific Boundaries

<!-- agent-rules-local:boundaries:start -->
- 시뮬레이션은 Scheduler로만 구동하고 스레드·실제 시계·time.sleep·실제 소켓을 사용하지 않는다. 컴포넌트별 난수는 Scheduler.fork_rng의 이름 붙은 스트림으로 분리하며, 전역 random 함수·hash()·set 순회 순서에 실행 결과가 의존하지 않게 한다. 같은 코드·입력·시드의 canonical JSONL과 SHA-256 다이제스트는 프로세스와 PYTHONHASHSEED가 달라도 같아야 한다.
- 시간 로직은 정수 마이크로초와 now_us·*_us API를 사용하고 초 단위 float는 입출력 편의에만 사용한다. 같은 시각의 사건은 등록 순서대로 실행하며, 실행 중 현재 시각에 추가한 사건도 기존 대기 사건 뒤에 둔다. run_until_us는 종료 시각의 사건까지 처리하고 사건이 없어도 시계를 종료 시각까지 진행시킨다.
- 계약만 통과 여부를 결정한다. 시뮬레이터와 시험 대상은 contract/를 import하지 않고, 무작위·LLM 시나리오 생성기는 판정을 맡지 않는다. 판정기는 시험 대상의 내부 상태 대신 트레이스만 관찰한다.
- 이벤트 kind는 send·recv·handle·effect·state·fault로 유지하고 도착(recv)과 처리(handle)를 구분한다. Channel은 send·recv·fault를, 엔드포인트는 handle·effect·state를 기록한다. trace.record의 부가 정보는 data 매핑 하나로 전달하고, 요청에 속한 이벤트에는 req_id를 넣는다. actor·kind·name은 순수 str, req_id는 순수 str 또는 None으로 전달한다.
- 트레이스 data와 메시지 필드는 _json.py의 순수 JSON 규칙을 공유한다. 튜플·문자열이 아닌 키·비유한 실수·열거형 등 하위 클래스는 허용하지 않고 열거형은 .value로 전달한다. 기록·송신 시점의 깊은 스냅샷과 수신 사본 간 독립성을 보존하며, 메시지 필드에서 예약 키 link를 사용하지 않는다.
- 링크 방향은 c2s·s2c로 유지하고 명시 계획은 MsgKey(dir, msg, req_id, k)로 송신을 식별한다. link.n은 방향별 전체 순번인 정보용 값이며 계획 식별자로 사용하지 않는다. 계획으로 겨냥하는 메시지에는 req_id를 부여하고, 키 정렬은 MsgKey.sort_key를 사용한다. 연결 단위 무ID 메시지를 추가할 때는 공유 k 카운터의 불안정성을 다시 검토한다.
- 무작위 링크는 link/c2s·link/s2c·link/disconnect RNG 스트림과 메시지별 추첨 순서(유실 여부 → 지연 → 중복 여부 → 중복일 때 추가 지연)를 보존한다. 유실되거나 끊김 중 보낸 메시지도 지연을 결정해 link.delay_us에 기록한다. 끊김 전 전송 중이던 메시지는 재연결 후에도 이전 연결의 메시지로 폐기한다.
- 외부 계획은 FaultPlan.from_dict로 파싱하고 알 수 없는 필드·필수 필드 누락·잘못된 타입을 거부한다. 명시 계획에는 기재된 장애만 적용한다. base=fixed의 미지정 지연은 프로필 하한, base=random의 미지정 지연은 시드와 메시지 키로 결정하며 명시 지연이 우선한다. 실행 후 Run.plan_report로 미일치 항목·끊김에 가려진 장애·미적용 끊김을 확인한다.
- 계약 종류 8개의 의미와 보고 시점은 docs/design-v0.md의 계약 DSL을 기준으로 유지한다. YAML 전이는 [from, on, to] 삼중항으로 작성하고 YAML 불리언으로 해석될 이름은 문자열로 명시한다. 조건식은 지원하는 피연산자와 ==·!=로 제한하며 임의 코드를 실행하지 않는다. last(pattern)은 현재 이벤트 이전의 일치 이벤트를 참조하도록 판정 후 갱신한다.
- 위반은 증명 가능한 가장 이른 이벤트에서 보고하고 실행 종료 시점에만 확인할 수 있으면 seq=len(trace)를 사용한다. end_us는 실제 시뮬레이션 종료 시각을 명시적으로 전달하며 마지막 이벤트 시각으로 대체하지 않는다. 계약이나 판정기 변경 시 독립 참조인 tests/lift_oracle.py도 함께 검토·갱신하고 실행·계약별 첫 위반 seq의 일치를 확인한다. 참조 오라클을 제품 코드에서 사용하지 않는다.
- 리프트 프로토콜·트레이스 스키마·뮤턴트의 의미는 docs/design-v0.md의 시험 대상 절을 기준으로 유지한다. 정상 장치는 재연결 후에도 중복 제거 결과를 유지하고 클라이언트가 복구를 주도한다. 뮤턴트는 동작만 바꾸며 기록 코드를 뮤턴트 분기에 넣거나 결함을 감추도록 기록 방식을 변경하지 않는다.
- 재현에는 시드와 명시 계획을 함께 보존하고 system·mutants·until_us도 저장한다. FaultPlan.from_trace로 추출한 계획은 같은 시드와 실행 조건에서 원본 다이제스트를 재현해야 한다. 재생 성공은 다이제스트·계약별 첫 위반 목록·목표 계약 위반을 모두 확인한 경우에만 인정한다. 현재 첫 위반 목록 비교에는 detail도 포함되므로 설명 문구 변경도 기존 재현 파일에 영향을 줄 수 있다. explain은 재생 비교 대상이 아니다.
- 축소는 목표 계약 ID가 계속 위반되는지를 기준으로 수행하고 첫 위반 seq·req_id·다이제스트의 동일성을 요구하지 않는다. 기본 지연과 base는 유지하고 유실·중복·끊김만 제거한다. 후보 원본 실행을 재사용하며 명시 계획 재생을 확인한 뒤 축소한다. 탐색 실행 수와 모든 후보의 재생·축소 실행 수를 구분해 보고한다. 축소 결과를 전역 최소라고 표현하지 않으며 실행 예산으로 중단되면 1-minimal도 보장하지 않는다.
- 탐색에서 한 번도 일치하지 않은 계약 패턴은 미검증으로 경고하고 위반 없음과 검증 완료를 구분한다. C1은 직접 겨냥하는 v0 뮤턴트가 없으므로 손으로 만든 트레이스 검증을 유지한다.
- Python 3.11 이상과 현재 런타임 의존성 PyYAML을 기준으로 개발하고 새 의존성 추가는 먼저 확인한다. 현재 개발 설치는 pip install -e ".[dev]"를 사용하고 명령 예시는 python3로 작성한다. 테스트 실행이 허용된 작업에서는 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q를 기본으로, 작업지시서 검증·커밋 전에는 -m ""를 추가해 전체를 확인한다. 대규모 시드 순회는 pytest.mark.slow로 표시한다.
- 기존 개발 절차인 작업 단위별 테스트 우선 작성과 작은 커밋을 유지하고, 작업 단위 완료 시 README의 Status 체크리스트를 갱신한다. 작업지시서 리뷰는 차단·보류로 구분하고 각 항목에 재현 여부, 차단 항목에는 막히는 다음 작업을 적는다. 보류 항목은 docs/backlog.md에 넣을 문구로 제안하며 리뷰 중 직접 기록하지 않는다. 관련 작업 시작 시 기존 보류 항목을 다시 검토한다.
- 계획기에게 보이는 문서(docs/protocol-lift.md, docs/plan-format.md, 계약 YAML)에는 뮤턴트·결함 단서나 운영자 쪽 파일 경로를 쓰지 않는다. 작업 모드 서버(replayspect.mcp_work)는 뮤턴트·시드를 숨기지 않으므로 실험 서버(mcp_server)에 섞거나 시행의 계획기에게 주지 않는다.
<!-- agent-rules-local:boundaries:end -->

## Validation

Before choosing commands, check repository-local scripts and configuration first.

<!-- agent-rules-local:validation_commands:start -->
Confirmed for this repository:

```bash
git diff --check
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest -q          # fast tests (slow excluded)
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest -q -m ""    # everything, before committing
```

`python` may be missing (use `python3`), and plugin autoload must stay disabled (ROS 2 shells
inject pytest plugins). MCP tests are skipped unless the `mcp` extra is installed.
<!-- agent-rules-local:validation_commands:end -->

Use conservative parallelism for local build or test validation when the environment is unknown. Prefer `-j2`, or `-j1` when memory pressure, OOM, VM/WSL constraints, embedded devices, or previous instability are involved.

If validation cannot be run, explain why and provide the command that should be run later.

## Final Report

For simple questions and progress updates, answer directly without mandatory headings.
For completed implementation or review reports, use the structure below. For PRs,
follow the destination repository template when one exists.

Before sending the response, verify that these Markdown headings appear verbatim, exactly once, and in this order; do not rename, omit, or combine them. Additional sections may appear after `## Changes` and before `## Validation`.

1. `## Summary`
2. `## Changes`
3. `## Validation`
4. `## Not Included`
5. `## Follow-up`

- **Summary**: what changed and why; begin with progress against the agreed plan
- **Changes**: files and behaviors affected
- **Validation**: what was run and results
- **Not Included**: what was intentionally left out
- **Follow-up**: known gaps or deferred work

For multi-step work, report completed stages out of the agreed total, the current
stage, remaining requested work, and blockers (or none) near the start of the
report, within Summary when that heading is required. Use meaningful stages and
completion evidence; do not invent percentages or split stages to inflate progress.
Stage counts describe scope completion, not elapsed time or effort. Include
requested PR, merge, or deployment steps before calling the whole task complete.
When additional requests change the plan, state the change and update the total;
do not silently drop unfinished work or count optional suggestions as requested work.
For small tasks, one sentence stating completion and remaining work is enough.
Progress reporting does not create a new approval gate or authorize extra actions.
