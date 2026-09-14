"""
File-based Benchmark Test Loader

Loads benchmark test definitions from YAML files instead of database.
Test definitions are version-controlled and easy to edit.
"""

import os
import yaml
from typing import Dict, List, Any, Optional
from pathlib import Path

# Cache for loaded benchmarks
_benchmark_cache: Dict[str, List[Dict[str, Any]]] = {}
_all_benchmarks: List[Dict[str, Any]] = []


def get_benchmarks_dir() -> Path:
    """Get the benchmarks tests directory path."""
    return Path(__file__).parent / "tests"


def load_benchmark_file(filepath: Path) -> List[Dict[str, Any]]:
    """Load benchmarks from a single YAML file."""
    with open(filepath, 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f)
    
    if not data or 'tests' not in data:
        return []
    
    category = data.get('category', filepath.stem)
    tests = []
    
    for test in data['tests']:
        # Normalize test structure
        tests.append({
            'test_id': test['id'],
            'name': test['name'],
            'description': test.get('description', ''),
            'category': category,
            'input_prompt': test['prompt'],
            'expected_output': test.get('expected', {}),
            'validation_type': test.get('validation', 'contains'),
            'timeout_seconds': test.get('timeout', 30),
            'applicable_agent_types': test.get('agents', None),
            'points': test.get('points', 1.0),
            'is_active': test.get('active', True),
        })
    
    return tests


def load_all_benchmarks(force_reload: bool = False) -> List[Dict[str, Any]]:
    """
    Load all benchmark tests from YAML files.
    
    Scans:
    - benchmarks/tests/*.yaml (built-in tests)
    - benchmarks/custom/*.yaml (user-defined tests)
    
    Returns list of all benchmark test definitions.
    """
    global _benchmark_cache, _all_benchmarks
    
    if _all_benchmarks and not force_reload:
        return _all_benchmarks
    
    _benchmark_cache = {}
    _all_benchmarks = []
    
    benchmarks_dir = get_benchmarks_dir()
    custom_dir = benchmarks_dir.parent / "custom"
    
    # Load built-in tests
    if benchmarks_dir.exists():
        for yaml_file in benchmarks_dir.glob("*.yaml"):
            tests = load_benchmark_file(yaml_file)
            category = yaml_file.stem
            _benchmark_cache[category] = tests
            _all_benchmarks.extend(tests)
    
    # Load custom tests
    if custom_dir.exists():
        for yaml_file in custom_dir.glob("*.yaml"):
            tests = load_benchmark_file(yaml_file)
            _all_benchmarks.extend(tests)
            # Add to cache with custom_ prefix
            _benchmark_cache[f"custom_{yaml_file.stem}"] = tests
    
    return _all_benchmarks


def get_benchmarks_by_category(category: str) -> List[Dict[str, Any]]:
    """Get benchmarks filtered by category."""
    load_all_benchmarks()  # Ensure loaded
    return [b for b in _all_benchmarks if b['category'] == category]


def get_benchmark_by_id(test_id: str) -> Optional[Dict[str, Any]]:
    """Get a specific benchmark by test_id."""
    load_all_benchmarks()  # Ensure loaded
    for b in _all_benchmarks:
        if b['test_id'] == test_id:
            return b
    return None


def get_benchmarks_for_agent(agent_id: str) -> List[Dict[str, Any]]:
    """Get benchmarks applicable to a specific agent type."""
    load_all_benchmarks()  # Ensure loaded
    
    applicable = []
    for b in _all_benchmarks:
        if not b.get('is_active', True):
            continue
        
        agent_types = b.get('applicable_agent_types')
        if agent_types is None:  # None means all agents
            applicable.append(b)
        elif agent_id in agent_types:
            applicable.append(b)
    
    return applicable


def get_categories() -> List[str]:
    """Get list of all benchmark categories."""
    load_all_benchmarks()  # Ensure loaded
    return list(set(b['category'] for b in _all_benchmarks))


def count_benchmarks() -> int:
    """Get total number of active benchmarks."""
    load_all_benchmarks()
    return len([b for b in _all_benchmarks if b.get('is_active', True)])

