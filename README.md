# Second Brain

Obsidian 기반의 개인 지식·프로젝트 작업 관리 시스템입니다. Markdown을 정본으로 관리하고, Python 하네스로 문서 구조·작업 인수 정보·편집 전 보존을 검사합니다. Codex와 Claude는 같은 규칙과 중앙 어댑터를 사용합니다.

## 주요 기능

- **지식 관리:** 사용자 맥락, 재사용 지식, 출처 자료를 역할별로 구분합니다.
- **작업 인수:** 프로젝트별 Task에 목표·범위·현재 결과·다음 행동을 기록합니다.
- **문서 검사:** 파일·문단 링크, 이름, Task 필드, 보존 상태와 미완료 편집을 검사합니다.
- **문맥 검색:** SQLite 색인에서 현재 문서의 관련 구간을 찾습니다. 원본과 이력은 별도로 조회합니다.
- **에이전트 연결:** 중앙 훅으로 명시적 편집 도구와 종료 시점의 문서 검사를 연결합니다.

## 프로젝트 구조

```text
Obsidian/
├── AGENTS.md             # 에이전트 진입
├── README.md             # 저장소 사용 안내와 문서 계약
├── wiki/                 # 로컬 개인 문서
│   ├── index.md
│   ├── profile.md
│   ├── notes/            # 지식·공통 규칙
│   ├── projects/         # 프로젝트별 index·tasks·reviews
│   ├── sources/          # 출처 자료·원본·첨부
│   └── log/              # 필요한 변경 근거와 검증 기록
├── docs/                 # 하네스 사용·설계 설명
├── harness/              # Python 실행 로직
├── tests/                # 합성 자료로 검증하는 회귀 테스트
├── orchestration/        # 독립 Git submodule
├── .local/harness/       # 머신 등록·검증 상태·검색 DB
├── .obsidian/            # Obsidian 설정
├── .githooks/            # 커밋 전 검사
├── pyproject.toml
├── uv.lock
└── Makefile
```

관리 문서 폴더의 입구는 `index.md`입니다. Python 파일은 snake_case, 일반 문서와 폴더는 소문자 kebab-case를 사용합니다. 루트 `README.md`, `AGENTS.md`, `Makefile` 등 도구·저장소 진입 이름은 유지합니다.

## 설치

요구 환경은 Python 3.14 이상과 uv입니다.

```sh
uv sync --locked
```

`pyproject.toml`은 프로젝트·의존성을 선언하고, `uv.lock`은 설치 버전을 고정합니다. `uv run`은 프로젝트 `.venv`를 사용합니다.

`wiki/`와 `.local/`은 개인 자료이므로 Git에서 제외합니다. 공개 저장소를 clone하면 개인 문서와 머신 등록 정보는 포함되지 않습니다. 새 머신의 문서 배치·프로젝트 등록·최초 checkpoint는 [설정 안내](docs/harness/document-workflow.md)를 따릅니다.

## 사용법

로컬 문서 탐색은 [위키 입구](wiki/index.md), 에이전트 작업은 [AGENTS.md](AGENTS.md)에서 시작합니다. 다음 명령은 문서와 프로젝트 등록을 구성한 저장소 루트에서 실행합니다.

### 프로젝트와 작업 찾기

```sh
uv run python -m harness context /absolute/project/path
uv run python -m harness context /absolute/project/path --task TASK_ID
uv run python -m harness context /absolute/project/path --task TASK_ID --query '작업 주제'
```

기존 Task의 전체 내용을 읽고 실제 저장소 상태와 대조한 뒤 작업을 이어갑니다. `context`는 같은 worktree의 미완료 호출도 반환합니다. 남아 있는 호출은 writer 종료와 파일 상태를 확인한 후 명시적으로 조정합니다.

실질적인 작성·수정·설계 전에는 프로젝트 지식 경로와 현재 주제·피드백 검색에서 관련 자료를 찾습니다. `context`는 공통·프로젝트 index의 Knowledge Routes를 짧게 보여줍니다. `--query`는 전체 Task와 함께 본문 없는 검색 후보 카드를 최대 5개 반환합니다. `--brief` 검색도 같은 카드를 사용합니다. 선언된 용도·적용 상황·추천 문단을 보고 선택한 원문 구간을 읽습니다. 모든 검색어가 포함된 결과를 찾으므로 결과가 없으면 짧은 주제어·다른 언어와 프로젝트 경로를 확인합니다. 정본의 적용 범위를 읽고 선택한 판단을 기존 Task의 수용 기준에 연결한 뒤 실제 산출물에서 대조합니다. 검색 성공은 지식 적용이나 산출물 품질 검증을 뜻하지 않습니다. [공통 지식 활용 절차](wiki/notes/agents/work-management-policy.md#use-existing-knowledge)를 따릅니다.

`work_contract: 1`인 등록 프로젝트의 코드 작업은 세션을 Task에 연결합니다. `SESSION_ID`는 SessionStart가 알려 준 접두어 없는 ID입니다.

```sh
uv run python -m harness work bind /absolute/project/path --task TASK_ID --agent codex --session SESSION_ID
# 코드 변경·검증 후 Task의 현재 결과와 다음 행동, 실제 Log 근거 갱신
uv run python -m harness work record --agent codex --session SESSION_ID --evidence wiki/log/RUN/result.json
```

Claude는 `--agent claude`를 사용합니다. 원인이 불명확한 shell 관측은 실제 파일과 writer를 대조한 `--reconciliation` 설명이 필요합니다. 자세한 중단·조정 절차는 [어댑터 설계](docs/harness/agent-hooks-design.md)를 따릅니다.

### 문서 검색

```sh
uv run python -m harness search '검색어' --brief
uv run python -m harness search '검색어'
uv run python -m harness read wiki/notes/example.md
uv run python -m harness search '원문 근거' --scope sources
uv run python -m harness search '과거 결정' --scope history
```

기본 검색은 현재 문서만 조회합니다. `current_domains`가 명시적으로 선택한 제품 Markdown·YAML·JSON 원장도 포함합니다. Sources 안에 있다는 이유만으로 모든 문서를 현재 owner로 취급하지 않습니다. 검색 결과의 정본과 확인 범위를 읽어 적용 가능성을 판단합니다. `read`는 추천 절과 적용 범위·근거를 함께 반환합니다. 추천 절이 없는 문서는 `--section`으로 선택하고, 잘린 결과는 `next_offset`과 `--expected-hash`로 이어 읽습니다. Task 인수는 `context --task`로 전문을 읽습니다.

### 역할별 템플릿 검사

[8개 템플릿](docs/harness/document-templates.md)은 Project·Task·Review·Log와 개념·절차·참조·규칙 Note를 제공합니다.

```sh
uv run python -m harness structure wiki/notes/example.md
```

필수 항목·문서 역할·검증 날짜·미입력 변수, H1 하나·H2 중복·템플릿 섹션 순서를 검사합니다. `uv run python -m harness.structure_audit`는 역할별 준수율과 파일별 진단·검사 책임을 집계합니다. 현재 Notes·Projects의 역할별 구조 적용을 완료했고, 로컬 등록의 `document_contract: 1`로 일반 `check`에도 통합했습니다. 내용의 사실 검증 범위는 문서별 근거와 확인 상태를 따릅니다.

### 문서 갱신

```sh
uv run python -m harness snapshot wiki/notes/example.md --reason '변경 이유'
# 문서 수정
uv run python -m harness check
uv run python -m harness checkpoint
```

정본과 관련 링크를 함께 갱신합니다. 현재 문서는 현재 적용되는 내용만 담고, 필요한 작업 근거는 Log에 기록합니다. 세부 작업 절차는 [공통 작업 규약](wiki/notes/agents/work-management-policy.md)을 따릅니다.

## Codex·Claude 연결

```sh
uv run python -m harness.install_hooks
```

설치기는 두 도구의 설정에 중앙 어댑터를 등록합니다. 훅은 `.venv/bin/python`으로 `harness/hooks.py`를 직접 실행합니다. 설정 등록 후에는 도구별 신뢰 상태와 실제 실행을 확인해야 합니다. [어댑터 설계·설정](docs/harness/agent-hooks-design.md)에 이벤트별 동작과 검증 범위를 설명합니다.

## 개발과 검증

```sh
make test     # 합성 자료 기반 회귀 테스트
make check    # 회귀 테스트 + 현재 문서 검사
make index    # 현재 문서 검색 색인 재생성
```

커밋 전 검사는 `.githooks/pre-commit`이 담당합니다. 해당 checkout에 연결하려면 `git config core.hooksPath .githooks`를 실행합니다. 개인 문서가 없는 환경에서는 `make test`로 실행 로직을 검증하고, 문서 설정이 끝난 환경에서는 `make check`로 실제 문서도 검사합니다.

`.local/harness/`의 `projects.json`, `checkpoint.json`, `hook-state.sqlite`는 필요한 머신 상태입니다. `checkpoint.lock`은 checkpoint 명령의 동시 실행을 조정하며 문서 상태를 소유하지 않습니다. `current.sqlite`, `sources.sqlite`, `history.sqlite`는 문서에서 재생성하는 검색 색인입니다.

## 문서 안내

| 문서 | 내용 |
| --- | --- |
| [문서 생애주기](docs/document-lifecycle.md) | 영역별 책임과 갱신·인수 흐름 |
| [문서 템플릿](docs/harness/document-templates.md) | 역할별 작성 형식과 조사 근거 |
| [하네스 사용 안내](docs/harness/document-workflow.md) | 설정·명령·검사 범위 |
| [에이전트 어댑터](docs/harness/agent-hooks-design.md) | 훅 설치와 동작 |
| [공통 작업 규약](wiki/notes/agents/work-management-policy.md) | 작업 탐색·기록·검증 기준 — 로컬 문서 |
| [구현 Task](wiki/projects/llm-wiki/tasks/shared-task-harness.md) | 현재 결과·남은 작업 — 로컬 문서 |

[orchestration/](orchestration/README.md)은 독립 Git submodule이며 자체 규칙과 커밋을 사용합니다.

## 적용 범위

하네스는 구조와 기록의 정합성을 검사합니다. 사실의 최신성·제품 동작·문서의 의미상 정확성은 출처와 실행 근거로 별도 검토해야 합니다. 모든 shell·MCP 쓰기의 사전 차단이나 코드 변경 후 Task 기록의 완전한 강제는 구현 범위에 포함되지 않습니다.

## File Naming

파일명은 문서가 책임지는 질문을 나타내는 안정적인 식별자입니다. 먼저 대상·역할·범위를 정하고 이름을 붙입니다.

- 일반 문서는 영문 소문자 kebab-case와 해당 확장자를 씁니다. 주제와 책임이 드러나는 명사구를 사용합니다.
- 정책은 policy, 구성은 design, 실행 순서는 workflow, 전환 조건은 lifecycle, 평가는 evaluation을 필요한 경우에만 붙입니다.
- 현재 문서에는 날짜·상태·개정 번호·latest·final을 붙여 편집본을 늘리지 않습니다.
- Task ID와 생성된 파일 경로는 상태 변화 이후에도 유지합니다. 완료 문서를 별도 폴더로 옮기지 않습니다.
- Log 사건 파일에는 날짜를 쓸 수 있습니다. 자동 보존 묶음은 UTC 시각과 식별자로 구분합니다.
- 원본 자료·첨부의 이름은 출처와 함께 보존합니다.
- 루트 README.md·AGENTS.md·Makefile과 도구가 요구하는 파일명은 유지합니다. 관리 문서 폴더의 진입점은 index.md 하나로 통일합니다. Python 파일은 snake_case를 사용합니다.
- 폴더가 나타내는 분류를 파일명에 반복하지 않습니다. 독립적인 질문이 없다면 파일을 새로 만들지 않습니다.

## Document Lifecycle

현재 문서는 지금 적용되는 사실·판단·이유·상태·근거·불확실성·다음 행동만 담습니다. 수정 전 문장, 없어진 항목, 폐기 결정, 제거 안내, 실행 과정과 변경 이유는 Log에만 둡니다.

| 영역 | 생성·갱신 | 종료 |
| --- | --- | --- |
| Profile·규칙 | 확인된 선호와 현재 규칙을 기존 owner에 반영 | 적용되는 내용만 유지 |
| Notes | 읽은 출처와 설명·확인 범위·불확실성 기록 | 재사용 시 근거의 현재성 확인 |
| Project·Task | 목표·범위·완료 기준·현재 결과·다음 행동·증거 갱신 | 같은 경로에 최종 결과와 한계 유지 |
| Sources | 원문·첨부·출처·시점 보존. 명시적으로 선택한 활성 도메인은 현재 owner 계약 적용 | 원본 bytes 보존, 활성 owner의 이전 상태는 Log |
| Log | 수정 전 전체 원문·변경 이유·과정·검사 결과 기록 | 이력으로 보존, 기본 검색에서 제외 |

편집 순서:

1. 정본과 근거를 읽고 기존 문서·활성 writer를 확인합니다.
2. 수정 전 전체 원문을 snapshot하고 해시를 검증합니다.
3. 현재 본문과 관련 링크를 갱신합니다. 불필요한 중복 owner는 정리합니다.
4. 문서 검사와 해당 제품 검증을 실행합니다. 실패를 수정한 뒤 완료를 기록합니다.
5. Task의 현재 결과·증거·다음 행동을 갱신하고 Log에 과정을 남긴 뒤 `uv run python -m harness checkpoint`로 검증 기준을 갱신합니다.

```sh
uv run python -m harness snapshot path/to/document.md --reason '변경 이유'
uv run python -m harness verify wiki/log/<record>
uv run python -m harness check
```

해시·구문·링크 검사는 사실 검증을 대신하지 않습니다. 자연어의 최신성, 실제 제품 동작과 완료 근거는 별도로 검토합니다. 검사 스크립트는 CI 방식으로 작동하며 동일 계정의 임의 파일 수정을 OS 권한으로 차단하지 않습니다.

보존 검사는 현재 영역의 비 Markdown 부속 파일과 `projects.json`에 등록한 추가 도메인도 포함합니다. 추가 도메인 등록은 해당 파일의 현재성·편집 권한·제품 스키마 검증을 대신하지 않습니다. 검색 DB는 Markdown과 선택된 YAML·JSON에서 재생성합니다. 기본 검색은 현재 문서만 대상으로 하며 원본과 이력은 명시적으로 범위를 선택합니다. Task를 이어받을 때는 전체 본문을 읽어 권한·blocker·검증 조건을 빠뜨리지 않습니다.
