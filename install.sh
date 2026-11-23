#!/usr/bin/env sh
# Vidyax Installer (Linux & macOS)
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/Vidyax-Lang/Vidyax/main/install.sh | sh
#   sh install.sh   (inside a cloned repo: builds & installs standalone ./vidyax)
set -eu

REPO="Vidyax-Lang/Vidyax"
BIN_DIR="${VIDYAX_BIN_DIR:-$HOME/.local/bin}"
TMP_DIR=""

cleanup() {
  if [ -n "$TMP_DIR" ] && [ -d "$TMP_DIR" ]; then
    rm -rf "$TMP_DIR"
  fi
}
trap cleanup EXIT INT TERM

need_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "error: required command '$1' not found" >&2
    exit 1
  fi
}

mkdir -p "$BIN_DIR"

# Case 1: Running locally inside a cloned Vidyax repository
if [ -f "./vm/vidyax_main.c" ] && [ -f "./vm/Makefile" ]; then
  echo "[Vidyax] Building standalone binary from local source..."
  make -C vm vxvm vidyax >/dev/null
  cp ./vidyax "$BIN_DIR/vidyax"
  chmod +x "$BIN_DIR/vidyax"
  ln -sf "$BIN_DIR/vidyax" "$BIN_DIR/vdx"
  echo "[Vidyax] Installed: $BIN_DIR/vidyax (alias: vdx)"
else
  # Case 2: Remote curl | sh install from GitHub Releases (with source fallback)
  need_cmd curl
  OS="$(uname -s | tr '[:upper:]' '[:lower:]')"
  ARCH="$(uname -m)"
  case "$ARCH" in
    x86_64|amd64) ARCH="x86_64" ;;
    aarch64|arm64) ARCH="aarch64" ;;
    *) echo "error: unsupported architecture '$ARCH'" >&2; exit 1 ;;
  esac
  case "$OS" in
    linux|darwin) ;;
    *) echo "error: unsupported OS '$OS' (use install.ps1 on Windows)" >&2; exit 1 ;;
  esac

  ASSET="vidyax-${OS}-${ARCH}"
  BASE_URL="https://github.com/${REPO}/releases/latest/download"
  TMP_DIR="$(mktemp -d)"

  echo "[Vidyax] Detecting target: ${OS}-${ARCH}"
  if curl -fsSL "${BASE_URL}/${ASSET}" -o "${TMP_DIR}/vidyax" 2>/dev/null; then
    if curl -fsSL "${BASE_URL}/checksums.sha256" -o "${TMP_DIR}/checksums.sha256" 2>/dev/null; then
      EXPECTED="$(grep " ${ASSET}\$" "${TMP_DIR}/checksums.sha256" | awk '{print $1}' || true)"
      if [ -n "$EXPECTED" ]; then
        if command -v sha256sum >/dev/null 2>&1; then
          ACTUAL="$(sha256sum "${TMP_DIR}/vidyax" | awk '{print $1}')"
        elif command -v shasum >/dev/null 2>&1; then
          ACTUAL="$(shasum -a 256 "${TMP_DIR}/vidyax" | awk '{print $1}')"
        else
          ACTUAL="$EXPECTED"
        fi
        if [ "$ACTUAL" != "$EXPECTED" ]; then
          echo "error: SHA-256 checksum mismatch for ${ASSET}" >&2
          exit 1
        fi
        echo "[Vidyax] SHA-256 verified."
      fi
    fi
    mv "${TMP_DIR}/vidyax" "$BIN_DIR/vidyax"
    chmod +x "$BIN_DIR/vidyax"
    ln -sf "$BIN_DIR/vidyax" "$BIN_DIR/vdx"
    echo "[Vidyax] Installed prebuilt binary: $BIN_DIR/vidyax (alias: vdx)"
  else
    echo "[Vidyax] No prebuilt release binary found for ${ASSET}; building from source..."
    need_cmd git
    need_cmd make
    git clone --depth 1 "https://github.com/${REPO}.git" "${TMP_DIR}/src" >/dev/null 2>&1
    make -C "${TMP_DIR}/src/vm" vxvm vidyax >/dev/null
    cp "${TMP_DIR}/src/vidyax" "$BIN_DIR/vidyax"
    chmod +x "$BIN_DIR/vidyax"
    ln -sf "$BIN_DIR/vidyax" "$BIN_DIR/vdx"
    echo "[Vidyax] Built & installed from source: $BIN_DIR/vidyax (alias: vdx)"
  fi
fi

case ":$PATH:" in
  *":$BIN_DIR:"*)
    echo "[Vidyax] Ready. Run: vidyax --version"
    ;;
  *)
    echo "[Vidyax] Add this to your shell profile (~/.bashrc or ~/.zshrc):"
    echo "  export PATH=\"$BIN_DIR:\$PATH\""
    ;;
esac
