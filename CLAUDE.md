# replayspect — Claude Code 작업 지침

## 이 프로젝트가 하는 일
로봇–설비(리프트, 도어, 충전기) 연동 프로토콜에서 재시도·타임아웃·중복 응답·재연결 같은
경계 상황 결함을 찾아내고, 시드 하나로 똑같이 재현한다. 양쪽(장치, 클라이언트)을 결정적
시뮬레이션으로 돌리고, 시드 기반으로 링크 장애를 주입하고, 실행 트레이스를 선언된 동작
계약으로 판정한다. 상세 설계는 `docs/design-v0.md`.

## 절대 원칙 (어기는 변경은 하지 말 것)
1. **결정성**: 스레드, `time.sleep`, 실제 시계, 실제 소켓 금지. 모든 사건은
   `Scheduler`를 거치고, 모든 무작위성은 `Scheduler.rng` 하나에서만 나온다.
   `random` 모듈 전역 함수, `set` 순회 순서, `hash()`에 의존하는 로직 금지.
2. **시간은 정수 마이크로초**: 로직은 `now_us`, `*_us` API만 쓴다. 초 단위 float는 입출력 편의용.
3. **계약이 유일한 정답**: 시뮬레이터 코드는 판정기(`contract/`)를 import하지 않는다.
   시나리오 생성기(무작위, 이후 LLM)는 통과 여부를 결정하지 않는다.
4. **트레이스가 유일한 관찰 경로**: 판정기는 트레이스만 읽는다. 이벤트 kind는
   `send, recv, handle, effect, state, fault` 여섯 개뿐. `recv`(도착)와 `handle`(처리)은 구분한다.
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

## 현재 상태
- [x] 가상 시간 스케줄러 (`src/replayspect/sim/scheduler.py`), 이름 붙은 RNG 스트림 `fork_rng`
- [x] 트레이스 이벤트 모델과 다이제스트 (`src/replayspect/trace.py`)
- [x] 링크 모델 (`src/replayspect/sim/link.py`)
- [ ] **다음 작업: 가상 리프트 장치와 클라이언트, 뮤턴트 M1~M8** (별도 작업지시서)

## 링크 모델 요약 (구현 완료)
- `Channel`이 `client`↔`device`를 잇는다. 방향은 `c2s`, `s2c`. `send`, `recv`, `fault` 이벤트는
  채널이 직접 기록하고, 엔드포인트는 `handle`, `effect`, `state`만 기록한다.
- 메시지 메타데이터는 이벤트 data의 예약 키 `link`에 담긴다 (`dir`, `n`, `delay_us`, `copy`).
  `n`은 방향별 송신 시도 번호로, 연결이 끊겨 버려진 송신도 센다.
- 무작위 모드는 `fork_rng("link/c2s")`, `"link/s2c"`, `"link/disconnect"` 스트림만 쓴다.
  다른 컴포넌트는 자기 이름의 스트림을 따로 만들어 쓴다 (`Scheduler.rng` 직접 사용 지양).
- `FaultPlan.from_trace(trace)`로 만든 명시 계획은 시드와 무관하게 같은 다이제스트로 재생된다.
  이 성질은 축소기의 기반이므로 깨지면 안 된다 (`tests/test_link.py`).
