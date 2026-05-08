#!/usr/bin/env python3
"""Compute multi-language LOC/SLOC snapshots per frozen tag.

This script keeps the same CSV schema as compute_loc_per_tag.py but counts the
source extensions needed by the expanded Phase I cohort.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import subprocess
from pathlib import Path


VERSION_REQUIRED_FIELDS = {
    "project_id",
    "tag_name",
    "commit_hash",
    "tag_date",
}

OUT_FIELDS = [
    "project_id",
    "tag_name",
    "commit_hash",
    "tag_date",
    "total_lines",
    "blank_lines",
    "comment_lines",
    "code_lines",
]

SOURCE_EXTENSIONS = {
    ".bash",
    ".c",
    ".cc",
    ".cjs",
    ".cpp",
    ".go",
    ".h",
    ".hpp",
    ".java",
    ".js",
    ".jsx",
    ".kt",
    ".kts",
    ".mjs",
    ".pl",
    ".pm",
    ".py",
    ".rb",
    ".rbi",
    ".rs",
    ".sh",
    ".ts",
    ".tsx",
    ".zsh",
}

LEGACY_PYTHON_PROJECTS = {
    "click",
    "flask",
    "requests",
    "urllib3",
}

HASH_COMMENT_EXTENSIONS = {
    ".bash",
    ".py",
    ".pl",
    ".pm",
    ".rb",
    ".rbi",
    ".sh",
    ".zsh",
}

C_STYLE_COMMENT_EXTENSIONS = {
    ".c",
    ".cc",
    ".cjs",
    ".cpp",
    ".go",
    ".h",
    ".hpp",
    ".java",
    ".js",
    ".jsx",
    ".kt",
    ".kts",
    ".mjs",
    ".rs",
    ".ts",
    ".tsx",
}

EXCLUDE_DIRS = {
    ".git",
    ".gradle",
    ".tox",
    ".venv",
    ".yarn",
    "__pycache__",
    "build",
    "coverage",
    "dist",
    "node_modules",
    "target",
    "vendor",
    "vendors",
    "venv",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--versions", default="data/versions_all.csv", type=Path)
    parser.add_argument("--repos-dir", default="repos", type=Path)
    parser.add_argument("--out", default="out/loc_per_tag_all.csv", type=Path)
    parser.add_argument("--error-log", default="logs/errors_all_loc.log", type=Path)
    return parser.parse_args()


def normalize_path(path: Path, base_dir: Path) -> Path:
    return path if path.is_absolute() else base_dir / path


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def append_error(log_path: Path, message: str) -> None:
    ensure_parent(log_path)
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(f"[{stamp}] {message}\n")


def run_git(repo_dir: Path, args: list[str]) -> subprocess.CompletedProcess:
    cmd = ["git", "-C", str(repo_dir)] + args
    return subprocess.run(
        cmd,
        text=True,
        capture_output=True,
        check=False,
        encoding="utf-8",
        errors="replace",
    )


def read_versions(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        if not reader.fieldnames:
            raise ValueError(f"{path} is empty or missing a header")
        missing = VERSION_REQUIRED_FIELDS.difference(set(reader.fieldnames))
        if missing:
            missing_list = ", ".join(sorted(missing))
            raise ValueError(f"{path} is missing required columns: {missing_list}")
        return [row for row in reader]


def get_repo_state(repo_dir: Path) -> tuple[str, str]:
    branch_proc = run_git(repo_dir, ["symbolic-ref", "-q", "--short", "HEAD"])
    if branch_proc.returncode == 0 and branch_proc.stdout.strip():
        return ("branch", branch_proc.stdout.strip())

    commit_proc = run_git(repo_dir, ["rev-parse", "HEAD"])
    if commit_proc.returncode != 0 or not commit_proc.stdout.strip():
        raise RuntimeError(f"Cannot determine git state for {repo_dir}")
    return ("detached", commit_proc.stdout.strip())


def restore_repo_state(repo_dir: Path, state_type: str, state_value: str) -> tuple[bool, str]:
    if state_type == "branch":
        proc = run_git(repo_dir, ["checkout", state_value])
    else:
        proc = run_git(repo_dir, ["checkout", "--detach", state_value])

    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip().replace("\n", " | ")
        return False, stderr
    return True, ""


def tracked_source_files(repo_dir: Path) -> list[Path]:
    proc = run_git(repo_dir, ["ls-files", "-z"])
    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip()
        raise RuntimeError(f"git ls-files failed: {stderr}")

    files: list[Path] = []
    for raw in proc.stdout.split("\0"):
        if not raw:
            continue
        rel = Path(raw)
        suffix = rel.suffix.lower()
        if suffix not in SOURCE_EXTENSIONS:
            continue
        if any(part in EXCLUDE_DIRS for part in rel.parts):
            continue
        files.append(repo_dir / rel)
    return files


def classify_hash_comment_line(stripped: str) -> str:
    if stripped == "":
        return "blank"
    if stripped.startswith("#"):
        return "comment"
    return "code"


def classify_c_style_line(stripped: str, in_block: bool) -> tuple[str, bool]:
    if stripped == "":
        return "blank", in_block

    cursor = stripped
    if in_block:
        end = cursor.find("*/")
        if end == -1:
            return "comment", True
        cursor = cursor[end + 2 :].strip()
        if cursor == "":
            return "comment", False

    if cursor.startswith("//"):
        return "comment", False

    if cursor.startswith("/*"):
        end = cursor.find("*/", 2)
        if end == -1:
            return "comment", True
        after = cursor[end + 2 :].strip()
        return ("comment" if after == "" else "code"), False

    return "code", False


def classify_ruby_line(stripped: str, in_ruby_block: bool) -> tuple[str, bool]:
    if stripped == "":
        return "blank", in_ruby_block
    if in_ruby_block:
        return "comment", not stripped.startswith("=end")
    if stripped.startswith("=begin"):
        return "comment", True
    if stripped.startswith("#"):
        return "comment", False
    return "code", False


def count_file(path: Path) -> tuple[int, int, int, int]:
    suffix = path.suffix.lower()
    with path.open("r", encoding="utf-8", errors="ignore") as fh:
        return count_lines(suffix, fh)


def count_lines(suffix: str, lines) -> tuple[int, int, int, int]:
    total_lines = 0
    blank_lines = 0
    comment_lines = 0
    code_lines = 0
    in_c_block = False
    in_ruby_block = False

    for line in lines:
        total_lines += 1
        stripped = line.strip()

        if suffix in {".rb", ".rbi"}:
            kind, in_ruby_block = classify_ruby_line(stripped, in_ruby_block)
        elif suffix in C_STYLE_COMMENT_EXTENSIONS:
            kind, in_c_block = classify_c_style_line(stripped, in_c_block)
        elif suffix in HASH_COMMENT_EXTENSIONS:
            kind = classify_hash_comment_line(stripped)
        else:
            kind = "blank" if stripped == "" else "code"

        if kind == "blank":
            blank_lines += 1
        elif kind == "comment":
            comment_lines += 1
        else:
            code_lines += 1

    return total_lines, blank_lines, comment_lines, code_lines


def count_multilang_sloc(repo_dir: Path) -> tuple[int, int, int, int]:
    total_lines = 0
    blank_lines = 0
    comment_lines = 0
    code_lines = 0

    for source_file in tracked_source_files(repo_dir):
        try:
            file_total, file_blank, file_comment, file_code = count_file(source_file)
        except OSError:
            continue
        total_lines += file_total
        blank_lines += file_blank
        comment_lines += file_comment
        code_lines += file_code

    return total_lines, blank_lines, comment_lines, code_lines


def count_legacy_python_sloc(repo_dir: Path) -> tuple[int, int, int, int]:
    """Preserve the original pilot Python LOC policy for Python-only projects."""

    total_lines = 0
    blank_lines = 0
    comment_lines = 0
    code_lines = 0

    for py_file in repo_dir.rglob("*.py"):
        rel_parts = py_file.relative_to(repo_dir).parts
        if any(part in EXCLUDE_DIRS for part in rel_parts):
            continue

        try:
            with py_file.open("r", encoding="utf-8", errors="ignore") as fh:
                for line in fh:
                    total_lines += 1
                    stripped = line.strip()
                    if stripped == "":
                        blank_lines += 1
                    elif stripped.startswith("#"):
                        comment_lines += 1
                    else:
                        code_lines += 1
        except OSError:
            continue

    return total_lines, blank_lines, comment_lines, code_lines


def count_project_sloc(
    project_id: str,
    repo_dir: Path,
    commit_hash: str,
) -> tuple[int, int, int, int]:
    _ = commit_hash
    if project_id in LEGACY_PYTHON_PROJECTS:
        return count_legacy_python_sloc(repo_dir)
    return count_multilang_sloc(repo_dir)


def write_csv(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    ensure_parent(path)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    args = parse_args()
    base_dir = Path.cwd()

    versions_path = normalize_path(args.versions, base_dir)
    repos_dir = normalize_path(args.repos_dir, base_dir)
    out_path = normalize_path(args.out, base_dir)
    error_log = normalize_path(args.error_log, base_dir)

    ensure_parent(error_log)
    error_log.write_text("", encoding="utf-8")

    try:
        versions = read_versions(versions_path)
    except Exception as exc:  # noqa: BLE001
        append_error(error_log, f"Fatal: cannot read versions file: {exc}")
        print(f"Failed to read versions: {exc}")
        return 1

    versions.sort(key=lambda r: (r["project_id"], r["tag_date"], r["tag_name"]))

    repo_states: dict[str, tuple[str, str]] = {}
    out_rows: list[dict] = []

    for row in versions:
        project_id = row["project_id"].strip()
        tag_name = row["tag_name"].strip()
        commit_hash = row["commit_hash"].strip()
        tag_date = row["tag_date"].strip()
        repo_dir = repos_dir / project_id

        if not repo_dir.exists():
            append_error(error_log, f"{project_id}/{tag_name}: repo path not found: {repo_dir}")
            continue

        if project_id not in repo_states:
            try:
                repo_states[project_id] = get_repo_state(repo_dir)
            except Exception as exc:  # noqa: BLE001
                append_error(error_log, f"{project_id}: cannot capture initial git state: {exc}")
                continue

        checkout = run_git(repo_dir, ["checkout", "--detach", commit_hash])
        if checkout.returncode != 0:
            stderr = (checkout.stderr or "").strip().replace("\n", " | ")
            append_error(
                error_log,
                f"{project_id}/{tag_name}: checkout failed for {commit_hash}; stderr={stderr}",
            )
            continue

        try:
            total_lines, blank_lines, comment_lines, code_lines = count_project_sloc(
                project_id,
                repo_dir,
                commit_hash,
            )
        except Exception as exc:  # noqa: BLE001
            append_error(error_log, f"{project_id}/{tag_name}: LOC count failed: {exc}")
            continue
        out_rows.append(
            {
                "project_id": project_id,
                "tag_name": tag_name,
                "commit_hash": commit_hash,
                "tag_date": tag_date,
                "total_lines": total_lines,
                "blank_lines": blank_lines,
                "comment_lines": comment_lines,
                "code_lines": code_lines,
            }
        )

    for project_id, (state_type, state_value) in repo_states.items():
        repo_dir = repos_dir / project_id
        ok, detail = restore_repo_state(repo_dir, state_type, state_value)
        if not ok:
            append_error(
                error_log,
                f"{project_id}: failed to restore repo state ({state_type}={state_value}); stderr={detail}",
            )

    out_rows.sort(key=lambda r: (r["project_id"], r["tag_date"], r["tag_name"]))
    write_csv(out_path, OUT_FIELDS, out_rows)

    print(f"Wrote {len(out_rows)} rows to {out_path}")
    print(f"Errors logged to {error_log}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
