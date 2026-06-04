from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path


def save_markdown_report(repo_name: str, markdown: str, reports_dir: Path) -> Path:
    reports_dir = Path(reports_dir)
    reports_dir.mkdir(parents=True, exist_ok=True)
    safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", repo_name or "repository")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = reports_dir / f"{safe_name}_{timestamp}.md"
    report_path.write_text(markdown, encoding="utf-8")
    return report_path

