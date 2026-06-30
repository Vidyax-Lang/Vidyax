#!/usr/bin/env bash
# Vidyax installer — makes `vidyax` (and the short alias `vdx`) real commands.
# Usage:  bash install.sh
set -e

SRC_DIR="$(cd "$(dirname "$0")" && pwd)"
LIB_DIR="$HOME/.local/share/vidyax"
BIN_DIR="$HOME/.local/bin"

mkdir -p "$LIB_DIR" "$BIN_DIR"
cp "$SRC_DIR/vidyax.py" "$LIB_DIR/vidyax.py"
cp "$SRC_DIR/tests.py" "$LIB_DIR/tests.py" 2>/dev/null || true

cat > "$BIN_DIR/vidyax" << 'LAUNCH'
#!/usr/bin/env bash
exec python3 "$HOME/.local/share/vidyax/vidyax.py" "$@"
LAUNCH
chmod +x "$BIN_DIR/vidyax"

# short alias: vdx
ln -sf "$BIN_DIR/vidyax" "$BIN_DIR/vdx"

echo "Installed: $BIN_DIR/vidyax  (alias: vdx)"
case ":$PATH:" in
  *":$BIN_DIR:"*) echo "PATH ok. Try:  vidyax --help" ;;
  *) echo "Add this to your ~/.bashrc or ~/.zshrc, then restart shell:"
     echo '  export PATH="$HOME/.local/bin:$PATH"' ;;
esac
