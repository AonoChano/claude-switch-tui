#!/bin/sh
set -eu

INSTALL_DIR="${HOME}/.claude/scripts/claude-switch-tui"
NO_PATH=0
SKIP_PIP=0
NO_LEGACY_CLEANUP=0
RESET_VENV=0
DRY_RUN=0

while [ "$#" -gt 0 ]; do
    case "$1" in
        --install-dir|--InstallDir|-InstallDir)
            shift
            [ "$#" -gt 0 ] || { echo "[csw] Missing value for --install-dir" >&2; exit 2; }
            INSTALL_DIR="$1"
            ;;
        --install-dir=*)
            INSTALL_DIR="${1#*=}"
            ;;
        --no-path|--NoPath|-NoPath)
            NO_PATH=1
            ;;
        --skip-pip|--SkipPip|-SkipPip)
            SKIP_PIP=1
            ;;
        --no-legacy-cleanup|--NoLegacyCleanup|-NoLegacyCleanup)
            NO_LEGACY_CLEANUP=1
            ;;
        --reset-venv|--ResetVenv|-ResetVenv)
            RESET_VENV=1
            ;;
        --dry-run|--DryRun|-DryRun)
            DRY_RUN=1
            ;;
        *)
            echo "[csw] Unknown option: $1" >&2
            exit 2
            ;;
    esac
    shift
done

SOURCE_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
VENV_DIR="${INSTALL_DIR}/.venv"
VENV_PYTHON="${VENV_DIR}/bin/python"

log() {
    printf '[csw] %s\n' "$*"
}

run_step() {
    message="$1"
    shift
    log "$message"
    if [ "$DRY_RUN" -eq 0 ]; then
        "$@"
    fi
}

copy_file_if_exists() {
    src="$1"
    dest="$2"
    if [ -f "$src" ]; then
        cp -f "$src" "$dest"
    fi
}

remove_local_venv() {
    [ -d "$VENV_DIR" ] || return 0
    install_abs=$(cd "$INSTALL_DIR" 2>/dev/null && pwd -P || printf '%s' "$INSTALL_DIR")
    venv_parent=$(cd "$(dirname "$VENV_DIR")" 2>/dev/null && pwd -P || printf '')
    if [ "$venv_parent" != "$install_abs" ]; then
        echo "[csw] Refusing to remove venv outside install directory: $VENV_DIR" >&2
        exit 1
    fi
    rm -rf "$VENV_DIR"
}

remove_launchers() {
    for name in csw claude-sw; do
        path="${INSTALL_DIR}/${name}"
        [ -e "$path" ] || continue
        rm -f "$path"
    done
}

python_ok() {
    py="$1"
    "$py" -c 'import sys, venv; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1
}

create_venv() {
    candidates=""
    for py in python3 python; do
        if command -v "$py" >/dev/null 2>&1; then
            path=$(command -v "$py")
            case ":$candidates:" in
                *":$path:"*) ;;
                *) candidates="${candidates}${candidates:+:}${path}" ;;
            esac
        fi
    done

    usable=""
    old_ifs=$IFS
    IFS=:
    for py in $candidates; do
        if python_ok "$py"; then
            usable="${usable}${usable:+:}${py}"
        fi
    done
    IFS=$old_ifs

    if [ -z "$usable" ]; then
        detected=${candidates:-none}
        cat >&2 <<EOF
[csw] Python 3.10+ with venv support was not found.
[csw] Detected Python commands: $detected
[csw] Debian/Raspberry Pi OS: sudo apt install python3 python3-venv
[csw] macOS: install Python 3.10+ from python.org or Homebrew.
[csw] Then open a new terminal and rerun the installer.
EOF
        exit 1
    fi

    attempts=""
    old_ifs=$IFS
    IFS=:
    for py in $usable; do
        log "Trying Python: $py"
        remove_local_venv
        output=$("$py" -m venv "$VENV_DIR" 2>&1) && status=0 || status=$?
        if [ "$status" -eq 0 ] && [ -x "$VENV_PYTHON" ]; then
            IFS=$old_ifs
            return 0
        fi
        first_lines=$(printf '%s' "$output" | sed -n '1,3p' | tr '\n' ' ')
        attempts="${attempts}${attempts:+ | }${py} -> exit ${status}; ${first_lines}"
    done
    IFS=$old_ifs

    remove_local_venv
    cat >&2 <<EOF
[csw] Could not create ClaudeSwitch local virtual environment.
[csw] Tried: $attempts
[csw] Debian/Raspberry Pi OS often needs: sudo apt install python3-venv
EOF
    exit 1
}

copy_application_files() {
    mkdir -p "$INSTALL_DIR"
    copy_file_if_exists "${SOURCE_ROOT}/claude_switch.py" "${INSTALL_DIR}/claude_switch.py"
    copy_file_if_exists "${SOURCE_ROOT}/requirements.txt" "${INSTALL_DIR}/requirements.txt"
    copy_file_if_exists "${SOURCE_ROOT}/VERSION" "${INSTALL_DIR}/VERSION"
    copy_file_if_exists "${SOURCE_ROOT}/install.sh" "${INSTALL_DIR}/install.sh"
    copy_file_if_exists "${SOURCE_ROOT}/uninstall.sh" "${INSTALL_DIR}/uninstall.sh"
    copy_file_if_exists "${SOURCE_ROOT}/bootstrap.sh" "${INSTALL_DIR}/bootstrap.sh"
    copy_file_if_exists "${SOURCE_ROOT}/install.ps1" "${INSTALL_DIR}/install.ps1"
    copy_file_if_exists "${SOURCE_ROOT}/uninstall.ps1" "${INSTALL_DIR}/uninstall.ps1"
    copy_file_if_exists "${SOURCE_ROOT}/bootstrap.ps1" "${INSTALL_DIR}/bootstrap.ps1"
    if [ -d "${SOURCE_ROOT}/locales" ]; then
        rm -rf "${INSTALL_DIR}/locales"
        mkdir -p "${INSTALL_DIR}/locales"
        cp -R "${SOURCE_ROOT}/locales/." "${INSTALL_DIR}/locales/"
    fi
}

prepare_venv() {
    if [ "$RESET_VENV" -eq 1 ]; then
        remove_local_venv
    fi
    if [ ! -x "$VENV_PYTHON" ]; then
        remove_launchers
        create_venv
    else
        log "Reusing existing virtual environment: $VENV_DIR"
    fi
}

install_dependencies() {
    "$VENV_PYTHON" -m pip install --upgrade pip
    "$VENV_PYTHON" -m pip install -r "${INSTALL_DIR}/requirements.txt"
}

write_launchers() {
    cat > "${INSTALL_DIR}/csw" <<'EOF'
#!/bin/sh
CSW_HOME=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec "$CSW_HOME/.venv/bin/python" "$CSW_HOME/claude_switch.py" "$@"
EOF
    cat > "${INSTALL_DIR}/claude-sw" <<'EOF'
#!/bin/sh
CSW_HOME=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec "$CSW_HOME/.venv/bin/python" "$CSW_HOME/claude_switch.py" "$@"
EOF
    chmod +x "${INSTALL_DIR}/csw" "${INSTALL_DIR}/claude-sw"
}

remove_managed_block() {
    file="$1"
    [ -f "$file" ] || return 0
    tmp="${file}.csw-tmp"
    awk '
        /# >>> ClaudeSwitch managed block >>>/ { skip=1; next }
        /# <<< ClaudeSwitch managed block <<</ { skip=0; next }
        !skip { print }
    ' "$file" > "$tmp"
    mv "$tmp" "$file"
}

append_path_block() {
    file="$1"
    mkdir -p "$(dirname "$file")"
    [ -f "$file" ] || touch "$file"
    remove_managed_block "$file"
    quoted=$(printf "%s" "$INSTALL_DIR" | sed "s/'/'\\\\''/g")
    cat >> "$file" <<EOF

# >>> ClaudeSwitch managed block >>>
CSW_INSTALL_DIR='$quoted'
case ":\$PATH:" in
    *":\$CSW_INSTALL_DIR:"*) ;;
    *) export PATH="\$CSW_INSTALL_DIR:\$PATH" ;;
esac
# <<< ClaudeSwitch managed block <<<
EOF
}

register_path() {
    append_path_block "${HOME}/.profile"
    append_path_block "${HOME}/.bashrc"
    if [ -f "${HOME}/.zshrc" ]; then
        append_path_block "${HOME}/.zshrc"
    fi
    log "Registered PATH in shell profiles. Open a new terminal and run: csw"
}

version="0.2.0"
if [ -f "${SOURCE_ROOT}/VERSION" ]; then
    version=$(tr -d '\r\n' < "${SOURCE_ROOT}/VERSION")
fi

log "Installing Claude Switch $version"
log "InstallDir: $INSTALL_DIR"

run_step "Creating install directory" mkdir -p "$INSTALL_DIR"
run_step "Copying application files" copy_application_files

if [ "$SKIP_PIP" -eq 0 ]; then
    run_step "Preparing local virtual environment" prepare_venv
    run_step "Installing Python dependencies into local venv" install_dependencies
else
    log "Skipped pip dependency installation."
fi

run_step "Writing launchers" write_launchers

if [ "$NO_LEGACY_CLEANUP" -eq 1 ]; then
    log "Skipped legacy cleanup."
fi

if [ "$NO_PATH" -eq 0 ]; then
    run_step "Registering install directory in PATH" register_path
else
    log "Skipped PATH registration."
fi

log "Done. Open a new terminal and run: csw"
