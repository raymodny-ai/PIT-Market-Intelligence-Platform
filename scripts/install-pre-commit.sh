#!/usr/bin/env bash
# =============================================================================
# Install pre-commit hook (T-42)
# Usage: bash scripts/install-pre-commit.sh
# =============================================================================
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HOOK_DIR="$PROJECT_ROOT/.git/hooks"
HOOK_FILE="$HOOK_DIR/pre-commit"

mkdir -p "$HOOK_DIR"

# Create symlink (or copy on Windows)
if [ -L "$HOOK_FILE" ] || [ -f "$HOOK_FILE" ]; then
    rm -f "$HOOK_FILE"
fi

# Write a wrapper that calls our script
cat > "$HOOK_FILE" << 'WRAPPER'
#!/usr/bin/env bash
exec bash "$(git rev-parse --show-toplevel)/scripts/pre-commit-check.sh"
WRAPPER

chmod +x "$HOOK_FILE"
echo "Pre-commit hook installed at $HOOK_FILE"
echo "To uninstall: rm $HOOK_FILE"
