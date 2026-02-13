"""
Message Daemon
Unified message collection daemon integrating APScheduler with Watchdog patterns.
Polls IMAP/Outlook on schedule and monitors filesystem for local changes.
"""

import sys
import time
import logging
import threading
import signal
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Callable

import yaml
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# Add scripts directory to path for imports
SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

from adapters import get_adapter, get_all_adapters, list_adapters
from adapters.registry import _auto_register

# ─── Configuration ──────────────────────────────────────────
CONFIG_PATH = Path(r"D:\00.Work_AI_Tool\14.AI_Agent\ResearchVault\_config\message-config.yaml")
DEFAULT_OUTPUT_DIR = Path(r"D:\00.Work_AI_Tool\14.AI_Agent\ResearchVault\00-Inbox\Messages")
LOG_FILE = SCRIPT_DIR / "message_daemon.log"


def load_config() -> dict:
    """Load configuration from YAML file."""
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    return {
        "storage": {
            "base_path": str(DEFAULT_OUTPUT_DIR),
        },
        "adapters": {
            "imap": {"enabled": False, "poll_interval_minutes": 10},
            "outlook": {"enabled": True, "poll_interval_minutes": 5},
            "kakao": {"enabled": True},  # Manual import only
        },
        "processing": {
            "auto_tag": True,
            "dedup_enabled": True,
        },
        "daemon": {
            "debounce_seconds": 2,
            "max_retries": 3,
        }
    }


# ─── Logging Setup ──────────────────────────────────────────
def setup_logging(log_file: Path = LOG_FILE, level: int = logging.INFO):
    """Configure logging for the daemon."""
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )
    return logging.getLogger("message_daemon")


# ─── Debouncer (from watchdog_sync.py) ──────────────────────
class Debouncer:
    """File-based debouncing: wait N seconds after last event before callback."""

    def __init__(self, delay: float, callback: Callable[[str], None]):
        self.delay = delay
        self.callback = callback
        self._timers: dict[str, threading.Timer] = {}
        self._lock = threading.Lock()

    def trigger(self, filepath: str):
        with self._lock:
            if filepath in self._timers:
                self._timers[filepath].cancel()
            timer = threading.Timer(self.delay, self._fire, args=[filepath])
            self._timers[filepath] = timer
            timer.start()

    def _fire(self, filepath: str):
        with self._lock:
            self._timers.pop(filepath, None)
        self.callback(filepath)

    def cancel_all(self):
        with self._lock:
            for timer in self._timers.values():
                timer.cancel()
            self._timers.clear()


# ─── Message Collector ──────────────────────────────────────
class MessageCollector:
    """Collects messages from configured adapters."""

    def __init__(self, config: dict, log: logging.Logger):
        self.config = config
        self.log = log
        self.output_dir = Path(config.get("storage", {}).get("base_path", str(DEFAULT_OUTPUT_DIR)))
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Separate directories by source
        self.email_dir = self.output_dir / "Emails"
        self.chat_dir = self.output_dir / "Chats"
        self.email_dir.mkdir(parents=True, exist_ok=True)
        self.chat_dir.mkdir(parents=True, exist_ok=True)

        self._seen_ids: set = set()  # For deduplication
        self._load_seen_ids()

    def _load_seen_ids(self):
        """Load previously seen message IDs from marker file."""
        marker_file = self.output_dir / ".seen_ids"
        if marker_file.exists():
            try:
                self._seen_ids = set(marker_file.read_text(encoding="utf-8").splitlines())
                self.log.debug(f"Loaded {len(self._seen_ids)} seen message IDs")
            except Exception:
                pass

    def _save_seen_ids(self):
        """Save seen message IDs to marker file."""
        marker_file = self.output_dir / ".seen_ids"
        try:
            # Keep only recent IDs (last 10000)
            recent = sorted(self._seen_ids)[-10000:]
            marker_file.write_text("\n".join(recent), encoding="utf-8")
        except Exception as e:
            self.log.warning(f"Failed to save seen IDs: {e}")

    def collect_from_adapter(self, adapter_name: str, limit: int = 10) -> int:
        """
        Collect messages from a specific adapter.

        Returns:
            Number of new messages saved
        """
        adapter_config = self.config.get("adapters", {}).get(adapter_name, {})

        if not adapter_config.get("enabled", False):
            self.log.debug(f"Adapter '{adapter_name}' is disabled")
            return 0

        adapter = get_adapter(adapter_name, adapter_config)
        if not adapter:
            self.log.warning(f"Adapter not available: {adapter_name}")
            return 0

        try:
            messages = adapter.fetch(limit=limit)
            self.log.info(f"[{adapter_name}] Fetched {len(messages)} messages")

            saved_count = 0
            for msg in messages:
                # Deduplication
                if msg.id in self._seen_ids:
                    continue

                # Determine output directory
                if msg.source_type == "email":
                    out_dir = self.email_dir
                else:
                    out_dir = self.chat_dir

                # Save message
                try:
                    filepath = adapter.save_message(msg, out_dir)
                    self._seen_ids.add(msg.id)
                    saved_count += 1
                    self.log.info(f"[{adapter_name}] Saved: {filepath.name}")
                except Exception as e:
                    self.log.error(f"[{adapter_name}] Failed to save message: {e}")

            if saved_count > 0:
                self._save_seen_ids()

            return saved_count

        except Exception as e:
            self.log.error(f"[{adapter_name}] Collection failed: {e}")
            return 0

    def collect_all(self, limit: int = 10) -> dict:
        """
        Collect from all enabled adapters.

        Returns:
            Dict of adapter_name -> count
        """
        results = {}
        adapter_configs = self.config.get("adapters", {})

        for adapter_name in list_adapters():
            if adapter_name not in adapter_configs:
                continue
            if not adapter_configs[adapter_name].get("enabled", False):
                continue

            # Skip manual-only adapters (like kakao)
            adapter = get_adapter(adapter_name)
            if adapter and adapter.poll_interval == 0:
                continue

            count = self.collect_from_adapter(adapter_name, limit=limit)
            results[adapter_name] = count

        return results


# ─── Import Handler (Watchdog) ──────────────────────────────
class ImportFileHandler(FileSystemEventHandler):
    """Watches for dropped import files (KakaoTalk exports, etc.)."""

    def __init__(self, daemon: "MessageDaemon"):
        self.daemon = daemon
        self.log = daemon.log
        self.debouncer = Debouncer(
            delay=daemon.config.get("daemon", {}).get("debounce_seconds", 2),
            callback=self._process_import,
        )
        self.import_dir = Path(daemon.config.get("storage", {}).get("base_path", str(DEFAULT_OUTPUT_DIR))) / "Import"
        self.import_dir.mkdir(parents=True, exist_ok=True)

    def _process_import(self, filepath: str):
        """Process a dropped import file."""
        path = Path(filepath)

        if not path.exists():
            return

        if path.suffix.lower() == ".txt":
            # Assume KakaoTalk export
            self.log.info(f"[import] Processing KakaoTalk file: {path.name}")

            try:
                from adapters.kakao_adapter import KakaoAdapter

                adapter = KakaoAdapter()
                adapter.set_import_file(path)
                messages = adapter.fetch()

                if messages:
                    chat_dir = self.daemon.collector.chat_dir
                    saved = adapter.save_as_daily_digest(messages, chat_dir)
                    self.log.info(f"[import] Saved {len(saved)} digest files from {path.name}")

                    # Move processed file
                    processed_dir = self.import_dir / "processed"
                    processed_dir.mkdir(exist_ok=True)
                    path.rename(processed_dir / path.name)

            except Exception as e:
                self.log.error(f"[import] Failed to process {path.name}: {e}")

    def on_created(self, event):
        if event.is_directory:
            return
        self.debouncer.trigger(event.src_path)

    def on_modified(self, event):
        if event.is_directory:
            return
        self.debouncer.trigger(event.src_path)


# ─── Message Daemon ─────────────────────────────────────────
class MessageDaemon:
    """
    Main daemon class integrating:
    - APScheduler for periodic email/message polling
    - Watchdog for file import monitoring
    """

    def __init__(self, config: Optional[dict] = None, log: Optional[logging.Logger] = None):
        self.config = config or load_config()
        self.log = log or setup_logging()

        self.collector = MessageCollector(self.config, self.log)
        self.scheduler = BackgroundScheduler()
        self.observer = Observer()

        self._running = False
        self._alerted_cache_file = Path(
            self.config.get("storage", {}).get("base_path", str(DEFAULT_OUTPUT_DIR))
        ) / ".critical_alerted.json"
        self._setup_signal_handlers()

    def _setup_signal_handlers(self):
        """Setup graceful shutdown on SIGINT/SIGTERM."""
        def handle_signal(signum, frame):
            self.log.info(f"Received signal {signum}, shutting down...")
            self.stop()

        signal.signal(signal.SIGINT, handle_signal)
        signal.signal(signal.SIGTERM, handle_signal)

    def _setup_scheduled_jobs(self):
        """Configure scheduled collection jobs."""
        adapter_configs = self.config.get("adapters", {})

        for adapter_name in list_adapters():
            if adapter_name not in adapter_configs:
                continue

            ac = adapter_configs[adapter_name]
            if not ac.get("enabled", False):
                continue

            adapter = get_adapter(adapter_name)
            if not adapter or adapter.poll_interval == 0:
                continue

            interval = ac.get("poll_interval_minutes", adapter.poll_interval)

            self.scheduler.add_job(
                func=self._collect_job,
                trigger=IntervalTrigger(minutes=interval),
                args=[adapter_name],
                id=f"collect_{adapter_name}",
                name=f"Collect from {adapter_name}",
                replace_existing=True,
            )
            self.log.info(f"Scheduled {adapter_name} collection every {interval} minutes")

        # ─── Phase 1 Ingest Gate: 격리 정리 + TTL 아카이브 ───
        self.scheduler.add_job(
            func=self._quarantine_cleanup_job,
            trigger=CronTrigger(hour=3, minute=0),
            id="quarantine_cleanup",
            name="Quarantine cleanup (>7d)",
            replace_existing=True,
        )
        self.log.info("Scheduled quarantine cleanup daily at 03:00")

        self.scheduler.add_job(
            func=self._reference_ttl_archive_job,
            trigger=CronTrigger(hour=3, minute=30),
            id="reference_ttl_archive",
            name="Reference TTL archive (>90d)",
            replace_existing=True,
        )
        self.log.info("Scheduled reference TTL archive daily at 03:30")

    def _collect_job(self, adapter_name: str):
        """Scheduled job for message collection + auto-triage."""
        try:
            # 신규 파일 식별을 위해 수집 전 스냅샷
            inbox_dir = Path(self.config.get("storage", {}).get("base_path", str(DEFAULT_OUTPUT_DIR))) / "Emails"
            before_files = set(inbox_dir.glob("*.md")) if inbox_dir.exists() else set()

            count = self.collector.collect_from_adapter(adapter_name)
            if count > 0:
                self.log.info(f"[scheduled] {adapter_name}: collected {count} new messages")
                # Auto-trigger P5 email triage if new emails collected
                if adapter_name in ("outlook", "imap"):
                    after_files = set(inbox_dir.glob("*.md")) if inbox_dir.exists() else set()
                    new_files = after_files - before_files
                    self._run_auto_triage(new_files=new_files)
        except Exception as e:
            self.log.error(f"[scheduled] {adapter_name} collection error: {e}")

    def _run_auto_triage(self, new_files=None):
        """Automatically run P5 email triage after new mail collection.

        Args:
            new_files: 신규 수집된 파일 set. None이면 전체 Inbox 처리 (수동 호출 호환).
        """
        try:
            from p5_email_triage import TriageRules, EmailParser, TriageEngine, NoiseFilter, apply_triage_results, IngestPolicy
            self.log.info("[auto-triage] P5 메일 트리아지 시작...")

            rules = TriageRules()
            parser = EmailParser(rules)
            engine = TriageEngine(rules)
            noise_filter = NoiseFilter(rules)
            policy = IngestPolicy()

            inbox_dir = Path(self.config.get("storage", {}).get("base_path", str(DEFAULT_OUTPUT_DIR))) / "Emails"
            if not inbox_dir.exists():
                return

            # new_files가 주어지면 신규 파일만, 아니면 전체 (수동 호출 호환)
            if new_files is not None:
                mail_files = [f for f in new_files if f.exists()]
                self.log.info(f"[auto-triage] 신규 수집 {len(mail_files)}건 대상")
            else:
                mail_files = list(inbox_dir.glob("*.md"))
            results = []
            noise_count = 0
            for mail_file in mail_files:
                email = parser.parse_email_file(mail_file)
                if not email:
                    continue

                # 노이즈 필터 적용 (cmd_process와 동일 경로)
                nf_result = noise_filter.filter(email)
                if nf_result.disposition != "pass":
                    noise_count += 1
                    continue

                result = engine.triage(email, policy=policy)
                result.conversation_id = nf_result.conversation_id
                results.append((email, result))

            if results:
                # automation level 확인
                auto_level = rules.config.get("automation_level", "L2")
                auto_threshold = rules.config.get("auto_apply_threshold", 8)
                l3_config = rules.config.get("l3_config", {})

                # ── L3 판정: 전체 자동 적용 (accuracy 조건 충족 시) ──
                if auto_level == "L3" and l3_config.get("enabled", False):
                    if self._check_l3_eligibility(l3_config):
                        max_apply = l3_config.get("safety_limits", {}).get("max_auto_apply_per_run", 20)
                        apply_results = results[:max_apply]
                        skip_results = results[max_apply:]

                        counts = apply_triage_results(apply_results, dry_run=False, policy=policy)
                        self._append_triage_audit(apply_results, "L3")

                        if skip_results:
                            apply_triage_results(skip_results, dry_run=True, policy=policy)
                        self.log.info(f"[auto-triage:L3] 자동적용 {len(apply_results)}건, 스킵 {len(skip_results)}건")
                    else:
                        # L3 자격 미달 → L2.5 fallback
                        self.log.warning("[auto-triage] L3 자격 미달 → L2.5 fallback")
                        auto_level = "L2.5"  # fallthrough to L2.5

                # ── L2.5: 고점수 자동 + 저점수 제안 ──
                if auto_level in ("L2.5",):
                    high_conf = [(e, r) for e, r in results if getattr(r, 'total_score', 0) >= auto_threshold]
                    low_conf = [(e, r) for e, r in results if getattr(r, 'total_score', 0) < auto_threshold]

                    counts = {"updated": 0, "flagged": 0, "skipped": 0, "quarantined": 0, "wip_overflow": 0}
                    if high_conf:
                        counts = apply_triage_results(high_conf, dry_run=False, policy=policy)
                        self._append_triage_audit(high_conf, "L2.5-auto")
                    if low_conf:
                        low_counts = apply_triage_results(low_conf, dry_run=True, policy=policy)
                        counts["flagged"] += low_counts.get("flagged", 0)
                    self.log.info(f"[auto-triage:L2.5] 자동 {len(high_conf)}건, 제안 {len(low_conf)}건")

                # ── L2 (기본): 전체 적용 ──
                elif auto_level == "L2":
                    counts = apply_triage_results(results, dry_run=False, policy=policy)

                # 분류 분포 로그
                cls_dist: dict = {}
                for _, r in results:
                    if r.classification:
                        cls_dist[r.classification] = cls_dist.get(r.classification, 0) + 1
                dist_str = " | ".join(f"{k}:{v}" for k, v in sorted(cls_dist.items())) if cls_dist else "N/A"

                self.log.info(
                    f"[auto-triage] 완료: "
                    f"업데이트 {counts.get('updated', 0)}건, "
                    f"리뷰 {counts.get('flagged', 0)}건, "
                    f"스킵 {counts.get('skipped', 0)}건, "
                    f"노이즈 필터 {noise_count}건, "
                    f"격리 {counts.get('quarantined', 0)}건, "
                    f"WIP초과 {counts.get('wip_overflow', 0)}건"
                )
                self.log.info(f"[auto-triage] 분류 분포: {dist_str}")

                # Critical 이슈 텔레그램 즉시 알림
                try:
                    critical_items = [
                        (email, res) for email, res in results
                        if getattr(res, 'priority', '') == 'critical'
                    ]
                    if critical_items:
                        self._send_critical_alert(critical_items)
                except Exception as alert_err:
                    self.log.debug(f"[auto-triage] Critical 알림 전송 실패 (무시): {alert_err}")
        except ImportError:
            self.log.warning("[auto-triage] p5_email_triage 모듈 로드 실패 - 수동 실행 필요")
        except Exception as e:
            self.log.error(f"[auto-triage] 트리아지 실패: {e}")

    def _check_l3_eligibility(self, l3_config: dict) -> bool:
        """L3 자동화 자격 확인 (정확도 + 연속 주 + 최소 샘플)."""
        try:
            from p5_metrics import calc_auto_apply_accuracy
            result = calc_auto_apply_accuracy()
            accuracy = result.get("accuracy", 0)
            samples = result.get("sample_count", 0)

            criteria = l3_config.get("transition_criteria", {})
            min_acc = criteria.get("min_accuracy", 90)
            min_samples = criteria.get("min_samples", 20)

            # 기본 조건: 정확도 + 샘플 수
            if accuracy < min_acc or samples < min_samples:
                self.log.info(f"[L3-check] 미달: accuracy={accuracy}% (필요 {min_acc}%), samples={samples} (필요 {min_samples})")
                return False

            # rollback 조건
            floor = l3_config.get("rollback_criteria", {}).get("accuracy_floor", 80)
            if accuracy < floor:
                self.log.warning(f"[L3-check] Rollback 조건 해당: accuracy={accuracy}% < floor={floor}%")
                return False

            return True
        except Exception as e:
            self.log.debug(f"[L3-check] 판정 실패 → 안전하게 거부: {e}")
            return False

    def _append_triage_audit(self, results: list, mode: str):
        """트리아지 audit log 기록 (JSONL, append-only)."""
        try:
            import json as _json
            audit_path = Path(self.config.get("storage", {}).get("base_path", str(DEFAULT_OUTPUT_DIR))) / "triage-audit-log.jsonl"
            audit_path.parent.mkdir(parents=True, exist_ok=True)

            timestamp = datetime.now().isoformat()
            with open(audit_path, "a", encoding="utf-8") as f:
                for email, res in results:
                    entry = {
                        "timestamp": timestamp,
                        "mode": mode,
                        "email_file": str(getattr(email, 'file_path', '')),
                        "subject": getattr(email, 'subject', '')[:80],
                        "score": getattr(res, 'total_score', 0),
                        "priority": getattr(res, 'priority', ''),
                        "matched_issue": getattr(res, 'matched_issue_id', ''),
                        "corrected": False,  # 수동 수정 시 True로 변경
                    }
                    f.write(_json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception as e:
            self.log.debug(f"[audit] 기록 실패: {e}")

    def _send_critical_alert(self, critical_items):
        """Critical 이슈 감지 시 텔레그램으로 즉시 알림 전송 (dedup 적용)."""
        try:
            import os, json
            chat_id = os.getenv("TELEGRAM_ALLOWED_USERS", "").split(",")[0].strip()
            if not chat_id:
                return

            # ── 중복 알림 방지: 이미 알림한 메일 ID 로드 ──
            alerted_ids = set()
            if self._alerted_cache_file.exists():
                try:
                    data = json.loads(self._alerted_cache_file.read_text(encoding="utf-8"))
                    alerted_ids = set(data.get("alerted", []))
                except Exception:
                    pass

            # 신규 critical만 필터링 (EmailData.file_path 기반 dedup)
            new_critical = []
            for email, res in critical_items:
                email_id = str(getattr(email, 'file_path', '')) or getattr(email, 'subject', '')
                if email_id and email_id not in alerted_ids:
                    new_critical.append((email, res))

            if not new_critical:
                self.log.debug("[critical-alert] 신규 critical 없음 (모두 이미 알림됨)")
                return

            from telegram.telegram_sender import send_message_sync

            msg = f"🚨 *Critical 이슈 {len(new_critical)}건 감지*\n\n"
            for email, res in new_critical[:5]:  # 최대 5건
                subject = getattr(email, 'subject', '제목 없음')[:60]
                sender = getattr(email, 'sender', '알 수 없음')
                score = getattr(res, 'total_score', 0)
                msg += f"• [{score}점] {subject}\n  ↳ {sender}\n"
            if len(new_critical) > 5:
                msg += f"\n... 외 {len(new_critical) - 5}건"
            msg += "\n\n즉시 확인이 필요합니다."

            send_message_sync(int(chat_id), msg)
            self.log.info(f"[critical-alert] 텔레그램 알림 전송: {len(new_critical)}건")

            # ── 알림 완료 ID 저장 ──
            for email, res in new_critical:
                email_id = str(getattr(email, 'file_path', '')) or getattr(email, 'subject', '')
                if email_id:
                    alerted_ids.add(email_id)
            try:
                self._alerted_cache_file.write_text(
                    json.dumps({"alerted": list(alerted_ids)}, ensure_ascii=False),
                    encoding="utf-8"
                )
            except Exception:
                pass
        except Exception as e:
            self.log.debug(f"[critical-alert] 텔레그램 알림 실패: {e}")

    def _quarantine_cleanup_job(self):
        """Quarantine 폴더에서 quarantine_days 초과 파일 삭제."""
        try:
            from p5_email_triage import IngestPolicy
            policy = IngestPolicy()
            q_dir = policy.quarantine_dir
            if not q_dir.exists():
                return
            max_days = policy.ttl.get("quarantine_days", 7)
            now = datetime.now()
            deleted = 0
            for f in q_dir.glob("*.md"):
                try:
                    mtime = datetime.fromtimestamp(f.stat().st_mtime)
                    age = (now - mtime).days
                    if age > max_days:
                        f.unlink()
                        deleted += 1
                except Exception:
                    pass
            if deleted > 0:
                self.log.info(f"[quarantine-cleanup] {deleted}건 삭제 (>{max_days}일)")
        except Exception as e:
            self.log.error(f"[quarantine-cleanup] 실패: {e}")

    def _reference_ttl_archive_job(self):
        """Reference 분류 이메일 중 TTL 초과 → Archive 이동."""
        try:
            from p5_email_triage import IngestPolicy
            import yaml as _yaml
            policy = IngestPolicy()
            ref_days = policy.ttl.get("reference_days", 90)
            archive_dir = policy.archive_dir
            archive_dir.mkdir(parents=True, exist_ok=True)

            inbox_dir = Path(self.config.get("storage", {}).get("base_path", str(DEFAULT_OUTPUT_DIR))) / "Emails"
            if not inbox_dir.exists():
                return

            now = datetime.now()
            archived = 0
            for f in inbox_dir.glob("*.md"):
                try:
                    content = f.read_text(encoding="utf-8")
                    if not content.startswith("---"):
                        continue
                    parts = content.split("---", 2)
                    if len(parts) < 3:
                        continue
                    fm = _yaml.safe_load(parts[1]) or {}
                    if fm.get("classification") != "Reference":
                        continue
                    mtime = datetime.fromtimestamp(f.stat().st_mtime)
                    age = (now - mtime).days
                    if age > ref_days:
                        dest = archive_dir / f.name
                        f.rename(dest)
                        archived += 1
                except Exception:
                    pass
            if archived > 0:
                self.log.info(f"[reference-ttl] {archived}건 아카이브 (>{ref_days}일)")
        except Exception as e:
            self.log.error(f"[reference-ttl] 실패: {e}")

    def _setup_file_watcher(self):
        """Configure Watchdog for import file monitoring."""
        handler = ImportFileHandler(self)
        self.observer.schedule(handler, str(handler.import_dir), recursive=False)
        self.log.info(f"Watching for import files in: {handler.import_dir}")

    def start(self):
        """Start the daemon."""
        if self._running:
            self.log.warning("Daemon is already running")
            return

        self.log.info("=" * 50)
        self.log.info("Message Daemon Starting")
        self.log.info("=" * 50)

        # Re-register adapters
        _auto_register()

        # Setup jobs
        self._setup_scheduled_jobs()
        self._setup_file_watcher()

        # Start components
        self.scheduler.start()
        self.observer.start()

        self._running = True
        self.log.info("Daemon started successfully")

        # Initial collection
        self.log.info("Running initial collection...")
        inbox_dir = Path(self.config.get("storage", {}).get("base_path", str(DEFAULT_OUTPUT_DIR))) / "Emails"
        before_files = set(inbox_dir.glob("*.md")) if inbox_dir.exists() else set()

        results = self.collector.collect_all()
        total_new = 0
        for adapter, count in results.items():
            self.log.info(f"  {adapter}: {count} messages")
            total_new += count

        # Auto-triage if new emails were collected
        if total_new > 0:
            after_files = set(inbox_dir.glob("*.md")) if inbox_dir.exists() else set()
            new_files = after_files - before_files
            self._run_auto_triage(new_files=new_files)

    def stop(self):
        """Stop the daemon gracefully."""
        if not self._running:
            return

        self.log.info("Stopping daemon...")

        self.scheduler.shutdown(wait=False)
        self.observer.stop()
        self.observer.join(timeout=5)

        self._running = False
        self.log.info("Daemon stopped")

    def run_forever(self):
        """Start and run until interrupted."""
        self.start()

        try:
            while self._running:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
        finally:
            self.stop()

    def status(self) -> dict:
        """Get daemon status."""
        jobs = []
        for job in self.scheduler.get_jobs():
            jobs.append({
                "id": job.id,
                "name": job.name,
                "next_run": str(job.next_run_time),
            })

        return {
            "running": self._running,
            "adapters": list_adapters(),
            "scheduled_jobs": jobs,
            "output_dir": str(self.collector.output_dir),
        }


# ─── CLI Interface ──────────────────────────────────────────
def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Message Collection Daemon",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python message_daemon.py start              # Start daemon
  python message_daemon.py collect --all      # One-time collection
  python message_daemon.py collect outlook    # Collect from Outlook only
  python message_daemon.py status             # Show status
        """,
    )

    sub = parser.add_subparsers(dest="command", help="Command")

    # start
    p_start = sub.add_parser("start", help="Start the daemon")
    p_start.add_argument("--debug", action="store_true", help="Enable debug logging")

    # collect
    p_collect = sub.add_parser("collect", help="One-time collection")
    p_collect.add_argument("source", nargs="?", default="all", help="Source adapter (or 'all')")
    p_collect.add_argument("--limit", type=int, default=10, help="Max messages to fetch")
    p_collect.add_argument("--triage", action="store_true", help="Auto-run P5 triage after collection")

    # status
    p_status = sub.add_parser("status", help="Show daemon status")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    config = load_config()
    log_level = logging.DEBUG if getattr(args, "debug", False) else logging.INFO
    log = setup_logging(level=log_level)

    if args.command == "start":
        daemon = MessageDaemon(config, log)
        daemon.run_forever()

    elif args.command == "collect":
        collector = MessageCollector(config, log)
        total_new = 0

        # 수집 전 스냅샷 (triage 플래그 시 before/after diff용)
        inbox_dir = Path(config.get("storage", {}).get("base_path", str(DEFAULT_OUTPUT_DIR))) / "Emails"
        before_files = set(inbox_dir.glob("*.md")) if inbox_dir.exists() else set()

        if args.source == "all":
            results = collector.collect_all(limit=args.limit)
            print(f"\nCollection results:")
            for adapter, count in results.items():
                print(f"  {adapter}: {count} new messages")
                total_new += count
        else:
            count = collector.collect_from_adapter(args.source, limit=args.limit)
            print(f"\nCollected {count} messages from {args.source}")
            total_new = count

        # Auto-triage if requested and new emails found
        if getattr(args, "triage", False) and total_new > 0:
            after_files = set(inbox_dir.glob("*.md")) if inbox_dir.exists() else set()
            new_files = after_files - before_files
            daemon = MessageDaemon(config, log)
            daemon._run_auto_triage(new_files=new_files)

    elif args.command == "status":
        daemon = MessageDaemon(config, log)
        status = daemon.status()

        print("\n=== Message Daemon Status ===")
        print(f"Running: {status['running']}")
        print(f"Output: {status['output_dir']}")
        print(f"\nRegistered adapters: {', '.join(status['adapters'])}")

        print(f"\nScheduled jobs:")
        for job in status["scheduled_jobs"]:
            print(f"  - {job['name']}: next run at {job['next_run']}")


if __name__ == "__main__":
    main()
