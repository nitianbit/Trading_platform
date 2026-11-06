#!/bin/zsh
set -eu
cd "${0:A:h}"
docker compose -p dhk-paper -f compose.paper.yml up -d --wait
exec .venv/bin/python scripts/dev.py
