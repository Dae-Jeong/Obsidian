# Second Brain

`wiki/`는 프로젝트 작업과 재사용 지식을 관리하는 LLM Wiki입니다. 이 README는 저장소 구성과 문서 계약을 안내합니다. 지식 탐색과 작업 인수는 [Wiki 진입점](wiki/index.md)에서 시작합니다.

| 위치 | 역할 |
| --- | --- |
| [wiki/profile.md](wiki/profile.md) | 확인된 사용자 맥락과 협업 선호 |
| [wiki/notes/](wiki/notes/index.md) | 현재 지식·참고 설명·공통 규칙 |
| [wiki/projects/](wiki/projects/index.md) | 프로젝트 목적·Task·검토 결과 |
| wiki/sources/ | 원본 자료·첨부·출처별 도메인 원장 |
| [wiki/log/index.md](wiki/log/index.md) · wiki/log/ | 수정 전 원문·변경 이유·작업 과정 |
| [harness/](docs/harness/document-workflow.md) | 문서 검사·프로젝트 탐색·검색 코드 |
| [docs/](docs/harness/document-workflow.md) | harness 설치·사용·구현 설명 |
| tests/ | 실행 규칙의 자동 회귀 검사 |
| .local/harness/ | 프로젝트 등록·보존 checkpoint·훅 실행 상태·재생성 가능한 검색 DB |

개인 본문·원본·Log·DB는 Git에서 제외합니다. 공개 저장소는 도구·규약·가짜 테스트 자료만 제공합니다. 코드·구현 계약·원시 실행 증거는 해당 제품 저장소가 소유합니다.

## 구성

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

루트 저장소 안내는 `README.md`, 관리 문서 폴더의 탐색 입구는 `index.md`입니다. `wiki/`와 `.local/`은 로컬 전용이므로 공개 저장소를 clone하면 개인 본문과 머신 등록 정보는 포함되지 않습니다.

## 시작하기

1. 머신 진입 규칙과 [AGENTS.md](AGENTS.md)를 읽습니다.
2. [wiki/index.md](wiki/index.md)에서 질문의 정본을 찾습니다.
3. 작업은 해당 프로젝트 index와 Task를 읽고 실제 작업 상태와 대조합니다.
4. [공통 작업 규약](wiki/notes/agents/work-management-policy.md)을 따릅니다.

```sh
uv sync --locked
make check
uv run python -m harness context /absolute/project/path
uv run python -m harness check
uv run python -m harness checkpoint
uv run python -m harness search '검색어'
uv run python -m harness search '과거 결정' --scope history
uv run python -m harness search '원문 근거' --scope sources
uv run python -m unittest discover -s tests -v
```

Python 3.14 이상과 uv를 사용합니다. `pyproject.toml`과 `uv.lock`이 환경·의존성을 관리하며, `uv run`은 프로젝트 `.venv`에서 실행합니다. `make check`는 회귀 테스트와 현재 문서 검사를 함께 수행합니다. 새 머신의 개인 문서·프로젝트 등록·최초 checkpoint 설정은 [실행 안내](docs/harness/document-workflow.md)를 따릅니다.

## 에이전트 연결과 검사 범위

Codex·Claude는 [중앙 어댑터](docs/harness/agent-hooks-design.md) 하나를 사용합니다. 설치 명령은 `uv run python -m harness.install_hooks`이며, 설치된 훅은 `.venv/bin/python`으로 `harness/hooks.py`를 직접 실행합니다. 설정 등록과 런타임 신뢰·실제 실행 검증은 별도 단계입니다.

- 명시적 편집 도구의 before-state 보존, 파일 이름, 진행 중인 편집 충돌을 검사합니다.
- 도구 실행 후와 종료 시 문서 검사·checkpoint 상태를 확인합니다.
- 기본 검색은 현재 문서만 조회하며 원본·이력은 명시적으로 선택합니다.
- 문서의 사실 최신성, 모든 shell·MCP 쓰기, 코드 변경 후 Task 기록을 완전히 강제하는 기능은 보장하지 않습니다.

현재 구현·문서 정리의 진행 상태는 [구현 Task](wiki/projects/llm-wiki/tasks/shared-task-harness.md)가 소유합니다.

문서의 배치·갱신·종료·인수 흐름은 [문서 구조와 생애주기](docs/document-lifecycle.md)의 Mermaid 도표에서 확인합니다.

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
| Sources | 원문·첨부·출처·시점 보존 | 원본 bytes 보존 |
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

검색 DB는 Markdown에서 재생성합니다. 기본 검색은 현재 문서만 대상으로 하며 원본과 이력은 명시적으로 범위를 선택합니다. Task를 이어받을 때는 전체 본문을 읽어 권한·blocker·검증 조건을 빠뜨리지 않습니다.

## 별도 실행 저장소

[orchestration](orchestration/README.md)은 독립 Git submodule입니다. 그 영역의 작업은 해당 AGENTS.md를 따릅니다. 부모와 자식의 변경·커밋은 각각 관리합니다.

현재 문서는 wiki/notes·wiki/projects·wiki/profile.md에서 관리합니다. 구조 검사는 숨김 파일과 빈 폴더까지 확인하며, 역할이 정의된 루트 항목만 허용합니다. 원본과 출처 자료는 wiki/sources에서 별도로 조회합니다.

`.local/harness/projects.json`은 실제 저장소 경로, `checkpoint.json`은 보존 검사의 기준, `hook-state.sqlite`는 중앙 훅의 세션·미완료 편집·검증 상태입니다. 이들은 삭제 가능한 검색 캐시가 아닙니다. `current.sqlite`, `sources.sqlite`, `history.sqlite`는 Markdown에서 다시 만드는 검색 캐시입니다. 실행 결과와 과거 문서는 `wiki/log/`, 원본 자료는 `wiki/sources/`에 둡니다.
