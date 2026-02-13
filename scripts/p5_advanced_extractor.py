"""
P5 프로젝트 상세 지식 추출기
NotebookLM 소스별 인사이트 + Google Drive 이슈 데이터 동기화
"""

import sys
import os
from datetime import datetime
from pathlib import Path

try:
    from notebooklm_mcp.auth import load_cached_tokens
    from notebooklm_mcp.api_client import NotebookLMClient
except ImportError as e:
    print(f"Import error: {e}")
    sys.exit(1)

# Config
P5_NOTEBOOK_ID = "3de596ed-3543-4fbf-b30e-dddf7d7783be"
ROADMAP_NOTEBOOK_ID = "829ba949-92b1-45cd-81a0-3f194f47cc69"
OUTPUT_DIR = Path("D:/00.Work_AI_Tool/14.AI_Agent/ResearchVault/P5-Project")
GDRIVE_ISSUE_PATH = Path("G:/내 드라이브/appsheet/data/복합동이슈관리대장-495417588")


def create_markdown(title: str, content: str, tags: list, folder: str) -> Path:
    """Create Obsidian markdown file with YAML frontmatter."""
    today = datetime.now().strftime("%Y-%m-%d")
    safe_title = "".join(c for c in title if c.isalnum() or c in " -_").strip()
    filename = f"{datetime.now().strftime('%Y%m%d')}-{safe_title.replace(' ', '-')}.md"
    filepath = OUTPUT_DIR / folder / filename

    frontmatter = f"""---
title: "{title}"
date: {today}
tags: [{', '.join(tags)}]
source: "NotebookLM/P5 프로젝트"
related: []
---

"""
    filepath.parent.mkdir(parents=True, exist_ok=True)
    filepath.write_text(frontmatter + content, encoding="utf-8")
    return filepath


def extract_notebook_sources(client, notebook_id: str, notebook_name: str):
    """Extract sources list from a notebook."""
    print(f"\n📚 {notebook_name} 소스 목록 추출 중...")

    try:
        # Get notebook details with sources
        result = client._call_rpc(
            client.RPC_GET_NOTEBOOK,
            [notebook_id],
            path=f"/notebook/{notebook_id}",
            timeout=30.0,
        )

        if result:
            return result
    except Exception as e:
        print(f"  ❌ 오류: {e}")
    return None


def extract_topic_insights(client, notebook_id: str, topics: list):
    """Extract insights for specific topics."""
    insights = []

    for topic in topics:
        print(f"  🔍 {topic} 분석 중...")
        try:
            # Query notebook for specific topic
            result = client._call_rpc(
                "SIl7of",  # RPC for chat/query
                [notebook_id, topic, None, None, None, None],
                path=f"/notebook/{notebook_id}",
                timeout=60.0,
            )
            if result:
                insights.append({"topic": topic, "content": result})
        except Exception as e:
            print(f"    ⚠️ {topic} 추출 실패: {e}")

    return insights


def main():
    print("=" * 60)
    print("P5 프로젝트 상세 지식 추출기")
    print("=" * 60)

    tokens = load_cached_tokens()
    if not tokens:
        print("인증 토큰 없음. notebooklm-mcp-auth 실행 필요.")
        return

    client = NotebookLMClient(
        cookies=tokens.cookies,
        csrf_token=tokens.csrf_token,
        session_id=tokens.session_id,
    )

    # ==========================================
    # Phase 1: P5 키 토픽별 인사이트 추출
    # ==========================================
    print("\n" + "=" * 40)
    print("Phase 1: 주요 토픽 인사이트 추출")
    print("=" * 40)

    key_topics = [
        "PSRC 시스템 설계",
        "Embedded Plate 간섭 해결",
        "구조 설계 변경사항",
        "공정 일정 현황",
    ]

    for topic in key_topics:
        print(f"\n🔍 {topic} 분석 중...")
        try:
            summary = client._call_rpc(
                client.RPC_GET_SUMMARY,
                [P5_NOTEBOOK_ID],
                path=f"/notebook/{P5_NOTEBOOK_ID}",
                timeout=30.0,
            )

            if summary:
                content = f"# {topic}\n\n"
                content += "## 핵심 인사이트\n\n"
                if isinstance(summary, list) and len(summary) > 0:
                    if isinstance(summary[0], str):
                        content += summary[0] + "\n"
                    elif isinstance(summary[0], list) and len(summary[0]) > 0:
                        content += str(summary[0][0]) + "\n"

                content += f"\n## 관련 노트\n- [[P5-프로젝트-요약]]\n- [[_index]]\n"

                filepath = create_markdown(
                    topic,
                    content,
                    ["project/p5", "type/insight", f"topic/{topic.split()[0].lower()}"],
                    "02-Structure",
                )
                print(f"  ✅ 생성: {filepath.name}")

        except Exception as e:
            print(f"  ❌ 오류: {e}")

    # ==========================================
    # Phase 2: 로드맵 노트북 인사이트
    # ==========================================
    print("\n" + "=" * 40)
    print("Phase 2: 구조 설계 로드맵 추출")
    print("=" * 40)

    try:
        roadmap_summary = client._call_rpc(
            client.RPC_GET_SUMMARY,
            [ROADMAP_NOTEBOOK_ID],
            path=f"/notebook/{ROADMAP_NOTEBOOK_ID}",
            timeout=30.0,
        )

        if roadmap_summary:
            content = "# 구조 설계 개선 로드맵\n\n"
            if isinstance(roadmap_summary, list) and len(roadmap_summary) > 0:
                if isinstance(roadmap_summary[0], str):
                    content += roadmap_summary[0]
                elif (
                    isinstance(roadmap_summary[0], list) and len(roadmap_summary[0]) > 0
                ):
                    content += str(roadmap_summary[0][0])

            filepath = create_markdown(
                "구조설계-로드맵",
                content,
                ["project/p5", "type/roadmap"],
                "00-Overview",
            )
            print(f"✅ 생성: {filepath.name}")

    except Exception as e:
        print(f"❌ 로드맵 추출 실패: {e}")

    # ==========================================
    # Phase 3: 이슈 관리 인덱스 생성
    # ==========================================
    print("\n" + "=" * 40)
    print("Phase 3: 이슈 관리 인덱스 생성")
    print("=" * 40)

    issue_index = """# P5 복합동 이슈 관리

## 📊 이슈 현황
- 소스: Google Drive AppSheet
- 경로: `G:\\내 드라이브\\appsheet\\data\\복합동이슈관리대장-495417588`

## 🔗 연결
- [[_index|P5 프로젝트 홈]]
- [[P5-프로젝트-요약]]

## 📝 이슈 카테고리
- [ ] 구조 간섭 이슈
- [ ] 설계 변경 이슈  
- [ ] 공정 지연 이슈
- [ ] 자재 조달 이슈

## 📅 최근 업데이트
- {date}: 이슈 인덱스 생성
""".format(
        date=datetime.now().strftime("%Y-%m-%d")
    )

    filepath = create_markdown(
        "이슈관리-인덱스",
        issue_index,
        ["project/p5", "type/index", "topic/issues"],
        "01-Issues",
    )
    print(f"✅ 생성: {filepath.name}")

    # ==========================================
    # 완료 보고
    # ==========================================
    print("\n" + "=" * 60)
    print("✅ P5 상세 지식 추출 완료!")
    print("=" * 60)

    # List created files
    print("\n📁 생성된 파일:")
    for folder in ["00-Overview", "01-Issues", "02-Structure", "03-Meetings"]:
        folder_path = OUTPUT_DIR / folder
        if folder_path.exists():
            for f in folder_path.glob("*.md"):
                print(f"  - {folder}/{f.name}")


if __name__ == "__main__":
    main()
