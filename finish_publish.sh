#!/usr/bin/env bash
set -euo pipefail
# Finish publishing runtime modules from a local artifacts/maxop_mcp_harness tree
REPO="${1:-ZuluYokohama/maxop-mcp-harness}"
ROOT="$(cd "$(dirname "$0")" && pwd)"
WORKDIR=$(mktemp -d)
git clone "https://github.com/${REPO}.git" "$WORKDIR/repo"
cd "$WORKDIR/repo"
cp -a "$ROOT/src" "$ROOT/tests" .
git add -A
git status
git commit -m "feat: complete runtime — gates loop mcp_tools mcp_server selftest" || true
git push origin main
echo "Done. PYTHONPATH=src python -m maxop_harness.cli selftest"
