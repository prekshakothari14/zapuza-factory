#!/usr/bin/env python3
"""
Build factory_qc_submission.zip from this project directory.

Uses only the standard library (zipfile). Skips virtualenvs, secrets,
local DB, media, bytecode, and any existing zip archives.
"""
from __future__ import annotations

import os
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT.parent / "factory_qc_submission.zip"
# If manage.py lives in ROOT, package that folder as factory_qc/
ARCHIVE_ROOT_NAME = "factory_qc"

SKIP_DIR_NAMES = {
    ".venv",
    "venv",
    "__pycache__",
    "media",
    "staticfiles",
    ".git",
    ".idea",
    ".vscode",
}
SKIP_FILE_NAMES = {
    ".env",
    "db.sqlite3",
}
SKIP_SUFFIXES = {".pyc", ".pyo", ".zip"}


def should_skip(path: Path) -> bool:
    rel_parts = path.relative_to(ROOT).parts
    for part in rel_parts[:-1] if path.is_file() else rel_parts:
        if part in SKIP_DIR_NAMES:
            return True
    if path.is_file():
        if path.name in SKIP_FILE_NAMES:
            return True
        if path.suffix in SKIP_SUFFIXES:
            return True
        # Never package this script's previous output if dropped in-tree
        if path.name == "factory_qc_submission.zip":
            return True
    return False


def main() -> None:
    files: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        # prune skipped directories in-place
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIR_NAMES]
        base = Path(dirpath)
        for name in filenames:
            p = base / name
            if should_skip(p):
                continue
            files.append(p)

    files.sort(key=lambda p: str(p.relative_to(ROOT)).lower())

    if OUT.exists():
        OUT.unlink()

    with zipfile.ZipFile(OUT, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in files:
            arcname = f"{ARCHIVE_ROOT_NAME}/{path.relative_to(ROOT).as_posix()}"
            zf.write(path, arcname)

    # Report
    size = OUT.stat().st_size
    with zipfile.ZipFile(OUT, "r") as zf:
        names = zf.namelist()
    top_level = sorted({n.split("/")[1] for n in names if n.startswith(f"{ARCHIVE_ROOT_NAME}/") and n.count("/") >= 1 and not n.endswith("/")})
    # also include files directly under factory_qc/
    top_files = sorted({
        n.split("/")[1]
        for n in names
        if n.startswith(f"{ARCHIVE_ROOT_NAME}/") and n.count("/") == 1 and not n.endswith("/")
    })
    top = sorted(set(top_level) | set(top_files))

    print(f"Wrote {OUT}")
    print(f"Size: {size} bytes ({size / 1024:.1f} KiB)")
    print(f"Entries: {len(names)}")
    print("Top-level contents:")
    for item in top:
        print(f"  {item}")

    forbidden = {".venv", "venv", ".env", "db.sqlite3", "media"}
    leaked = [n for n in names if any(f"/{bad}/" in n or n.endswith(f"/{bad}") or n.endswith(f"/{bad}/") for bad in forbidden)]
    # also catch .env as a file path component
    leaked += [n for n in names if n.rstrip("/").endswith("/.env") or n.rstrip("/").endswith("/db.sqlite3")]
    leaked = sorted(set(leaked))
    if leaked:
        print("WARNING — forbidden paths found in zip:")
        for n in leaked:
            print(f"  {n}")
        raise SystemExit(1)
    print("OK — no .venv, .env, db.sqlite3, or media entries.")


if __name__ == "__main__":
    main()
