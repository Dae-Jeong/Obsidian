# Document Templates

역할별 Markdown 작성 템플릿입니다. 템플릿은 `harness/templates/`가 소유하며 이 문서는 선택 기준, 필드 의미, 갱신 계기와 검증 범위를 설명합니다. 조사 확인일은 2026-09-27입니다. 템플릿 적용은 기존 문서 전체의 내용 검증이나 자동 변환을 의미하지 않습니다.

## 선택과 역할

| 템플릿 | 위치와 책임 | 본문 구성 |
| --- | --- | --- |
| [Project](../../harness/templates/project.md) | `wiki/projects/<project>/index.md`: 프로젝트 진입점·경계 | Purpose · Scope · Workspace · Current Work · Canonical Documents |
| [Task](../../harness/templates/task.md) | `wiki/projects/<project>/tasks/<work>.md`: 작업의 현재 상태·재개 | Goal · Scope · Acceptance Criteria · Current Result · Unresolved Conditions · Next Action |
| [Concept Note](../../harness/templates/note.md) | `wiki/notes/<topic>/<subject>.md`: 개념 이해 | Summary · Explanation · Applicability · Evidence |
| [Procedure Note](../../harness/templates/note-procedure.md) | 같은 Notes 영역: 반복 가능한 실행 안내 | Outcome · Prerequisites · Procedure · Verification · Evidence |
| [Reference Note](../../harness/templates/note-reference.md) | 같은 Notes 영역: 정확한 값·명세 조회 | Scope · Definitions · Constraints · Evidence |
| [Policy Note](../../harness/templates/note-policy.md) | 같은 Notes 영역: 적용 조건과 준수 규칙 | Applicability · Requirements · Exceptions · Verification · Authority |
| [Review](../../harness/templates/review.md) | `wiki/projects/<project>/reviews/<subject>.md`: 특정 대상의 검증 판정 | Target · Scope and Criteria · Results · Limits and Remaining Work · Conclusion |
| [Log](../../harness/templates/log.md) | `wiki/log/<record>/`: 실제 수행한 과정 | Context · Action · Result |

Note의 네 가지 목적은 `subject_type`으로 구분합니다. 새 분류 폴더는 필요하지 않습니다. `note.md`는 개념 설명용입니다. 절차가 필요한 독자에게 개념 설명을 강제하지 않으며, 독립적으로 의미가 없는 조각으로 문서를 나누지 않습니다. 일반 폴더 index, Profile, 원본 자료, README에는 이 여덟 형식을 일괄 강제하지 않습니다.

## 항목의 작성 계약

각 템플릿의 HTML 주석은 항목의 목적과 작성 기준입니다. Required는 완성 문서에서 필요한 정보이고 Conditional은 해당 조건이 있을 때만 작성하는 정보입니다. Conditional에 해당하지 않으면 주석과 빈 제목을 함께 제거합니다. 작성 가이드 주석과 미입력 변수는 완성 문서에 남기지 않습니다.

| 항목 | 기록할 정보와 판별 기준 |
| --- | --- |
| Project Purpose / Scope | 해결할 문제·기대 결과와 책임 경계. 개별 작업의 완료 조건은 Task가 소유 |
| Workspace / Canonical Documents | 실제 저장소·진입 규칙·환경 안내와 질문별 정본 링크. 설정 값과 규칙을 중복 복제하지 않음 |
| Current Work | 실제 Task 링크. 상태·현재 결과·다음 행동은 Task에서 읽음 |
| Task Acceptance Criteria | 기준별 안정적인 식별자·기대 결과·검증 방법. 작업을 실행했다는 사실만으로 완료 처리하지 않음 |
| Current Result | 지금 존재하는 산출물·대상 버전이나 환경·확인 근거·불확실성. 미착수이면 사실대로 기재 |
| Unresolved Conditions | 의존 작업·미결정 사항·blocker. 실제 확인 후 없다고 기록할 수 있음 |
| Next Action | 다음 실행 단계·작업 위치·입력과 선행 조건·성공 확인 방법. 종료 Task는 남은 행동 여부와 별도 후속 Task를 명시 |
| Note Evidence / Policy Authority | 출처가 뒷받침하는 주장과 실제 확인 범위. 내부 규칙은 사용자 결정·정본을 연결. 해석과 미확인을 사실과 구분 |
| Procedure Verification | 실행 후 확인할 방법과 기대 결과. 검증 방법을 적었다고 실제 실행한 것으로 표현하지 않음 |
| Review Target / Scope and Criteria | 대상 파일·버전·환경과 검토해야 할 전체 항목. 결과부터 작성해서 누락 대상을 숨기지 않음 |
| Review Results | 기준 ID · 대상 · 기대 결과 · 관찰 결과 · 판정 · 증거를 연결. 미검토 항목도 유지 |
| Review Conclusion | 결과표로 뒷받침되는 판정과 후속 Task. 전체 범위의 미검토나 실패가 남으면 전체 검증 완료로 표현하지 않음 |
| Log Context / Action / Result | 연결 Task·수행 시점·실제 행동·결과·필요한 증거. 현재 상태는 정본을 연결하고 단순 정리는 짧게 기록 |

절차의 Prerequisites, 참조의 Constraints, 규칙의 Exceptions는 조건부입니다. 예시·그림·실패 분석은 이해에 필요할 때만 추가합니다. 우리 Procedure의 Verification은 필수 작성 정보로 채택했으며, 외부 템플릿의 모든 선택 항목을 필수로 바꾼 것은 아닙니다.

## 메타데이터

| 필드 | 의미와 입력 규칙 |
| --- | --- |
| `type` | 문서 역할: index, task, note, review, log |
| `subject_type` | Note의 작성 목적: concept, procedure, reference, policy. 기존 문서의 유형은 검토 없이 자동 매핑하지 않음 |
| `title` | 책임지는 질문이나 작업을 나타내는 제목 |
| `id` | Task의 영구 식별자. 경로·ID는 상태가 바뀌어도 유지 |
| `project_id` | Project와 Task를 소유하는 프로젝트 폴더의 식별자 |
| `kind` | 기존 Task 검사와 검색에 사용하는 식별값 `task` |
| `status` | Task 상태: ready, active, blocked, review, done, cancelled |
| `checked` | 본문에 명시한 범위와 근거를 실제 확인한 날짜. 생성일이나 파일 mtime을 대입하지 않음 |
| `verification` | Note·Review의 검토 상태: unverified, partial, verified. 확인 범위와 한계는 본문에 기재 |
| `evidence` | Task의 실제 근거 경로·URL 목록. done에는 근거가 필요 |
| `recorded` | Log 작성 날짜. 실행 시각이나 사실 검증 날짜와 구분 |

`verification`은 Note와 Review에서 unverified·partial·verified를 사용하며 역할 구조 검사로 확인합니다. unverified는 근거 대조 전, partial은 일부 확인·실패·미해결이 남은 상태, verified는 선언한 범위 전체에 대한 검증 완료를 뜻합니다. Task·index 등 다른 역할의 상태 어휘와 혼동하지 않습니다. Review의 개별 행은 pass, fail, unverified, not-applicable을 사용하고 not-applicable에는 이유를 씁니다. 날짜 하나로 문서 전체의 최신성을 인증하지 않습니다.

blocked Task에는 `blocker`와 `unblock_condition`을 추가합니다. 실제 선행 Task가 있을 때만 `depends_on`에 존재하는 Task ID를 기록합니다. 빈 선택 필드를 미리 늘리지 않습니다.

## 갱신과 sync

| 문서 | 갱신 계기 | 대조할 근거 |
| --- | --- | --- |
| Project | 목적·범위·저장소·정본이나 현재 Task 연결 변경 | 프로젝트 지시·실제 위치·해당 Task |
| Task | 의미 있는 결과·범위·blocker·다음 행동 변경, 인수 전 | 실제 workspace·산출물·검증 결과 |
| Note | 출처·적용 버전·규칙 변경, 내용 재사용 시 | 해당 주장을 소유하는 원본·코드·사용자 결정 |
| Review | 검토 대상 변경 또는 후속 검증 | 명시한 대상 버전과 기준별 실행·대조 결과 |
| Log | 실제 작업 수행 | 해당 실행의 결과와 필요한 원본 증거 |

현재 문서에는 최신 적용 내용만 남깁니다. Review를 갱신할 때도 이전 판정을 누적하지 않습니다. 필요한 이전 상태와 과정은 Log에 둡니다. 원본 자료와 Log를 최신 사실로 덮어쓰지 않습니다. 전체 sync는 인벤토리의 모든 현재 문서를 검토 대상으로 포함하고, 문서별로 대상 근거와 확인 범위를 대조하는 작업입니다. 템플릿 채우기나 `checked` 일괄 입력으로 대신하지 않습니다.

## 사용과 검사

1. 기존 정본이 있는지 검색하고 새 문서가 필요한 경우 역할에 맞는 템플릿을 선택합니다.
2. 템플릿을 복사하거나 Obsidian Templates 폴더를 `harness/templates`로 지정해 삽입합니다. 이 작업은 앱 설정을 자동 변경하지 않습니다.
3. 제목·ID와 본문을 채웁니다. Obsidian은 `{{title}}`, `{{date:YYYY-MM-DD}}`를 치환하지만 꺾쇠 ID는 직접 입력해야 합니다. 에이전트는 모든 변수를 실제 값으로 바꿉니다.
4. 필요한 조건부 항목을 작성하고 나머지 빈 항목과 가이드 주석을 제거합니다. Task의 미해결 사항처럼 필수 정보가 없을 때는 확인 후 없음을 명시합니다.
5. 근거를 실제 확인한 범위만 기록합니다. 템플릿의 `checked: null`은 미확인 표시입니다. 현 Task 검사는 실제 날짜를 요구하므로 Task를 관리 문서로 등록하기 전에 현재 작업 상태와 범위를 확인해야 합니다. 이는 제품 완료 검증과 다릅니다.
6. 편집 전 보존, 검사와 checkpoint는 [공통 작업 규약](../../wiki/notes/agents/work-management-policy.md)을 따릅니다.

`harness check`는 Task 필드·상태·blocker·완료 증거·의존성 등을 검사합니다. `uv run python -m harness structure [문서경로]`는 템플릿의 필수 항목·Note 목적·날짜·미입력 변수·작성 주석을 검사합니다. 조건부 섹션은 생략할 수 있습니다. 경로를 생략하면 현재 Notes·Projects 전체를 검사하고, 명시한 Log 문서도 검사할 수 있습니다. 역할 템플릿 대상이 아닌 단일 파일은 적용 범위 오류를 반환합니다. 현재 Notes·Projects의 역할 적용과 전체 structure 검사를 마쳐 `.local/harness/projects.json`의 `document_contract: 1`을 활성화했습니다. 일반 `check`도 역할 구조 오류를 실패로 반환합니다. 원본 Sources·Log에 현재 문서 형식을 일괄 강제하지 않습니다. 자동 검사는 필드·유형·링크·항목 누락을 다루고, 근거의 적합성·사실의 최신성은 실제 내용 대조로 확인합니다.

## 조사 근거와 적용 판단

| 근거 | 확인한 구조·원칙 | 적용 |
| --- | --- | --- |
| [Atlassian Project Poster](https://www.atlassian.com/software/confluence/templates/project-poster) | 문제·가정 검증·범위 정리 | Project 목적과 경계; 작업 진행 정보는 Task에 연결 |
| [GitLab Issue 운영](https://handbook.gitlab.com/handbook/marketing/project-management-guidelines/issues/) | 긴 논의 대신 본문에 최신 상태 유지; 관계·의존성 추적 | Task에 최신 결과와 재개 정보 유지 |
| [Anthropic 장기 에이전트 사례](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents) | 진행 기록·기능 검증·실행 환경 안내로 세션 간 인수 | 현재 상태는 Task, 실행 과정은 Log; 별도 progress 정본을 추가하지 않음 |
| [Red Hat 모듈 가이드·실제 템플릿](https://redhat-documentation.github.io/modular-docs/) | 개념·절차·참조의 목적과 작성 요건 구분 | Note 세 가지 형식; Policy는 우리 규칙 문서에 맞춘 추가 설계 |
| [Diátaxis](https://www.diataxis.fr/start-here/) · [적용 안내](https://www.diataxis.fr/how-to-use-diataxis/) | 독자 목적별 문서 구분, 빈 분류 구조를 먼저 만들지 않음 | 목적별 본문 선택, 불필요한 폴더·빈 항목 생성 방지 |
| [NASA Software Test Report](https://swehb.nasa.gov/spaces/7150/pages/16449691/SWE-118%2B-%2BSoftware%2BTest%2BReport) | 대상 환경·상세 결과·한계·판단 근거 | Review의 기준별 결과와 미검토 범위. 확인한 페이지는 2017년 갱신 자료로 현행 준수 표준을 주장하지 않음 |
| [Google SRE Postmortem](https://sre.google/workbook/postmortem-culture/) | 사실·영향·원인·추적 가능한 후속 행동 | Log에 필요한 사실과 증거 연결. 장애 보고서 전체 형식은 일상 작업에 강제하지 않음 |
| [Obsidian Templates](https://obsidian.md/help/plugins/templates) · [Properties](https://obsidian.md/help/properties) | Markdown 삽입·변수 치환·YAML 속성 | 재사용 파일과 짧은 검색용 메타데이터 |

이 구성은 외부 표준 하나를 그대로 구현한 것이 아니라 사용자 요구에 맞춰 조합한 작성 계약입니다. 필수 여부, 최신 내용과 Log의 분리, Review의 전체 대상 목록은 이 프로젝트의 설계 판단입니다.
