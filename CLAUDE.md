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
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q
```
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
- [x] 가상 리프트 장치·클라이언트와 뮤턴트 M1~M8 (`src/replayspect/sut/lift.py`)
- [ ] **다음 작업: 계약 YAML과 판정기** (별도 작업지시서). 결과가 `tests/lift_oracle.py`와 같아야 한다

## 리프트와 오라클 요약 (구현 완료)
- 프로토콜, 장치·클라이언트 동작, 트레이스 스키마, 뮤턴트 표는 `docs/design-v0.md` "시험 대상" 절이 기준이다.
- 뮤턴트는 동작만 바꾸고 기록 방식은 바꾸지 않는다. 기록 코드를 뮤턴트 분기 안에 넣지 않는다.
- `tests/lift_oracle.py`는 계약 C1~C8의 의미를 손으로 고정한 참조 판정기다. 제품 코드가 아니며,
  이후 계약 YAML로 만든 판정기는 이 오라클과 같은 위반 집합을 내야 한다.
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
