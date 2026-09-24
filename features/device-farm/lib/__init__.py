"""Shared python for features/device-farm (host controllers + tests).

The folder name carries a dash, so this package is never reached by an `import`
statement: core loads it with importlib (`features.<name>.<part>`, see
shared/src/lib/utils/features.py) and everything inside uses relative imports.
Tests do the same — `importlib.import_module('features.device-farm.lib.config')`.
"""
