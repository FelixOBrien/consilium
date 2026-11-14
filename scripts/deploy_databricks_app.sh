#!/usr/bin/env bash
# Stage the App, sync it to the workspace, and deploy.  # pragma: allowlist secret
#
# Refuses to run unless CONSILIUM_DEPLOY_DATABRICKS=1. Do not deploy until  # pragma: allowlist secret
# SKO-280 has loaded real cohort data into the Volume and Lakebase. A laptop
# run remains the demo path until that load exists.
#
# Apps stop 24 hours after start or redeploy. Restart on Sunday morning
# before judging (`databricks apps start <name>`).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ "${CONSILIUM_DEPLOY_DATABRICKS:-}" != "1" ]]; then  # pragma: allowlist secret
  cat >&2 <<'EOF'
Refusing to deploy. Set CONSILIUM_DEPLOY_DATABRICKS=1 when SKO-280 has loaded  # pragma: allowlist secret
real data and the App resources below are attached.

Sunday morning: Apps stop 24 hours after start or redeploy. Run
`databricks apps start <name>` before judging.

Attach these resource keys on the App before the first deploy:
  volume              Unity Catalog volume (/Volumes/.../raw)
  postgres            Lakebase database
  database-url        secret, postgresql URL with sslmode=require
  anthropic-api-key   secret
  hf-token            secret
EOF
  exit 1
fi

if [[ -n "${DATABRICKS_HOST:-}" ]]; then
  # Clients and the CLI join API paths onto this host. A trailing slash breaks that.
  export DATABRICKS_HOST="${DATABRICKS_HOST%/}"
fi

: "${DATABRICKS_APP_SOURCE:?Set DATABRICKS_APP_SOURCE to a workspace directory, for example /Workspace/Users/you@example.com/consilium-app}"  # pragma: allowlist secret

APP_NAME="${DATABRICKS_APP_NAME:-consilium}"  # pragma: allowlist secret
STAGE="${CONSILIUM_APP_STAGE:-$ROOT/build/databricks-app}"  # pragma: allowlist secret

if ! command -v databricks >/dev/null 2>&1; then
  echo "databricks CLI is not on PATH." >&2
  exit 1
fi

"$ROOT/scripts/stage_databricks_app.sh"

databricks sync "$STAGE" "$DATABRICKS_APP_SOURCE"
databricks apps deploy "$APP_NAME" \
  --source-code-path "$DATABRICKS_APP_SOURCE" \
  --mode SNAPSHOT

echo "Deployed $APP_NAME from $DATABRICKS_APP_SOURCE"
echo "Restart reminder: databricks apps start $APP_NAME"
