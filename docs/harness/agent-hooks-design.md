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

기존 파일은 **현재 bytes와 같은 해시의 snapshot**이 있어야 편집할 수 있습니다. 생성 전에는 이름을 검사합니다. 기존 Sources·Log 원문은 일반 편집 경로에서 거부하며 도메인별 보존 절차로 안내합니다. 이는 Sources 내부 활성 도메인 원장 지원 완료를 뜻하지 않습니다.

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

이 명령은 check를 통과해야 pending을 해제하며 Log에 조정 근거를 남깁니다. 오래된 시각만으로 자동 인수하지 않습니다. 데이터베이스는 삭제 가능한 검색 캐시가 아닙니다. 손실 시 Log와 실제 파일을 대조해야 하며 현재 자동 재구성 기능은 없습니다.

## 설치와 활성 확인

```sh
uv run python -m harness.install_hooks
```

설치기는 두 설정의 전체 before-state를 Log에 해시 보존하고 `Central Wiki document contract` 항목을 병합합니다. 재실행은 중복 등록하지 않습니다. Codex에서는 `/hooks`로 새 정의를 검토·신뢰 등록해야 하며 설치기는 신뢰 상태를 변경하지 않습니다. Claude는 실제 실행 세션에서 로딩과 도구 판정을 확인합니다. 설정 파일 존재만으로 작동을 선언하지 않습니다.

## 보장 범위와 남은 작업

명시적 편집 도구의 보존 누락·명명 오류·미완료 편집 충돌은 사전 차단 대상입니다. 등록 프로젝트의 shell 실행 등에서 중앙 Markdown 변화가 감지되면 사후와 종료 검사로 보존 위반을 찾습니다. **임의 shell·MCP·외부 편집기의 모든 쓰기를 사전 차단하는 시스템은 아닙니다.** 훅 미실행·미신뢰·실행 파일 부재·런타임 시간 초과도 OS 수준에서 막지 못합니다.

현재 check와 fingerprint의 내용 검사 범위는 current Markdown입니다. HTML·YAML·JSON의 명시적 편집도 snapshot은 요구하지만 내용·검색·checkpoint까지 완전히 검사하지 않습니다. 다른 세션의 변화를 관측할 수 있으므로 자기 작업 증거로 자동 귀속하지 않습니다. Task의 실제 갱신·완료 근거와 최신성은 내용 검토를 유지합니다.

남은 구현은 활성 도메인·부속 형식의 관리 범위, 구조화된 후보 적용 명령, checkpoint 전진과 writer 간 원자적 동기화, 실행 상태 손실 복구입니다. pending과 예상 상태 확인은 완전한 다중 파일 트랜잭션이나 외부 writer 잠금이 아닙니다.

설치·네이티브 실행·미확인 범위는 [구현 증거](../../wiki/log/20260927T041642Z-2b3230c3/README.md), 전체 수용은 [기존 Task](../../wiki/projects/llm-wiki/tasks/shared-task-harness.md)가 소유합니다.

## 근거

확인일: 2026-09-27. 로컬 Codex CLI 0.157.1, Claude Code 2.1.282.

- [Codex Hooks](https://learn.chatgpt.com/docs/hooks): 이벤트·도구 입력·차단 JSON·신뢰·병렬 실행.
- [Claude Hooks](https://code.claude.com/docs/en/hooks): settings 등록·거부 응답·오류·Stop 반복 처리.
- [공통 작업 규약](../../wiki/notes/agents/work-management-policy.md): 보존·검증·정본 인수 조건.
- [검사 범위 검토](../../wiki/projects/llm-wiki/reviews/content-audit.md): 현재 관리 범위의 미해결 사항.

단일 진입점·pending 관리·재시도 한도는 이 프로젝트의 구현 판단입니다. 두 런타임의 이벤트 전체가 동일하다고 가정하지 않습니다.
