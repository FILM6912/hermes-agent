#!/usr/bin/env bash
set -euo pipefail

PATCH_SCRIPT="${HERMES_WEBUI_PATCH_DIR:-/opt/hermes-webui-patch}/patch_agent_skill_view_frontmatter.py"

# Patch hermes-agent skill_view before gateway startup (shared /opt/hermes volume).
if [ -f /opt/hermes/tools/skills_tool.py ] && [ -f "$PATCH_SCRIPT" ]; then
  python3 "$PATCH_SCRIPT" /opt/hermes/tools/skills_tool.py \
    || echo "!! WARNING: could not patch /opt/hermes/tools/skills_tool.py (continuing)"
fi

exec /init /opt/hermes/docker/main-wrapper.sh "$@"
