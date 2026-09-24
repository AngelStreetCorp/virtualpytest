#!/usr/bin/env python3
import os
import subprocess
from pathlib import Path

def count_lines(file_path):
    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            return len(f.readlines())
    except:
        return 0

# Code file extensions to count
CODE_EXTS = {'.py', '.js', '.jsx', '.ts', '.tsx', '.sh', '.sql', '.yml', '.yaml', '.json', '.html', '.css', '.conf', '.service'}

SKIP_NAMES = {'venv', '__pycache__', 'node_modules', 'dist', 'tmp', 'docs', 'infra', 'screenshot', 'security_report', 'tests', 'scripts'}


def _ignored_paths(root, candidates):
    """The subset of `candidates` the repo ignores, or None when that can't be asked.

    Counting the raw working tree double-counts generated output: a 12 316-line
    generated api-report, the pitch-deck, and 797 files of the built frontend copied
    into the Android app's assets — 524 043 lines against 469 612 of real source.
    All three are already in .gitignore, so the ignore rules are exactly the filter
    that is wanted.

    This deliberately asks `check-ignore` rather than taking `ls-files`, even though
    the tracked list looks like the obvious answer. The deploy tree is an rsync
    TARGET: its .git is frozen at a March 2026 commit with ~1650 files reported
    modified or deleted, so `ls-files` there returns a six-month-old list and would
    produce a wrong count on the one machine that actually runs this at build time.
    `.gitignore` is rsynced like any other file, so check-ignore is current there.
    Verified on the deploy VM: it flags api-report, pitch-deck and the android assets
    copy, and leaves real source alone.

    One batched call, not one per file.
    """
    if not candidates:
        return set()
    payload = '\n'.join(str(p.relative_to(root)) for p in candidates)
    try:
        result = subprocess.run(
            ['git', '-C', str(root), 'check-ignore', '--stdin', '--no-index'],
            input=payload.encode('utf-8'),
            capture_output=True, timeout=60,
        )
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        return None
    # check-ignore exits 0 when something matched, 1 when nothing did; both are fine.
    if result.returncode not in (0, 1):
        return None
    return {line for line in result.stdout.decode('utf-8', 'replace').split('\n') if line}


def count_repo(root=None):
    """Walk the repo and return {'total', 'files', 'by_area', 'method'}.

    Extracted so scripts/docs/build_project_metrics.py reuses the exact same
    definition of "a line of code" that this script has always printed — two
    different answers to the same question on one page would be worse than none.
    """
    root = Path(root) if root else Path(__file__).parent.parent
    total_lines = 0
    total_files = 0
    folder_data = {}

    code_exts = CODE_EXTS
    skip_names = SKIP_NAMES

    # First pass: everything that looks like code and survives the directory skips.
    candidates = []
    for file_path in root.rglob('*'):
        if file_path.is_file() and file_path.suffix in code_exts:
            rel_parts = file_path.relative_to(root).parts

            # Skip files directly at the project root
            if len(rel_parts) == 1:
                continue

            # Skip hidden folders (.*), build/cache dirs, docs/infra/screenshot/security_report, and any test_* / tests_* dir
            if any(
                part.startswith('.')
                or part in skip_names
                or part.startswith('tests_')
                or part.startswith('test_')
                for part in rel_parts[:-1]
            ):
                continue
            candidates.append(file_path)

    # Second pass: drop generated output, which is exactly what the repo ignores.
    ignored = _ignored_paths(root, candidates)
    method = 'source' if ignored is not None else 'working-tree'
    if ignored:
        candidates = [p for p in candidates if str(p.relative_to(root)) not in ignored]

    for file_path in candidates:
        lines = count_lines(file_path)
        total_lines += lines
        total_files += 1

        # Attribute to the top-level folder
        folder = file_path.relative_to(root).parts[0]
        if folder not in folder_data:
            folder_data[folder] = {'lines': 0, 'files': 0}
        folder_data[folder]['lines'] += lines
        folder_data[folder]['files'] += 1

    return {'total': total_lines, 'files': total_files, 'by_area': folder_data,
            'method': method}


def main():
    stats = count_repo()
    print(f"Total lines: {stats['total']:,} ({stats['files']} files, {stats['method']})")
    print("\nPer folder:")
    for folder, data in sorted(stats['by_area'].items()):
        print(f"  {folder}: {data['lines']:,} lines ({data['files']} files)")

if __name__ == "__main__":
    main()
