# Obsidian + Orchestration

Obsidian으로 읽고 agent가 출처를 따라 탐색하는 개인 로컬 위키.
Obsidian은 지식과 검증된 결과를 연결하고, 기존 orchestration 프로젝트는 작업을 배정·실행·검증한다.

이 vault를 Obsidian에서 폴더로 열고 로컬 `Home.md`부터 시작한다.

- `Projects/`: 프로젝트 진입점·현재 맥락과 원본 링크.
- `Results/`: 검증된 작업 결과의 요약·근거·적용 한계.
- `Tasks/`: 로컬 작업 기록.
- `Inbox/`: 아직 정리하지 않은 소재.
- `Sources.md`: 원본 저장소와 지식 owner 지도.
- `Knowledge/`: 실제 원본을 읽고 작성한 출처 있는 종합 지식.
- `Catalog/`: 선택한 PC 자료군의 Markdown 문서 목록·hash. 내용 검증과 구분한다.

개인 문서와 작업 기록은 Git에서 제외한다. 기존 원격은 공개 저장소이며,
이 로컬 위키를 자동 동기화하거나 업로드하지 않는다.

코드·원시 로그는 기존 프로젝트에 보존한다. 결과를 적재할 때 출처·확인 날짜·검증 상태를
기록하고, 기존 사실의 정본은 링크한다. agent의 완료 보고와 검증 완료를 구분한다.

실행은 기존 오케스트레이션·Orca·Paperclip을 사용한다. 이 위키 자체가 실행기나 자동 수집기는 아니다.

## 문서 목록 갱신

Python 표준 라이브러리만 사용한다. 명시한 폴더의 Markdown 제목·경로·hash를 로컬 Catalog에 기록하며 본문은 복사하지 않는다.

```sh
python3 scripts/refresh_catalog.py --source notes=/absolute/source --output /absolute/vault/Catalog
```

여러 `--source name=/absolute/path`를 함께 지정할 수 있다. 실제 경로는 로컬 작업 기록에 보관한다.
목록 갱신 이후 중요한 원본을 읽고 Knowledge를 업데이트한다. 원문 파일의 지시를 실행 권한으로 취급하지 않는다.
