"""
P5 Dashboard Data Bridge
------------------------
Reads Markdown files from ResearchVault and generates a unified JSON feed for the P5 React Dashboard.

Output: dashboard/public/data.json
"""

import os
import json
import yaml
import glob
from pathlib import Path
from datetime import datetime

# Configuration
SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
VAULT_DIR = PROJECT_ROOT / "ResearchVault" / "P5-Project"
OUTPUT_DIR = PROJECT_ROOT / "dashboard" / "public"
OUTPUT_FILE = OUTPUT_DIR / "data.json"

# Ensure output directory exists (even if dashboard isn't init'd yet)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def parse_frontmatter(content):
    """Parses YAML frontmatter from a Markdown file."""
    try:
        if content.startswith("---"):
            parts = content.split("---", 2)
            if len(parts) >= 3:
                return yaml.safe_load(parts[1])
    except Exception as e:
        print(f"Error parsing frontmatter: {e}")
    return {}


def calculate_risk_score(data):
    """Calculates risk score based on Impact and Urgency."""
    impact_map = {"critical": 5, "high": 4, "medium": 3, "low": 2, "negligible": 1}
    urgency_map = {"immediate": 5, "high": 4, "medium": 3, "low": 2, "planned": 1}

    impact = impact_map.get(str(data.get("impact", "")).lower(), 1)
    urgency = urgency_map.get(str(data.get("urgency", "")).lower(), 1)

    return impact * urgency


def get_issues():
    issues = []
    issue_dir = VAULT_DIR / "01-Issues"

    if not issue_dir.exists():
        return []

    for file_path in issue_dir.glob("*.md"):
        try:
            content = file_path.read_text(encoding="utf-8")
            data = parse_frontmatter(content)
            if not data:
                continue

            # Basic Validation
            if "issue_id" not in data:
                data["issue_id"] = file_path.stem

            # Risk Score
            data["risk_score"] = calculate_risk_score(data)

            # Append
            issues.append(data)
        except Exception as e:
            print(f"Failed to process {file_path.name}: {e}")

    # Sort by Risk Score (Desc)
    issues.sort(key=lambda x: x.get("risk_score", 0), reverse=True)
    return issues


def get_meetings():
    meetings = []
    meeting_dir = VAULT_DIR / "03-Meetings"

    if not meeting_dir.exists():
        return []

    for file_path in meeting_dir.glob("*-Analysis.md"):
        try:
            content = file_path.read_text(encoding="utf-8")
            data = parse_frontmatter(content)

            # Extract Summary (Section 2)
            summary = ""
            if "SECTION 2: SUMMARY_5_LINES" in content:
                parts = content.split("SECTION 2: SUMMARY_5_LINES")
                if len(parts) > 1:
                    summary_part = parts[1].split("SECTION 3")[0]
                    summary = summary_part.strip()

            data["summary"] = summary
            data["filename"] = file_path.name
            meetings.append(data)
        except Exception as e:
            print(f"Failed to process {file_path.name}: {e}")

    # Sort by Date (Desc)
    meetings.sort(key=lambda x: str(x.get("date", "")), reverse=True)
    return meetings


def main():
    print("🚀 Generating P5 Dashboard Data...")

    issues = get_issues()
    meetings = get_meetings()

    # Calculate Stats
    stats = {
        "total_issues": len(issues),
        "critical_issues": sum(
            1 for i in issues if str(i.get("priority", "")).lower() == "critical"
        ),
        "open_issues": sum(
            1
            for i in issues
            if str(i.get("status", "")).lower() in ["open", "in_progress"]
        ),
        "recent_meetings": len(meetings),
    }

    dashboard_data = {
        "generated_at": datetime.now().isoformat(),
        "stats": stats,
        "issues": issues,
        "meetings": meetings,
    }

    # Write JSON
    try:
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(dashboard_data, f, ensure_ascii=False, indent=2, default=str)
        print(f"✅ Data saved to {OUTPUT_FILE}")
        print(f"   - Issues: {len(issues)}")
        print(f"   - Meetings: {len(meetings)}")
    except Exception as e:
        print(f"❌ Failed to save data: {e}")


if __name__ == "__main__":
    main()
