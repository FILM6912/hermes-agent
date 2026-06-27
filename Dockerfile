# syntax=docker/dockerfile:1

ARG HERMES_AGENT_IMAGE=nousresearch/hermes-agent:latest

FROM node:20-bookworm-slim AS frontend-build

WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
# Cache npm modules ระหว่าง build
RUN --mount=type=cache,target=/root/.npm \
    npm ci
COPY frontend/ ./
RUN npm run build

FROM ${HERMES_AGENT_IMAGE} AS hermes-agent-build

FROM python:3.12-slim

LABEL maintainer="nesquena"
LABEL description="Hermes Web UI — browser interface for Hermes Agent"

ENV DEBIAN_FRONTEND=noninteractive

# รวม apt-get เป็น RUN เดียว ลด layer และไม่ต้อง update ซ้ำ
RUN if [ "A${BUILD_APT_PROXY:-}" != "A" ]; then \
        printf 'Acquire::http::Proxy "%s";\n' "$BUILD_APT_PROXY" > /etc/apt/apt.conf.d/01proxy; \
    fi \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        apt-utils \
        ca-certificates \
        curl \
        git \
        gnupg \
        locales \
        openssh-client \
        rsync \
        wget \
        xz-utils \
        libreoffice-writer \
        libreoffice-calc \
        libreoffice-impress \
    && apt-get upgrade -y \
    && rm -rf /var/lib/apt/lists/* /etc/apt/apt.conf.d/01proxy \
    && apt-get clean

# UTF-8
RUN localedef -i en_US -c -f UTF-8 -A /usr/share/locale/locale.alias en_US.UTF-8
ENV LANG=en_US.utf8 \
    LC_ALL=C \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /apptoo

RUN groupadd -g 1024 hermeswebui \
    && useradd -u 1024 -d /home/hermeswebui -g hermeswebui -G users -s /bin/bash -m hermeswebui \
    && mkdir -p /app /uv_cache /workspace \
    && chmod 0755 /home/hermeswebui \
    && chmod 1777 /app /uv_cache /workspace
# หมายเหตุ: ลบ chown -R ออก แล้วให้ uv venv ทำ chown ครั้งเดียวตอนท้ายแทน

COPY --chmod=555 docker_init.bash /hermeswebui_init.bash
RUN touch /.within_container

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

# ติดตั้ง Python deps — layer นี้ cache ได้ตราบใดที่ requirements.txt ไม่เปลี่ยน
COPY requirements.txt /apptoo/
RUN --mount=type=cache,target=/root/.cache/uv,sharing=locked \
    uv venv /app/venv --python python3.12 \
    && uv pip install --python /app/venv/bin/python \
        -r /apptoo/requirements.txt \
        --trusted-host pypi.org --trusted-host files.pythonhosted.org \
    && touch /app/venv/.webui_python_deps_installed /app/venv/.hindsight_installed \
    && chown -R hermeswebui:hermeswebui /app

COPY --chown=root:root . /apptoo
COPY --from=frontend-build /build/static/dist /apptoo/static/dist

# Node.js runtime
COPY --from=frontend-build /usr/local/bin/node /usr/local/bin/node
COPY --from=frontend-build /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -sf ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -sf ../lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx \
    && ln -sf node /usr/local/bin/nodejs

# Bun runtime (stdio MCP servers / skills tooling)
COPY --from=oven/bun:1 /usr/local/bin/bun /usr/local/bin/bun
RUN ln -sf bun /usr/local/bin/bunx

ARG HERMES_VERSION=unknown
RUN echo "__version__ = '${HERMES_VERSION}'" > /apptoo/app/domain/_version.py \
    && md5sum /apptoo/server.py | awk '{print $1}' > /apptoo/.docker_sync_stamp.server \
    && echo "${HERMES_VERSION}-$(cat /apptoo/.docker_sync_stamp.server)" > /apptoo/.docker_sync_stamp

# Bake hermes-agent Python deps at image build time (not on every container start).
COPY --from=hermes-agent-build /opt/hermes /apptoo/hermes-agent-build/
RUN --mount=type=cache,target=/root/.cache/uv,sharing=locked \
    python /apptoo/scripts/patch_agent_skill_view_frontmatter.py /apptoo/hermes-agent-build/tools/skills_tool.py \
    && uv pip install --python /app/venv/bin/python \
        "/apptoo/hermes-agent-build[all]" \
        --trusted-host pypi.org --trusted-host files.pythonhosted.org \
    && md5sum /apptoo/hermes-agent-build/pyproject.toml | awk '{print $1}' > /app/venv/.agent_deps_fingerprint \
    && rm -rf /apptoo/hermes-agent-build \
    && touch /app/venv/.agent_deps_installed /app/venv/.deps_installed \
    && chown -R hermeswebui:hermeswebui /app

ENV HERMES_WEBUI_HOST=0.0.0.0 \
    HERMES_WEBUI_PORT=8787

EXPOSE 8787

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD curl -f http://localhost:8787/health || exit 1

USER root
CMD ["/hermeswebui_init.bash"]
