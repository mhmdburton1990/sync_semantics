#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

# Build frontend first
./scripts/build-frontend.sh

# Deploy via Databricks Apps CLI
databricks apps deploy databricks-to-pbi --source-dir . "$@"
