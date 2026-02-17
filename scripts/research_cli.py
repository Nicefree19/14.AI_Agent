"""
연구 자동화 CLI 도구
Obsidian ResearchVault + NotebookLM 통합 관리
"""

import sys
import argparse
import logging
from pathlib import Path
from datetime import datetime

import yaml

# ─── 설정 ─────────────────────────────────────────────────
SCRIPTS_DIR = Path(__file__).resolve().parent
VAULT_PATH = SCRIPTS_DIR.parent / "ResearchVault"
LOG_FILE = SCRIPTS_DIR / "research_cli.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("research_cli")


# ─── 공통 유틸 ────────────────────────────────────────────
def search_vault(query: str) -> list[dict]:
    """Vault에서 키워드 검색, 매칭 노트 반환"""
    results = []
    keywords = [kw.strip().lower() for kw in query.split() if len(kw.strip()) > 1]
    skip_dirs = {
        "_config",
        "Templates",
        "Rules",
        "Workflows",
        "Skills",
        ".obsidian",
        ".trash",
    }

    for md_file in VAULT_PATH.rglob("*.md"):
        rel = md_file.relative_to(VAULT_PATH)
        if any(part in skip_dirs for part in rel.parts):
            continue
        try:
            content = md_file.read_text(encoding="utf-8")
            content_lower = content.lower()
            stem_lower = md_file.stem.lower()

            score = sum(1 for kw in keywords if kw in content_lower or kw in stem_lower)
            if score > 0:
                # frontmatter 추출
                title = md_file.stem
                tags = []
                if content.startswith("---"):
                    parts = content.split("---", 2)
                    if len(parts) >= 3:
                        try:
                            fm = yaml.safe_load(parts[1])
                            if fm:
                                title = fm.get("title", title)
                                tags = fm.get("tags", [])
                        except yaml.YAMLError:
                            pass

                results.append(
                    {
                        "path": str(rel),
                        "title": title,
                        "tags": tags,
                        "score": score,
                    }
                )
        except Exception:
            continue

    results.sort(key=lambda x: x["score"], reverse=True)
    return results


# ─── deep-research 서브커맨드 ─────────────────────────────
def cmd_deep_research(args):
    """심층 연구 수행: Vault 검색 + NotebookLM 인사이트 + 종합 노트 생성"""
    topic = args.topic
    log.info(f"=== 심층 연구 시작: '{topic}' ===")

    # Step 1: Vault 검색
    print(f"\n[1/4] ResearchVault에서 '{topic}' 관련 노트 검색...")
    existing = search_vault(topic)
    print(f"  -> {len(existing)}개 관련 노트 발견")
    for note in existing[:5]:
        print(f"     - [{note['score']}] {note['path']}: {note['title']}")

    # Step 2: NotebookLM 인사이트 추출
    print(f"\n[2/4] NotebookLM에서 인사이트 추출...")
    nlm_insights = []
    try:
        from nlm_to_obsidian import create_client

        client = create_client()
        if client:
            notebooks = client.list_notebooks()
            # 주제와 관련된 노트북 필터링
            topic_lower = topic.lower()
            relevant = [
                nb
                for nb in notebooks
                if nb.title and topic_lower in nb.title.lower() and nb.source_count > 0
            ]

            if relevant:
                for nb in relevant[:3]:
                    try:
                        result = client._call_rpc(
                            client.RPC_GET_SUMMARY,
                            [nb.id],
                            path=f"/notebook/{nb.id}",
                            timeout=30.0,
                        )
                        if result and isinstance(result, list) and result[0]:
                            raw = result[0]
                            text = (
                                raw
                                if isinstance(raw, str)
                                else (
                                    str(raw[0]) if isinstance(raw, list) and raw else ""
                                )
                            )
                            nlm_insights.append(
                                {
                                    "notebook": nb.title,
                                    "summary": text,
                                }
                            )
                            print(f"  -> '{nb.title}' 인사이트 추출 완료")
                    except Exception as e:
                        log.warning(f"  '{nb.title}' 추출 실패: {e}")
            else:
                print(f"  -> '{topic}' 관련 노트북 없음")
        else:
            print("  -> NotebookLM 인증 필요 (notebooklm-mcp-auth 실행)")
    except ImportError:
        print("  -> nlm_to_obsidian 모듈 로드 실패, NotebookLM 건너뜀")
    except Exception as e:
        print(f"  -> NotebookLM 오류: {e}")

    print(f"  -> {len(nlm_insights)}개 인사이트 추출")

    # Step 3: 종합 노트 생성
    print(f"\n[3/4] 연구 노트 생성...")
    today = datetime.now().strftime("%Y-%m-%d")
    today_compact = datetime.now().strftime("%Y%m%d")

    import re

    slug = re.sub(r"[^\w\s가-힣-]", "", topic)
    slug = re.sub(r"\s+", "-", slug.strip())[:60]

    related_links = [f"[[{n['title']}]]" for n in existing[:5]]

    frontmatter = {
        "title": f"{topic} 심층 연구",
        "tags": ["type/research", "status/draft"],
        "date": today,
        "source": "deep-research CLI",
        "related": related_links,
    }

    lines = ["---"]
    lines.append(
        yaml.dump(frontmatter, allow_unicode=True, default_flow_style=False).rstrip()
    )
    lines.append("---")
    lines.append("")
    lines.append(f"# {topic} 심층 연구")
    lines.append("")

    # 기존 노트 요약
    lines.append("## 기존 지식")
    if existing:
        for n in existing[:10]:
            lines.append(f"- [[{n['title']}]] ({n['path']})")
    else:
        lines.append("- _관련 기존 노트 없음_")
    lines.append("")

    # NotebookLM 인사이트
    lines.append("## NotebookLM 인사이트")
    if nlm_insights:
        for ins in nlm_insights:
            lines.append(f"### {ins['notebook']}")
            lines.append(ins["summary"][:2000])
            lines.append("")
    else:
        lines.append("- _NotebookLM 인사이트 없음_")
    lines.append("")

    # 종합 섹션 (사용자가 채울 부분)
    lines.append("## 종합 분석")
    lines.append("<!-- 위 자료를 바탕으로 종합 분석을 작성하세요 -->")
    lines.append("")
    lines.append("## 핵심 질문")
    lines.append("- [ ] ")
    lines.append("")
    lines.append("## 다음 단계")
    lines.append("- [ ] ")
    lines.append("")

    content = "\n".join(lines)

    # 저장
    save_dir = VAULT_PATH / "02-Notes"
    save_dir.mkdir(parents=True, exist_ok=True)
    filepath = save_dir / f"{today_compact}-{slug}-research.md"
    filepath.write_text(content, encoding="utf-8")
    print(f"  -> 저장 완료: {filepath.relative_to(VAULT_PATH)}")

    # Step 4: 결과
    print(f"\n[4/4] 심층 연구 완료!")
    print(f"  기존 노트: {len(existing)}개")
    print(f"  NLM 인사이트: {len(nlm_insights)}개")
    print(f"  결과 파일: {filepath}")

    return filepath


# ─── sync 서브커맨드 ──────────────────────────────────────
def cmd_sync(args):
    """양방향 동기화 실행"""
    direction = args.direction

    if direction in ("all", "to-nlm"):
        print("[Obsidian -> NotebookLM] watchdog 동기화 상태 확인...")
        sync_log = SCRIPTS_DIR / "sync.log"
        if sync_log.exists():
            lines = sync_log.read_text(encoding="utf-8").strip().split("\n")
            recent = lines[-10:] if len(lines) > 10 else lines
            print("  최근 로그:")
            for line in recent:
                print(f"    {line}")
        else:
            print("  동기화 로그 없음. start_sync.bat를 실행하세요.")

    if direction in ("all", "from-nlm"):
        print("\n[NotebookLM -> Obsidian] 역방향 동기화 실행...")
        try:
            from nlm_to_obsidian import sync_all

            results = sync_all(limit=args.limit)
            print(f"  -> {len(results)}개 파일 동기화 완료")
        except ImportError:
            print("  -> nlm_to_obsidian 모듈 로드 실패")
        except Exception as e:
            print(f"  -> 오류: {e}")


# ─── list-notebooks 서브커맨드 ────────────────────────────
def cmd_list_notebooks(args):
    """NotebookLM 노트북 목록 조회"""
    print("NotebookLM 노트북 목록 조회...")

    try:
        from nlm_to_obsidian import create_client

        client = create_client()
        if not client:
            return

        notebooks = client.list_notebooks()
        active = [nb for nb in notebooks if nb.title]
        active.sort(key=lambda x: x.source_count, reverse=True)

        print(f"\n총 {len(active)}개 노트북:\n")
        print(f"{'#':>3}  {'Sources':>7}  {'Title'}")
        print("-" * 60)
        for i, nb in enumerate(active, 1):
            print(f"{i:3}  {nb.source_count:7}  {nb.title[:50]}")

    except ImportError:
        print("nlm_to_obsidian 모듈 로드 실패")
    except Exception as e:
        print(f"오류: {e}")


# ─── search 서브커맨드 ────────────────────────────────────
def cmd_search(args):
    """Vault 내 노트 검색"""
    query = args.query
    print(f"'{query}' 검색 중...\n")

    results = search_vault(query)
    if results:
        print(f"{len(results)}개 결과:\n")
        for r in results[:20]:
            tags = ", ".join(r["tags"]) if r["tags"] else ""
            print(f"  [{r['score']}] {r['path']}")
            print(f"      제목: {r['title']}")
            if tags:
                print(f"      태그: {tags}")
            print()
    else:
        print("결과 없음.")


# ─── fetch-mail 서브커맨드 ────────────────────────────────
def cmd_fetch_mail(args):
    """이메일 가져오기"""
    print("이메일 가져오기 시작...")
    try:
        from fetch_emails import fetch_emails

        fetch_emails(limit=args.limit)
        print("완료.")
    except ImportError:
        print("fetch_emails 모듈 로드 실패")
    except Exception as e:
        print(f"오류: {e}")


# ─── messages 서브커맨드 ─────────────────────────────────────
def cmd_messages(args):
    """통합 메시지 수집 명령어"""
    action = args.action

    if action == "fetch":
        _messages_fetch(args)
    elif action == "status":
        _messages_status(args)
    elif action == "daemon":
        _messages_daemon(args)
    elif action == "list-adapters":
        _messages_list_adapters(args)


def _messages_fetch(args):
    """메시지 수집 실행"""
    source = args.source
    limit = args.limit

    print(f"메시지 수집 시작 (source={source}, limit={limit})...")

    try:
        from message_daemon import MessageCollector, load_config

        config = load_config()
        collector = MessageCollector(config, log)

        if source == "all":
            results = collector.collect_all(limit=limit)
            print(f"\n수집 결과:")
            total = 0
            for adapter, count in results.items():
                print(f"  {adapter}: {count}개 새 메시지")
                total += count
            print(f"\n총 {total}개 메시지 수집 완료")
        else:
            count = collector.collect_from_adapter(source, limit=limit)
            print(f"\n{source}에서 {count}개 메시지 수집 완료")

    except ImportError as e:
        print(f"모듈 로드 실패: {e}")
    except Exception as e:
        print(f"오류: {e}")


def _messages_status(args):
    """메시지 데몬 상태 확인"""
    print("=== 메시지 수집 상태 ===\n")

    try:
        from adapters.registry import list_adapters, get_adapter
        from message_daemon import load_config

        config = load_config()

        # 등록된 어댑터 목록
        adapters = list_adapters()
        print(f"등록된 어댑터: {', '.join(adapters)}\n")

        # 각 어댑터 상태
        adapter_configs = config.get("adapters", {})
        for name in adapters:
            ac = adapter_configs.get(name, {})
            enabled = ac.get("enabled", False)
            status_icon = "[O]" if enabled else "[X]"

            adapter = get_adapter(name)
            if adapter:
                poll = adapter.poll_interval
                watch = "Yes" if adapter.supports_watch else "No"
                print(f"  {status_icon} {name}")
                print(f"      Enabled: {enabled}")
                print(f"      Poll interval: {poll} min")
                print(f"      Watch support: {watch}")
            else:
                print(f"  [?] {name} (load failed)")
            print()

        # 데몬 로그 상태
        daemon_log = SCRIPTS_DIR / "message_daemon.log"
        if daemon_log.exists():
            import os
            mtime = datetime.fromtimestamp(os.path.getmtime(daemon_log))
            print(f"데몬 로그: {mtime.strftime('%Y-%m-%d %H:%M:%S')}")

            # 최근 로그 출력
            lines = daemon_log.read_text(encoding="utf-8").strip().split("\n")
            recent = lines[-5:] if len(lines) > 5 else lines
            print("\n최근 로그:")
            for line in recent:
                print(f"  {line}")
        else:
            print("데몬 로그: 없음")

    except ImportError as e:
        print(f"모듈 로드 실패: {e}")
    except Exception as e:
        print(f"오류: {e}")


def _messages_daemon(args):
    """메시지 데몬 제어"""
    daemon_action = args.daemon_action

    if daemon_action == "start":
        print("메시지 데몬 시작...")
        print("별도 터미널에서 다음 명령어를 실행하세요:")
        print(f"  python {SCRIPTS_DIR / 'message_daemon.py'} start")
    elif daemon_action == "stop":
        print("데몬을 중지하려면 실행 중인 터미널에서 Ctrl+C를 누르세요.")
    elif daemon_action == "status":
        _messages_status(args)


def _messages_list_adapters(args):
    """사용 가능한 어댑터 목록"""
    print("=== 사용 가능한 메시지 어댑터 ===\n")

    try:
        from adapters.registry import list_adapters, get_adapter

        adapters = list_adapters()

        for name in adapters:
            adapter = get_adapter(name)
            if adapter:
                print(f"[*] {name}")
                print(f"    유형: {adapter.source_type}")
                print(f"    폴링 주기: {adapter.poll_interval}분")
                print(f"    실시간 감시: {'지원' if adapter.supports_watch else '미지원'}")
                print()

    except ImportError as e:
        print(f"모듈 로드 실패: {e}")


# ─── import-chat 서브커맨드 ──────────────────────────────
def cmd_import_chat(args):
    """채팅 로그 가져오기"""
    path = args.file
    print(f"채팅 로그 가져오기: {path}")
    try:
        from import_messages import parse_kakao_pc, save_as_markdown
        from pathlib import Path

        if not Path(path).exists():
            print("파일을 찾을 수 없습니다.")
            return

        msgs = parse_kakao_pc(path)
        save_as_markdown(msgs, Path(path).stem)
        print("완료.")
    except ImportError:
        print("import_messages 모듈 로드 실패")
    except Exception as e:
        print(f"오류: {e}")


# ─── status 서브커맨드 ────────────────────────────────────
def cmd_status(args):
    """ResearchVault 상태 요약"""
    print("=== ResearchVault 상태 ===\n")

    folders = {
        "00-Inbox": "미분류",
        "01-Sources": "출처",
        "02-Notes": "노트",
        "03-Projects": "프로젝트",
        "04-Archive": "보관",
    }

    total = 0
    for folder, label in folders.items():
        path = VAULT_PATH / folder
        if path.exists():
            count = len(list(path.rglob("*.md")))
            total += count
            print(f"  {label:10} ({folder}): {count:4}개")

    print(f"\n  {'전체':10}: {total:4}개 노트")

    # 동기화 상태
    sync_log = SCRIPTS_DIR / "sync.log"
    if sync_log.exists():
        import os

        mtime = datetime.fromtimestamp(os.path.getmtime(sync_log))
        print(f"\n  최근 동기화: {mtime.strftime('%Y-%m-%d %H:%M:%S')}")
    else:
        print("\n  동기화 로그: 없음")


# ─── 메인 ────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="연구 자동화 CLI - Obsidian + NotebookLM",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
사용 예시:
  python research_cli.py deep-research "AI 에이전트"
  python research_cli.py sync
  python research_cli.py sync --direction from-nlm
  python research_cli.py list-notebooks
  python research_cli.py search "transformer"
  python research_cli.py status
  python research_cli.py messages fetch --source all
  python research_cli.py messages status
        """,
    )

    sub = parser.add_subparsers(dest="command", help="명령어")

    # deep-research
    p_dr = sub.add_parser("deep-research", help="심층 연구 수행")
    p_dr.add_argument("topic", help="연구 주제")
    p_dr.set_defaults(func=cmd_deep_research)

    # sync
    p_sync = sub.add_parser("sync", help="양방향 동기화")
    p_sync.add_argument(
        "--direction",
        choices=["all", "to-nlm", "from-nlm"],
        default="all",
        help="동기화 방향",
    )
    p_sync.add_argument("--limit", type=int, default=10, help="최대 노트북 수")
    p_sync.set_defaults(func=cmd_sync)

    # list-notebooks
    p_list = sub.add_parser("list-notebooks", help="NotebookLM 노트북 목록")
    p_list.set_defaults(func=cmd_list_notebooks)

    # search
    p_search = sub.add_parser("search", help="Vault 내 검색")
    p_search.add_argument("query", help="검색어")
    p_search.set_defaults(func=cmd_search)

    # status
    p_status = sub.add_parser("status", help="ResearchVault 상태")
    p_status.set_defaults(func=cmd_status)

    # fetch-mail
    p_mail = sub.add_parser("fetch-mail", help="이메일 가져오기")
    p_mail.add_argument("--limit", type=int, default=5, help="가져올 최대 이메일 수")
    p_mail.set_defaults(func=cmd_fetch_mail)

    # import-chat
    p_chat = sub.add_parser("import-chat", help="채팅 로그 가져오기")
    p_chat.add_argument("file", help="채팅 로그 파일 경로 (txt)")
    p_chat.set_defaults(func=cmd_import_chat)

    # messages (통합 메시지 명령어)
    p_msg = sub.add_parser(
        "messages",
        help="통합 메시지 수집",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
사용 예시:
  python research_cli.py messages fetch --source all
  python research_cli.py messages fetch --source outlook --limit 20
  python research_cli.py messages status
  python research_cli.py messages daemon start
  python research_cli.py messages list-adapters
        """,
    )
    msg_sub = p_msg.add_subparsers(dest="action", help="messages 서브명령")

    # messages fetch
    p_msg_fetch = msg_sub.add_parser("fetch", help="메시지 수집")
    p_msg_fetch.add_argument(
        "--source",
        default="all",
        help="소스 어댑터 (all, imap, outlook, kakao)",
    )
    p_msg_fetch.add_argument("--limit", type=int, default=10, help="최대 메시지 수")

    # messages status
    p_msg_status = msg_sub.add_parser("status", help="메시지 수집 상태")

    # messages daemon
    p_msg_daemon = msg_sub.add_parser("daemon", help="메시지 데몬 제어")
    p_msg_daemon.add_argument(
        "daemon_action",
        choices=["start", "stop", "status"],
        help="데몬 작업",
    )

    # messages list-adapters
    p_msg_list = msg_sub.add_parser("list-adapters", help="어댑터 목록")

    p_msg.set_defaults(func=cmd_messages)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return

    args.func(args)


if __name__ == "__main__":
    main()
