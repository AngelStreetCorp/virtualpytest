#!/usr/bin/env python3
import os
from pathlib import Path

def count_lines(file_path):
    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            return len(f.readlines())
    except:
        return 0

def main():
    root = Path(__file__).parent.parent
    total_lines = 0
    total_files = 0
    folder_data = {}
    
    # Code file extensions to count
    code_exts = {'.py', '.js', '.jsx', '.ts', '.tsx', '.sh', '.sql', '.yml', '.yaml', '.json', '.html', '.css', '.conf', '.service'}

    skip_names = {'venv', '__pycache__', 'node_modules', 'dist', 'tmp', 'docs', 'infra', 'screenshot', 'security_report', 'tests', 'scripts'}

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

            lines = count_lines(file_path)
            total_lines += lines
            total_files += 1

            # Get folder relative to root
            folder = rel_parts[0]
            if folder not in folder_data:
                folder_data[folder] = {'lines': 0, 'files': 0}
            folder_data[folder]['lines'] += lines
            folder_data[folder]['files'] += 1
    
    print(f"Total lines: {total_lines:,} ({total_files} files)")
    print("\nPer folder:")
    for folder, data in sorted(folder_data.items()):
        print(f"  {folder}: {data['lines']:,} lines ({data['files']} files)")

if __name__ == "__main__":
    main()
