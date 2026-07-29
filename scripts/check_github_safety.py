"""Fail when files staged for GitHub include local secrets or transaction data."""

from __future__ import annotations

import fnmatch
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
BLOCKED_PATTERNS = (
    ".streamlit/secrets.toml",
    "*/.streamlit/secrets.toml",
    ".streamlit/*secrets*.toml",
    "*/.streamlit/*secrets*.toml",
    ".streamlit/*credentials*.txt",
    "*/.streamlit/*credentials*.txt",
    "*.sqlite",
    "*.sqlite3",
    "*.sqlite3-*",
    "*.db",
    "*.db-*",
    ".env",
    ".env.*",
    "*.pem",
    "*.key",
)


def staged_files() -> list[str]:
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return [line.strip().replace("\\", "/") for line in result.stdout.splitlines()]


def main() -> None:
    try:
        files = staged_files()
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        raise SystemExit(
            "Git初期化後、git addを実行してから再度確認してください。"
        ) from exc

    blocked = [
        path
        for path in files
        if any(fnmatch.fnmatch(path, pattern) for pattern in BLOCKED_PATTERNS)
    ]
    if blocked:
        print("公開禁止ファイルがステージされています:", file=sys.stderr)
        for path in blocked:
            print(f"  - {path}", file=sys.stderr)
        raise SystemExit(1)

    print(f"公開前チェックOK: ステージ済み{len(files)}ファイル")


if __name__ == "__main__":
    main()
