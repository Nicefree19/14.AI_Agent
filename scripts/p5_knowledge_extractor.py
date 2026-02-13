"""
P5 프로젝트 지식 추출기
NotebookLM에서 P5 관련 인사이트를 추출하여 Obsidian 마크다운으로 저장
"""

import sys
import os
from datetime import datetime
from pathlib import Path

# Add venv for imports
sys.path.insert(
    0, str(Path(__file__).parent.parent / ".agent_venv" / "Lib" / "site-packages")
)

try:
    from notebooklm_mcp.auth import load_cached_tokens
    from notebooklm_mcp.api_client import NotebookLMClient
except ImportError as e:
    print(f"Import error: {e}")
    sys.exit(1)

# Config
P5_NOTEBOOK_ID = "3de596ed-3543-4fbf-b30e-dddf7d7783be"
OUTPUT_DIR = Path("D:/00.Work_AI_Tool/14.AI_Agent/ResearchVault/P5-Project")


def create_markdown(title: str, content: str, tags: list, folder: str) -> Path:
    """Create Obsidian markdown file with YAML frontmatter."""
    today = datetime.now().strftime("%Y-%m-%d")
    filename = f"{datetime.now().strftime('%Y%m%d')}-{title.replace(' ', '-')}.md"
    filepath = OUTPUT_DIR / folder / filename

    frontmatter = f"""---
title: "{title}"
date: {today}
tags: [{', '.join(tags)}]
source: "NotebookLM/P5 프로젝트"
---

"""
    filepath.parent.mkdir(parents=True, exist_ok=True)
    filepath.write_text(frontmatter + content, encoding="utf-8")
    return filepath


def main():
    print("=" * 60)
    print("P5 프로젝트 지식 추출기")
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

    print(f"\n노트북 ID: {P5_NOTEBOOK_ID}")
    print("인사이트 추출 중...")

    try:
        # Get notebook summary
        summary = client._call_rpc(
            client.RPC_GET_SUMMARY,
            [P5_NOTEBOOK_ID],
            path=f"/notebook/{P5_NOTEBOOK_ID}",
            timeout=30.0,
        )

        if summary:
            print(f"✅ 요약 추출 완료")

            # Create overview file
            content = "# P5 프로젝트 요약\n\n"
            if isinstance(summary, list) and len(summary) > 0:
                if isinstance(summary[0], str):
                    content += summary[0]
                elif isinstance(summary[0], list):
                    content += str(summary[0][0]) if summary[0] else ""

            filepath = create_markdown(
                "P5-프로젝트-요약",
                content,
                ["project/p5", "type/summary"],
                "00-Overview",
            )
            print(f"📄 생성됨: {filepath}")

    except Exception as e:
        print(f"❌ 오류: {e}")
        import traceback

        traceback.print_exc()

    print("\n" + "=" * 60)
    print("완료!")


if __name__ == "__main__":
    main()
