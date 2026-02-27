# TECH_SPEC_P5_INTEGRATION.md

> P5 Integration Architecture &mdash; Technical Specification v1.0
> Date: 2026-02-17 | Status: Draft | Owner: AI Agent Team

---

## 1. Executive Summary

### Problem

P5 건설 프로젝트 자동화 시스템(`14.AI_Agent`)은 310+ 키워드, 47 executor, 31 skill을 보유한 풍부한 기능 기반이나, **데이터 품질**과 **운영 루프 완성도**에 심각한 격차가 존재한다.

**데이터 품질 위기** (732건 이슈 기준):
- `owner` 필드: 3/732건 입력 (99.6% 누락)
- `due_date` 필드: 2/732건 입력 (99.7% 누락)
- `decision` 필드: 0/732건 입력 (100% 공란)
- `priority: normal` 값 161건 존재 &mdash; config에 정의 없어 정규화 실패
- `zone` 필드: 완전 자유형 텍스트 (표준화 부재, 집계/필터 불가)

**운영 루프 미완성**:
- 일일 트리아지가 `--dry-run`으로만 실행 중 (`p5_daily.bat:64`) &mdash; 실제 반영 없음
- 6개 feature flag 전부 `False` (`config.py:66-73`) &mdash; 구현된 기능이 비활성
- 4개 스크립트에 하드코딩 경로 잔존 (`p5_config.py` 원칙 위반)

### Solution

1. **Unified Data Contract v1**: priority/status/zone/source_origin 정규화 스키마 정의
2. **파이프라인 hardening**: dry-run → prod 전환, feature flag 단계적 활성화
3. **레거시 흡수**: `11.P5_PJT/master_config.json`에서 zone/severity/production stage 정의만 선별 수용

### Expected Outcomes

| Metric | Current | Target |
|--------|---------|--------|
| Priority 정규화 | 161건 invalid (`normal`) | 0건 (100% canonical) |
| Owner/due (critical) | ~0% | >80% (hard gate) |
| Triage 모드 | dry-run only | live (`--auto-apply-above 5`) |
| Feature flags active | 0/6 | 3/6 (Phase 1) |
| Dashboard feed | 없음 | JSON 자동 생성 |

---

## 2. As-Is Architecture

### System Topology

```
Google Sheets (접수 메일)
    │
    ▼
p5_issue_sync.py ──sync──▶ ResearchVault/P5-Project/01-Issues/ (732 .md)
    │                            │
    │                            ├── p5_metrics.py ──▶ 운영메트릭.md (5 KPI)
    │                            │
    ├──push──▶ Google Sheets     ├── p5_daily_briefing.py ──▶ 브리핑.md
    │         (역동기화)          │
    │                            └── p5_email_triage.py ──▶ [DRY-RUN ONLY]
    │
    └──context──▶ NotebookLM Context Sheet

Outlook ──message_daemon.py──▶ ResearchVault/00-Inbox/Messages/Emails/
                                    │
                                    └── OCR Pipeline (GLM-OCR via Ollama)

Telegram ──310+ keywords──▶ 47 executors ──▶ 31 skills
    │
    └── telegram_bot.py (check → combine → execute → report → done)
```

### Data Quality Dashboard (Current State)

| Field | Populated | Total | Fill Rate | Impact |
|-------|-----------|-------|-----------|--------|
| issue_id | 732 | 732 | 100% | &mdash; |
| title | 732 | 732 | 100% | &mdash; |
| priority | 732 | 732 | 100% | 161건 `normal` (config 미정의) |
| status | 732 | 732 | 100% | &mdash; |
| owner | 3 | 732 | 0.4% | critical 이슈 담당자 부재 |
| due_date | 2 | 732 | 0.3% | 일정 관리 불가 |
| decision | 0 | 732 | 0% | 의사결정 추적 불가 |
| zone | ~200 | 732 | ~27% | 자유형 텍스트, 집계 불가 |

### Feature Flags Status

| Flag | State | Purpose | Impact of `False` |
|------|-------|---------|-------------------|
| `hard_gate_issues` | `False` | CRITICAL 이슈 데이터 차단 | owner 없는 critical 이슈 통과 |
| `state_machine` | `False` | 7단계 메시지 상태 전이 | 상태 전이 검증 없음 |
| `error_classification` | `False` | 에러 심각도 분류 | 에러 구분 없이 로깅 |
| `kakao_preflight` | `False` | 카카오톡 프리플라이트 체크 | 카카오 미실행 시 무응답 |
| `rag_search` | `False` | TF 가중 메모리 검색 | 단순 키워드 검색만 |
| `proactive_alerts` | `False` | 건강 모니터링 알림 | 사전 알림 없음 |

---

## 3. To-Be Architecture

### System Topology (변경 사항 강조)

```
Google Sheets (접수 메일)
    │
    ▼
p5_issue_sync.py ──sync──▶ [NEW] Data Contract Validator
    │                            │
    │                            ├── priority 정규화 (normal→medium)
    │                            ├── zone 정규화 (regex 사전)
    │                            ├── owner/due hard gate (critical)
    │                            │
    │                            ▼
    │                       ResearchVault/P5-Project/01-Issues/ (732 .md)
    │                            │
    │                            ├── p5_metrics.py ──▶ 운영메트릭.md
    │                            │       └── [NEW] generate_dashboard_feed()
    │                            │              └── dashboard-feed.json
    │                            │
    ├──push──▶ Google Sheets     ├── p5_daily_briefing.py ──▶ 브리핑.md
    │                            │
    │                            └── p5_email_triage.py ──▶ [LIVE MODE]
    │                                 └── --auto-apply-above 5
    │
    └──context──▶ NotebookLM

Feature Flags:  hard_gate_issues=True → state_machine=True → error_classification=True
```

### Key Changes

1. **Data Contract enforcement layer**: `parse_issue()` 내에서 priority/zone 자동 정규화
2. **Triage live mode**: `p5_daily.bat:64`에서 `--dry-run` 제거, `--auto-apply-above 5` 적용
3. **Feature flag graduated rollout**: `hard_gate_issues` (Week 1) → `state_machine` (Week 3) → `error_classification` (Week 3)
4. **Zone 정규화**: sync 시점에 regex 사전 적용, 미매칭 시 `na` 기본값 + 로그 경고
5. **Dashboard feed**: `p5_metrics.py generate` 실행 시 JSON 자동 생성

---

## 4. Design Principles

1. **API-first**: GUI 스크래핑 배제. Google Sheets API, Telegram Bot API, Outlook COM/EWS만 사용
2. **SSOT on Obsidian**: `ResearchVault`가 유일한 진실 원천(Single Source of Truth). Sheets/Notion은 뷰
3. **State machine 기반 처리**: 7-state lifecycle 활성화 (INBOX → TRIAGE → CONTEXT_READY → EXECUTING → VERIFIED → CLOSED → LEARNED)
4. **Evidence-first logging**: `triage-audit-log.jsonl` 활용. 모든 자동 결정에 감사 추적
5. **Atomic writes**: `.tmp` + `os.replace()` 패턴. JSON 파일 손상 방지
6. **Feature flag 기반 graduated rollout**: 신규 기능은 반드시 flag 뒤에 배치. 문제 시 즉시 비활성화

---

## 5. Unified Data Contract v1

### 5.1 Priority Enum

정규화 규칙 &mdash; `PRIORITY_MAPPING` (`p5_issue_sync.py:115-120`) + `p5-sync-config.yaml:38-42` 확장:

| Raw Value | Canonical | Notes |
|-----------|-----------|-------|
| `긴급` / `critical` | `critical` | |
| `높음` / `high` | `high` | |
| `중간` / `medium` | `medium` | |
| `낮음` / `low` | `low` | |
| `normal` | `medium` | **161건 재매핑** (Google Sheets 기본값) |
| (empty) | `medium` | 기본값 |

**구현 위치**: `p5_issue_sync.py:115-120` PRIORITY_MAPPING에 `"normal": "medium"` 추가, `p5-sync-config.yaml:38-42` priority_mapping에 동일 항목 추가.

### 5.2 Status Enum

현행 5값 + 레거시 `master_config.json` statusCodes 7값 통합:

| Current (14.AI_Agent) | Legacy (11.P5_PJT) | Canonical | Description |
|------------------------|---------------------|-----------|-------------|
| `열림` / open | pending | `open` | 신규/미처리 |
| `진행중` / in_progress | active | `in_progress` | 처리 중 |
| `완료` / resolved | installed | `resolved` | 조치 완료 |
| `종료` / closed | &mdash; | `closed` | 최종 종료 |
| `보류` / on_hold | hold_tc, hold_design, hold_material, hold_safety | `on_hold` | 보류 + `hold_reason` 필드 추가 |

**hold_reason enum** (Phase 2 도입): `tc` | `design` | `material` | `safety` | `other`

### 5.3 Zone Normalization Dictionary

레거시 `master_config.json` zone 모델 흡수:

| zone_id | Column Range | Display Name | Matching Patterns (regex) |
|---------|-------------|--------------|---------------------------|
| `zone_a` | 1-23열 | FAB | `[1-9]열`, `1[0-9]열`, `2[0-3]열`, `FAB`, `ZONE\s*A`, `유틸리티` |
| `zone_b` | 24-45열 | CUB | `2[4-9]열`, `3[0-9]열`, `4[0-5]열`, `CUB`, `ZONE\s*B` |
| `zone_c` | 46-69열 | COMPLEX | `4[6-9]열`, `5[0-9]열`, `6[0-9]열`, `복합동`, `ZONE\s*C`, `COMPLEX` |
| `cross_zone` | &mdash; | 교차 구간 | `전구간`, `전체`, `전층`, `P5.*P6`, `경계` |
| `na` | &mdash; | 해당없음 | `해당없음`, `미정`, 빈값, regex 미매칭 fallback |

**구현**: `p5-sync-config.yaml`에 `zone_normalization:` 섹션 추가, `parse_issue()`에서 매칭 로직 적용. 미매칭 시 `na` + 로그 경고.

### 5.4 Source Origin Enum

| Code | Name | Domain |
|------|------|--------|
| `SAMSUNG` | 삼성E&A | @samsung.com |
| `SENKUZO` | 센구조 | @senkuzo.com |
| `EANDI` | 이앤디몰 | naver.com |
| `SAMOO` | 삼우종합건축 | @samoo.com |
| `ENA` | ENA | (기타) |
| `OTHER` | 기타 | 미분류 |

### 5.5 Required/Optional Fields & Enforcement Rules

| Field | Required | Default | Enforcement Rule |
|-------|----------|---------|------------------|
| `issue_id` | 필수 | &mdash; | 누락 시 sync 차단 (parse_issue → None) |
| `title` | 필수 | &mdash; | 누락 시 sync 차단 |
| `priority` | 필수 | `medium` | `normal` → `medium` 자동 변환, 빈값 → `medium` |
| `status` | 필수 | `open` | 기본값 적용 |
| `owner` | 조건부 | &mdash; | `critical`: `hard_gate_issues=True` 시 sync 차단. `high`: 경고만 |
| `due_date` | 조건부 | &mdash; | `critical`: `hard_gate_issues=True` 시 sync 차단. `high`: 경고만 |
| `zone` | 선택 | `na` | 정규화 사전 적용 |
| `category` | 선택 | `일반` | CATEGORY_MAPPING 적용 |
| `decision` | 선택 | &mdash; | 완전도 KPI에 반영 |
| `source_origin` | 선택 | &mdash; | contractor 코드 정규화 (Phase 2) |
| `hold_reason` | 선택 | &mdash; | status=`on_hold` 시 사유 (Phase 2) |
| `production_stage` | 선택 | &mdash; | 6단계 코드 (Phase 2) |

---

## 6. Data Pipeline Spec

### 7-State Lifecycle

| # | State | Entry Condition | Exit Condition | Failure Handling |
|---|-------|-----------------|----------------|------------------|
| 1 | `INBOX` | 새 메시지/이메일 도착 | 트리아지 엔진 수신 | 30분 미처리 시 경고 |
| 2 | `TRIAGE` | 트리아지 엔진 수신 | score 계산 + classification 완료 | 파싱 실패 시 `flag_for_review` |
| 3 | `CONTEXT_READY` | 이슈 매칭 + 엔티티 추출 완료 | executor 할당 | 매칭 실패 시 리뷰큐 |
| 4 | `EXECUTING` | executor 시작 + working.json 잠금 | 작업 완료 + report_telegram() | 30분 타임아웃 시 잠금 자동 해제 |
| 5 | `VERIFIED` | 결과물 검증 통과 | mark_done + 메모리 저장 | 검증 실패 시 재실행 또는 수동 |
| 6 | `CLOSED` | 모든 후속 작업 완료 | Obsidian worklog 생성 | &mdash; |
| 7 | `LEARNED` | 결과/패턴 메모리 저장 | 세션 종료 또는 다음 작업 | 메모리 저장 실패 시 로그 |

**활성화**: `state_machine` feature flag = `True` (Phase 1, Week 3)

### Pipeline Execution Flow (p5_daily.bat)

```
Step 0: 텔레그램 미처리 확인
Step 1: Outlook 이메일 수집 + 자동 트리아지
Step 2a: OCR 서비스 점검
Step 2b: 첨부파일 OCR (GLM-OCR)
Step 3: Google Sheets → Vault 동기화 (+ Data Contract 검증)
Step 3.5: Sheets → Notion 동기화
Step 3.6: NotebookLM Context 업데이트
Step 4: 이메일 트리아지 (현재: --dry-run → 변경: --auto-apply-above 5)
Step 4.5: NotebookLM → Obsidian 동기화
Step 5: 리뷰큐 자동 정리 (dedup + clean)
Step 6: Vault → Sheets 역동기화
Step 7: 데일리 브리핑 생성
Step 8: 운영 메트릭 대시보드 (+ dashboard-feed.json)
Step 9: 종합 상태 리포트
```

---

## 7. Legacy Asset Mapping

Source: `11.P5_PJT/src/dashboard/data/master_config.json`

### 7.1 zones[] → Zone Normalization Dictionary

| Legacy Field | Target | Mapping |
|-------------|--------|---------|
| `zones[0]` (zone_a, FAB, col 1-23) | `zone_normalization.zone_a` | range + regex patterns |
| `zones[1]` (zone_b, CUB, col 24-45) | `zone_normalization.zone_b` | range + regex patterns |
| `zones[2]` (zone_c, COMPLEX, col 46-69) | `zone_normalization.zone_c` | range + regex patterns |

### 7.2 severityLevels[] → Priority Enum

| Legacy | Canonical | Status |
|--------|-----------|--------|
| `critical` | `critical` | 이미 정렬됨 |
| `high` | `high` | 이미 정렬됨 |
| `medium` | `medium` | 이미 정렬됨 |
| `low` | `low` | 이미 정렬됨 |

### 7.3 productionStages[] → production_stage 필드 (Phase 2)

| Code | Korean | English | Order |
|------|--------|---------|-------|
| `hmb_fab` | HMB제작 | HMB Fabrication | 1 |
| `pre_assem` | 면조립 | Pre-Assembly | 2 |
| `main_assem` | 대조립 | Main Assembly | 3 |
| `hmb_psrc` | HMB+PSRC | HMB+PSRC Insert | 4 |
| `form` | FORM | Formwork | 5 |
| `embed` | 앰베드 | Embed | 6 |

### 7.4 statusCodes → Status Enum + hold_reason

| Legacy Code | Legacy Label | Canonical Status | hold_reason |
|-------------|-------------|-----------------|-------------|
| `pending` | 대기 | `open` | &mdash; |
| `active` | 진행중 | `in_progress` | &mdash; |
| `installed` | 설치완료 | `resolved` | &mdash; |
| `hold_tc` | T/C Hold | `on_hold` | `tc` |
| `hold_design` | 설계 변경 | `on_hold` | `design` |
| `hold_material` | 자재 대기 | `on_hold` | `material` |
| `hold_safety` | 안전 점검 | `on_hold` | `safety` |

### 7.5 issueTypes[] → Category Mapping

| Legacy Code | Legacy Label | Category |
|-------------|-------------|----------|
| `tc` | T/C 간섭 | `interference` (기존 CATEGORY_MAPPING) |
| `design` | 설계 변경 | `design` |
| `material` | 자재 이슈 | `material` |
| `safety` | 안전 이슈 | `safety` (신규 추가) |
| `quality` | 품질 이슈 | `quality` (신규 추가) |

### 7.6 shopIssue.typeDefinitions → Shop Type Codes

| Code | Name | Full Name | Owner |
|------|------|-----------|-------|
| `A` | 일반 사항 | 일반 사항(전체 영향) | 공통 |
| `P` | PSRC | PSRC 사항 | 강상규, 센구조 |
| `G` | PC | PC 사항 | 강상규, 이엔디몰 |
| `W` | PTW | PTW 사항 | 이지영, PSTEC |
| `R` | 철근 | 철근 사항 (기초제외) | 미정 |
| `S` | 철골 | 철골 사항 | 미정 |
| `D` | DECK | DECK 사항 | 미정 |
| `F` | 기초 | 기초 사항 | 미정 |

---

## 8. Dashboard Feed Spec

### Output Path

`ResearchVault/P5-Project/00-Overview/dashboard-feed.json`

### JSON Schema

```json
{
  "$schema": "dashboard-feed-v1",
  "generated_at": "2026-02-17T09:00:00+09:00",
  "kpi": {
    "snr": {
      "value": 4.2,
      "status": "green",
      "description": "Signal-to-Noise Ratio"
    },
    "triage_accuracy": {
      "value": 78.5,
      "unit": "%",
      "status": "yellow",
      "description": "Triage matching accuracy"
    },
    "decision_velocity": {
      "value": 2,
      "unit": "decisions/week",
      "status": "red",
      "target": 3,
      "description": "Decision velocity"
    },
    "queue_health": {
      "total": 45,
      "unchecked": 12,
      "stale_7d": 3,
      "status": "yellow",
      "description": "Review queue health"
    },
    "data_completeness": {
      "overall": 42.5,
      "unit": "%",
      "status": "red",
      "breakdown": {
        "critical": {"total": 15, "owner": 0, "due_date": 0, "decision": 0},
        "high": {"total": 45, "owner": 2, "due_date": 1, "decision": 0},
        "medium": {"total": 500, "owner": 1, "due_date": 1, "decision": 0},
        "low": {"total": 172, "owner": 0, "due_date": 0, "decision": 0}
      },
      "description": "Data completeness by priority"
    }
  },
  "priority_actions": [
    {
      "id": "PA-001",
      "action": "critical 이슈 15건 owner 미지정",
      "severity": "critical",
      "due": "immediate"
    }
  ],
  "zone_progress": {
    "zone_a": {"open": 45, "in_progress": 12, "resolved": 30, "total": 87},
    "zone_b": {"open": 38, "in_progress": 8, "resolved": 25, "total": 71},
    "zone_c": {"open": 52, "in_progress": 15, "resolved": 35, "total": 102},
    "cross_zone": {"open": 10, "in_progress": 3, "resolved": 5, "total": 18},
    "na": {"open": 200, "in_progress": 50, "resolved": 204, "total": 454}
  },
  "risk_items": [
    {
      "issue_id": "SEN-001",
      "title": "Example risk item",
      "priority": "critical",
      "days_open": 45,
      "owner": "",
      "zone": "zone_a"
    }
  ]
}
```

### Generation

- **Trigger**: `python p5_metrics.py generate` 실행 시 `generate_dashboard_feed()` 함수 호출
- **Consumers**: p5_daily_briefing.py, telegram 봇 (briefing executor), Obsidian Dashboard.md
- **Frequency**: 1일 1회 (p5_daily.bat Step 8)

---

## 9. Reliability & Error Handling

### Bare Except 축소 원칙

**규칙**: 프로덕션 코드에서 `except Exception: pass` 금지. 최소한 로깅 필수.

```python
# BAD
try:
    sync_issue(record)
except Exception:
    pass

# GOOD
try:
    sync_issue(record)
except Exception as e:
    log.warning(f"이슈 동기화 실패: {record.get('issue_id', '?')}: {e}")
```

### ErrorSeverity Enum 활용

Source: `scripts/telegram/config.py:88-93`

| Level | Action | Example |
|-------|--------|---------|
| `LOW` | 로그만 | OCR 단일 페이지 파싱 실패 |
| `MEDIUM` | 재시도 가능, 사용자 미통보 | API 일시적 타임아웃 |
| `HIGH` | 재시도 필요 + 텔레그램 경고 | Sheets API 인증 만료 |
| `CRITICAL` | 즉시 중단 + 즉시 알림 | 데이터 파일 손상, 잠금 교착 |

### Retry Strategy

- API 호출: 최대 3회, exponential backoff (1s, 2s, 4s)
- 파일 I/O: 최대 2회, 0.5s 간격
- 외부 서비스 (OCR): health check 후 skip (p5_daily.bat:33-37)

---

## 10. Security & Governance

### Credentials Management

| Secret | Storage | Access |
|--------|---------|--------|
| Telegram Bot Token | `.env` (`TELEGRAM_BOT_TOKEN`) | `dotenv` 런타임 로드 |
| Telegram User ID | `.env` (`TELEGRAM_ALLOWED_USERS`) | 허용 목록 검증 |
| Google Sheets API | `.secrets/google-sheets-credentials.json` | Service account |
| Google Drive API | `.secrets/google-sheets-credentials.json` | 동일 SA |

### Sensitive Data Rules

- `.env`, `.secrets/` 디렉토리: `.gitignore`에 등록, 커밋 금지
- 로그에 토큰/키/비밀번호 출력 금지
- 사용자 개인정보(이메일, 전화번호) 로그 시 마스킹

### Audit Trail

- **Triage audit log**: `ResearchVault/_config/triage-audit-log.jsonl`
- **기록 항목**: timestamp, email_id, action, score, classification, matched_issue, applied_changes
- **보존**: 90일 (이후 아카이브)

---

## 11. Migration Strategy (6 Weeks)

### Week 1-2: P0 &mdash; Foundation

| Task | Description | Risk |
|------|-------------|------|
| Priority 정규화 | `"normal"` → `"medium"` 161건 재매핑 | Low: 단순 매핑 추가 |
| Zone 정규화 사전 | regex 기반 5-zone 매핑 | Medium: regex 미매칭 가능 |
| 하드코딩 경로 제거 | 4개 파일 (launch_dashboard, _verify_ocr, scheduler) | Low: p5_config import |
| 회귀 테스트 | test_data_contract.py + test_dashboard_feed.py | Low |
| Owner/due 강제 규칙 | hard_gate_issues flag 활성화 | Medium: critical 이슈 sync 차단 |
| Dry-run → prod | p5_daily.bat:64 변경 | Medium: 라이브 반영 시작 |
| Dashboard feed 설계 | JSON 스키마 + generate 함수 | Low |
| 라우팅 감사 | KEYWORD_MAP vs EXECUTOR_MAP 검증 | Low |

### Week 3-4: P1 &mdash; Activation

| Task | Description | Risk |
|------|-------------|------|
| state_machine flag | 7-state lifecycle 활성화 | Medium: 상태 전이 오류 |
| error_classification flag | ErrorSeverity 기반 분류 | Low |
| p5_metrics 경로 리팩터 | L26-34 → p5_config import | Low |
| 중복 함수 제거 | load_config/\_load_config 통합 | Low |
| p5_daily.bat 정합성 | 단계 번호 불일치 수정 | Low |
| Triage 감사 로그 | jsonl 활성화 | Low |

### Week 5-6: P2 &mdash; Enhancement

| Task | Description | Risk |
|------|-------------|------|
| production_stage 필드 | 레거시 6단계 코드 도입 | Medium: frontmatter 확장 |
| hold_reason 세분화 | on_hold 사유 코드 | Low |
| zone_progress 메트릭 | zone별 open/resolved 집계 | Low |
| contractor 코드 정규화 | source_origin enum 적용 | Low |
| Executive Report 강화 | 주간 리포트에 zone/stage 포함 | Low |

---

## 12. KPI / SLI / SLO

| KPI | Current | Target (6wk) | Measurement Method |
|-----|---------|--------------|-------------------|
| Priority 일관성 | 161 invalid | 0 | `grep "priority: normal" 01-Issues/` |
| Data completeness (critical) | ~0% | >80% | `p5_metrics.py calc_data_completeness()` |
| Decision velocity | ~0/week | >3/week | `p5_metrics.py calc_decision_velocity()` |
| Queue health (unchecked) | 미측정 | <5 | `p5_metrics.py calc_queue_health()` |
| Triage accuracy | 미측정 | >70% | `p5_metrics.py calc_triage_accuracy()` |
| SNR (Signal-to-Noise) | 미측정 | >3.0 | `p5_metrics.py calc_snr()` |
| Feature flags active | 0/6 | 3/6 | `config.py FEATURE_FLAGS` 확인 |
| Hardcoded paths | 4건 | 0건 | `grep -r "r\"D:" scripts/` |

### SLI/SLO

| SLI | SLO | Measurement |
|-----|-----|-------------|
| Issue sync latency | <5 min (Sheets → Vault) | p5_issue_sync.py 실행 시간 |
| Triage processing | <10 min (전체 큐) | p5_email_triage.py 실행 시간 |
| Telegram response | <30 sec (첫 응답) | working.json timestamp diff |
| Dashboard freshness | <24h | dashboard-feed.json generated_at |

---

## 13. Risks and Mitigations

| # | Risk | Probability | Impact | Mitigation |
|---|------|-------------|--------|------------|
| R1 | Priority 정규화 후 기존 필터 깨짐 | Low | Medium | 회귀 테스트 + dry-run 선행 |
| R2 | Zone regex 미매칭 비율 >20% | Medium | Medium | fallback=`na` + 로그, 점진적 regex 개선 |
| R3 | hard_gate로 critical 이슈 대량 차단 | Medium | High | 사전 데이터 보충 캠페인, flag 즉시 비활성 가능 |
| R4 | Triage live 전환 후 오분류 | Medium | Medium | `--auto-apply-above 5` (고점수만), audit log |
| R5 | Sheets API quota 초과 (빈번 sync) | Low | High | tiered_sync로 API 호출 최소화 |
| R6 | OCR 서비스 장기 불가 | Medium | Low | health check + skip 패턴 이미 구현 |
| R7 | working.json 교착 (30분 타임아웃 부족) | Low | Medium | 활동 기반 감지, 자동 해제 |
| R8 | Notion 양방향 sync 충돌 | Medium | Medium | only_fill_empty 전략 유지 |
| R9 | 레거시 master_config 구조 변경 | Low | Low | 읽기 전용 참조, 복사본 불필요 |
| R10 | 테스트 커버리지 부족으로 regression | Medium | High | P0-8에서 핵심 테스트 우선 구축 |

---

## 14. Definition of Done

### Phase 0 (P0) Checklist

- [ ] `grep "priority: normal" ResearchVault/P5-Project/01-Issues/` → 0건
- [ ] 전체 732 이슈의 priority가 `{critical, high, medium, low}`만 존재
- [ ] 전체 이슈의 zone이 `{zone_a, zone_b, zone_c, cross_zone, na}`만 존재
- [ ] `grep -r 'r"D:' scripts/ --include="*.py"` → launch_dashboard, _verify_ocr 이외 0건 → 수정 후 완전 0건
- [ ] `hard_gate_issues` flag = `True` 상태에서 critical+owner 누락 이슈 sync 차단 확인
- [ ] `p5_daily.bat:64`에서 `--dry-run` 제거, `--auto-apply-above 5` 적용
- [ ] `dashboard-feed.json` JSON schema validation 통과
- [ ] `pytest tests/ -v` 전체 통과 (기존 + 신규 테스트)
- [ ] KEYWORD_MAP의 모든 value가 EXECUTOR_MAP에 존재 (`test_keyword_routing.py` pass)

### Phase 1 (P1) Checklist

- [ ] `state_machine` flag = `True`, 7-state 전이 검증 통과
- [ ] `error_classification` flag = `True`, ErrorSeverity 기반 분류 작동
- [ ] `p5_metrics.py` 내 하드코딩 경로 0건 (L26-34 → p5_config import)
- [ ] `p5_issue_sync.py` 중복 `_load_config()` 제거, `load_config()` 1개만 존재
- [ ] `p5_daily.bat` 단계 번호 일관성 확인 (/9 vs /10 혼재 해소)
- [ ] triage-audit-log.jsonl에 감사 기록 생성 확인

### Phase 2 (P2) Checklist

- [ ] `production_stage` frontmatter 필드 추가, 6단계 코드 유효
- [ ] `hold_reason` 필드 추가, on_hold 이슈에 사유 기록
- [ ] `zone_progress` 메트릭이 dashboard-feed.json에 포함
- [ ] source_origin contractor 코드 정규화 적용
- [ ] 주간 Executive Report에 zone별 진행률 포함
