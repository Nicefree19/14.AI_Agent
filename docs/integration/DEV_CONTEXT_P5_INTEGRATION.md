# DEV_CONTEXT_P5_INTEGRATION.md

> P5 Integration &mdash; Developer Context & Onboarding Guide v1.0
> Date: 2026-02-17 | Ref: TECH_SPEC_P5_INTEGRATION.md

---

## 1. Repository Structure

```
D:\00.Work_AI_Tool\14.AI_Agent\
├── .env                              # 환경 변수 (TELEGRAM_BOT_TOKEN, ALLOWED_USERS)
├── .secrets/                         # Google API credentials (gitignored)
├── CLAUDE.md                         # 시스템 프롬프트 (봇 동작 규약)
├── docs/
│   └── integration/                  # 이 문서들이 위치한 디렉토리
│       ├── TECH_SPEC_P5_INTEGRATION.md
│       ├── TODO_P5_INTEGRATION.md
│       ├── DEV_CONTEXT_P5_INTEGRATION.md
│       └── PHASE1_EXECUTION_PROMPT.md
├── logs/
│   └── agent.log                     # RotatingFileHandler (5MB x 5 = max 25MB)
├── ResearchVault/                    # Obsidian Vault (SSOT)
│   ├── 00-Inbox/
│   │   └── Messages/Emails/         # Outlook 수집 이메일
│   │       └── Attachments/          # OCR 대상 첨부파일
│   ├── 02-Notes/                     # 일반 노트
│   ├── P5-Project/
│   │   ├── 00-Overview/              # 운영메트릭.md, dashboard-feed.json (예정)
│   │   ├── 01-Issues/                # 732 이슈 .md (Google Sheets 동기화)
│   │   ├── 04-Decisions/             # 의사결정 기록
│   │   └── 05-WorkLog/              # 텔레그램 작업 결과 자동 저장
│   └── _config/
│       ├── p5-sync-config.yaml       # 동기화 설정 (핵심)
│       ├── p5-triage-rules.yaml      # 트리아지 규칙
│       ├── ingest-policy.yaml        # 인입 정책
│       └── ocr-corrections.yaml      # OCR 교정 사전
├── scripts/
│   ├── p5_config.py                  # 중앙 경로 상수 (모든 스크립트의 경로 소스)
│   ├── p5_utils.py                   # 공통 유틸리티 (load_yaml 등)
│   ├── p5_issue_sync.py              # 이슈 동기화 (1700+ lines)
│   ├── p5_email_triage.py            # 이메일 분류 엔진 (1200+ lines)
│   ├── p5_daily_briefing.py          # 일일 브리핑 생성기
│   ├── p5_metrics.py                 # 운영 메트릭 대시보드
│   ├── p5_ocr_pipeline.py            # OCR 파이프라인 (GLM-OCR)
│   ├── p5_notion_sync.py             # Notion 동기화
│   ├── p5_daily.bat                  # 일일 파이프라인 배치
│   ├── p5_weekly.bat                 # 주간 배치
│   ├── p5_daemons_start.bat          # 데몬 시작
│   ├── p5_autoexecutor.bat           # Claude Code 자동 실행기
│   ├── message_daemon.py             # 메시지 수집 데몬
│   ├── launch_dashboard.py           # Obsidian 대시보드 실행 (하드코딩 경로 잔존)
│   ├── _verify_ocr_module.py         # OCR 검증 (하드코딩 경로 잔존)
│   └── telegram/                     # 텔레그램 봇 모듈
│       ├── config.py                 # 중앙 설정 (Feature flags, ErrorSeverity)
│       ├── logger.py                 # 중앙 로거
│       ├── telegram_bot.py           # 통합 봇 로직
│       ├── telegram_sender.py        # 응답 전송기
│       ├── telegram_listener.py      # 메시지 수집기
│       ├── telegram_runner.py        # 작업 실행기
│       ├── telegram_executors.py     # 키워드 라우팅 + 47 executor
│       ├── skills_registry.py        # 스킬 카탈로그
│       ├── skills/                   # 31 skill 모듈
│       │   └── kakao_live_skills.py  # 카카오톡 6종
│       ├── cleanup_manager.py        # 디스크 클린업 매니저
│       ├── claude_executor.py        # Claude Code executor
│       ├── python_runner.py          # Python 실행기
│       ├── kakao_desktop.py          # 카카오톡 PC 자동화 (MCP)
│       ├── kakao_utils.py            # 카카오톡 파싱 유틸리티
│       ├── google_utils.py           # Google API 유틸리티
│       ├── memory_search.py          # 메모리 검색 (TF 가중)
│       └── error_handler.py          # 에러 핸들러 (ErrorSeverity)
├── telegram_data/                    # 텔레그램 데이터 저장소
│   ├── telegram_messages.json        # 메시지 내역
│   ├── working.json                  # 작업 잠금 (30분 타임아웃)
│   ├── new_instructions.json         # 작업 중 새 메시지
│   ├── kakao_pending_reply.json      # 카카오톡 답장 대기 (10분 만료)
│   └── tasks/                        # 작업 폴더
│       ├── index.json                # 작업 인덱스
│       └── msg_{id}/                 # 개별 작업 (task_info.txt + 결과물)
└── tests/                            # pytest 테스트
    ├── conftest.py                   # 공통 fixture
    ├── test_core_e2e.py
    ├── test_executor_contracts.py
    ├── test_keyword_routing.py
    ├── test_state_machine.py
    ├── test_error_handler.py
    ├── test_kakao_error_paths.py
    └── test_memory_search.py
```

---

## 2. Core Script Role Map

| Script | Role | Key APIs | Called By |
|--------|------|----------|-----------|
| `scripts/p5_config.py` | 중앙 경로 상수 | `PROJECT_ROOT`, `VAULT_PATH`, `ISSUES_DIR`, `OVERVIEW_DIR`, `CONFIG_DIR`, `SECRETS_DIR`, `resolve_path()` | 전체 스크립트 (should be) |
| `scripts/p5_utils.py` | 공통 유틸리티 | `load_yaml()`, `setup_logger()` | p5_issue_sync, p5_email_triage 등 |
| `scripts/p5_issue_sync.py` | Google Sheets ↔ Vault 동기화 | `cmd_sync()`, `cmd_push()`, `cmd_context()`, `parse_issue()`, `upsert_issue()`, `load_config()`, `_validate_issue_completeness()`, `generate_data_quality_report()` | p5_daily.bat step 3/6 |
| `scripts/p5_email_triage.py` | 이메일 분류 + 채점 엔진 | `TriageEngine.triage()`, `NoiseFilter`, `EntityExtractor`, `apply_triage_results()`, `cmd_process()` | p5_daily.bat step 4 |
| `scripts/p5_daily_briefing.py` | 일일 브리핑 생성 | `cmd_generate()` | p5_daily.bat step 7 |
| `scripts/p5_metrics.py` | 운영 KPI 대시보드 | `calc_snr()`, `calc_triage_accuracy()`, `calc_decision_velocity()`, `calc_queue_health()`, `calc_data_completeness()`, `calc_auto_apply_accuracy()`, `calc_classification_distribution()`, `calc_tier_distribution()`, `cmd_generate()` | p5_daily.bat step 8 |
| `scripts/p5_ocr_pipeline.py` | OCR 파이프라인 | `health`, `process` subcommands | p5_daily.bat step 2a/2b |
| `scripts/p5_notion_sync.py` | Notion 동기화 | `sync` subcommand | p5_daily.bat step 3.5 |
| `scripts/message_daemon.py` | Outlook 이메일 수집 | `collect outlook --limit N --triage` | p5_daily.bat step 1 |
| `scripts/telegram/config.py` | Feature flags + 상수 | `FEATURE_FLAGS`, `is_enabled()`, `ErrorSeverity`, `PROJECT_ROOT`, `TELEGRAM_DATA_DIR` | 전체 telegram 모듈 |
| `scripts/telegram/telegram_bot.py` | 통합 봇 로직 | `check_telegram()`, `combine_tasks()`, `create_working_lock()`, `remove_working_lock()`, `reserve_memory_telegram()`, `report_telegram()`, `mark_done_telegram()`, `load_memory()`, `search_memory()`, `get_task_dir()` | p5_autoexecutor.bat |
| `scripts/telegram/telegram_executors.py` | 키워드 라우팅 | `get_executor()`, `KEYWORD_MAP` (310+ keywords), `EXECUTOR_MAP` (47 executors), `list_available_executors()` | python_runner, claude_executor |
| `scripts/telegram/telegram_sender.py` | 텔레그램 응답 전송 | `send_message_sync()`, `send_file_sync()` | 전체 봇 시스템 |
| `scripts/telegram/telegram_listener.py` | 메시지 수집기 | 10초 간격 polling | telegram_runner |
| `scripts/telegram/cleanup_manager.py` | 디스크 정리 | `cleanup_old_tasks()`, `cleanup_messages()` | p5_autoexecutor.bat (1일 1회) |

---

## 3. Known Inconsistencies / Tech Debt

| ID | Category | Description | File:Line | Impact | Fix Phase |
|----|----------|-------------|-----------|--------|-----------|
| TD-1 | Data Quality | `"normal"` priority 값 161건 &mdash; config에 정의 없어 정규화 실패. `parse_issue()`에서 `priority_mapping.get(raw_priority, raw_priority.lower())`로 fallback → `"normal"` 그대로 저장 | `p5-sync-config.yaml:38-42`, `p5_issue_sync.py:803` | 분류/필터링 오류 | P0-1 |
| TD-2 | Hardcoded Path | `launch_dashboard.py`에 절대경로 하드코딩 | `launch_dashboard.py:8` (`r"D:\00.Work_AI_Tool\14.AI_Agent\ResearchVault"`) | p5_config 원칙 위반 | P0-6 |
| TD-3 | Hardcoded Path | `_verify_ocr_module.py`에 절대경로 하드코딩 (sys.path) | `_verify_ocr_module.py:3` (`r"D:\00.Work_AI_Tool\14.AI_Agent\scripts"`) | p5_config 원칙 위반 | P0-6 |
| TD-4 | Hardcoded Path | `_verify_ocr_module.py`에 절대경로 하드코딩 (스크립트 경로) | `_verify_ocr_module.py:62` (`r"D:\00.Work_AI_Tool\14.AI_Agent\scripts\p5_ocr_pipeline.py"`) | p5_config 원칙 위반 | P0-6 |
| TD-5 | Code Duplication | `p5_issue_sync.py`에 동일 기능 함수 2개: `load_config()` (L1263)과 `_load_config()` (L1696) | `p5_issue_sync.py:1263,1696` | 유지보수 혼란 | P1-4 |
| TD-6 | Path Duplication | `p5_metrics.py` L26-34에서 경로 직접 계산 &mdash; `p5_config.py`와 중복 | `p5_metrics.py:26-34` | SSOT 위반 | P1-3 |
| TD-7 | Numbering Inconsistency | `p5_daily.bat` step 번호 `/9`와 `/10` 혼재 (L26: `[1/9]`, L47: `[3/10]`, L52: `[3.5/10]`) | `p5_daily.bat:26,47,52` | 혼란 유발 | P1-5 |
| TD-8 | Dead Feature | 일일 트리아지 `--dry-run`으로만 실행 &mdash; 분류 결과 미반영 | `p5_daily.bat:64` | 트리아지 실효성 제로 | P0-5 |
| TD-9 | Dead Features | Feature flags 6개 전부 `False` &mdash; 구현된 기능 비활성 | `config.py:66-73` | hard_gate, state_machine, error_classification 등 미작동 | P0-3, P1-1, P1-2 |
| TD-10 | Data Quality | zone 필드 비표준화 &mdash; 자유형 텍스트로 집계/필터 불가 | `p5_issue_sync.py:828` (zone 값 그대로 저장) | zone별 분석 불가 | P0-2 |
| TD-11 | Data Quality | owner 필드 99.6% 누락 (3/732건) | 이슈 frontmatter | 담당자 추적 불가 | P0-3 |
| TD-12 | Data Quality | due_date 필드 99.7% 누락 (2/732건) | 이슈 frontmatter | 일정 관리 불가 | P0-3 |
| TD-13 | Data Quality | decision 필드 100% 공란 (0/732건) | 이슈 frontmatter | 의사결정 추적 불가 | KPI 반영 |

---

## 4. Command Catalog

### Issue Sync

```bash
# Google Sheets → Vault 동기화
python scripts/p5_issue_sync.py sync

# CSV fallback 동기화
python scripts/p5_issue_sync.py sync --csv "path/to/issues.csv"

# Vault → Google Sheets 역동기화
python scripts/p5_issue_sync.py push

# 종합 상태 리포트
python scripts/p5_issue_sync.py status

# NotebookLM Context Sheet 업데이트
python scripts/p5_issue_sync.py context
```

### Email Triage

```bash
# 이메일 트리아지 (dry-run)
python scripts/p5_email_triage.py process --dry-run

# 이메일 트리아지 (live, score >= threshold 자동 적용)
python scripts/p5_email_triage.py process --auto-apply-above 5

# 리뷰큐 중복 제거
python scripts/p5_email_triage.py queue dedup

# 리뷰큐 오래된 항목 정리
python scripts/p5_email_triage.py queue clean --max-age 14
```

### Briefing

```bash
# 오늘 브리핑 생성 (파일 + 콘솔)
python scripts/p5_daily_briefing.py generate

# 브리핑 생성 + Telegram/Notion push
python scripts/p5_daily_briefing.py generate --push

# 48시간 윈도우
python scripts/p5_daily_briefing.py generate --window 48

# 콘솔만 출력
python scripts/p5_daily_briefing.py generate --stdout
```

### Metrics

```bash
# 운영 메트릭 대시보드 생성
python scripts/p5_metrics.py generate

# 콘솔만 출력
python scripts/p5_metrics.py generate --stdout
```

### Outlook Collection

```bash
# Outlook 이메일 수집 + 자동 트리아지
python scripts/message_daemon.py collect outlook --limit 20 --triage
```

### OCR Pipeline

```bash
# OCR 서비스 상태 점검
python scripts/p5_ocr_pipeline.py health

# 첨부파일 OCR 처리
python scripts/p5_ocr_pipeline.py process --limit 20
```

### Cleanup

```bash
# Dry-run (삭제 없이 확인)
python -m scripts.telegram.cleanup_manager --dry-run

# 실제 정리 (30일 초과)
python -m scripts.telegram.cleanup_manager --days 30
```

### Batch Pipelines

```bash
# 일일 파이프라인 (9+단계)
scripts\p5_daily.bat

# 주간 파이프라인
scripts\p5_weekly.bat

# 데몬 시작
scripts\p5_daemons_start.bat

# Claude Code 자동 실행기 (작업 스케줄러에서 1분마다)
scripts\p5_autoexecutor.bat
```

### Tests

```bash
# 전체 테스트
pytest tests/ -v

# 특정 테스트
pytest tests/test_keyword_routing.py -v
pytest tests/test_state_machine.py -v
pytest tests/test_data_contract.py -v    # (P0-8에서 생성 예정)
```

---

## 5. Operational Considerations

### Dry-run vs Production Defaults

- `p5_email_triage.py process`: **현재 `--dry-run` 기본** (p5_daily.bat:64). P0-5에서 `--auto-apply-above 5`로 전환 예정.
- `p5_issue_sync.py sync`: 항상 live. `hard_gate_issues` flag로 차단 수준 제어.
- `cleanup_manager`: `--dry-run` 플래그로 사전 확인 권장.

### working.json 잠금

- **타임아웃**: 30분 (마지막 활동 기준)
- **스탈 감지**: `check_telegram()`이 자동으로 30분 초과 잠금 해제
- **수동 해제**: `telegram_data/working.json` 삭제 (프로세스 확인 후)
- **이중 안전**: p5_autoexecutor.bat에서 Claude 프로세스 존재 여부 선확인

### Atomic JSON Writes

모든 JSON 파일 쓰기는 원자적 패턴 필수:

```python
import tempfile, os, json

def atomic_write_json(path, data):
    dir_path = os.path.dirname(path)
    with tempfile.NamedTemporaryFile('w', dir=dir_path, suffix='.tmp',
                                      delete=False, encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
        tmp_path = f.name
    os.replace(tmp_path, path)
```

**적용 대상**: telegram_messages.json, index.json, new_instructions.json, working.json, kakao_pending_reply.json, dashboard-feed.json (예정)

### UTF-8 Encoding

- 모든 파일 I/O: `encoding="utf-8"` 명시
- Windows stdout: `sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")`
- Batch 파일: `chcp 65001 >nul` + `set PYTHONIOENCODING=utf-8`

### Scheduling

- **작업 스케줄러**: `Claude_P5Agent_14.AI_Agent` (1분마다 p5_autoexecutor.bat)
- **일일 배치**: p5_daily.bat (수동 또는 스케줄러)
- **클린업**: p5_autoexecutor.bat 내 1일 1회 (cleanup_last_run.txt 마커)

---

## 6. Collaboration Rules

### Path Management

- **모든 경로는 `p5_config.py` 경유**. 직접 `Path(__file__).parent.parent / ...` 금지.
- 신규 경로 필요 시 `p5_config.py`에 상수 추가 후 import.
- `resolve_path()` 사용: 상대경로 → PROJECT_ROOT 기준 해석.

### YAML Loading

- **`p5_utils.load_yaml()`** 사용. 직접 `yaml.safe_load(open(...))` 금지.
- 파일 미존재 시 빈 dict 반환, 파싱 에러 시 로그 + 빈 dict.

### Keyword/Executor Registration

- 신규 키워드 추가 시: `KEYWORD_MAP`에 키워드 → executor 이름 매핑 추가.
- 신규 executor 추가 시: `EXECUTOR_MAP`에 함수 등록 필수.
- **검증**: `test_keyword_routing.py`에서 모든 KEYWORD_MAP value가 EXECUTOR_MAP에 존재하는지 확인.
- Dead keyword(KEYWORD_MAP에 있으나 EXECUTOR_MAP에 없음) 절대 금지.

### Feature Flag Protocol

- 신규 기능은 반드시 `config.py` `FEATURE_FLAGS`에 등록.
- 기본값: `False`. 테스트 통과 후 활성화.
- 확인: `is_enabled("flag_name")` 사용.
- 긴급 비활성화: `config.py`에서 `False`로 설정, 재시작 불필요 (import 시점 반영).

### Testing

- 테스트 디렉토리: `tests/`
- 파일 명명: `test_*.py` (pytest 자동 수집)
- Fixture: `conftest.py`에 공통 fixture 정의
- 마커: `@pytest.mark.slow`, `@pytest.mark.integration` 등 사용
- **신규 기능은 반드시 테스트 동반** (test_data_contract.py, test_dashboard_feed.py 등)

### Commit Rules

- `.env`, `.secrets/` 커밋 금지
- `working.json`, `p5_autoexecutor.lock` 커밋 금지
- 자동 커밋 금지 (사용자 명시적 요청 시만)
- 커밋 메시지: 한글 또는 영문, "what + why" 포함
