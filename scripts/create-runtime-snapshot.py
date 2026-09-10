from __future__ import annotations

import argparse
import shutil
import sqlite3
from pathlib import Path


DATABASE_SUFFIXES = {".db", ".sqlite", ".sqlite3"}


def is_database(path: Path) -> bool:
    return path.suffix.lower() in DATABASE_SUFFIXES


def copy_runtime_tree(source: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=False)
    database_files: list[tuple[Path, Path]] = []
    for item in source.rglob("*"):
        relative = item.relative_to(source)
        target = destination / relative
        if item.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        if item.name.endswith((".db-wal", ".db-shm", ".sqlite-wal", ".sqlite-shm")):
            continue
        if is_database(item):
            database_files.append((item, target))
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, target)

    for database, target in database_files:
        target.parent.mkdir(parents=True, exist_ok=True)
        source_connection = sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True)
        target_connection = sqlite3.connect(target)
        try:
            source_connection.backup(target_connection)
        finally:
            target_connection.close()
            source_connection.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a consistent STEM-SCI team runtime snapshot.")
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    source = args.source.resolve()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)

    copy_runtime_tree(source / "backend" / ".stem_sci", output / "backend_state")
    copy_runtime_tree(source / ".stem_sci", output / "root_state")
    shutil.copytree(source / "data" / "local", output / "data_local")
    shutil.copytree(
        source / "acceptance_runs" / "cgt_blind_output_rerun_046",
        output / "acceptance_rerun_046",
    )

    synergy_cache = source / "backend" / "synergy_cache.sqlite"
    if synergy_cache.exists():
        source_connection = sqlite3.connect(f"file:{synergy_cache.as_posix()}?mode=ro", uri=True)
        target_connection = sqlite3.connect(output / "synergy_cache.sqlite")
        try:
            source_connection.backup(target_connection)
        finally:
            target_connection.close()
            source_connection.close()


if __name__ == "__main__":
    main()
