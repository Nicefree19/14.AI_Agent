"""
NotebookLM Insight Extractor
Fetches summaries and insights from notebooks via MCP API.
"""

import sys

try:
    from notebooklm_mcp.auth import load_cached_tokens
    from notebooklm_mcp.api_client import NotebookLMClient
except ImportError as e:
    print(f"Error importing modules: {e}")
    sys.exit(1)


def main():
    print("=" * 60)
    print("NotebookLM Insight Extractor")
    print("=" * 60)

    tokens = load_cached_tokens()
    if not tokens:
        print("No cached tokens. Run 'notebooklm-mcp-auth' first.")
        return

    # Patch headers for Windows
    NotebookLMClient._PAGE_FETCH_HEADERS["User-Agent"] = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36"
    )
    NotebookLMClient._PAGE_FETCH_HEADERS["sec-ch-ua-platform"] = '"Windows"'

    client = NotebookLMClient(
        cookies=tokens.cookies,
        csrf_token=tokens.csrf_token,
        session_id=tokens.session_id,
    )

    # Pre-initialize HTTP client with correct headers
    cookie_str = "; ".join(f"{k}={v}" for k, v in tokens.cookies.items())
    import httpx

    client._client = httpx.Client(
        headers={
            "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
            "Origin": "https://notebooklm.google.com",
            "Referer": "https://notebooklm.google.com/",
            "Cookie": cookie_str,
            "X-Same-Domain": "1",
            "User-Agent": NotebookLMClient._PAGE_FETCH_HEADERS["User-Agent"],
        },
        timeout=60.0,
    )

    print("\nFetching notebooks...")
    notebooks = client.list_notebooks()

    # Filter notebooks with sources
    active_notebooks = [nb for nb in notebooks if nb.source_count > 0 and nb.title]
    print(f"Found {len(active_notebooks)} notebooks with sources.\n")

    # Show top 10 by source count
    sorted_nbs = sorted(active_notebooks, key=lambda x: x.source_count, reverse=True)[
        :10
    ]

    print("Top 10 notebooks by source count:")
    print("-" * 60)
    for i, nb in enumerate(sorted_nbs, 1):
        print(f"{i:2}. [{nb.source_count:3} sources] {nb.title[:50]}")

    print("\n" + "=" * 60)
    print("Extracting insights from top 3 notebooks...")
    print("=" * 60)

    for nb in sorted_nbs[:3]:
        print(f"\n📓 {nb.title}")
        print("-" * 50)
        try:
            # Get notebook summary (if available)
            summary = client._call_rpc(
                client.RPC_GET_SUMMARY, [nb.id], path=f"/notebook/{nb.id}", timeout=30.0
            )
            if summary and isinstance(summary, list):
                # Extract summary text
                if len(summary) > 0 and summary[0]:
                    summary_text = summary[0]
                    if isinstance(summary_text, str):
                        print(f"📝 Summary: {summary_text[:500]}...")
                    elif isinstance(summary_text, list) and len(summary_text) > 0:
                        print(f"📝 Summary: {str(summary_text[0])[:500]}...")

                # Extract suggested topics if present
                if len(summary) > 1 and summary[1]:
                    topics = summary[1]
                    if isinstance(topics, list):
                        print(f"💡 Suggested Topics: {topics[:5]}")
            else:
                print("No summary available for this notebook.")
        except Exception as e:
            print(f"Error getting summary: {e}")

    print("\n" + "=" * 60)
    print("Insight extraction complete!")


if __name__ == "__main__":
    main()
