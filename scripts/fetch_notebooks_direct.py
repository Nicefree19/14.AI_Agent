import sys
import os
import json

# Add venv site-packages to path explicitly if needed, but running with venv python should handle it
try:
    from notebooklm_mcp.auth import load_cached_tokens
    from notebooklm_mcp.api_client import NotebookLMClient
except ImportError as e:
    print(f"Error importing modules: {e}")
    sys.exit(1)


def main():
    print("Loading cached tokens...")
    tokens = load_cached_tokens()
    if not tokens:
        print("No cached tokens found. Please authenticte first.")
        return

    print(f"Tokens loaded. Initializing client...")
    try:
        # Initialize client with cookies
        # Monkey-patch headers for Windows
        print("Patching User-Agent for Windows...")
        NotebookLMClient._PAGE_FETCH_HEADERS["User-Agent"] = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        )
        NotebookLMClient._PAGE_FETCH_HEADERS["sec-ch-ua-platform"] = '"Windows"'

        # We also need to ensure the _get_client method uses these headers,
        # but the class implementation hardcodes them in _get_client.
        # We'll just instantiate and then modify the client if possible,
        # OR we can rely on the fact that _refresh_auth_tokens uses _PAGE_FETCH_HEADERS.
        # However, _get_client uses hardcoded headers on line 456.
        # We need to monkey-patch the class constant/method or just subclass.
        # Let's simple-patch the method if we can, or just modify the instance's client after creation.
        # Actually, _get_client is called lazily. We can pre-create the client with correct headers.

        print(f"Initializing client with {len(tokens.cookies)} cookies.")
        # Debug: print cookie keys
        print(f"Cookie keys: {list(tokens.cookies.keys())}")

        client = NotebookLMClient(
            cookies=tokens.cookies,
            csrf_token=tokens.csrf_token,
            session_id=tokens.session_id,
        )

        # Pre-initialize the internal HTTP client with correct headers
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
            timeout=30.0,
        )

        print("Fetching notebooks...")
        # Enable debug in list_notebooks
        try:
            notebooks = client.list_notebooks(debug=True)
            print(f"Found {len(notebooks)} notebooks:")
            for nb in notebooks:
                print(f"- [{nb.title}] (ID: {nb.id}) - {nb.source_count} sources")
        except ValueError as ve:
            print(f"ValueError during fetch: {ve}")
            # Manually try to fetch homepage to see redirect
            print("Attempting manual homepage fetch to debug...")
            import httpx

            headers = NotebookLMClient._PAGE_FETCH_HEADERS.copy()
            headers["Cookie"] = "; ".join(f"{k}={v}" for k, v in tokens.cookies.items())
            with httpx.Client(headers=headers, follow_redirects=False) as c:
                resp = c.get("https://notebooklm.google.com/")
                print(f"Homepage Status: {resp.status_code}")
                print(f"Homepage Location: {resp.headers.get('location')}")
                if resp.status_code == 302:
                    print("Redirected to login. Cookies are invalid.")

    except Exception as e:
        print(f"Error fetching notebooks: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    main()
