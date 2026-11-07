# v2 실험 운영 절차: 계획기가 결함을 몇 번 만에 찾는가

질문: LLM이 고른 장애가, 기존 무작위 탐색보다 적은 시뮬레이션으로 결함을 드러내는가.
이 문서는 운영자용이다. 계획기에게 제공하지 않는다. WO-009에서는 이 절차를 실행하지 않는다.

## 비교 조건

| 조건 | 계획 | 실행 i의 시드 |
| --- | --- | --- |
| 무작위 (기준선) | 없음. `SEARCH_PROFILE`의 무작위 장애, 장애 수 상한 없음 | `seed_base + i` |
| LLM | 계획기가 쓴 `base: random` 계획 (장애와 끊김 합계 20개 이하, 프로필 범위 안) | `seed_base + i` |

- 두 조건은 시드 순서와 클라이언트의 RNG 스트림을 공유하지만, 메시지 지연까지 같지는 않다.
  기준선은 방향별 순차 RNG에서 장애와 지연을 뽑고, 계획은 메시지 키별 RNG에서 미지정 지연을 뽑는다.
  LLM은 범위 안에서 지연을 직접 지정할 수도 있다. 따라서 이 실험은 **두 생성 전략 전체**를 비교하며,
  같은 지연 아래 장애 선택만 바꾸는 통제 실험은 아니다. 기존 기준선의 난수 순서와 다이제스트를 유지한다.
- 무작위 장애가 많다는 사실이 검출에 유리함을 보장하지 않는다. 유실이나 끊김이 결함을 일으킬 동작을
  가릴 수도 있다. 이를 LLM에 불리한 보수적 비교라고 해석하지 않는다.
- 측정: 첫 위반까지의 실행 수. 세션이 받은 잘못된 계획과 효과 없는 계획도 예산에 포함한다.
  MCP 자체의 도구 인자 검증 오류는 세션까지 도달하지 않을 수 있으므로 전사에 따로 집계한다.
- 목표 계약과 뮤턴트, 시드를 계획기에게 알려 주지 않는다. 과제는 "아무 계약이나 위반시켜라"다.
- 손으로 짠 계획(`tests/test_session.py`의 `REASONED`)은 과제가 풀리는지 확인하는 테스트일 뿐,
  LLM 시행 결과로 집계하지 않는다. 테스트 코드와 그 결과 설명을 계획기에게 보여 주지 않는다.

## 시행을 등록하기

모델을 호출하기 전에 운영자 전용 기록에 시행 ID, 뮤턴트, seed_base, 예산, 모델의 정확한 ID와
클라이언트·Python·MCP 버전, 하네스 커밋을 고정한다. 예: `trial-001`, M4, 1000, 120.
시행 수와 전체 시드 목록도 사전에 고정하고 잘된 시행만 골라 보고하지 않는다.
계획기에게 보이는 디렉터리·세션·설정 파일 이름은 `trial-001`처럼 중립적으로 정한다.
`m4-1000` 같은 이름은 현재 작업 경로만으로도 뮤턴트와 시드를 노출한다.

아래 셸 명령은 운영자가 실행한다. `/path/to/replayspect`를 실제 저장소 경로로 바꾼다.

```bash
trial_repo=/path/to/replayspect
python3 -m venv "$trial_repo/.venv"
"$trial_repo/.venv/bin/python3" -m pip install -e "$trial_repo[mcp]"
trial_python="$trial_repo/.venv/bin/python3"
mkdir -p "$HOME/rs-trials/trial-001" "$HOME/rs-control/trial-001" "$HOME/rs-logs"
chmod 700 "$HOME/rs-control" "$HOME/rs-logs"
cd "$HOME/rs-trials/trial-001"
```

## 클라이언트를 제한하기

이 절차는 Claude Code 2.1.319의 `--help` 및 공식 문서를 기준으로 작성했다.
다른 버전이나 클라이언트를 쓰면 같은 제약을 먼저 검증하고 버전을 기록한다.

`permissions.allow`는 자동 승인 목록이며 도구의 전체 허용 목록이 아니다. `Read`·`Bash` 등을
`deny`로 막아도 다른 MCP·플러그인이나 자동 주입 문맥을 모두 막는다는 보장은 없다.
여기서는 영구적인 `claude mcp add` 등록 대신 명시적인 설정으로 딱 한 서버를 로드하고,
내장 도구와 스킬을 끄며 사용자 문맥 자동 검색을 제한한다.

```bash
"$trial_python" - "$trial_python" "$HOME/rs-control/trial-001/server.json" "$HOME/rs-logs/trial-001.jsonl" <<'PYCONFIG'
import json
import sys
from pathlib import Path
python, config, log = sys.argv[1:]
data = {"mcpServers": {"replayspect": {
    "command": python,
    "args": ["-m", "replayspect.mcp_server", "--mutant", "M4", "--seed-base", "1000",
             "--budget", "120", "--log", log],
}}}
with Path(config).open("x", encoding="utf-8") as f:
    json.dump(data, f, indent=2)
PYCONFIG
```

- `--tools ""`는 내장 도구를 제거한다. MCP 도구를 제한하는 옵션은 아니다.
- `--strict-mcp-config`는 명시한 설정의 MCP 서버만 사용하게 한다.
- `--bare`는 CLAUDE.md 자동 검색·자동 메모리·설정/플러그인 훅 등을 생략한다.
  스킬 해석은 남으므로 `--disable-slash-commands`도 함께 쓴다.
- `--restricted --setting-sources ""`로 사용자·프로젝트 설정을 제외한다. 관리 정책과 명시적
  설정은 여전히 적용될 수 있으므로 운영자가 관리 정책·주입 문맥·활성 도구를 확인해야 한다.
- 이 `--bare` 절차는 클라이언트 인증에 `ANTHROPIC_API_KEY` 또는 명시적 `apiKeyHelper`가 필요하다.
  구독 OAuth 인증은 사용하지 않는다. 비밀 값은 전사나 결과표에 기록하지 않는다.
  인증 방식이 맞지 않으면 제한 옵션을 임의로 빼지 말고 별도 격리 절차를 검증한다.

### 구독 인증 경로 (`--bare` 없이)

구독(OAuth) 인증으로 시행하려면 `--bare`를 빼는 대신 비어 있는 전용 설정 디렉터리를 쓴다.
사용자 스킬·플러그인·메모리·기록·설정·CLAUDE.md는 설정 디렉터리에서 읽히므로 처음부터 없다.
토큰은 운영자가 `claude setup-token`으로 만들어 권한 600 파일에 두고, 전사·결과표에 남기지 않는다.

```bash
mkdir -p "$HOME/rs-control/claude-config" && chmod 700 "$HOME/rs-control/claude-config"
env -u ANTHROPIC_API_KEY -u ANTHROPIC_AUTH_TOKEN \
  CLAUDE_CONFIG_DIR="$HOME/rs-control/claude-config" \
  CLAUDE_CODE_OAUTH_TOKEN="$(tr -d '[:space:]' < "$HOME/rs-control/oauth-token")" \
  claude --restricted --setting-sources "" --tools "" ...   # 나머지 옵션은 아래 시행 명령과 같다
```

- `--max-budget-usd`로 세션당 상한을 둔다. 상한이나 구독 사용량 한도에 걸리면 중단된 시행이다.
- 계정에 연결된 claude.ai 커넥터는 설정 디렉터리와 무관하게 계정 쪽에서 올 수 있다.
  `--strict-mcp-config`가 이를 막는지는 점검 세션의 초기화 이벤트로 확인한다.
- 이 경로는 `--bare`보다 보장이 약하므로 시행마다 전사의 초기화 이벤트(도구·MCP 서버·스킬·플러그인)와
  숨긴 정보 단어를 감사하고, 하나라도 어긋나면 오염된 시행으로 분류한다.
  클라이언트 내장 플러그인(`path: builtin`)과, 실행할 도구가 없는 내장 에이전트 정의는 허용하되 기록한다.
- 토큰을 붙여넣을 때 줄바꿈이 섞이면 인증이 실패하므로 공백을 제거해 넘긴다.

파일 읽기 요청 한 번이 거부됐다는 사실만으로 격리를 통과시켜서는 안 된다. 실제 시행 전 별도의
중립 점검 ID와 별도 로그로 내장 도구 부재, 다른 MCP 부재, 자동 주입된 답 단서 부재를 확인한다.
점검 세션과 실제 시행 세션·로그를 재사용하지 않는다. **WO-009에서는 이 모델 호출 점검도 하지 않는다.**

공식 근거: [CLI 옵션](https://code.claude.com/docs/en/cli-reference),
[권한의 의미](https://code.claude.com/docs/en/permissions).
`--help` 확인은 했지만 이 작업에서 실제 계획기 세션의 격리 동작을 검증했다는 뜻은 아니다.

## 시행하기

새 프로세스에서 아래 과제 문장을 그대로 사용한다. 모델의 정확한 ID는 사전 등록한 값으로 지정한다.
아래 명령은 실제 시행 단계에서만 실행한다.

```bash
trial_model='REPLACE_WITH_REGISTERED_MODEL_ID'
claude --bare --restricted --setting-sources "" --tools "" \
  --disable-slash-commands --no-chrome --strict-mcp-config \
  --mcp-config "$HOME/rs-control/trial-001/server.json" \
  --allowedTools 'mcp__replayspect__describe,mcp__replayspect__run_plan' \
  --permission-mode dontAsk --permission-prompts none \
  --model "$trial_model" --no-session-persistence --verbose --output-format stream-json \
  -p 'You have an MCP server named replayspect. Call describe first. Then use run_plan to find
 a fault plan that makes the system violate at least one contract, using as few runs as
 possible. Use no other tools. When a run reports a violation, stop and explain in a few
 sentences which faults caused it and why.' \
  > "$HOME/rs-control/trial-001/transcript.jsonl"
```

중간에 사람이 힌트를 주지 않는다. 질문이나 조기 종료로 예산을 다 쓰지 못한 경우에도 그 사실을
결과에 남긴다. 전사의 초기화 이벤트와 도구 호출을 확인한다. 외부 정보를 읽거나 실행할 수 있는
도구가 둘 외에 노출되거나 숨긴 정보가 문맥에 들어갔으면 오염된 시행으로 분류한다.
클라이언트가 자체 종료 제어 도구를 추가하면 그 이름과 역할도 기록한다.

세션 로그는 **새 경로만** 허용한다. 같은 로그로 서버를 재시작하면 시작이 거부되므로 예산·시드를
처음부터 반복할 수 없다. 프로세스 중단·재연결 실패는 중단된 시행으로 기록한다. 로그 삭제나 새
로그 이름으로 같은 시행을 다시 돌려 성공한 것만 선택하지 않는다. 세션은 운영자의 로그 삭제나
새 시행 생성까지 통제하는 보안 경계가 아니며, 그 부분은 사전 등록과 전사 감사로 관리한다.

## 결과 정리

```bash
"$trial_python" -m replayspect session "$HOME/rs-logs/trial-001.jsonl" --verify
"$trial_python" -m replayspect baseline --mutant M4 --seed-base 1000 --budget 120
```

로그는 하나의 헤더, 연속 실행 번호, 시드 순서, 예산 이내 기록을 검사한다. 여러 세션을 합친 로그는
거부한다. `--verify`는 현재 환경에서 계획의 결과를 재생 비교한다. 기록된 버전·문서 해시와 현재
환경을 자동 대조하는 기능은 아직 없으므로 운영자가 이를 확인하고 차이를 함께 보고한다.

| 시행 ID | 상태(완료/미검출/중단/오염) | seed_base | 클라이언트·모델 | 첫 위반까지 실행 수 | 거부 수 | 기준선 실행 수 | 로그 재생 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| trial-001 | 완료 (C3) | 1000 | Claude Code 2.1.319 · claude-opus-5-5 | 9 | 0 | 70 | ok |
| trial-002 | 중단 (0회 사용) | 2000 | Claude Code 2.1.319 · claude-opus-5-5 | — | 0 | — | 실행 없음 |
| trial-003 | 완료 (C3) | 3000 | Claude Code 2.1.319 · claude-opus-5-5 | 7 | 0 | 25 | ok |
| trial-004 (사후 추가, trial-002 대체) | 완료 (C3) | 2000 | Claude Code 2.1.319 · claude-opus-5-5 | 5 | 0 | 40 | ok |

예산 내 미검출은 예산+1회에 성공한 것으로 바꾸지 말고 미검출로 보고한다. 중단·오염도 제외하지
말고 사유와 소모한 예산을 남긴다. 시드별 짝을 보존하고 성공률과 실행 수를 함께 비교한다.
계획기의 원인 설명과 전체 전사를 로그와 보관하고, 시행이 끝난 뒤 사람이 실제 결함과 대조한다.

## 1차 시행 기록 (2026-11-07)

사전 등록: M4, seed_base 1000/2000/3000, 예산 120, 장애·끊김 합계 20 이하, 모델 `claude-opus-5-5`,
구독 인증 경로, 세션당 `--max-budget-usd 25`. 하네스 `fa136df`에서 모든 시행을 돌렸고, 네 세션 로그의
문서 해시가 이 커밋의 계획기용 문서 3개와 같다. 등록 기록·전사·로그는 운영자 디렉터리에 보관한다.

**격리 점검.** 점검 세션 3개를 시행과 별도 ID·로그로 돌렸다.
- check-001: 토큰 파일에 줄바꿈이 섞여 인증 실패(모델 호출 없음). 이후 토큰의 공백을 제거해 넘긴다.
- check-002: 도구·MCP 서버·문맥은 깨끗했지만, `describe`가 그대로 돌려주는 계약 YAML 머리 주석에
  구현·설계 문서·참조 오라클 경로가 있었다. `ff51d4b`에서 제거하고 테스트로 막았다.
- check-003: 통과. 노출 도구는 `describe`·`run_plan` 둘, MCP 서버는 하나, 스킬·사용자 플러그인 없음.
  클라이언트 내장 플러그인 4개와 실행 도구 없는 내장 에이전트 정의는 허용하고 기록했다.
  `--max-budget-usd`는 구독 인증에서도 모델 문맥에 예산으로 표시되고 비용이 집계됐다.

**시행.**
- 등록한 3회 중 2회 완료, 1회 중단. 오염·미검출·거부된 계획은 없다. 모든 로그 재생이 일치했다.
- trial-002는 시작 약 3초 뒤 실행 스크립트가 종료 신호로 끊겼다(첫 `describe` 응답 전, 실행 0회).
  원인은 기록으로 확인되지 않았다. 같은 ID의 재실행은 거부됐고 로그는 그대로 두었다.
- trial-004는 trial-001·003 결과를 본 뒤 같은 시드(2000)로 추가했다. 사후 추가이므로 등록한 3회와
  구분해 보고한다.
- 짝별 첫 위반까지 실행 수(계획기 대 기준선): 1000은 9 대 70, 3000은 7 대 25, 2000(사후)은 5 대 40.
- 모델 사용량은 목록가 환산으로 점검 포함 약 $1.35였다(구독 안에서 처리).

**계획기의 동작.** 세 완료 시행 모두 앞선 실행에서 재전송·중복·타임아웃·끊김 가설을 하나씩 확인한 뒤,
같은 계획으로 C3를 위반시켰다. `MOVE_UP r-0001`의 첫 송신과 첫 재전송을 유실시키고 마지막 재전송에
최대 지연을 주며, 그 ACK를 유실시키고, 다음 `MOVE_DOWN r-0002`에 최소 지연을 준다. 클라이언트가
`ack_timeout`으로 명령을 닫은 뒤 장치가 아직 `MOVING_UP`일 때 반대 명령이 도착한다. 세 번 모두
원인 설명("정확히 `UP`이 아니라 `DOWN`이 아닌지만 검사한다")이 실제 결함과 맞았다.

**해석의 한계.**
- 뮤턴트 하나, 완료 짝 2개(사후 포함 3개)다. 이 결함에서 계획기가 원인 경로를 빨리 추론했다는
  관찰이며, 일반적인 검출 효율 주장은 아니다.
- 위반 계획의 지연·유실 항목이 `tests/test_session.py`의 `REASONED`와 같다. 계획기에게 파일 도구가
  없었고 감사에서 테스트 이름이 나오지 않았으며, 저장소 첫 커밋(2026-11-04)이 모델 지식 기준일보다
  늦으므로 독립적으로 같은 답에 도달한 것으로 판단한다. 값은 프로필 범위의 양 끝이고 프로토콜의
  재전송·ACK 타임아웃에서 따라 나온다.
- 비교 조건 절에 적은 대로 기준선과 계획은 지연 생성 방식이 다르다. 두 전략 전체의 비교다.
- 계획기 스스로 이 계획이 클라이언트 생각 시간에 따라 일부 시드에서만 성공한다고 설명했다.
  첫 위반까지 실행 수에는 이 운이 포함된다.
