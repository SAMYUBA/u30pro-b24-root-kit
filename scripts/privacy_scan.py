#!/usr/bin/env python3
"""Reject likely private inputs in the public tree; does not rewrite evidence."""

import argparse
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP = {".git", "__pycache__", ".venv", ".mypy_cache", ".ruff_cache", ".pytest_cache"}
DENIED_SUFFIX = {
    ".bin",
    ".img",
    ".apk",
    ".zip",
    ".7z",
    ".pem",
    ".key",
    ".pub",
    ".log",
    ".pcap",
    ".dylib",
}
PATTERNS = {
    "private-key": re.compile(rb"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "github-token": re.compile(rb"(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{30,})"),
    "private-home": re.compile(rb"/(?:Users|home)/[A-Za-z0-9][A-Za-z0-9_.-]+/"),
    "device-id": re.compile(rb"(?<![A-Za-z0-9])\d{12,17}(?![A-Za-z0-9])"),
    "adb-public-key": re.compile(rb"(?m)^[A-Za-z0-9+/]{650,}={0,2}(?:\s|$)"),
}


def inspect(name, data, deny):
    findings = []
    if Path(name).suffix.lower() in DENIED_SUFFIX or Path(name).name in (
        "adbkey",
        ".env",
        "credentials.json",
    ):
        findings.append("private/binary file class")
    if len(data) > 500_000 or b"\0" in data:
        findings.append("large/binary content")
    for label, regex in PATTERNS.items():
        if regex.search(data):
            findings.append(label)
    if any(marker and marker.encode() in data for marker in deny):
        findings.append("local deny marker")
    return findings


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--deny-file", type=Path, help="Local JSON array of private markers; never publish it"
    )
    p.add_argument("--history", action="store_true")
    a = p.parse_args()
    deny = json.loads(a.deny_file.read_text()) if a.deny_file else []
    violations, count = [], 0
    for path in ROOT.rglob("*"):
        relative = path.relative_to(ROOT)
        if set(relative.parts) & SKIP or not path.is_file():
            continue
        if path.is_symlink():
            violations.append((str(relative), ["symlink requires manual review"]))
            continue
        found = inspect(str(relative), path.read_bytes(), deny)
        count += 1
        if found:
            violations.append((str(relative), found))
    if a.history:
        rows = subprocess.check_output(
            ["git", "rev-list", "--objects", "--all"], cwd=ROOT, text=True
        ).splitlines()
        for row in rows:
            parts = row.split(" ", 1)
            if len(parts) != 2:
                continue
            oid, name = parts
            kind = subprocess.check_output(
                ["git", "cat-file", "-t", oid], cwd=ROOT, text=True
            ).strip()
            if kind != "blob":
                continue
            data = subprocess.check_output(["git", "cat-file", "blob", oid], cwd=ROOT)
            found = inspect(name, data, deny)
            if found:
                violations.append(("history:" + name, found))
    print(
        json.dumps(
            {
                "files_scanned": count,
                "findings": violations,
                "scope": "heuristic tree/history scan, plus optional private denylist; manual review still required",
            },
            indent=2,
        )
    )
    raise SystemExit(bool(violations))


if __name__ == "__main__":
    main()
