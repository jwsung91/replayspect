<!-- agent-rules:
source=https://github.com/jwsung91/agent-rules
profile=claude
source_ref=main
source_commit=c9acb2598f00941fc4f1c5d03e0eb2083fb051a2
generated_at=2026-11-07T17:33:00+09:00
managed_block=true
-->

# replayspect — Claude Code 작업 지침

## 이 프로젝트가 하는 일
로봇–설비(리프트, 도어, 충전기) 연동 프로토콜에서 재시도·타임아웃·중복 응답·재연결 같은
경계 상황 결함을 찾아내고, 시드 하나로 똑같이 재현한다. 양쪽(장치, 클라이언트)을 결정적
시뮬레이션으로 돌리고, 시드 기반으로 링크 장애를 주입하고, 실행 트레이스를 선언된 동작
계약으로 판정한다. 상세 설계는 `docs/design-v0.md`.

## 절대 원칙 (어기는 변경은 하지 말 것)
1. **결정성**: 스레드, `time.sleep`, 실제 시계, 실제 소켓 금지. 모든 사건은
   `Scheduler`를 거치고, 모든 무작위성은 `Scheduler`에서 파생된 스트림에서만 나온다.
   컴포넌트마다 `Scheduler.fork_rng("<컴포넌트 이름>")`으로 자기 스트림을 만들어 쓴다.
   `random` 모듈 전역 함수, `set` 순회 순서, `hash()`에 의존하는 로직 금지.
2. **시간은 정수 마이크로초**: 로직은 `now_us`, `*_us` API만 쓴다. 초 단위 float는 입출력 편의용.
3. **계약이 유일한 정답**: 시뮬레이터 코드는 판정기(`contract/`)를 import하지 않는다.
   시나리오 생성기(무작위, 이후 LLM)는 통과 여부를 결정하지 않는다.
4. **트레이스가 유일한 관찰 경로**: 판정기는 트레이스만 읽는다. 이벤트 kind는
   `send, recv, handle, effect, state, fault` 여섯 개뿐. `recv`(도착)와 `handle`(처리)은 구분한다.
   기록은 `trace.record(actor, kind, name, req_id=None, data=None)` 형식이다. 부가 정보는
   반드시 `data` 딕셔너리 하나로 넘긴다(키워드 인자로 넘기면 TypeError). 요청에 속한 이벤트는
   `req_id`를 빠뜨리지 않는다. 판정기가 req_id별로 세기 때문에 빠지면 위반을 놓친다.
   `actor`, `kind`, `name`은 str, `req_id`는 str 또는 None이어야 하고(아니면 TraceError),
   `data`와 메시지 필드는 같은 규칙(`replayspect/_json.py`)으로 순수 JSON만 허용한다.
   튜플, 정수 키, NaN, 열거형 같은 하위 클래스는 거부되니 열거형은 `.value`로 넘긴다.
5. **같은 시드 = 같은 다이제스트**: 결정성을 깨는 변경은 버그다.
   `tests/test_determinism.py`는 항상 통과해야 한다.

## 개발
```bash
pip install -e ".[dev]"
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q          # 빠른 테스트 (slow 제외)
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q -m ""    # 전체 (작업지시서 검증, 커밋 전)
```
- 시드 수백 개를 도는 테스트는 `@pytest.mark.slow`로 표시한다. 기본 실행에서 빠지고 `-m ""`로 포함된다.
- 이 저장소의 명령 예시는 `python3`를 쓴다(`python`이 없는 환경이 있다).
- ROS 2 환경이 켜진 셸에서는 ROS의 pytest 플러그인이 자동 로드되어 수집 단계에서 실패할 수 있다.
  replayspect는 pytest 플러그인을 쓰지 않으므로 항상 `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`로 실행한다.
- Python 3.11+, 런타임 의존성은 PyYAML뿐. 새 의존성은 먼저 물어볼 것.
- 작업 단위마다 테스트를 먼저 쓰고, 작은 커밋으로 나눈다.
- 작업 단위를 끝내면 README의 Status 체크리스트를 갱신한다.

## 리뷰 보고 방식
작업지시서의 리뷰 단계에서는 찾은 항목을 두 가지로 나눠 보고한다.
- **차단**: 다음 작업지시서의 작업을 시작하기 전에 고쳐야 하는 것. 그대로 두면 다음 작업의
  결과가 틀리거나(특히 판정기의 미탐), 고치는 비용이 크게 늘어나는 것.
- **보류**: 실제 위험이지만 지금 고치지 않아도 되는 것. `docs/backlog.md`에 추가할 문구로
  한두 줄씩 적는다. 직접 파일에 쓰지는 않는다(지시서가 반영한다).
각 항목에는 재현 여부와, 차단이면 막히는 다음 작업을 함께 적는다.

## 현재 상태
- [x] 가상 시간 스케줄러 (`src/replayspect/sim/scheduler.py`), 이름 붙은 RNG 스트림 `fork_rng`
- [x] 트레이스 이벤트 모델과 다이제스트 (`src/replayspect/trace.py`)
- [x] 링크 모델 (`src/replayspect/sim/link.py`)
- [x] 가상 리프트 장치·클라이언트와 뮤턴트 M1~M11 (`src/replayspect/sut/lift.py`, M9~M11은 v2 3차용)
- [x] 계약 YAML과 판정기 (`contracts/lift.v0.yaml`, `src/replayspect/contract/`)
- [x] 실행기, 재현 파일, 축소기, 명령행 (`runner.py`, `shrink.py`, `__main__.py`). v0 완료 기준 4개 충족
- [x] v2 실험 준비: 계획 검사·`base: random`·계획 적용 보고·위반 설명·실행 수 집계
- [x] v2 실험 장치: 계획 세션(`session.py`), MCP 서버(`mcp_server.py`), 기준선·세션 명령행
- [x] v2 1차 시행: M4, 완료 3회(사후 추가 1회 포함), 결과와 해석의 한계는 `docs/experiment-v2.md` "1차 시행 기록"
- [x] 작업 모드 MCP 도구: 별도 서버(`mcp_work.py`)의 search·shrink·replay
- [x] v2 2차 시행: M8, 완료 3회, 기준선과 거의 같음(20 대 21). `docs/experiment-v2.md` "2차 시행 기록"
- [x] v1 Hypothesis 기준선: 계획기와 같은 계획 공간의 생성 계획(`hyp.py`), 결과는 `docs/design-v0.md` "v1 기준선"
- [x] v2 3차 시행: M9·M10·M11, 27회 중 26회 검출, 검출 시 모두 무작위보다 빠름. `docs/experiment-v2.md` "3차 시행 기록"
- [x] 두 번째 시스템: 가상 턴테이블(`turntable.v0`, `src/replayspect/sut/turntable.py`), 뮤턴트 없음. `docs/design-v0.md` "가상 턴테이블"
- [x] v3 WP1 되감기 뷰어: `rewind` 명령(`src/replayspect/rewind.py`), `replay --trace-out`. 트레이스 파일만 읽는다
- [x] v3 WP2 트레이스 스키마: `docs/trace-schema.md`, `schemas/trace-1.schema.json`, `src/replayspect/tracefile.py`. 헤더(선택), 사건마다 fidelity·source, 다이제스트는 사건 핵심 필드만, `rewind --full`은 잘라낸 트레이스 파일
- [x] v3 WP3 구현 변형: `--variant 파일.py:이름`으로 패키지 밖 구현을 실행(`src/replayspect/variant.py`). `System.run`만 바뀌고 repro·세션 로그에 spec과 파일 해시를 남김. 트레이스 헤더와 계획기 출력에는 없음
- [x] v3 WP4 다리 실험: 하네스(`incident.py`, `bridge.py`, MCP `--incident`, `incident` 명령)와 최소 시행. LLM은 로그 4개를 모두 2~6회 만에 재현, 기준선 160세션은 0. 결과·사전 등록과 다른 점은 `docs/experiments/bridge-01.md`. 본 시행은 따로 등록
- [x] v3 WP4 본 시행: 규칙 기반 로그 읽기 재현기(`reconstruct.py`)가 주 기준선, 결함 질문(`name_defect`/`describe_defect`), 증상, 모드(full/answer_only/symptom_only). 35세션. 조건 A는 증상만으로 6/8이라 결함 질문이 너무 쉬웠고, 조건 B는 증상만 4/4 부분, 로그를 본 답 11/12 맞음. 재현은 LLM 11/16(1~6회), 재현기 8/16, 겹침 6. `check_cause`는 16세션 중 1회. 결과·사전 등록과 다른 점은 `docs/experiments/bridge-02.md`
- [x] v3.1 WP5a 텍스트 로그 수집: `ingest LOG --rules RULES --out TRACE`(`src/replayspect/ingest.py`), 규칙 파일 형식은 `docs/rules-schema.md`. 사건마다 `log`(줄 번호·표시, 다이제스트 밖), 헤더 `origin`. 시각순 안정 정렬 후 `out_of_order`/`out_of_tolerance` 표시, 연속 묶음은 `clock_step` 의심으로 요약. 시계 보정·구동 재생은 WP5b
- [x] v3.1 WP5b 구동 재생(구현): `drive`(`src/replayspect/driven.py`). 클라이언트 쪽 로그를 대본으로 재생하고 장치만 모델(`System.device`, 변형은 선택 `device`), `base: fixed`라 시드 없음. 판정은 클라이언트 수신만(폴링 제외), 일치한 수신에 `log.line`. 재현기 연결(`--reconstruct`), 왕복 시간 초기화(`--rtt`), 분할 민감도(`--sensitivity`). 시드 없는 시험(driven-01)은 사전 등록 후
- [x] v3.1 WP5b 시드 없는 시험 driven-01: 클라이언트 로그 17개. 시드 있음 6/17(옛·새 판정 같음), 시드 없음 재현기 그대로 0/17, 왕복 시간 초기화 1/17. 원래 링크 계획이면 µs 17/17, ms 8/17(재연결 순간의 재송신이 ms 절삭으로 재연결 앞에 놓임). `docs/experiments/driven-01.md`. 실물 로그 경로는 남음
- [ ] v3.1 WP5b 맞춤 방식 재설계: `drive --fit`(`src/replayspect/fit.py`). 응답 지연은 계산, 로그의 연결 사건은 사실, 미지수는 요청 도착 시각(첫 선택은 응답이 허락하는 구간의 중간, 한 번에 한 이동, 실행 상한). 설명 불가·유실·중복 보고, `--branches`. 개발용 17개에서 5개 재현(성적 아님). 측정은 새 사건으로 지시 후
- [ ] v3.1 WP5c 테스트베드 1단계: `examples/testbed-uno/`(Uno 펌웨어 `lift_device.h`, Orin 클라이언트·링크, 규칙 파일). 적합성 테스트(네이티브 컴파일, 파이썬 모델과 대조), `drive --link-delay`·`--residuals`. 실물 실행(장치 로그 끔/켬)은 운영자 몫으로 대기
- [ ] 다음: `docs/work-order-v3.md`의 다음 WP (지시 후 시작)

## 실행기와 축소 요약 (구현 완료)
- `python3 -m replayspect search --mutant M4 --target C3`는 무작위 탐색 후 실패 시드 몇 개를 축소해
  가장 작은 재현 파일을 `repros/`에 쓴다. `python3 -m replayspect replay <파일>`로 재생한다.
- 축소의 "같은 위반"은 목표 계약 ID가 위반 목록에 남아 있는가다. 첫 위반 seq·req_id는
  장애를 빼면 바뀌므로 기준으로 쓰지 않는다. seq와 다이제스트는 재생 확인에만 쓴다.
- 축소는 장애(유실·중복·끊김)만 빼고 기본 지연은 남긴다.
- 탐색은 한 번도 일치하지 않은 계약 패턴을 경고한다. 그 계약은 검증되지 않은 것이다.
- `FaultPlan.from_dict`는 모르는/빠진 필드와 잘못된 타입을 거부한다. 계획에 `base: random`을 주면
  지연은 시드와 메시지 키로 뽑고 장애는 계획에 적힌 것만 일어난다(사람·LLM이 쓴 계획용).
- 계획을 준 실행은 `Run.plan_report`로 효과 없던 항목(없는 키, 끊김 중 송신, 안 일어난 끊김)을 알려 준다.

## 계약과 판정기 요약 (구현 완료)
- 계약 종류 8개의 의미와 보고 시점은 `docs/design-v0.md` "계약 DSL" 절이 기준이다.
- 모든 위반은 그것을 증명하는 가장 이른 이벤트에서 보고하고, 실행 끝에서만 알 수 있는
  위반은 `seq = len(trace)`로 보고한다. 실행 종료 시각 `end_us`는 판정기에 명시적으로 넘긴다.
- 판정기는 (실행, 계약)마다 첫 위반의 seq가 `tests/lift_oracle.py`와 같아야 한다.
  계약이나 판정기를 바꾸면 오라클도 함께 바꾸고, 두 쪽이 일치하는지 확인한다.
- YAML에서 전이는 `[from, on, to]` 삼중항으로 쓴다. 따옴표 없는 `on` 키는 YAML 1.1에서 `true`가 된다.

## 리프트와 오라클 요약 (구현 완료)
- 프로토콜, 장치·클라이언트 동작, 트레이스 스키마, 뮤턴트 표는 `docs/design-v0.md` "시험 대상" 절이 기준이다.
- 뮤턴트는 동작만 바꾸고 기록 방식은 바꾸지 않는다. 기록 코드를 뮤턴트 분기 안에 넣지 않는다.
- `tests/lift_oracle.py`는 계약 C1~C8의 의미를 손으로 고정한 참조 판정기다. 제품 코드가 아니다.
- 재현에는 시드와 계획이 함께 필요하다. 계획은 링크만 고정하고, 클라이언트 생각 시간처럼
  엔드포인트가 쓰는 난수는 시드에서 나온다.

## 링크 모델 요약 (구현 완료)
- `Channel`이 `client`↔`device`를 잇는다. 방향은 `c2s`, `s2c`. `send`, `recv`, `fault` 이벤트는
  채널이 직접 기록하고, 엔드포인트는 `handle`, `effect`, `state`만 기록한다.
- 메시지 필드는 JSON으로 왕복해도 그대로인 값만 허용한다(리스트, 문자열 키, NaN 없음).
  튜플이나 정수 키가 있으면 송신 시점에 `LinkError`. 필드는 송신 시점에 스냅샷되고,
  수신자는 매번 독립된 사본을 받는다. `Trace.record`도 data를 JSON 스냅샷으로 저장한다.
- 메시지 메타데이터는 이벤트 data의 예약 키 `link`에 담긴다.
  `n`은 방향별 송신 순번(정보용), `k`는 같은 `(방향, 메시지 이름, req_id)`의 몇 번째 송신인지다.
- 명시 계획은 메시지를 `MsgKey(dir, msg, req_id, k)`로 지정한다. 한 요청의 재시도가
  생기거나 사라져도 다른 요청의 키는 바뀌지 않는다. `req_id`가 없는 메시지는 같은 이름끼리
  카운터를 공유하므로, 계획으로 겨냥할 메시지에는 `req_id`를 붙인다.
  `MsgKey`는 비교 정렬이 안 되므로 `sorted(keys, key=MsgKey.sort_key)`로 정렬한다.
- 모든 송신은 유실되더라도 지연을 추첨하고 `link.delay_us`에 기록한다. 그래서 계획에서
  유실이나 끊김을 빼면 그 메시지는 원래 뽑혔던 지연으로 도착한다.
- `FaultPlan`은 기본 지연(`delays`)과 장애(`faults`, `disconnects`)를 분리한다.
  축소기는 장애만 빼고(`without_fault`), 지연은 그대로 둔다.
- 무작위 모드는 `fork_rng("link/c2s")`, `"link/s2c"`, `"link/disconnect"` 스트림만 쓰고,
  메시지당 추첨 순서(유실 여부 → 지연 → 중복 여부 → 중복일 때만 추가 지연)는 테스트로 고정돼 있다.
- `FaultPlan.from_trace(trace)`로 만든 명시 계획은 같은 시드와 함께 쓰면 같은 다이제스트로 재생된다.
  이 성질은 축소기의 기반이므로 깨지면 안 된다 (`tests/test_link.py`).

## Hypothesis 기준선 요약 (구현 완료)
- `hyp.py`는 Hypothesis가 쓴 `base: random` 계획을 `Session`으로 돌린다. 시드·범위 검사·실행 수가 계획기 세션과 같다.
- 메시지 키는 `System.vocabulary`(`PlanVocabulary`)에서만 뽑는다. 프로토콜 문서에서 읽을 수 있는 것만 넣고 뮤턴트 정보는 넣지 않는다.
- Hypothesis에게 실패를 알리지 않는다(재실행이 다른 시드를 받아 flaky가 되고 예산을 쓴다). 첫 위반은 세션이 기록한다.
- `hyp_search`는 Hypothesis의 로컬 소스 상수 추첨을 막는다(`no_local_constants`, 비공개 훅). Hypothesis를 올릴 때
  `tests/test_hyp.py`의 표식 상수 테스트가 통과하는지 확인하고, 결과에는 Hypothesis 버전을 적는다.
- `hypothesis`는 선택 의존성이다(`pip install -e ".[hyp]"`). 없으면 관련 테스트는 건너뛴다.

## 계획 세션과 MCP 요약 (구현 완료)
- 계획기에게 보이는 문서는 `docs/protocol-lift.md`, `docs/plan-format.md`, 계약 YAML뿐이다.
  턴테이블은 `docs/protocol-turntable.md`와 `contracts/turntable.v0.yaml`이다. 이 파일들에는 뮤턴트나 결함의 단서를 절대 쓰지 않는다. `tests/test_session.py`(턴테이블은 `tests/test_turntable.py`)가 `describe` 결과를 검사한다.
- 세션 API에서 시드 배정·예산·범위·로그를 강제하고 도구 결과에 뮤턴트를 포함하지 않는다. 숨긴 설정의 파일·자동 문맥 노출 차단과 시행 등록은 운영 절차가 맡는다.
- MCP 도구 래퍼는 비동기 함수로 두고 세션 호출 중 await하지 않는다. SDK 2의 작업 스레드로 세션 상태 변경이 분산되지 않게 한다.
- 세션 로그에는 뮤턴트가 적힌다. 계획기가 읽을 수 있는 디렉터리에 두지 않는다. 기존 로그 경로는 재사용할 수 없으며 중단된 시행을 새 로그로 몰래 재시도하지 않는다.
- 같은 시드여도 기준선과 계획은 지연 생성 방식이 다르다. 장애가 많을수록 검출에 유리하다고 가정하지 않는다.
- 시행 경로는 중립 ID로 만들고, 클라이언트 내장 도구·다른 MCP·자동 문맥을 제한한다. `permissions.allow`만으로 도구 전체 허용 목록을 만들 수는 없다.
- `mcp` 패키지는 선택 의존성이다(`pip install -e ".[mcp]"`). 없으면 MCP 서버 테스트는 건너뛴다.
- 작업 모드 서버(`python3 -m replayspect.mcp_work --repros DIR`)는 개발자용이다. 뮤턴트·시드를 숨기지 않고
  예산도 없으므로 시행의 계획기에게 절대 주지 않는다. 실험 서버(`mcp_server.py`)에 작업 도구를 섞지 않는다.
  재현 파일은 `--repros` 안에서만 파일 이름으로 읽고 쓰며 덮어쓰지 않는다.

<!-- agent-rules-managed:start -->

This is the Claude instruction entrypoint for this repository.

## Agent Usage Model

Claude may operate in either mode:

- **Primary Mode**: implementation, documentation update, investigation, or refactoring.
- **Review Mode**: cross-check, risk analysis, scope review, and validation gap review.

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

- This repository installs shared skills under `.claude/skills/`: `investigate-bug`, `review-change`, `validate-change`, `prepare-commit`.
- When a message reports a bug or unexpected behavior, invoke the `investigate-bug` skill before planning any fix — even when the same message also requests unrelated work such as refactoring, new tests, or cleanup. Investigate the bug first and keep its fix focused. Preserve other explicitly requested work as separate authorized stages or commits; do not silently drop it or ask for repeated approval merely because it is separate. Unrequested work remains out of scope.
- When asked to review code, documentation, a diff, working tree, commit, branch, patch, pull request, or completed implementation, invoke the `review-change` skill before reporting findings. Stay in Review Mode and do not modify files unless the user separately authorizes changes. If the requested review target cannot be inspected, report the review as blocked; never substitute a different accessible branch, pull request, commit, repository, or remote target.
- When asked to validate, test, verify, check, or perform pre-commit verification of an existing change, invoke the `validate-change` skill before running checks. Keep validation focused and non-mutating, record the initial worktree state, report exact commands and outcomes, and identify any validation-created changes without deleting or reverting them unless separately authorized.
- When asked to commit, prepare or stage a commit, or write a commit message for the current changes, invoke the `prepare-commit` skill before committing. Review the diff, commit only the requested logical change, run lightweight pre-commit checks including `git diff --check`, and write a Conventional Commits message. Do not amend or rewrite history, reformat code, or include unrelated changes unless separately authorized. Never bypass signing, hooks, or required checks without an explicit user request.
- When a request could match more than one shared skill's trigger (for example, reviewing a pull request that fixes a bug), prioritize `review-change` if the primary ask is judging the quality of an existing change, diff, or pull request; use `investigate-bug` if the primary ask is reproducing or root-causing a defect that has no fix yet; use `validate-change` if the primary ask is executing checks and reporting validation evidence for an existing change; use `prepare-commit` if the primary ask is composing a commit for the current changes. Report defects found while reviewing within `review-change`'s structure unless the user separately asks for a fix. Validation may support either workflow without replacing its primary purpose, and prepare-commit's lightweight pre-commit checks do not replace a full `validate-change` or `review-change` pass.

<!-- agent-rules-managed:end -->

## Repository-specific Boundaries

- The Korean sections above are this repository's boundaries and take precedence: "절대 원칙" (determinism, integer microseconds, contracts as the only oracle, trace as the only observation path, same seed = same digest) and the summaries that follow.
- Never put mutant or defect hints in planner-visible files (`docs/protocol-lift.md`, `docs/plan-format.md`, contract YAML), and never mix work-mode tools into the planning-session server.
- Work follows docs/work-order-v3.md. One WP per branch; stop and report after each WP.

## Validation

- Run the narrowest relevant checks first.
- Add or update tests when behavior changes; explain when not.
- Do not claim validation was run if it was not.
- Before committing, run at minimum: `git diff --check`.
- Use resource-safe parallelism: prefer `-j2` by default, `-j1` under memory pressure or resource-constrained environments (e.g., WSL, VMs).

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

Report validation using this format:

```text
Validation:
- [x] Ran: ...
- [ ] Not run: ... because ...
- Tests: added / updated / not needed / not added because ...
- Documentation: updated / not needed / not updated because ...
```

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

For review reports, put the repository's 차단 / 보류 classification (see "리뷰 보고 방식" above) in an additional section between `## Changes` and `## Validation`.

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
