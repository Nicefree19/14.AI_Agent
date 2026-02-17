# PHASE1_EXECUTION_PROMPT.md

> P5 Integration Phase 1 &mdash; Claude Code Execution Prompt v1.0
> Date: 2026-02-17 | Ref: TODO_P5_INTEGRATION.md (P0-1 ~ P0-8)

이 문서는 Claude Code에 즉시 투입 가능한 9단계 실행 프롬프트입니다.
각 단계는 독립적이며, 실패 시 다음 단계로 진행할 수 있습니다.

---

## Step 1: Priority 정규화 (P0-1)

**목표**: `"normal"` → `"medium"` 매핑 추가. 161건 invalid priority 해소.

**작업**:

1. `scripts/p5_issue_sync.py:115-120`의 `PRIORITY_MAPPING`에 추가:
   ```python
   PRIORITY_MAPPING = {
       "긴급": "critical",
       "높음": "high",
       "중간": "medium",
       "낮음": "low",
       "normal": "medium",   # Google Sheets 기본값 재매핑
   }
   ```

2. `ResearchVault/_config/p5-sync-config.yaml:38-42`의 `priority_mapping`에 추가:
   ```yaml
   priority_mapping:
     긴급: critical
     높음: high
     중간: medium
     낮음: low
     normal: medium    # Google Sheets 기본값 재매핑
   ```

3. re-sync 실행:
   ```bash
   python scripts/p5_issue_sync.py sync
   ```

**검증**:
```bash
grep -r "priority: normal" ResearchVault/P5-Project/01-Issues/ | wc -l
# 기대: 0
```

**진행 보고**: "Step 1 완료: PRIORITY_MAPPING에 normal→medium 추가, re-sync 완료. priority:normal 잔존 N건"

**실패 시**: 매핑 추가만 완료하고 re-sync는 보류. Step 2로 진행.

---

## Step 2: Zone 정규화 사전 (P0-2)

**목표**: 자유형 텍스트 zone 값을 5개 canonical 값으로 정규화.

**작업**:

1. `ResearchVault/_config/p5-sync-config.yaml`에 `zone_normalization` 섹션 추가:
   ```yaml
   # Zone 정규화 사전 (11.P5_PJT master_config.json 기반)
   zone_normalization:
     zone_a:
       display_name: "FAB"
       column_range: "1-23"
       patterns:
         - "[1-9]열"
         - "1[0-9]열"
         - "2[0-3]열"
         - "FAB"
         - "ZONE\\s*A"
         - "유틸리티"
     zone_b:
       display_name: "CUB"
       column_range: "24-45"
       patterns:
         - "2[4-9]열"
         - "3[0-9]열"
         - "4[0-5]열"
         - "CUB"
         - "ZONE\\s*B"
     zone_c:
       display_name: "COMPLEX"
       column_range: "46-69"
       patterns:
         - "4[6-9]열"
         - "5[0-9]열"
         - "6[0-9]열"
         - "복합동"
         - "ZONE\\s*C"
         - "COMPLEX"
     cross_zone:
       display_name: "교차 구간"
       patterns:
         - "전구간"
         - "전체"
         - "전층"
         - "P5.*P6"
         - "경계"
     na:
       display_name: "해당없음"
       patterns:
         - "해당없음"
         - "미정"
   ```

2. `scripts/p5_issue_sync.py`의 `parse_issue()` 함수 내 zone 처리 부분(L828 부근)에 정규화 로직 추가:
   ```python
   import re

   def _normalize_zone(raw_zone: str, config: Optional[dict] = None) -> str:
       """zone 자유형 텍스트를 canonical 값으로 정규화."""
       if not raw_zone or not raw_zone.strip():
           return "na"

       raw = raw_zone.strip()
       zone_norm = {}
       if config:
           zone_norm = config.get("zone_normalization", {})

       for zone_id, zone_def in zone_norm.items():
           for pattern in zone_def.get("patterns", []):
               if re.search(pattern, raw, re.IGNORECASE):
                   return zone_id

       log.warning(f"Zone 미매칭: '{raw}' → 'na' (regex 패턴 추가 필요)")
       return "na"
   ```

3. `parse_issue()` L828에서 호출:
   ```python
   # 기존: zone=str(mapped.get("zone", "")).strip(),
   # 변경:
   zone=_normalize_zone(str(mapped.get("zone", "")), config),
   ```

4. re-sync 실행:
   ```bash
   python scripts/p5_issue_sync.py sync
   ```

**검증**:
```bash
grep -r "zone:" ResearchVault/P5-Project/01-Issues/ | grep -v "zone_a\|zone_b\|zone_c\|cross_zone\|na" | wc -l
# 기대: 0 (모든 zone이 canonical 값)
```

**진행 보고**: "Step 2 완료: zone_normalization 사전 추가, _normalize_zone() 구현. 미매칭 N건 (na 처리)"

**실패 시**: YAML 사전만 추가하고 코드 변경은 보류. Step 3으로 진행.

---

## Step 3: 하드코딩 경로 제거 (P0-6)

**목표**: p5_config.py 원칙 위반 3개 파일 수정.

**작업**:

1. `scripts/launch_dashboard.py:8`:
   ```python
   # 기존:
   # VAULT_PATH = r"D:\00.Work_AI_Tool\14.AI_Agent\ResearchVault"

   # 변경:
   from p5_config import VAULT_PATH
   ```

2. `scripts/_verify_ocr_module.py:3`:
   ```python
   # 기존:
   # sys.path.insert(0, r"D:\00.Work_AI_Tool\14.AI_Agent\scripts")

   # 변경:
   sys.path.insert(0, str(Path(__file__).resolve().parent))
   ```

3. `scripts/_verify_ocr_module.py:62`:
   ```python
   # 기존:
   # r"D:\00.Work_AI_Tool\14.AI_Agent\scripts\p5_ocr_pipeline.py"

   # 변경:
   str(Path(__file__).resolve().parent / "p5_ocr_pipeline.py")
   ```

**검증**:
```bash
grep -rn 'r"D:' scripts/ --include="*.py"
# 기대: p5_config.py:5 (docstring 주석)만 남음
```

**진행 보고**: "Step 3 완료: 하드코딩 경로 3건 제거 (launch_dashboard.py, _verify_ocr_module.py)"

**실패 시**: 각 파일 개별 수정. 실패한 파일만 보류. Step 4로 진행.

---

## Step 4: p5_metrics.py 경로 리팩터 (P1-3)

**목표**: L26-34의 중복 경로 정의를 `p5_config.py` import로 교체.

**작업**:

`scripts/p5_metrics.py:25-34` 교체:

```python
# 기존:
# SCRIPT_DIR = Path(__file__).parent
# PROJECT_ROOT = SCRIPT_DIR.parent
# VAULT_PATH = PROJECT_ROOT / "ResearchVault"
# ISSUES_DIR = VAULT_PATH / "P5-Project" / "01-Issues"
# DECISIONS_DIR = VAULT_PATH / "P5-Project" / "04-Decisions"
# OVERVIEW_DIR = VAULT_PATH / "P5-Project" / "00-Overview"
# INBOX_DIR = VAULT_PATH / "00-Inbox" / "Messages" / "Emails"
# SYNC_CONFIG_PATH = VAULT_PATH / "_config" / "p5-sync-config.yaml"
# LOG_FILE = SCRIPT_DIR / "p5_metrics.log"

# 변경:
from p5_config import (
    PROJECT_ROOT, VAULT_PATH, ISSUES_DIR, OVERVIEW_DIR,
    INBOX_DIR, CONFIG_DIR, LOG_DIR,
)

SCRIPT_DIR = Path(__file__).parent
DECISIONS_DIR = VAULT_PATH / "P5-Project" / "04-Decisions"
SYNC_CONFIG_PATH = CONFIG_DIR / "p5-sync-config.yaml"
LOG_FILE = LOG_DIR / "p5_metrics.log"
```

**검증**:
```bash
python scripts/p5_metrics.py generate --stdout
# 기대: 정상 출력 (경로 해석 동일)
```

**진행 보고**: "Step 4 완료: p5_metrics.py 경로 7개 → p5_config import로 교체"

**실패 시**: import 경로 문제일 가능성. sys.path 보정 확인 후 보류. Step 5로 진행.

---

## Step 5: Dashboard Feed 생성기 (P0-4)

**목표**: `p5_metrics.py`에 `generate_dashboard_feed()` 함수 추가.

**작업**:

`scripts/p5_metrics.py`의 `cmd_generate()` 함수 직전(L420 부근)에 추가:

```python
import json

def generate_dashboard_feed(metrics: List[Dict]) -> Path:
    """운영 KPI를 JSON feed로 생성.

    Output: ResearchVault/P5-Project/00-Overview/dashboard-feed.json
    """
    feed = {
        "$schema": "dashboard-feed-v1",
        "generated_at": datetime.now().isoformat(),
        "kpi": {},
        "priority_actions": [],
        "zone_progress": {},
        "risk_items": [],
    }

    for m in metrics:
        name_key = {
            "신호대잡음비": "snr",
            "트리아지 정확도": "triage_accuracy",
            "결정 속도": "decision_velocity",
            "큐 건강도": "queue_health",
            "데이터 완전성": "data_completeness",
        }.get(m.get("name", ""), "")

        if name_key:
            entry = {"value": m.get("value"), "status": m.get("status", "")}
            if "unit" in m:
                entry["unit"] = m["unit"]
            if "breakdown" in m:
                entry["breakdown"] = m["breakdown"]
            feed["kpi"][name_key] = entry

    # zone_progress: 이슈 디렉토리에서 zone별 집계
    zone_counts = {"zone_a": {}, "zone_b": {}, "zone_c": {}, "cross_zone": {}, "na": {}}
    if ISSUES_DIR.exists():
        for issue_file in ISSUES_DIR.glob("*.md"):
            try:
                content = issue_file.read_text(encoding="utf-8", errors="replace")
                if not content.startswith("---"):
                    continue
                parts = content.split("---", 2)
                if len(parts) >= 2:
                    fm = yaml.safe_load(parts[1]) or {}
                    zone = fm.get("zone", "na")
                    status = fm.get("issue_status", "open")
                    if zone not in zone_counts:
                        zone = "na"
                    if zone not in zone_counts:
                        zone_counts[zone] = {}
                    zone_counts[zone][status] = zone_counts[zone].get(status, 0) + 1
            except Exception:
                pass

    feed["zone_progress"] = zone_counts

    # risk_items: critical + open + no owner
    if ISSUES_DIR.exists():
        for issue_file in ISSUES_DIR.glob("*.md"):
            try:
                content = issue_file.read_text(encoding="utf-8", errors="replace")
                if not content.startswith("---"):
                    continue
                parts = content.split("---", 2)
                if len(parts) >= 2:
                    fm = yaml.safe_load(parts[1]) or {}
                    if (fm.get("priority") == "critical"
                            and fm.get("issue_status") in ("open", "in_progress")
                            and not fm.get("owner", "").strip()):
                        feed["risk_items"].append({
                            "issue_id": fm.get("issue_id", ""),
                            "title": fm.get("title", ""),
                            "priority": "critical",
                            "owner": "",
                            "zone": fm.get("zone", "na"),
                        })
            except Exception:
                pass

    output_path = OVERVIEW_DIR / "dashboard-feed.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # atomic write
    import tempfile
    tmp_fd, tmp_path = tempfile.mkstemp(dir=str(output_path.parent), suffix=".tmp")
    try:
        with os.fdopen(tmp_fd, 'w', encoding='utf-8') as f:
            json.dump(feed, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, str(output_path))
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise

    log.info(f"Dashboard feed 생성: {output_path}")
    return output_path
```

그리고 `cmd_generate()` 함수 내에서 호출 추가:

```python
def cmd_generate(args):
    # ... (기존 코드)
    metrics = [calc_snr(), calc_triage_accuracy(), ...]
    md = render_metrics_dashboard(metrics)
    # ... (기존 파일 출력)

    # Dashboard feed 생성 (추가)
    try:
        generate_dashboard_feed(metrics)
    except Exception as e:
        log.warning(f"Dashboard feed 생성 실패: {e}")
```

**검증**:
```bash
python scripts/p5_metrics.py generate
cat ResearchVault/P5-Project/00-Overview/dashboard-feed.json | python -m json.tool
# 기대: valid JSON, kpi/zone_progress/risk_items 포함
```

**진행 보고**: "Step 5 완료: generate_dashboard_feed() 추가. JSON feed 생성 확인"

**실패 시**: 함수 코드만 추가하고 cmd_generate 연동은 보류. Step 6으로 진행.

---

## Step 6: Triage 모드 전환 (P0-5)

**목표**: `p5_daily.bat:64`에서 `--dry-run` → `--auto-apply-above 5`.

**작업**:

`scripts/p5_daily.bat:64` 변경:

```batch
REM 기존:
REM python scripts\p5_email_triage.py process --dry-run

REM 변경:
python scripts\p5_email_triage.py process --auto-apply-above 5
```

**참고**: `--auto-apply-above 5`는 score >= 5인 트리아지 결과만 자동 적용, score < 5는 dry-run 동작.

**검증**:
```bash
grep "auto-apply" scripts/p5_daily.bat
# 기대: python scripts\p5_email_triage.py process --auto-apply-above 5
```

**진행 보고**: "Step 6 완료: p5_daily.bat:64 triage 모드 dry-run → auto-apply-above 5 전환"

**실패 시**: `p5_email_triage.py`에 `--auto-apply-above` 옵션 미지원일 가능성. 옵션 존재 확인 후 보류. Step 7로 진행.

---

## Step 7: 회귀 테스트 (P0-8)

**목표**: `tests/test_data_contract.py` + `tests/test_dashboard_feed.py` 생성.

**작업**:

1. `tests/test_data_contract.py`:

```python
"""Data Contract 검증 테스트.

priority/zone/owner 정규화 규칙 검증.
"""
import pytest
import sys
from pathlib import Path

# sys.path 보정
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))


class TestPriorityNormalization:
    """Priority 정규화 테스트."""

    def test_normal_maps_to_medium(self):
        """'normal' → 'medium' 매핑 확인."""
        from p5_issue_sync import PRIORITY_MAPPING
        assert "normal" in PRIORITY_MAPPING
        assert PRIORITY_MAPPING["normal"] == "medium"

    def test_all_canonical_values(self):
        """모든 매핑 결과가 canonical 값."""
        from p5_issue_sync import PRIORITY_MAPPING
        canonical = {"critical", "high", "medium", "low"}
        for raw, mapped in PRIORITY_MAPPING.items():
            assert mapped in canonical, f"'{raw}' → '{mapped}' is not canonical"

    def test_korean_mappings(self):
        """한글 매핑 확인."""
        from p5_issue_sync import PRIORITY_MAPPING
        assert PRIORITY_MAPPING["긴급"] == "critical"
        assert PRIORITY_MAPPING["높음"] == "high"
        assert PRIORITY_MAPPING["중간"] == "medium"
        assert PRIORITY_MAPPING["낮음"] == "low"


class TestZoneNormalization:
    """Zone 정규화 테스트."""

    def test_zone_normalization_config_exists(self):
        """p5-sync-config.yaml에 zone_normalization 섹션 존재."""
        from p5_config import CONFIG_DIR
        from p5_utils import load_yaml
        config = load_yaml(CONFIG_DIR / "p5-sync-config.yaml")
        assert "zone_normalization" in config, "zone_normalization 섹션 없음"

    def test_five_zones_defined(self):
        """5개 zone 정의 확인."""
        from p5_config import CONFIG_DIR
        from p5_utils import load_yaml
        config = load_yaml(CONFIG_DIR / "p5-sync-config.yaml")
        zones = config.get("zone_normalization", {})
        expected = {"zone_a", "zone_b", "zone_c", "cross_zone", "na"}
        assert set(zones.keys()) == expected


class TestOwnerDueEnforcement:
    """Owner/due_date 강제 규칙 테스트."""

    def test_hard_gate_flag_exists(self):
        """hard_gate_issues flag 존재 확인."""
        from scripts.telegram.config import FEATURE_FLAGS
        assert "hard_gate_issues" in FEATURE_FLAGS

    def test_validate_completeness_warns_on_critical(self):
        """critical 이슈에 owner 누락 시 경고."""
        from p5_issue_sync import _validate_issue_completeness
        from dataclasses import dataclass

        @dataclass
        class MockIssue:
            issue_id: str = "SEN-TEST"
            priority: str = "critical"
            owner: str = ""
            due_date: str = ""

        warnings, _ = _validate_issue_completeness(MockIssue())
        assert len(warnings) > 0, "critical + owner 누락인데 경고 없음"
```

2. `tests/test_dashboard_feed.py`:

```python
"""Dashboard Feed 검증 테스트."""
import pytest
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))


class TestDashboardFeedSchema:
    """Dashboard feed JSON 스키마 검증."""

    def test_feed_file_is_valid_json(self):
        """dashboard-feed.json이 유효한 JSON."""
        from p5_config import OVERVIEW_DIR
        feed_path = OVERVIEW_DIR / "dashboard-feed.json"
        if not feed_path.exists():
            pytest.skip("dashboard-feed.json 미생성")
        data = json.loads(feed_path.read_text(encoding="utf-8"))
        assert isinstance(data, dict)

    def test_feed_has_required_keys(self):
        """필수 키 존재 확인."""
        from p5_config import OVERVIEW_DIR
        feed_path = OVERVIEW_DIR / "dashboard-feed.json"
        if not feed_path.exists():
            pytest.skip("dashboard-feed.json 미생성")
        data = json.loads(feed_path.read_text(encoding="utf-8"))
        required = {"$schema", "generated_at", "kpi", "zone_progress", "risk_items"}
        assert required.issubset(set(data.keys()))

    def test_kpi_contains_core_metrics(self):
        """5개 핵심 KPI 포함."""
        from p5_config import OVERVIEW_DIR
        feed_path = OVERVIEW_DIR / "dashboard-feed.json"
        if not feed_path.exists():
            pytest.skip("dashboard-feed.json 미생성")
        data = json.loads(feed_path.read_text(encoding="utf-8"))
        kpi = data.get("kpi", {})
        expected_kpis = {"snr", "triage_accuracy", "decision_velocity",
                         "queue_health", "data_completeness"}
        assert expected_kpis.issubset(set(kpi.keys())), \
            f"누락 KPI: {expected_kpis - set(kpi.keys())}"
```

**검증**:
```bash
pytest tests/test_data_contract.py tests/test_dashboard_feed.py -v
```

**진행 보고**: "Step 7 완료: test_data_contract.py (N개 테스트) + test_dashboard_feed.py (N개 테스트) 생성"

**실패 시**: 테스트 파일 생성만 완료. import 오류는 sys.path 보정 후 재시도. Step 8로 진행.

---

## Step 8: 중복 함수 정리 (P1-4)

**목표**: `p5_issue_sync.py`의 `_load_config()` (L1696) 제거, `load_config()` (L1263)으로 통합.

**작업**:

1. `_load_config()` 호출부 검색:
   ```bash
   grep -n "_load_config" scripts/p5_issue_sync.py
   ```

2. 모든 `_load_config()` 호출을 `load_config()`로 교체.

3. `_load_config()` 함수 정의 (L1696-1698) 삭제.

**검증**:
```bash
grep "def _load_config" scripts/p5_issue_sync.py
# 기대: 0건

python scripts/p5_issue_sync.py sync
python scripts/p5_issue_sync.py context
# 기대: 둘 다 정상 실행
```

**진행 보고**: "Step 8 완료: _load_config() 제거, load_config()로 통합. 호출부 N건 교체"

**실패 시**: 호출 그래프 확인. 외부에서 _load_config 참조 시 보류. Step 9로 진행.

---

## Step 9: 최종 검증

**목표**: 전체 변경 사항 통합 검증.

**작업**:

```bash
# 1. 테스트 전체 실행
pytest tests/ -v

# 2. Issue sync 상태 확인
python scripts/p5_issue_sync.py status

# 3. 메트릭 생성 확인
python scripts/p5_metrics.py generate --stdout

# 4. Priority 정규화 확인
grep -rc "priority: normal" ResearchVault/P5-Project/01-Issues/
# 기대: 0

# 5. 하드코딩 경로 확인
grep -rn 'r"D:' scripts/ --include="*.py" | grep -v "p5_config.py"
# 기대: 0건

# 6. 중복 함수 확인
grep -c "def _load_config" scripts/p5_issue_sync.py
# 기대: 0

# 7. Dashboard feed 확인
python -c "import json; d=json.load(open('ResearchVault/P5-Project/00-Overview/dashboard-feed.json','r',encoding='utf-8')); print(f'KPIs: {len(d.get(\"kpi\",{}))}건, Zones: {len(d.get(\"zone_progress\",{}))}건')"
# 기대: KPIs: 5건, Zones: 5건
```

**진행 보고**: 각 검증 결과를 개별 보고.

**전체 완료 기준**:
- [ ] pytest 전체 pass
- [ ] priority: normal → 0건
- [ ] 하드코딩 경로 → 0건
- [ ] _load_config() → 0건
- [ ] dashboard-feed.json → valid JSON with 5 KPIs
- [ ] p5_daily.bat:64 → --auto-apply-above 5

---

## Execution Notes

- 각 Step은 **작업 시작 시 즉시 진행 보고**, **완료 시 결과 보고** 필수.
- Step 간 의존성: Step 1 → Step 2 (독립 가능), Step 4 (의존), Step 5 (의존).
- **시간 제한**: 각 Step 최대 30분. 초과 시 다음 Step으로 이동.
- **우선순위**: Step 1 > 2 > 3 > 7 > 6 > 4 > 5 > 8 > 9
