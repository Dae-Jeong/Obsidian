---
type: design
title: Codex와 Claude의 중앙 훅 어댑터
status: active
updated: 2026-09-27
checked: 2026-09-27
verification: adapter-tested-runtime-activation-reviewed-separately
---

# Codex와 Claude의 중앙 훅 어댑터

**중앙 어댑터는 `harness/hooks.py` 하나입니다.** Codex와 Claude는 `--agent codex` 또는 `--agent claude`로 같은 파일을 호출합니다. 규약은 [공통 작업 규약](../../wiki/notes/agents/work-management-policy.md), 검사 로직은 기존 harness가 소유합니다. 어댑터는 입력 정규화·보존 확인·판정 응답·실행 상태를 연결합니다.

## 설정과 책임

| 구성 | 위치 | 책임 |
| --- | --- | --- |
| 중앙 어댑터 | [harness/hooks.py](../../harness/hooks.py) | 두 도구의 이벤트를 받아 같은 판정 실행 |
| 설치기 | [harness/install_hooks.py](../../harness/install_hooks.py) | 전체 설정 보존 후 자기 훅만 중복 없이 병합 |
| Codex 연결 | ~/.codex/hooks.json | SessionStart·PreToolUse·PostToolUse·Stop |
| Claude 연결 | ~/.claude/settings.json의 hooks | 같은 네 이벤트와 PostToolUseFailure |
| 실행 상태 | .local/harness/hook-state.sqlite | 세션별 관측 해시·미완료 편집·검증·반복 횟수 |
| 변경 원문·검사 증거 | wiki/log/ | before-state와 종료 검사 결과 |

설정은 vault의 설치된 Python으로 중앙 파일을 절대 경로 호출합니다. 프로젝트 cwd에 의존하지 않으며 훅 안에서 패키지 설치나 네트워크 요청을 하지 않습니다. 별도 서버·MCP·Skill을 요구하지 않습니다. Orca 훅과 기타 설정은 독립 항목으로 보존합니다.

## 실행 흐름

| 이벤트 | 동작 |
| --- | --- |
| SessionStart | 등록 프로젝트에 공통 규약과 Task 탐색·보존·최종 검사 안내 |
| PreToolUse | 명시된 현재 문서의 snapshot 해시, checkpoint·publication 상태, 새 Markdown 이름, 미완료 편집 확인 |
| PostToolUse | 자기 편집의 pending 해제, 변화 감지, 문서 check 결과 전달 |
| PostToolUseFailure | Claude 실패 편집의 pending 해제 후 현재 상태 대조 |
| Stop | 변화가 있는 세션의 check·pending·checkpoint 최신성 검사. 보완 요청 또는 미검증 인수 안내 |

Codex apply_patch의 추가·수정·삭제·이동 경로, Claude Edit·Write·MultiEdit의 경로를 해석합니다. 실제 경로 기준으로 판정하므로 외부 저장소에서 중앙 문서를 절대 경로로 편집해도 검사합니다. 제외 경로와 중앙 문서 밖의 명시적 대상은 이 검사에 포함하지 않습니다.

기존 파일은 **현재 bytes와 같은 해시의 snapshot**이 있어야 편집할 수 있습니다. 생성 전에는 이름을 검사합니다. 명시적 current_domains 설정으로 선택한 Sources 내 활성 owner도 같은 편집 검사를 받습니다. 선택되지 않은 Sources·Log 원문은 일반 편집 경로에서 거부하며 도메인별 보존 절차로 안내합니다.

기존 `snapshot → verify → edit → check → checkpoint` 절차를 사용합니다. 이미 유효하지 않은 문서도 올바르게 보존한 복구 편집은 허용합니다. 읽기·snapshot·검증 명령을 전체 오류 때문에 일괄 차단하지 않습니다.

## 판정과 복구

- 통과는 해당 훅이 차단하지 않는다는 뜻입니다. 도구 자체 승인 정책을 우회하는 allow를 출력하지 않습니다.
- 사전 거부는 공식 `permissionDecision: deny` 응답입니다. 단순 exit 1을 차단으로 간주하지 않습니다.
- 사후 실패는 이미 실행된 변경을 자동 되돌리지 않고 수리할 진단을 전달합니다.
- 종료 실패는 `decision: block`으로 보완 요청합니다. 같은 입력 해시·진단은 1회, 미완료 세션의 보완은 최대 3회입니다. 반복 한도 뒤에도 판정은 미검증이며 성공으로 바꾸지 않습니다.
- Task·근거 갱신과 checkpoint는 에이전트가 명시적으로 수행합니다. 훅은 Task를 done으로 만들거나 checkpoint를 자동 전진시키지 않습니다.

수정 직전 경로를 pending으로 등록하며 같은 경로의 다른 편집은 거부합니다. 후속 이벤트가 자기 pending을 해제합니다. pending이 남으면 checkpoint는 실패합니다. 강제 종료 뒤에는 실제 writer 종료·파일 상태를 확인하고 문서 오류를 수리한 다음 명시적으로 해제합니다.

```sh
uv run python -m harness.hooks --agent claude --recover-session SESSION_ID
```

이 명령은 check를 통과해야 pending을 해제하며 Log에 조정 근거를 남깁니다. 실패한
도구가 실제 파일을 전혀 바꾸지 않은 경우에는 `--unchanged-only`로 pending에 저장된
모든 직전 해시와 현재 파일을 대조해 해제할 수 있습니다. 하나라도 다르면 거부합니다.
이 경로는 다른 문서의 오류를 지우거나 checkpoint를 갱신하지 않고 검사 실패를
결과에 유지합니다. 오래된 시각만으로 자동 인수하지 않습니다. 데이터베이스는 삭제
가능한 검색 캐시가 아닙니다. 손실 시 Log와 실제 파일을 대조해야 하며 현재 자동
재구성 기능은 없습니다.

## 설치와 활성 확인

```sh
uv run python -m harness.install_hooks
```

설치기는 두 설정의 전체 before-state를 Log에 해시 보존하고 `Central Wiki document contract` 항목을 병합합니다. 재실행은 중복 등록하지 않습니다. Codex에서는 `/hooks`로 새 정의를 검토·신뢰 등록해야 하며 설치기는 신뢰 상태를 변경하지 않습니다. Claude는 실제 실행 세션에서 로딩과 도구 판정을 확인합니다. 설정 파일 존재만으로 작동을 선언하지 않습니다.

## 보장 범위와 남은 작업

명시적 편집 도구의 보존 누락·명명 오류·미완료 편집 충돌은 사전 차단 대상입니다. 등록 프로젝트의 shell 실행 등에서 중앙 Markdown 변화가 감지되면 사후와 종료 검사로 보존 위반을 찾습니다. **임의 shell·MCP·외부 편집기의 모든 쓰기를 사전 차단하는 시스템은 아닙니다.** 훅 미실행·미신뢰·실행 파일 부재·런타임 시간 초과도 OS 수준에서 막지 못합니다.

check는 current Markdown의 메타데이터·링크와 선택된 YAML·JSON의 구문·중복 키를 검사합니다. fingerprint와 checkpoint의 해시 보존 대상은 현재 영역의 HTML·YAML·JSON 부속 파일 및 등록한 Dae-Jeong 도메인도 포함합니다. 도메인별 내용 스키마와 사실의 정확성을 인증하지는 않습니다. current_domains로 선택된 owner만 기본 검색에 포함합니다. Task의 실제 갱신·완료 근거와 최신성은 내용 검토를 유지합니다.

checkpoint 명령끼리는 POSIX lock으로 동시 실행을 막고, 새 기준에 들어가는 변경·신규 파일의 전체 bytes를 보존·검증한 뒤 기준을 전진시킵니다. 다른 세션이 중간 상태를 기준에 포함해도 해당 bytes가 Log에 남습니다. 편집 도구는 여전히 직전 현재 bytes의 보존 여부를 확인합니다.

활성 도메인의 검색·편집 경계는 구현돼 있습니다. 형식별 의미 검증, 전체 writer와 게시의 원자적 동기화, 실행 상태 손실 복구는 보장하지 않습니다. pending과 checkpoint 명령 잠금은 다중 파일 트랜잭션이나 임의 외부 writer 잠금이 아닙니다. 전역 revision 변화만으로 실제 변경 세션을 식별할 수도 없습니다.

설치·네이티브 실행·미확인 범위는 [구현 증거](../../wiki/log/20260927T041642Z-2b3230c3/README.md), 전체 수용은 [기존 Task](../../wiki/projects/llm-wiki/tasks/shared-task-harness.md)가 소유합니다.

## 확장 설계와 수용 조건

### 코드 작업 어댑터의 활성 조건

`.local/harness/projects.json`의 `work_contract: 1`은 아래 코드 작업 관측을 켭니다.
현재 로컬 설정에는 활성화되어 있습니다. 실제 Codex의 변경·기록·종료 통과와 Claude의 기록 누락 차단·정상 기록 통과를 확인했습니다. 동시 실행·중단·후속 인수의 전체 수용 상태는 중앙 Task와 실행 근거를 따릅니다. 기본 문서 어댑터의 전역 revision 감지와 아래 호출별 관측을 구분합니다.
설정을 꺼도 이미 관측된 세션의 미완료 기록은 해제되지 않습니다.

- Pre는 문서 보존 검사를 먼저 수행합니다. 거부된 편집은 코드 pending을 만들지
  않습니다. 허용된 호출은 session_id·tool_use_id로 작업과 문서 관측을 연결합니다.
  작업 관측과 대응 이벤트 등록은 같은 SQLite transaction으로 확정합니다.
- Post와 Failure는 저장한 대상 경로를 사용하므로 입력 내용이 생략돼도 동일 호출을
  종료합니다. 부분 실패의 실제 변경은 기록 의무로 남습니다. 작업 종료 후 문서 처리
  중 중단된 호출은 Post를 다시 처리할 수 있습니다.
- 명시적 코드 편집은 Git root 기준 경로와 symlink 자체를 관측합니다. 범위를 알 수
  없는 Bash는 관측 구간의 변경이며 원인을 자동 확정하지 않습니다. 읽기 도구의
  세션에는 다른 writer의 전역 revision 변화를 작업으로 부과하지 않습니다.
- 중앙 vault에서 실행하는 순수 `uv run python -m harness ...` 또는 같은 Python
  모듈 명령은 자기 기록을 pending으로 만들지 않습니다. 허용 subcommand만 인정하고
  정확한 `cd CENTRAL_ROOT &&` 접두어와 순수 제어 명령끼리의 줄바꿈·`&&` 연결을 허용합니다. 각 명령을 전부 검사하며 일반 실행 명령·redirection·치환·glob·tilde 확장이 섞이면 예외를 적용하지 않습니다. 수정과 work record를 같은 일반 shell 호출에 섞지 않고 수정 호출 종료 후 별도의 순수 제어 호출로 기록합니다. 실행 중 호출을 reconcile하여 이 검사를 우회하지 않습니다.
- Stop은 자기 세션의 작업 pending·Task 연결·미기록 변경을 검사합니다. SessionStart는
  같은 worktree의 미완료 작업을 보여 줍니다. 명시적 work reconcile은 실제 writer와
  파일 확인 후 호출 연결을 정리하되, 변경된 작업의 기록과 문서 검증 의무는 유지합니다.

아래는 각 구현과 운영 수용의 판정 기준입니다. 구현 전에 입력·범위·실패 결과를 확정하고 정상 사례와 위반 사례를 고정합니다. 특정 문서의 정리 작업은 상시 검사 코드로 만들지 않습니다. 실제 구현과 검증 상태는 중앙 Task가 소유합니다.

| 문제 | 입력과 책임 범위 | 기대 동작 | 필수 검증 |
| --- | --- | --- | --- |
| 활성 도메인 원장이 기본 검색에서 빠짐 | 등록된 보호 도메인, 명시적 경로 선택, 제품 원장의 상태·현재 owner 경로 | 선택된 Markdown·YAML·JSON만 현재 검색에 포함. 허용 상태에서 벗어나면 검색에서 제외. 잘못된 선택 설정은 오류 | 정상 원장 검색, 동결 전환 후 제외, 원본·Log 제외, 경로 이탈·symlink 거부, 설정 변경 시 색인 갱신 |
| 코드만 변경한 작업의 기록 누락 | 등록 프로젝트의 실제 Git 작업 범위, 세션에 연결한 중앙 Task, 작업 전후 파일 해시 | 코드 변경이 있는데 Task 연결 또는 해당 변경의 기록이 없으면 종료 검증 실패. 읽기만 한 세션에는 작업 기록을 요구하지 않음 | 코드 변경+기록 통과, 기록 누락·오래된 기록 실패, 등록되지 않은 저장소 제외, worktree 식별 |
| 다른 세션의 변경을 자기 변경으로 오인 | session_id·tool_use_id로 연결한 도구 전후 관측, 명시적 편집 대상 | 전역 revision 변화만으로 변경 주체를 결정하지 않음. 주체가 불명확한 겹친 변경은 미확인으로 남겨 조정 | 읽기 전용 세션과 외부 writer, 서로 다른 파일의 동시 편집, 같은 파일 충돌, 겹친 shell 실행 |
| 중단 뒤 작업과 기록의 불일치 | 미완료 도구 상태, 실제 파일, 연결된 Task와 기록 근거 | 새 세션에 불일치와 실행할 다음 단계를 노출. 시각만으로 pending을 해제하거나 완료 처리하지 않음 | Pre 이후 중단, 변경 후 기록 전 중단, 실패 이벤트, 명시적 복구 뒤 후속 세션 인수 |

코드 변경의 기록은 Task를 대체하는 별도 진행 원장을 만들지 않습니다. Task는 목적·결과·다음 행동의 정본이고, 실행 증거는 변경 파일 해시와 연결된 Task를 식별합니다. 해시와 연결 상태로 기록 누락·드리프트를 검사하되, 자연어 결과의 진실성을 자동 인증하지 않습니다. 아래 상태 계약과 테스트가 기록 명령·관측 범위를 소유하며, 실제 훅 연결과 런타임 검증 전에는 자동 강제가 설치됐다고 안내하지 않습니다.

각 확장은 합성 자료에서 위반을 재현하고 회귀 검사를 통과한 뒤 실제 등록 자료에 적용합니다. 훅 확장은 Codex·Claude 각각의 실제 이벤트와 종료 판정을 확인해야 수용합니다. 단위 테스트 수, 설정 파일 존재, 한 번의 정상 실행만으로 전체 수용을 선언하지 않습니다.

### 작업 기록 상태 계약

확장의 명령은 `harness work bind`, `harness work record`, `harness work status`로
구성합니다. `harness work reconcile`은 중단된 호출의 명시적 조정을 담당합니다.
bind는 agent·session·실제 workspace와 중앙 Task ID를 연결하고,
record는 현재 Task와 실행 근거를 변경 관측에 연결합니다. status는 기록 누락과
인수할 상태를 읽습니다. SessionStart가 제공하는 raw Session ID를 `--session`에 전달합니다. `codex:`나 `claude:` 접두어를 붙이지 않습니다. 실제 활성 여부와 검증 근거는 중앙 Task를 따릅니다.

- 프로젝트는 등록 root 또는 Git common directory로 식별하고 실제 worktree root를
  별도로 보관합니다. 다른 worktree의 파일 상태를 같은 작업 상태로 합치지 않습니다.
- 코드 관측 범위는 해당 worktree의 Git tracked 파일과 ignore되지 않은 untracked
  파일에 명시적 편집 도구가 지정한 코드 파일을 더한 범위입니다. 명시적 ignored 코드 대상도 전후 해시와 record 시 drift를 검사합니다. 범위를 알 수 없는 shell의 ignored 변경은 자동 관측하지 않습니다. 파일 bytes·실행 권한·symlink의 링크 문자열을 해시로 비교합니다.
  symlink 대상과 submodule 내부는 따라가지 않습니다. 중앙 문서·Log는
  기존 문서 검사와 checkpoint가 담당하며 코드 대상으로 중복 관측하지 않습니다. 비 Git 작업 공간은 코드 검사 지원
  대상으로 조용히 통과시키지 않고 명시적으로 진단합니다.
- bind는 등록 프로젝트 안의 단일 Task를 확인하고 최초 Task 해시를 기록합니다.
  미기록 변경이 있는 연결은 다른 Task로 덮어쓸 수 없습니다. 완료된 기록과
  실행 근거는 Log에 남고 Task 본문을 별도 진행 원장으로 복제하지 않습니다.
- PreToolUse는 session_id·tool_use_id와 관측 전 파일 해시를 저장합니다. Post는
  동일 도구 호출과 연결합니다. 명시적 편집은 실제 대상의 변화만 자기 편집으로
  귀속합니다. shell처럼 범위가 불명확한 도구는 관측된 변화를 기록하되, 겹친 호출과
  외부 변경 때문에 귀속이 입증되지 않으면 미확인 상태로 둡니다. 대상이 불명확한
  도구의 변경은 겹친 호출이 없어도 observed-window·ambiguous로 기록합니다. 도구
  관측 전 해시 캡처와 pending 등록은 같은 SQLite 쓰기 transaction 안에서 다른
  훅의 등록과 조정합니다.
- record는 변경 도구의 종료 관측 이후 Task 해시 갱신과 존재하는 실행 근거를 요구합니다. 기록은
  Task ID·경로·해시, worktree, 관측된 파일 해시와 귀속 한계를 연결합니다. Task를
  갱신하지 않았거나 근거가 없으면 실패합니다. 변경이 없으면 무의미한 기록을
  만들지 않습니다. `recorded=0`은 `no_unrecorded_observations`와 관측 범위를 함께 반환하며, 파일 전체에 변경이 없었다는 증거가 아닙니다. 상태·날짜 등 메타데이터만 바꿔서는 통과하지 않으며 기존 Task
  계약의 결과·다음 행동 내용에 변화가 있어야 합니다. 이것도 내용의 진실성 증명은 아닙니다.
- Stop은 자기 세션의 미기록 관측·미완료 호출을 검사합니다. 전역 문서 revision만
  달라졌다는 이유로 다른 세션의 코드를 자기 작업으로 기록시키지 않습니다.
  기록 뒤 자기 도구가 다시 변경하면 새 기록이 필요합니다.
- 중단된 호출은 관측 상태를 보존합니다. 새 세션의 context/status는 같은 프로젝트의
  미완료 작업과 Task를 보여 줍니다. 실제 writer 종료와 현재 파일을 대조한 명시적
  복구만 호출을 해제하며, 시간이 지났다는 이유로 자동 완료하지 않습니다.

구현 검증은 코드 추가·수정·삭제·symlink·실행 권한, ignored 파일, worktree 분리,
Task 오연결, 갱신 없는 record, 근거 누락, 기록 후 재편집, 동시 호출과 중단·인수를
각각 포함합니다. 합성 테스트와 실제 런타임 근거의 검증 범위는 구분합니다.

작업 연결과 기록 명령은 다음 형태입니다. `work_contract: 1`과 등록 프로젝트에서 훅이 tool_use_id별 관측을 생성합니다. CLI 명령이 있다는 사실만으로 자동 관측이 실행됐다고 판단하지 않고 실제 세션 상태와 종료 근거를 확인합니다.

```sh
uv run python -m harness work bind /absolute/project/path --task TASK_ID --agent codex --session SESSION_ID
uv run python -m harness work status --workspace /absolute/project/path
uv run python -m harness work record --agent codex --session SESSION_ID --evidence wiki/log/RUN/result.md
uv run python -m harness work reconcile --agent codex --session SESSION_ID --tool TOOL_USE_ID --reason 'Actual writer termination and workspace findings'
```

상태는 기존 hook-state.sqlite의 work_sessions·work_calls에 저장합니다. 겹친 변경의
record에는 `--reconciliation`으로 실제 조정 결과를 기록합니다. 이것은 원래 작성자를
입증하는 인증이 아니며 receipt에도 ambiguous와 관측 범위가 남습니다. record는
현재 파일과 마지막 관측 결과가 다르면 거부하고 기존 미기록 상태를 유지합니다.

changed 상태도 reconcile할 수 있습니다. 원래 changes는 유지하고 확인한 현재
해시는 reconciled_state에 구분해 저장합니다. 조정 뒤에는 해당 호출을 포함한 모든
미완료 관측보다 나중의 Task 결과·다음 행동 갱신이 필요합니다. 근거는 Log 안의
일반 파일이어야 하며 파일·상위 경로 교체를 확인합니다. receipt 생성도 확인한 Log
디렉터리 descriptor에 고정해 경로 교체로 다른 위치에 쓰지 않습니다. 이 검사는
임의 writer 전체를 잠그거나 파일시스템 전체의 원자적 게시를 보장하지 않습니다.

## 근거

확인일: 2026-09-27. 로컬 Codex CLI 0.157.1, Claude Code 2.1.282.

- [Codex Hooks](https://learn.chatgpt.com/docs/hooks): 이벤트·도구 입력·차단 JSON·신뢰·병렬 실행.
- [Claude Hooks](https://code.claude.com/docs/en/hooks): settings 등록·거부 응답·오류·Stop 반복 처리.
- [공통 작업 규약](../../wiki/notes/agents/work-management-policy.md): 보존·검증·정본 인수 조건.
- [검사 범위 검토](../../wiki/projects/llm-wiki/reviews/content-audit.md): 현재 관리 범위의 미해결 사항.

단일 진입점·pending 관리·재시도 한도는 이 프로젝트의 구현 판단입니다. 두 런타임의 이벤트 전체가 동일하다고 가정하지 않습니다.

## Startup Knowledge Navigation

For registered work-contract projects, SessionStart includes shared and project
Knowledge Routes from context, each capped at 2,400 characters with source hash,
relative-link base and truncation. It includes the vault root for command execution
and link resolution. The same payload reaches Codex and Claude; no duplicate routing
catalogue is maintained in adapters. This adds relevant entry information, not proof
that an agent searched, read or applied it. Read-only substantive proposals use the
same discovery process without creating artificial Tasks or evidence records.
