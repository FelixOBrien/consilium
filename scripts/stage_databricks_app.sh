#!/usr/bin/env bash
# Build the SvelteKit app and stage a Databricks App source tree.
# Idempotent: the staging directory is replaced on every run.
# Nothing under build/ is committed.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STAGE="${CONSILIUM_APP_STAGE:-$ROOT/build/databricks-app}"  # pragma: allowlist secret
WEB_BUILD="$ROOT/typescript/apps/web/build"

cd "$ROOT/typescript"
bun install --frozen-lockfile
bun run --filter web build

if [[ ! -f "$WEB_BUILD/index.html" ]]; then
  echo "web build did not produce index.html at $WEB_BUILD" >&2
  exit 1
fi

rm -rf "$STAGE"
mkdir -p "$STAGE/src" "$STAGE/static_web"
cp -a "$ROOT/python/src/consilium" "$STAGE/src/consilium"  # pragma: allowlist secret
cp "$ROOT/python/pyproject.toml" "$STAGE/pyproject.toml"
cp "$ROOT/python/uv.lock" "$STAGE/uv.lock"
cp "$ROOT/python/README.md" "$STAGE/README.md"
cp "$ROOT/python/databricks/app.yaml" "$STAGE/app.yaml"
cp -a "$WEB_BUILD/." "$STAGE/static_web/"

find "$STAGE" -type d -name '__pycache__' -prune -exec rm -rf {} +
find "$STAGE" -type f \( -name '*.pyc' -o -name '.env' -o -name '.env.*' \) -delete

python3 - "$STAGE/pyproject.toml" <<'PY'
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
old = 'default-groups = ["dev"]'
new = 'default-groups = ["pipeline"]'
if old not in text:
    raise SystemExit(f"{path} is missing the dev default-groups marker")
path.write_text(text.replace(old, new, 1), encoding="utf-8")
PY

# Query-time CONCH-Z text and bge-small live in the pipeline group. `uv sync`
# on the App installs default-groups, so the staged lock records pipeline.
# requirements.txt is intentionally absent so the App installs with uv.
(cd "$STAGE" && uv lock)

too_big="$(find "$STAGE" -type f -size +10M -print || true)"
if [[ -n "$too_big" ]]; then
  echo "Databricks Apps reject a source file over 10 MB:" >&2
  printf '%s\n' "$too_big" >&2
  exit 1
fi

static_bytes="$(du -sb "$STAGE/static_web" | awk '{print $1}')"
stage_bytes="$(du -sb "$STAGE" | awk '{print $1}')"
echo "Staged Databricks App: $STAGE"
echo "Static build bytes: $static_bytes"
echo "Stage bytes: $stage_bytes"
