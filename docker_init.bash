#!/bin/bash

set -e

error_exit() {
  echo -n "!! ERROR: "
  echo $*
  echo "!! Exiting script (ID: $$)"
  exit 1
}

ok_exit() {
  echo $*
  echo "++ Exiting script (ID: $$)"
  exit 0
}

## Environment variables loaded when passing environment variables from user to user
# Ignore list: variables to ignore when loading environment variables from user to user
export ENV_IGNORELIST="HOME PWD USER SHLVL TERM OLDPWD SHELL _ SUDO_COMMAND HOSTNAME LOGNAME MAIL SUDO_GID SUDO_UID SUDO_USER CHECK_NV_CUDNN_VERSION VIRTUAL_ENV VIRTUAL_ENV_PROMPT ENV_IGNORELIST ENV_OBFUSCATE_PART"
# Obfuscate part: part of the key to obfuscate when loading environment variables from user to user, ex: HF_TOKEN, ...
export ENV_OBFUSCATE_PART="TOKEN API KEY"

# Check for ENV_IGNORELIST and ENV_OBFUSCATE_PART
if [ -z "${ENV_IGNORELIST+x}" ]; then error_exit "ENV_IGNORELIST not set"; fi
if [ -z "${ENV_OBFUSCATE_PART+x}" ]; then error_exit "ENV_OBFUSCATE_PART not set"; fi

# whoami fails under set -e if the UID has no /etc/passwd entry (k8s runAsUser).
whoami=$(whoami 2>/dev/null || echo "uid-$(id -u)")
script_dir=$(dirname $0)
script_name=$(basename $0)
echo ""; echo ""
echo "======================================"
echo "=================== Starting script (ID: $$)"
echo "== Running ${script_name} in ${script_dir} as ${whoami}"
script_fullname=$0
echo "  - script_fullname: ${script_fullname}"
ignore_value="VALUE_TO_IGNORE"

# Keep init scratch files private to the container user that owns them.
umask 0077

write_privtmpfile() {
  tmpfile=$1
  if [ -z "${tmpfile}" ]; then error_exit "write_privtmpfile: missing argument"; fi
  if [ -f "$tmpfile" ]; then rm -f "$tmpfile"; fi
  printf '%s' "$2" > "$tmpfile"
  chmod 600 "$tmpfile"
}

_hermes_home_base() {
  if [ -n "${HERMES_HOME:-}" ]; then
    echo "$HERMES_HOME"
  else
    echo "/home/hermeswebui/.hermes"
  fi
}

# Resolve profile-relative paths (./workspace, ./webui) against the Hermes home
# directory. Absolute paths are returned unchanged.
resolve_hermes_path() {
  local raw="$1"
  if [ -z "$raw" ]; then
    echo ""
    return
  fi
  case "$raw" in
    /*) echo "$raw" ;;
    ./*) echo "$(_hermes_home_base)/${raw#./}" ;;
    *) echo "$(_hermes_home_base)/$raw" ;;
  esac
}

_resolve_webui_path_env() {
  local key="$1"
  local current="${!key}"
  if [ -z "$current" ]; then
    return
  fi
  local resolved
  resolved="$(resolve_hermes_path "$current")"
  if [ "$resolved" != "$current" ]; then
    echo "-- Resolved $key: $current -> $resolved"
    export "$key=$resolved"
  fi
}

itdir=/tmp/hermeswebui_init
if [ ! -d "$itdir" ]; then mkdir -p "$itdir"; fi
chmod 700 "$itdir" || error_exit "Failed to secure $itdir"
if [ ! -d "$itdir" ]; then error_exit "Failed to create $itdir"; fi

# Set user and group id
# logic: if not set and file exists, use file value, else use default. Create file for persistence when the container is re-run
# reasoning: needed when using docker compose as the file will exist in the stopped container, and changing the value from environment variables or configuration file must be propagated from the root init phase to the hermeswebui runtime phase
it=$itdir/hermeswebui_user_uid
if [ -z "${WANTED_UID+x}" ]; then
  if [ -f $it ]; then WANTED_UID=$(cat $it); fi
fi
# Auto-detect from mounted volumes if still unset (#569, #668).
# On macOS, host UIDs start at 501. Using the wrong UID means the container
# user cannot read the bind-mounted files, making the workspace appear empty.
# In two-container setups (hermes-agent + hermes-webui), the shared hermes-home
# volume may be owned by the agent container's UID — detect from there first.
if [ -z "${WANTED_UID+x}" ] || [ "${WANTED_UID}" = "1024" ]; then
  # Priority 1: hermes-home shared volume — covers two-container Zeabur/Compose setups (#668)
  for _probe_dir in "/home/hermeswebui/.hermes" "$HERMES_HOME" "/opt/data"; do
    if [ -d "$_probe_dir" ]; then
      _detected_uid=$(stat -c '%u' "$_probe_dir" 2>/dev/null || echo "")
      if [ -n "$_detected_uid" ] && [ "$_detected_uid" != "0" ]; then
        echo "-- Auto-detected UID: $_detected_uid (from $_probe_dir)"
        WANTED_UID=$_detected_uid
        break
      fi
    fi
  done
fi
if [ -z "${WANTED_UID+x}" ] || [ "${WANTED_UID}" = "1024" ]; then
  # Priority 2: /workspace bind-mount — the standard single-container mount point
  if [ -d "/workspace" ]; then
    _detected_uid=$(stat -c '%u' "/workspace" 2>/dev/null || echo "")
    if [ -n "$_detected_uid" ] && [ "$_detected_uid" != "0" ]; then
      echo "-- Auto-detected workspace UID: $_detected_uid (from /workspace)"
      WANTED_UID=$_detected_uid
    fi
  fi
fi
WANTED_UID=${WANTED_UID:-1024}
write_privtmpfile $it "$WANTED_UID"
echo "-- WANTED_UID: \"${WANTED_UID}\""

it=$itdir/hermeswebui_user_gid
if [ -z "${WANTED_GID+x}" ]; then
  if [ -f $it ]; then WANTED_GID=$(cat $it); fi
fi
# Auto-detect GID from mounted volumes to match (#569, #668)
if [ -z "${WANTED_GID+x}" ] || [ "${WANTED_GID}" = "1024" ]; then
  # Priority 1: hermes-home shared volume
  for _probe_dir in "/home/hermeswebui/.hermes" "$HERMES_HOME" "/opt/data"; do
    if [ -d "$_probe_dir" ]; then
      _detected_gid=$(stat -c '%g' "$_probe_dir" 2>/dev/null || echo "")
      if [ -n "$_detected_gid" ] && [ "$_detected_gid" != "0" ]; then
        echo "-- Auto-detected GID: $_detected_gid (from $_probe_dir)"
        WANTED_GID=$_detected_gid
        break
      fi
    fi
  done
fi
if [ -z "${WANTED_GID+x}" ] || [ "${WANTED_GID}" = "1024" ]; then
  # Priority 2: /workspace bind-mount
  if [ -d "/workspace" ]; then
    _detected_gid=$(stat -c '%g' "/workspace" 2>/dev/null || echo "")
    if [ -n "$_detected_gid" ] && [ "$_detected_gid" != "0" ]; then
      echo "-- Auto-detected workspace GID: $_detected_gid (from /workspace)"
      WANTED_GID=$_detected_gid
    fi
  fi
fi
WANTED_GID=${WANTED_GID:-1024}
write_privtmpfile $it "$WANTED_GID"
echo "-- WANTED_GID: \"${WANTED_GID}\""

echo "== Most Environment variables set"

# Check user id and group id
new_gid=`id -g`
new_uid=`id -u`
echo "== user ($whoami)"
echo "  uid: $new_uid / WANTED_UID: $WANTED_UID"
echo "  gid: $new_gid / WANTED_GID: $WANTED_GID"

save_env() {
  tosave=$1
  echo "-- Saving environment variables to $tosave"
  env | sort > "$tosave"
}

load_env() {
  tocheck=$1
  overwrite_if_different=$2
  ignore_list="${ENV_IGNORELIST}"
  obfuscate_part="${ENV_OBFUSCATE_PART}"
  if [ -f "$tocheck" ]; then
    echo "-- Loading environment variables from $tocheck (overwrite existing: $overwrite_if_different) (ignorelist: $ignore_list) (obfuscate: $obfuscate_part)"
    while IFS='=' read -r key value; do
      doit=false
      # checking if the key is in the ignorelist
      for i in $ignore_list; do
        if [[ "A$key" ==  "A$i" ]]; then doit=ignore; break; fi
      done
      if [[ "A$doit" == "Aignore" ]]; then continue; fi
      rvalue=$value
      # checking if part of the key is in the obfuscate list
      doobs=false
      for i in $obfuscate_part; do
        if [[ "A$key" == *"$i"* ]]; then doobs=obfuscate; break; fi
      done
      if [[ "A$doobs" == "Aobfuscate" ]]; then rvalue="**OBFUSCATED**"; fi

      if [ -z "${!key}" ]; then
        echo "  ++ Setting environment variable $key [$rvalue]"
        doit=true
      elif [ "A$overwrite_if_different" == "Atrue" ]; then
        cvalue="${!key}"
        if [[ "A${doobs}" == "Aobfuscate" ]]; then cvalue="**OBFUSCATED**"; fi
        if [[ "A${!key}" != "A${value}" ]]; then
          echo "  @@ Overwriting environment variable $key [$cvalue] -> [$rvalue]"
          doit=true
        else
          echo "  == Environment variable $key [$rvalue] already set and value is unchanged"
        fi
      fi
      if [[ "A$doit" == "Atrue" ]]; then
        export "$key=$value"
      fi
    done < "$tocheck"
  fi
}

chown_agents_skills_bind_mount() {
  # npx skills writes to ~/.agents/skills (bind-mounted in Docker). Installs run as
  # root (e.g. `docker exec` debugging) leave root-owned trees the WebUI user cannot
  # delete. Always align this subtree even when the fast home chown path is skipped.
  local _agents_skills="/home/hermeswebui/.agents/skills"
  if [ ! -d "$_agents_skills" ]; then
    return 0
  fi
  echo "  -- Aligning npx skills bind mount ownership at ${_agents_skills}"
  find "$_agents_skills" -exec chown -h "${WANTED_UID}:${WANTED_GID}" {} + \
    2>/dev/null || echo "  !! WARNING: Could not chown all of ${_agents_skills} (continuing)"
}

chown_shared_workspace_bind_mount() {
  # Multi-user workspaces live under ~/.hermes/workspace/<account>/.uploads/.
  # Docker may create bind-mount subdirs as root; the fast home chown path only
  # checks the top-level ~/.hermes owner and skips nested root-owned trees.
  local _workspace_raw="${HERMES_WEBUI_PROFILE_WORKSPACE:-${HERMES_WEBUI_DEFAULT_WORKSPACE:-./workspace}}"
  local _workspace
  _workspace="$(resolve_hermes_path "$_workspace_raw")"
  if [ -z "$_workspace" ]; then
    _workspace="$(_hermes_home_base)/workspace"
  fi
  if [ ! -d "$_workspace" ]; then
    return 0
  fi
  echo "  -- Aligning shared workspace bind mount ownership at ${_workspace}"
  find "$_workspace" -exec chown -h "${WANTED_UID}:${WANTED_GID}" {} + \
    2>/dev/null || echo "  !! WARNING: Could not chown all of ${_workspace} (continuing)"
}


ensure_hermes_home_traversable() {
  # The bind-mounted Hermes home must be traversable by the runtime user. A
  # root-owned 0700 top-level directory blocks every API path under ~/.hermes
  # even when nested workspace trees are world-accessible.
  local _home
  _home="$(_hermes_home_base)"
  if [ ! -d "$_home" ]; then
    return 0
  fi
  echo "  -- Ensuring Hermes home entry is traversable for UID ${WANTED_UID} at ${_home}"
  chown "${WANTED_UID}:${WANTED_GID}" "$_home" 2>/dev/null     || echo "  !! WARNING: Could not chown ${_home} (continuing)"
  chmod u+rwx "$_home" 2>/dev/null     || echo "  !! WARNING: Could not chmod ${_home} (continuing)"
}

chown_home_hermeswebui() {
  # macOS Docker bind mounts can expose hermes-agent git object packs as
  # read-only host files. The runtime only needs to read those existing objects;
  # requiring chown on them makes startup fail before WebUI can run (#2237).
  #
  # Multi-container compose (#2470) additionally mounts the entire
  # hermes-agent-src volume read-only on the WebUI side because the WebUI only
  # reads it for `uv pip install`. On a :ro mount, chown returns EROFS for any
  # file inside the subtree, which would propagate to `set -e` and kill startup
  # before the WebUI can run. Either way, the WebUI never writes to the agent
  # source — prune the entire hermes-agent path from the chown walk so a
  # read-only or partially-read-only mount doesn't break the rest of the home
  # ownership alignment.
  #
  # Fast path: when bind mounts already match the aligned runtime UID/GID, skip
  # the expensive recursive walk over ~/.hermes session trees on every restart.
  local _probe="/home/hermeswebui/.hermes"
  if [ -d "$_probe" ]; then
    local _owner
    _owner=$(stat -c '%u:%g' "$_probe" 2>/dev/null || echo "")
    if [ "$_owner" = "${WANTED_UID}:${WANTED_GID}" ]; then
      echo "  -- Skipping recursive home chown — ${_probe} already ${WANTED_UID}:${WANTED_GID}"
      ensure_hermes_home_traversable
      return 0
    fi
  fi
  find /home/hermeswebui \
    -path "/home/hermeswebui/.hermes/hermes-agent" -prune \
    -o -exec chown -h "${WANTED_UID}:${WANTED_GID}" {} +
}

# The production image does not ship sudo. The entrypoint starts as root only
# long enough to align the hermeswebui UID/GID with mounted volumes, prepare
# root-owned paths, and then drop privileges for the server process.
if [ "A${whoami}" == "Aroot" ]; then
  echo "-- Running as root for one-time container init; will switch to hermeswebui"

  # We are altering the UID/GID of the hermeswebui user to the desired ones and restarting as that user
  # using usermod for the already created hermeswebui user, knowing it is not already in use
  # per usermod manual: "You must make certain that the named user is not executing any processes when this command is being executed"
  # Guard for read-only root filesystem (podman with read_only=true, issue #1470).
  _readonly_root=false
  if ! sh -c 'test -w /etc/group && test -w /etc/passwd' 2>/dev/null; then
    _readonly_root=true
    echo "  !! Detected read-only root filesystem — /etc/group or /etc/passwd is not writable"
  fi
  if [ "A${_readonly_root}" == "Atrue" ]; then
    _current_hermeswebui_gid=$(id -g hermeswebui 2>/dev/null || echo "")
    _current_hermeswebui_uid=$(id -u hermeswebui 2>/dev/null || echo "")
    if [ "A${_current_hermeswebui_gid}" == "A${WANTED_GID}" ] && [ "A${_current_hermeswebui_uid}" == "A${WANTED_UID}" ]; then
      echo "  -- Skipping groupmod/usermod — hermeswebui already has UID ${WANTED_UID} GID ${WANTED_GID} and root fs is read-only"
    else
      error_exit "Cannot modify /etc/group or /etc/passwd (read-only root fs). Set UID=${_current_hermeswebui_uid} and GID=${_current_hermeswebui_gid} to match, or run without read_only=true. See issue #1470."
    fi
  else
    groupmod -o -g "${WANTED_GID}" hermeswebui || error_exit "Failed to set GID of hermeswebui user"
    usermod -o -u "${WANTED_UID}" hermeswebui || error_exit "Failed to set UID of hermeswebui user"
  fi

  ensure_hermes_home_traversable
  chown_home_hermeswebui || error_exit "Failed to set owner of /home/hermeswebui"
  ensure_hermes_home_traversable
  chown_agents_skills_bind_mount
  _resolve_webui_path_env HERMES_WEBUI_DEFAULT_WORKSPACE
  _resolve_webui_path_env HERMES_WEBUI_PROFILE_WORKSPACE
  chown_shared_workspace_bind_mount

  _resolve_webui_path_env HERMES_WEBUI_STATE_DIR
  _resolve_webui_path_env HERMES_WEBUI_DEFAULT_WORKSPACE

  echo ""; echo "-- Preparing /app for the hermeswebui runtime user"
  mkdir -p /app || error_exit "Failed to create /app directory"
  chown hermeswebui:hermeswebui /app || error_exit "Failed to set owner of /app to hermeswebui user"
  _sync_stamp=""
  if [ -f /apptoo/.docker_sync_stamp ]; then
    _sync_stamp=$(cat /apptoo/.docker_sync_stamp)
  fi
  _app_synced=""
  if [ -f /app/.docker_sync_stamp ]; then
    _app_synced=$(cat /app/.docker_sync_stamp)
  fi
  if [ -n "$_sync_stamp" ] && [ "$_sync_stamp" = "$_app_synced" ] && [ -f /app/server.py ]; then
    echo "  -- Skipping /apptoo -> /app rsync (sync stamp matches: $_sync_stamp)"
  else
    rsync -av --chown=hermeswebui:hermeswebui /apptoo/ /app/ || error_exit "Failed to sync /apptoo to /app with correct ownership"
    if [ -n "$_sync_stamp" ]; then
      echo "$_sync_stamp" > /app/.docker_sync_stamp
      chown hermeswebui:hermeswebui /app/.docker_sync_stamp || error_exit "Failed to set owner of /app/.docker_sync_stamp"
    fi
  fi
  # Image-baked /app/venv is owned by the build-time UID (1024). usermod above
  # remaps hermeswebui to WANTED_UID — re-align venv ownership so uv pip can
  # upgrade packages when installing hermes-agent deps.
  if [ -d /app/venv ]; then
    echo "  -- Aligning /app/venv ownership after UID/GID remap"
    chown -R hermeswebui:hermeswebui /app/venv || error_exit "Failed to chown /app/venv for hermeswebui"
  fi

  if [ -z "${HERMES_WEBUI_DEFAULT_WORKSPACE+x}" ]; then export HERMES_WEBUI_DEFAULT_WORKSPACE="/workspace"; fi
  if [ ! -d "$HERMES_WEBUI_DEFAULT_WORKSPACE" ]; then
    mkdir -p "$HERMES_WEBUI_DEFAULT_WORKSPACE" || error_exit "Failed to create default workspace at $HERMES_WEBUI_DEFAULT_WORKSPACE"
  fi
  if [ ! -d "$HERMES_WEBUI_DEFAULT_WORKSPACE" ]; then error_exit "HERMES_WEBUI_DEFAULT_WORKSPACE directory does not exist at $HERMES_WEBUI_DEFAULT_WORKSPACE"; fi
  chown hermeswebui:hermeswebui "$HERMES_WEBUI_DEFAULT_WORKSPACE" 2>/dev/null || echo "!! WARNING: Could not chown $HERMES_WEBUI_DEFAULT_WORKSPACE (continuing)"

  if [ -n "${HERMES_WEBUI_STATE_DIR:-}" ]; then
    if [ ! -d "$HERMES_WEBUI_STATE_DIR" ]; then
      mkdir -p "$HERMES_WEBUI_STATE_DIR" || error_exit "Failed to create state directory at $HERMES_WEBUI_STATE_DIR"
    fi
    chown hermeswebui:hermeswebui "$HERMES_WEBUI_STATE_DIR" 2>/dev/null || echo "!! WARNING: Could not chown $HERMES_WEBUI_STATE_DIR (continuing)"
  fi

  export UV_CACHE_DIR=${UV_CACHE_DIR:-/uv_cache}
  mkdir -p "${UV_CACHE_DIR}" || error_exit "Failed to create ${UV_CACHE_DIR} directory"
  chown -R hermeswebui:hermeswebui "${UV_CACHE_DIR}" || error_exit "Failed to set owner of ${UV_CACHE_DIR} to hermeswebui user"

  chown -R "${WANTED_UID}:${WANTED_GID}" "$itdir" || error_exit "Failed to set owner of $itdir"
  # Issue #2010 — Railway / user-namespaced runtimes: in-container UID 0 may map
  # to a host UID outside the writable subuid range, so /tmp writes fail despite
  # id -u == 0. Probe writability and fall back through $itdir → /app.
  ENV_FILE="/tmp/hermeswebui_root_env.txt"
  if ! ( : > "$ENV_FILE" ) 2>/dev/null; then
    ENV_FILE="${itdir:-/tmp/hermeswebui_init}/hermeswebui_root_env.txt"
    mkdir -p "$(dirname "$ENV_FILE")" 2>/dev/null
    if ! ( : > "$ENV_FILE" ) 2>/dev/null; then
      ENV_FILE="/app/.hermeswebui_root_env"
    fi
    echo "  !! /tmp not writable by root — falling back to $ENV_FILE (user-namespaced runtime?)"
  fi
  save_env "$ENV_FILE"
  chown "${WANTED_UID}:${WANTED_GID}" "$ENV_FILE" || error_exit "Failed to set owner of $ENV_FILE"
  chmod 600 "$ENV_FILE" || error_exit "Failed to secure $ENV_FILE"
  export _HW_ROOT_ENV_PATH="$ENV_FILE"

  # restart the script as hermeswebui set with the correct UID/GID this time
  echo "-- Restarting as hermeswebui user with UID ${WANTED_UID} GID ${WANTED_GID}"
  exec su -s /bin/bash -c "exec \"${script_fullname}\"" hermeswebui || error_exit "subscript failed"
fi

# If we are here, the script is started as an unprivileged runtime user.
# Because the whoami value for the hermeswebui user can be any existing user, we cannot check against it;
# instead we check if the UID/GID are the expected ones.
if [ "$WANTED_GID" != "$new_gid" ]; then error_exit "hermeswebui MUST be running as UID ${WANTED_UID} GID ${WANTED_GID}, current UID ${new_uid} GID ${new_gid}"; fi
if [ "$WANTED_UID" != "$new_uid" ]; then error_exit "hermeswebui MUST be running as UID ${WANTED_UID} GID ${WANTED_GID}, current UID ${new_uid} GID ${new_gid}"; fi

########## 'hermeswebui' specific section below

# We are therefore running as hermeswebui
echo ""; echo "== Running as hermeswebui"

# Load environment variables one by one if they do not exist from the root init phase
tmp_root_env="${_HW_ROOT_ENV_PATH:-/tmp/hermeswebui_root_env.txt}"
if [ -f $tmp_root_env ]; then
  echo "-- Loading not already set environment variables from $tmp_root_env"
  load_env $tmp_root_env true
fi

##
if [ ! -f /app/server.py ] && [ -d /apptoo ]; then
  echo ""; echo "-- Seeding /app from /apptoo (rootless startup)"
  cp -a /apptoo/. /app/ || error_exit "Failed to seed /app from /apptoo (is /app writable by the runtime user?)"
fi

echo ""; echo "-- Verifying /app is writable by the hermeswebui runtime user"
if [ ! -d /app ]; then error_exit "/app directory does not exist"; fi
it=/app/.testfile; touch $it || error_exit "Failed to verify /app directory"
rm -f $it || error_exit "Failed to delete test file in /app"

######## Environment variables (consume AFTER the load_env)

_resolve_webui_path_env HERMES_WEBUI_STATE_DIR
_resolve_webui_path_env HERMES_WEBUI_DEFAULT_WORKSPACE

echo ""; echo "== Checking required environment variables for hermes-webui"

echo ""; echo "-- HERMES_WEBUI_STATE_DIR: Where to store sessions, workspaces, and other state (default: ~/.hermes/webui)"
if [ -z "${HERMES_WEBUI_STATE_DIR+x}" ]; then error_exit "HERMES_WEBUI_STATE_DIR not set"; fi; 
echo "-- HERMES_WEBUI_STATE_DIR: $HERMES_WEBUI_STATE_DIR"
if [ ! -d "$HERMES_WEBUI_STATE_DIR" ]; then mkdir -p $HERMES_WEBUI_STATE_DIR || error_exit "Failed to create state directory at $HERMES_WEBUI_STATE_DIR"; fi
if [ ! -d "$HERMES_WEBUI_STATE_DIR" ]; then error_exit "HERMES_WEBUI_STATE_DIR directory does not exist at $HERMES_WEBUI_STATE_DIR"; fi
it="$HERMES_WEBUI_STATE_DIR/.testfile"; touch $it || error_exit "Failed to verify state directory at $HERMES_WEBUI_STATE_DIR"
rm -f $it || error_exit "Failed to delete test file in $HERMES_WEBUI_STATE_DIR"

echo ""; echo "-- HERMES_WEBUI_DEFAULT_WORKSPACE: Default workspace directory shown on first launch"
if [ -z "${HERMES_WEBUI_DEFAULT_WORKSPACE+x}" ]; then echo "HERMES_WEBUI_DEFAULT_WORKSPACE not set, setting to /workspace"; export HERMES_WEBUI_DEFAULT_WORKSPACE="/workspace"; fi;
echo "-- HERMES_WEBUI_DEFAULT_WORKSPACE: $HERMES_WEBUI_DEFAULT_WORKSPACE"
# The root init phase creates/chowns missing bind-mount directories before
# dropping privileges. After that, the runtime user only verifies access.
if [ ! -d "$HERMES_WEBUI_DEFAULT_WORKSPACE" ]; then
  mkdir -p "$HERMES_WEBUI_DEFAULT_WORKSPACE" || error_exit "Failed to create default workspace at $HERMES_WEBUI_DEFAULT_WORKSPACE"
fi
if [ ! -d "$HERMES_WEBUI_DEFAULT_WORKSPACE" ]; then error_exit "HERMES_WEBUI_DEFAULT_WORKSPACE directory does not exist at $HERMES_WEBUI_DEFAULT_WORKSPACE"; fi
# Only write-test if the workspace is writable. Read-only bind-mounts (:ro)
# are valid — the workspace is used for browsing, not writing by the server.
if [ -w "$HERMES_WEBUI_DEFAULT_WORKSPACE" ]; then
  it="$HERMES_WEBUI_DEFAULT_WORKSPACE/.testfile"; touch $it && rm -f $it || echo "!! WARNING: Could not write to $HERMES_WEBUI_DEFAULT_WORKSPACE (continuing)"
else
  echo "-- HERMES_WEBUI_DEFAULT_WORKSPACE is read-only — skipping write check (read-only workspace is supported)"
fi

echo ""; echo "==================="
echo ""; echo "== Installing uv and creating a new virtual environment for hermes-webui"

export PATH="/home/hermeswebui/.local/bin/:$PATH"
if command -v uv &>/dev/null; then
  echo "-- uv already installed ($(uv --version)), skipping download"
else
  echo "-- uv not found, downloading..."
  curl -LsSf https://astral.sh/uv/install.sh | sh || error_exit "Failed to install uv — check network connectivity"
fi
export UV_PROJECT_ENVIRONMENT=venv

export UV_CACHE_DIR=${UV_CACHE_DIR:-/uv_cache}
mkdir -p "${UV_CACHE_DIR}" || error_exit "Failed to create ${UV_CACHE_DIR} directory"
if [ ! -w "${UV_CACHE_DIR}" ]; then
  _uv_fallback="/home/hermeswebui/.cache/uv"
  mkdir -p "${_uv_fallback}" || error_exit "Failed to create ${_uv_fallback} directory"
  echo "-- ${UV_CACHE_DIR} not writable; using ${_uv_fallback} for uv cache"
  export UV_CACHE_DIR="${_uv_fallback}"
fi
test -w "${UV_CACHE_DIR}" || error_exit "${UV_CACHE_DIR} is not writable by hermeswebui"

cd /app
if [ -f /app/venv/bin/python3 ]; then
  echo ""; echo "== Existing virtual environment found — reusing (fast restart)"
else
  echo ""; echo "== Creating new virtual environment"
  uv venv venv
fi
export VIRTUAL_ENV=/app/venv
export HERMES_WEBUI_VIRTUAL_ENV=/app/venv
test -d /app/venv
test -f /app/venv/bin/activate

repair_agent_venv_python() {
  local venv_bin="/home/hermeswebui/.hermes/hermes-agent/.venv/bin"
  if [ ! -d "$venv_bin" ]; then
    return 0
  fi
  if "$venv_bin/python3" -c "import sys" >/dev/null 2>&1; then
    return 0
  fi
  # Two-container compose mounts hermes-agent read-only; repair is impossible and
  # unnecessary — WebUI runs from /app/venv (HERMES_WEBUI_VIRTUAL_ENV).
  if [ ! -w "$venv_bin" ]; then
    echo "-- Skipping hermes-agent .venv python repair (read-only mount; WebUI uses /app/venv)"
    return 0
  fi
  local py
  py="$(command -v python3)"
  if [ -z "$py" ]; then
    echo "!! WARNING: hermes-agent .venv python is broken and python3 was not found"
    return 0
  fi
  echo "-- Repairing broken hermes-agent .venv python symlink -> $py"
  ln -sf "$py" "$venv_bin/python" || {
    echo "!! WARNING: could not repair hermes-agent .venv python symlink (continuing)"
    return 0
  }
  ln -sf python "$venv_bin/python3" || true
  ln -sf python "$venv_bin/python3.13" 2>/dev/null || true
}
repair_agent_venv_python

echo "";echo "== Activating hermes webui's virtual environment"
source /app/venv/bin/activate || error_exit "Failed to activate hermeswebui virtual environment"
test -x /app/venv/bin/python3

ensure_hindsight_client_docker_dependency() {
  # Keep this outside the .deps_installed fast-restart guard so existing
  # two-container Docker venvs self-heal after this dependency was added.
  _hindsight_client_requirement="hindsight-client>=0.4.22"
  if [ -f /app/venv/.hindsight_installed ]; then
    echo "-- hindsight-client already verified (fast restart)"
    return 0
  fi
  echo ""; echo "== Checking Hindsight memory provider dependency"
  if uv pip show hindsight-client >/dev/null 2>&1; then
    echo "-- hindsight-client already installed"
  else
    echo "-- Installing ${_hindsight_client_requirement} for Hindsight memory provider support"
    uv pip install "${_hindsight_client_requirement}" --trusted-host pypi.org --trusted-host files.pythonhosted.org || error_exit "Failed to install hindsight-client"
  fi
  touch /app/venv/.hindsight_installed
}

install_webui_and_document_api_deps() {
  if [ -f /app/venv/.webui_python_deps_installed ]; then
    echo ""; echo "== WebUI + document API Python deps pre-installed in image — skipping"
    return 0
  fi
  echo ""; echo "== Installing hermes-webui dependencies"
  uv pip install --python /app/venv/bin/python \
    -r requirements.txt \
    --trusted-host pypi.org --trusted-host files.pythonhosted.org \
    || error_exit "Failed to install WebUI requirements"
  touch /app/venv/.webui_python_deps_installed
}

maybe_warn_agent_deps_drift() {
  if [ ! -f /app/venv/.agent_deps_fingerprint ]; then
    return 0
  fi
  _agent_paths=(
    "/home/hermeswebui/.hermes/hermes-agent"
    "/opt/hermes"
  )
  _baked_fp="$(cat /app/venv/.agent_deps_fingerprint)"
  for _p in "${_agent_paths[@]}"; do
    if [ -f "$_p/pyproject.toml" ]; then
      _live_fp="$(md5sum "$_p/pyproject.toml" | awk '{print $1}')"
      if [ "$_live_fp" != "$_baked_fp" ]; then
        echo ""
        echo "!! WARNING: mounted hermes-agent pyproject.toml differs from image-baked Python deps."
        echo "!!   Rebuild the WebUI image, or set HERMES_WEBUI_REINSTALL_AGENT_DEPS=1 to reinstall at startup."
        echo ""
      fi
      return 0
    fi
  done
}

install_agent_pyproject_deps() {
  echo ""; echo "== Adding hermes-agent's pyproject.toml base dependencies to the virtual environment"
  _agent_paths=(
    "/home/hermeswebui/.hermes/hermes-agent"
    "/opt/hermes"
  )
  _agent_src=""
  for _p in "${_agent_paths[@]}"; do
    if [ -d "$_p" ] && [ -f "$_p/pyproject.toml" ]; then
      _agent_src="$_p"
      break
    fi
  done
  if [ -n "$_agent_src" ]; then
    if [ -w "$_agent_src" ]; then
      echo ""
      echo "!! WARNING: hermes-agent source mount is writable from the WebUI container."
      echo "!!   Path: $_agent_src"
      echo "!! The multi-container compose defaults use a read-only mount for defence-in-depth."
      echo "!! If this is not an intentional local development checkout, switch the WebUI"
      echo "!! agent source volume/bind mount to read-only. See docs/rfcs/agent-source-boundary.md."
      echo ""
    fi
    # The agent source can be mounted read-only (see docker-compose.two-container.yml
    # / docker-compose.three-container.yml — the WebUI only reads this volume to
    # install the agent's Python dependencies and never writes to it). setuptools'
    # `egg_info` build step, however, touches `hermes_agent.egg-info/` inside the
    # source tree even under PEP 517 build isolation, which `EROFS`-fails on a
    # `:ro` mount and (under `set -e`) kills startup of every multi-container
    # deploy. Stage the source into a writable tmpfs copy so the build can write
    # its metadata side-by-side without touching the underlying mount.
    #
    # The copy excludes any pre-baked `*.egg-info` / `build` / `dist` artifacts
    # to avoid the timestamp-update path setuptools takes when one is present,
    # and `--reflink=auto` makes the copy near-free on overlay2/btrfs where
    # supported. Runtime installs are skipped when the image already baked
    # agent deps (see Dockerfile); this path remains for legacy venvs and when
    # HERMES_WEBUI_REINSTALL_AGENT_DEPS=1 is set.
    _stage_src="/tmp/hermes-agent-build"
    rm -rf "$_stage_src"
    mkdir -p "$_stage_src"
    if command -v rsync >/dev/null 2>&1; then
      rsync -a \
        --exclude='*.egg-info' --exclude='build' --exclude='dist' \
        --exclude='__pycache__' --exclude='.git' \
        "$_agent_src"/ "$_stage_src"/ \
        || error_exit "Failed to stage hermes-agent source to writable build dir"
    else
      # Fallback when rsync isn't in the image — straight cp -a, then drop
      # the build artifacts that would trip setuptools.
      cp -a "$_agent_src"/. "$_stage_src"/ \
        || error_exit "Failed to copy hermes-agent source to writable build dir"
      rm -rf "$_stage_src"/*.egg-info "$_stage_src"/build "$_stage_src"/dist 2>/dev/null || true
      find "$_stage_src" -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
    fi
    if [ -f /apptoo/scripts/patch_agent_skill_view_frontmatter.py ] \
        && [ -f "$_stage_src/tools/skills_tool.py" ]; then
      echo "  -- Patching hermes-agent skill_view frontmatter lookup"
      python /apptoo/scripts/patch_agent_skill_view_frontmatter.py "$_stage_src/tools/skills_tool.py" \
        || echo "  !! WARNING: Could not patch staged hermes-agent skills_tool.py (continuing)"
    fi
    uv pip install "$_stage_src[all]" --trusted-host pypi.org --trusted-host files.pythonhosted.org \
      || error_exit "Failed to install hermes-agent's requirements"
    if [ -f "$_stage_src/pyproject.toml" ]; then
      md5sum "$_stage_src/pyproject.toml" | awk '{print $1}' > /app/venv/.agent_deps_fingerprint
    fi
    rm -rf "$_stage_src"
  else
    echo ""
    echo "!! WARNING: hermes-agent source not found."
    echo "!!   Looked in: ${_agent_paths[0]}"
    echo "!!              ${_agent_paths[1]}"
    echo "!! The WebUI will start with reduced functionality (no model auto-detection,"
    echo "!! no personality routing, no CLI session imports)."
    echo "!! To fix: mount the agent source volume into the container:"
    echo "!!   -v /path/to/hermes-agent:/home/hermeswebui/.hermes/hermes-agent"
    echo "!! Or see the two-container compose example:"
    echo "!!   https://github.com/nesquena/hermes-webui/blob/master/docker-compose.two-container.yml"
    echo ""
  fi
  touch /app/venv/.agent_deps_installed
}

if [ "${HERMES_WEBUI_REINSTALL_AGENT_DEPS:-0}" = "1" ]; then
  echo ""; echo "== HERMES_WEBUI_REINSTALL_AGENT_DEPS=1 — forcing hermes-agent dependency reinstall"
  rm -f /app/venv/.agent_deps_installed /app/venv/.deps_installed
fi

if [ -f /app/venv/.deps_installed ]; then
  echo ""; echo "== Dependencies already installed — skipping (fast restart)"
  maybe_warn_agent_deps_drift
else
  install_webui_and_document_api_deps
  if [ -f /app/venv/.agent_deps_installed ]; then
    echo ""; echo "== hermes-agent Python deps pre-installed in image — skipping"
  else
    install_agent_pyproject_deps
  fi
  touch /app/venv/.deps_installed
fi

ensure_hindsight_client_docker_dependency

echo ""; echo "== Multi-user admin bootstrap (if configured)"
if [ -f /app/app/domain/users.py ]; then
  python -c "
from app.domain.users import bootstrap_default_admin
bootstrap_default_admin()
" || error_exit "Multi-user admin bootstrap failed"
else
  echo "-- Skipping multi-user bootstrap (users module not present)"
fi

echo ""; echo "== Running hermes-webui"
cd /app
_webui_host="${HERMES_WEBUI_HOST:-0.0.0.0}"
_webui_port="${HERMES_WEBUI_PORT:-8787}"
if [ -f /app/app/main.py ]; then
  python -m uvicorn app.main:app --host "${_webui_host}" --port "${_webui_port}" --log-level warning \
    || error_exit "hermes-webui failed or exited with an error"
else
  python server.py || error_exit "hermes-webui failed or exited with an error"
fi

# we should never be here because the server should be running indefinitely, but if we are, we exit safely
ok_exit "Clean exit"
