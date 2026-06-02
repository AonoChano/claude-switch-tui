#!/bin/sh
set -eu

INSTALL_DIR="${HOME}/.claude/scripts/claude-switch-tui"
KEEP_FILES=0
NO_PATH=0

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
        --keep-files|--KeepFiles|-KeepFiles)
            KEEP_FILES=1
            ;;
        --no-path|--NoPath|-NoPath)
            NO_PATH=1
            ;;
        *)
            echo "[csw] Unknown option: $1" >&2
            exit 2
            ;;
    esac
    shift
done

log() {
    printf '[csw] %s\n' "$*"
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

if [ "$NO_PATH" -eq 0 ]; then
    remove_managed_block "${HOME}/.profile"
    remove_managed_block "${HOME}/.bashrc"
    remove_managed_block "${HOME}/.zshrc"
    log "Removed managed PATH blocks from shell profiles."
fi

if [ "$KEEP_FILES" -eq 0 ] && [ -e "$INSTALL_DIR" ]; then
    case "$INSTALL_DIR" in
        ""|"/"|"$HOME"|"$HOME/"|"$HOME/.claude"|"$HOME/.claude/"|"$HOME/.claude/scripts"|"$HOME/.claude/scripts/")
            echo "[csw] Refusing to remove unsafe install directory: $INSTALL_DIR" >&2
            exit 1
            ;;
    esac
    rm -rf "$INSTALL_DIR"
    log "Removed install directory: $INSTALL_DIR"
fi

log "Uninstall complete. Open a new terminal for PATH changes to take effect."
