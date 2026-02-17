# TODO_P5_INTEGRATION.md

> P5 Integration &mdash; Task Backlog v1.0
> Date: 2026-02-17 | Ref: TECH_SPEC_P5_INTEGRATION.md

---

## P0 (Week 1-2) &mdash; Foundation

8 tasks. Goal: data contract enforcement + regression safety net.

| ID | Priority | Task | Why | Input | Output | Dep | Est(h) | Validation | Done Criteria |
|----|----------|------|-----|-------|--------|-----|--------|------------|---------------|
| P0-1 | P0 | Priority 정규화 | 161건 `"normal"` 값이 config에 없어 미분류 &mdash; `p5_issue_sync.py:803`에서 `raw_priority.lower()` fallback으로 `"normal"` 그대로 저장 | `p5_issue_sync.py:115-120` PRIORITY_MAPPING, `p5-sync-config.yaml:38-42` priority_mapping | PRIORITY_MAPPING에 `"normal": "medium"` 추가, YAML에 동일 항목 추가, re-sync 실행 | 없음 | 2h | `grep "priority: normal" ResearchVault/P5-Project/01-Issues/` → 0건 | 전체 732 이슈의 priority가 `{critical, high, medium, low}`만 존재 |
| P0-2 | P0 | Zone 정규화 사전 | zone 필드가 자유형 텍스트로 집계/필터 불가. 레거시 `master_config.json`에 3-zone 모델 정의 있음 | `master_config.json` zones[], 현행 이슈 zone 값 분석 | `p5-sync-config.yaml`에 `zone_normalization:` 섹션 + `p5_issue_sync.py` `parse_issue()`에 regex 매칭 로직 | 없음 | 4h | 전체 이슈의 zone이 `{zone_a, zone_b, zone_c, cross_zone, na}`만 존재 | regex 미매칭 시 `na` + `log.warning()`, 정규화 커버리지 >80% |
| P0-3 | P0 | Owner/due 강제 규칙 | critical 이슈 99.6% owner 누락은 운영 불가. `_validate_issue_completeness()` 이미 구현되어 있으나 flag=False | `config.py:67` `hard_gate_issues` flag, `p5_issue_sync.py:616-655` 검증 로직 | flag 활성화 문서화, 동작 검증 시나리오, 사전 데이터 보충 계획 | P0-1 | 2h | `hard_gate_issues=True` 상태에서 critical+owner+due 모두 누락 이슈 sync 차단 확인 | flag=True 상태에서 `_validate_issue_completeness()` 테스트 통과, 차단 로그 확인 |
| P0-4 | P0 | Dashboard feed 생성기 설계 | 운영 KPI를 JSON으로 소비 가능하게 &mdash; briefing/telegram/Obsidian에서 활용 | `p5_metrics.py` 8개 KPI 함수 (L72-370), TECH_SPEC 8장 JSON 스키마 | JSON 스키마 정의 + `generate_dashboard_feed()` 함수 설계 (p5_metrics.py:420+ 추가) | 없음 | 3h | JSON schema validation 통과, 5개 핵심 KPI + zone_progress + risk_items 포함 | `dashboard-feed.json` 생성 + consumer(briefing)에서 파싱 가능 |
| P0-5 | P0 | Dry-run/prod 분리 | 일일 트리아지가 `--dry-run`으로만 실행 → 분류 결과가 실제 반영되지 않아 실효성 제로 | `p5_daily.bat:64` (`python scripts\p5_email_triage.py process --dry-run`) | `--dry-run` 제거, `--auto-apply-above 5`로 변경 &mdash; score ≥ 5만 자동 적용, <5는 dry-run 유지 | P0-1 | 1h | 일일 배치 실행 후 triage 결과가 이슈 frontmatter에 반영 확인 | score ≥ 5 자동 적용, <5 dry-run, audit log 기록 |
| P0-6 | P0 | 하드코딩 경로 제거 | `p5_config.py` 원칙 위반 4건 잔존 | `launch_dashboard.py:8` (`r"D:\...\ResearchVault"`), `_verify_ocr_module.py:3,62` (`r"D:\...\scripts"`, `r"D:\...\p5_ocr_pipeline.py"`) | `p5_config.py` import 또는 `Path(__file__).resolve().parent` 상대경로로 교체 | 없음 | 2h | `grep -r 'r"D:' scripts/ --include="*.py"` → 0건 (주석/문서 제외) | 모든 경로가 동적 해석, import 경로 확인 |
| P0-7 | P0 | 라우팅/폴백 정비 | 310+ 키워드 중 dead keyword 또는 미등록 executor 잠재 &mdash; 사용자 명령 실패 원인 | `telegram_executors.py` KEYWORD_MAP (L49+) vs EXECUTOR_MAP (L1182+) | 감사 스크립트 결과 문서 + 불일치 수정 | 없음 | 3h | 모든 KEYWORD_MAP value가 EXECUTOR_MAP에 존재 | `test_keyword_routing.py` 100% pass, dead keyword 0건 |
| P0-8 | P0 | 회귀 테스트 전략 | 정규화 변경 후 regression 방지 &mdash; 기존 7개 테스트 파일로는 data contract 미검증 | 기존 `tests/` (7개 파일: conftest, test_core_e2e, test_executor_contracts, test_keyword_routing, test_state_machine, test_error_handler, test_kakao_error_paths, test_memory_search) | `tests/test_data_contract.py` + `tests/test_dashboard_feed.py` 설계 | P0-1, P0-2 | 4h | `pytest tests/ -v` 전체 통과 | priority 정규화/zone 정규화/owner 강제 규칙 테스트 케이스 포함 |

**P0 Total Estimate**: 21h

---

## P1 (Week 3-4) &mdash; Activation

6 tasks. Goal: feature flag 활성화 + 코드 정합성 개선.

| ID | Priority | Task | Why | Input | Output | Dep | Est(h) | Validation | Done Criteria |
|----|----------|------|-----|-------|--------|-----|--------|------------|---------------|
| P1-1 | P1 | state_machine flag 활성화 | 7단계 메시지 상태 전이 미사용 &mdash; 메시지 처리 추적 불가 | `config.py:68` `state_machine: False`, `test_state_machine.py` | flag=True, 기존 테스트 통과 확인, 전이 규칙 문서화 | P0-8 | 3h | `test_state_machine.py` 전체 pass | 7-state 전이 (INBOX→...→LEARNED) 정상 작동, 잘못된 전이 차단 |
| P1-2 | P1 | error_classification flag 활성화 | ErrorSeverity enum 정의됨(config.py:88-93)이나 미사용 | `config.py:69` `error_classification: False`, `error_handler.py` | flag=True, 기존 테스트 통과 확인, severity별 동작 검증 | P0-8 | 2h | `test_error_handler.py` 전체 pass | HIGH→텔레그램 경고, CRITICAL→중단+알림 |
| P1-3 | P1 | p5_metrics.py 경로 리팩터 | L26-34에서 경로를 직접 계산 &mdash; p5_config.py와 중복 정의 | `p5_metrics.py:26-34` (SCRIPT_DIR, PROJECT_ROOT, VAULT_PATH, ISSUES_DIR, DECISIONS_DIR, OVERVIEW_DIR, INBOX_DIR, SYNC_CONFIG_PATH) | `from p5_config import PROJECT_ROOT, VAULT_PATH, ISSUES_DIR, OVERVIEW_DIR, ...`로 교체 | 없음 | 1h | `python p5_metrics.py generate --stdout` 정상 출력 | 중복 경로 정의 0건, p5_config 단일 소스 |
| P1-4 | P1 | 중복 함수 제거 (load_config) | `p5_issue_sync.py`에 `load_config()` (L1263)과 `_load_config()` (L1696) 동일 기능 2개 | `p5_issue_sync.py:1263`, `p5_issue_sync.py:1696` | `_load_config()` 제거, 호출부 `load_config()`로 통합 | 없음 | 1h | `python p5_issue_sync.py sync` + `python p5_issue_sync.py context` 정상 실행 | `grep "def _load_config" p5_issue_sync.py` → 0건 |
| P1-5 | P1 | p5_daily.bat 단계 번호 정합성 | Step 번호 `/9`와 `/10` 혼재 (L26: `[1/9]`, L47: `[3/10]`, L52: `[3.5/10]`) | `p5_daily.bat` 전체 | 단계 번호 통일 (총 단계 수 확정 후 일괄 수정) | 없음 | 0.5h | step 번호 일관성 확인 | 모든 echo 라인에서 동일 총수 사용 |
| P1-6 | P1 | Triage 감사 로그 활성화 | triage-audit-log.jsonl 경로 정의되어 있으나 실제 기록 미구현 | `p5_email_triage.py` apply_triage_results() | 각 적용 건에 대해 jsonl append 로직 추가 | P0-5 | 2h | 트리아지 실행 후 `triage-audit-log.jsonl` 파일에 기록 확인 | 최소 필드: timestamp, email_subject, action, score, classification, matched_issue |

**P1 Total Estimate**: 9.5h

---

## P2 (Week 5-6) &mdash; Enhancement

5 tasks. Goal: 레거시 자산 완전 흡수 + 리포팅 강화.

| ID | Priority | Task | Why | Input | Output | Dep | Est(h) | Validation | Done Criteria |
|----|----------|------|-----|-------|--------|-----|--------|------------|---------------|
| P2-1 | P2 | production_stage 필드 도입 | 레거시 6단계 제작 공정 추적 &mdash; 현재 이슈에 공정 단계 정보 없음 | `master_config.json` productionStages[] (hmb_fab, pre_assem, main_assem, hmb_psrc, form, embed) | `p5-sync-config.yaml`에 production_stage enum, `parse_issue()`에 매핑 + frontmatter 추가 | P0-2 | 3h | 이슈 frontmatter에 production_stage 필드 존재, 6단계 코드 유효 | `grep "production_stage:" 01-Issues/ \| sort -u` → 6단계 + 빈값만 |
| P2-2 | P2 | hold_reason 세분화 | `on_hold` 상태의 사유가 불분명 &mdash; 레거시에 4가지 hold 유형 정의됨 | `master_config.json` statusCodes (hold_tc, hold_design, hold_material, hold_safety) | status=`on_hold` 시 `hold_reason` 필드 추가 (tc/design/material/safety/other) | P0-1 | 2h | on_hold 이슈에 hold_reason 필드 존재 | hold_reason enum validation 통과 |
| P2-3 | P2 | zone_progress 메트릭 추가 | zone별 이슈 진행률 미집계 | P0-2 결과 (zone 정규화 완료), `p5_metrics.py` | `calc_zone_progress()` 함수 + dashboard-feed.json에 zone_progress 섹션 | P0-2, P0-4 | 2h | dashboard-feed.json에 zone_progress 데이터 포함, zone별 open/resolved 집계 정확 | 5개 zone별 카운트 합산 = 전체 이슈 수 |
| P2-4 | P2 | Contractor 코드 정규화 | source_origin 필드가 자유형 텍스트 &mdash; 집계 불가 | `master_config.json` contractors[], 현행 이슈 source_origin 값 | `p5-sync-config.yaml`에 contractor normalization + `parse_issue()` 적용 | 없음 | 2h | source_origin이 enum 값만 존재 | SAMSUNG/SENKUZO/EANDI/SAMOO/ENA/OTHER만 허용 |
| P2-5 | P2 | 주간 Executive Report 강화 | 현행 브리핑에 zone/stage 정보 부재 | P2-1, P2-3 결과, `p5_daily_briefing.py` | 브리핑 템플릿에 zone별 진행률 + production stage 분포 섹션 추가 | P2-1, P2-3 | 3h | 브리핑 .md에 zone 진행률 테이블 + stage 분포 포함 | Obsidian에서 렌더링 확인 |

**P2 Total Estimate**: 12h

---

## Summary

| Phase | Tasks | Estimate | Key Deliverables |
|-------|-------|----------|------------------|
| P0 | 8 | 21h | Data contract, zone normalization, regression tests |
| P1 | 6 | 9.5h | Feature flags, code cleanup, audit log |
| P2 | 5 | 12h | Legacy assets, reporting enhancement |
| **Total** | **19** | **42.5h** | |

---

## P0 Top 10 Execution Order

| Order | ID | Task | Rationale |
|-------|----|------|-----------|
| 1 | P0-1 | Priority 정규화 | 모든 후속 작업의 기반. 161건 invalid 값 해소 |
| 2 | P0-2 | Zone 정규화 사전 | P0-1과 독립, 병렬 가능. zone_progress의 전제 |
| 3 | P0-6 | 하드코딩 경로 제거 | 독립적, 빠른 수정. 원칙 위반 해소 |
| 4 | P0-8 | 회귀 테스트 프레임워크 | P0-1,2 결과 검증. 이후 변경의 안전망 |
| 5 | P0-5 | Dry-run → prod 전환 | 운영 효용 즉시 발생. P0-1 이후 안전 |
| 6 | P0-3 | Owner/due 강제 규칙 | hard_gate flag 활성화. P0-1 이후 |
| 7 | P0-4 | Dashboard feed 생성기 | KPI 소비 채널 확보 |
| 8 | P0-7 | 라우팅 감사 + 폴백 정비 | 독립적, 운영 안정성 |
| 9 | P1-3 | p5_metrics.py 경로 리팩터 | 빠른 코드 정리 |
| 10 | P1-4 | 중복 함수 제거 | 빠른 코드 정리 |
