"""
P5 Vault 정기 백업 스크립트
01-Issues 폴더를 타임스탬프 백업하고 오래된 백업을 정리한다.

Usage:
    python p5_vault_backup.py                    # 기본 백업 (5개 유지)
    python p5_vault_backup.py --keep 3           # 최근 3개만 유지
    python p5_vault_backup.py --target 01-Issues # 백업 대상 지정
    python p5_vault_backup.py --list             # 기존 백업 목록 표시
"""

import sys
import io
import shutil
import argparse
import logging
from pathlib import Path
from datetime import datetime

# Windows cp949 인코딩 문제 방지
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# ─── Configuration ──────────────────────────────────────────
SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
VAULT_PATH = PROJECT_ROOT / "ResearchVault" / "P5-Project"
LOG_FILE = SCRIPT_DIR / "p5_vault_backup.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("p5_vault_backup")


def get_backup_dirs(target_name: str) -> list:
    """기존 백업 디렉토리 목록 반환 (오래된 순)."""
    pattern = f"{target_name}_backup_*"
    backups = sorted(
        [d for d in VAULT_PATH.glob(pattern) if d.is_dir()],
        key=lambda d: d.name,
    )
    return backups


def create_backup(target_name: str = "01-Issues") -> Path | None:
    """대상 폴더를 타임스탬프 백업."""
    source = VAULT_PATH / target_name
    if not source.exists():
        log.error(f"백업 대상 없음: {source}")
        return None

    timestamp = datetime.now().strftime("%Y%m%d")
    backup_name = f"{target_name}_backup_{timestamp}"
    dest = VAULT_PATH / backup_name

    # 동일 날짜 백업이 이미 있으면 스킵
    if dest.exists():
        log.info(f"오늘 백업 이미 존재: {backup_name}")
        return dest

    log.info(f"백업 시작: {source.name} → {backup_name}")

    try:
        # 파일 수 카운트
        file_count = sum(1 for _ in source.rglob("*") if _.is_file())
        log.info(f"  대상 파일: {file_count}개")

        shutil.copytree(source, dest)

        # 백업 검증
        backup_count = sum(1 for _ in dest.rglob("*") if _.is_file())
        log.info(f"  백업 완료: {backup_count}개 파일 복사됨")

        if backup_count != file_count:
            log.warning(f"  ⚠️ 파일 수 불일치: 원본 {file_count} ≠ 백업 {backup_count}")

        return dest

    except Exception as e:
        log.error(f"백업 실패: {e}")
        # 실패한 부분 백업 정리
        if dest.exists():
            try:
                shutil.rmtree(dest)
            except Exception:
                pass
        return None


def cleanup_old_backups(target_name: str, keep: int = 5) -> int:
    """오래된 백업 제거, 최신 N개만 유지."""
    backups = get_backup_dirs(target_name)

    if len(backups) <= keep:
        log.info(f"정리 불필요: {len(backups)}개 백업 (유지 {keep}개)")
        return 0

    to_remove = backups[: len(backups) - keep]
    removed = 0

    for backup_dir in to_remove:
        try:
            shutil.rmtree(backup_dir)
            log.info(f"  삭제: {backup_dir.name}")
            removed += 1
        except Exception as e:
            log.error(f"  삭제 실패 ({backup_dir.name}): {e}")

    log.info(f"정리 완료: {removed}개 삭제, {len(backups) - removed}개 유지")
    return removed


def list_backups(target_name: str):
    """기존 백업 목록 표시."""
    backups = get_backup_dirs(target_name)

    if not backups:
        log.info(f"'{target_name}' 백업 없음")
        return

    log.info(f"'{target_name}' 백업 목록 ({len(backups)}개):")
    for i, d in enumerate(backups, 1):
        # 파일 수와 대략적 크기 계산
        file_count = sum(1 for _ in d.rglob("*") if _.is_file())
        size_mb = sum(f.stat().st_size for f in d.rglob("*") if f.is_file()) / (1024 * 1024)
        log.info(f"  [{i}] {d.name}  ({file_count}파일, {size_mb:.1f}MB)")


def main():
    parser = argparse.ArgumentParser(description="P5 Vault 정기 백업")
    parser.add_argument(
        "--target", default="01-Issues",
        help="백업 대상 폴더명 (기본: 01-Issues)"
    )
    parser.add_argument(
        "--keep", type=int, default=5,
        help="유지할 백업 수 (기본: 5)"
    )
    parser.add_argument(
        "--list", action="store_true",
        help="기존 백업 목록 표시"
    )

    args = parser.parse_args()

    log.info("=" * 50)
    log.info("P5 Vault 백업")
    log.info("=" * 50)

    if args.list:
        list_backups(args.target)
        return

    # 백업 실행
    result = create_backup(args.target)
    if result:
        log.info(f"✅ 백업 성공: {result.name}")
    else:
        log.error("❌ 백업 실패")
        return

    # 오래된 백업 정리
    cleanup_old_backups(args.target, keep=args.keep)

    log.info("=" * 50)
    log.info("백업 완료")
    log.info("=" * 50)


if __name__ == "__main__":
    main()
