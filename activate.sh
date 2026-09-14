#!/bin/bash

# Simple script to activate the parent virtual environment
source venv/bin/activate
export CODEX_HOME="$(pwd)/.codex"
echo "✅ Virtual environment activated!"
echo "🧭 Codex home: ${CODEX_HOME}"
echo "🐍 Python path: $(which python)"
echo "📦 Pip path: $(which pip)"
