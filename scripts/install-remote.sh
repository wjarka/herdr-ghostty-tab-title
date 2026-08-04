#!/usr/bin/env bash
# Install (or update) this plugin on one or more remote herdr hosts.
#
#   scripts/install-remote.sh agent@host-a agent@host-b
#
# Each host needs: a running herdr server, herdr on PATH (or ~/.local/bin),
# python3, and network access to GitHub.
set -euo pipefail

REPO="${HGT_REPO:-wjarka/herdr-ghostty-tab-title}"
PLUGIN_ID="ghostty-tab-title"

if [ "$#" -eq 0 ]; then
  echo "usage: $(basename "$0") <ssh-target>..." >&2
  echo "example: $(basename "$0") agent@host-a.example.com" >&2
  exit 2
fi

failed=0

for target in "$@"; do
  echo "==> $target"
  if ssh -o BatchMode=yes "$target" "REPO='$REPO' PLUGIN_ID='$PLUGIN_ID' bash -s" <<'REMOTE'
set -euo pipefail
herdr_bin="$(command -v herdr || true)"
[ -n "$herdr_bin" ] || herdr_bin="$HOME/.local/bin/herdr"
if [ ! -x "$herdr_bin" ]; then
  echo "herdr not found on PATH or in ~/.local/bin" >&2
  exit 1
fi
command -v python3 >/dev/null || { echo "python3 not found" >&2; exit 1; }

# Reinstall cleanly so an existing copy is updated rather than conflicting.
"$herdr_bin" plugin uninstall "$PLUGIN_ID" >/dev/null 2>&1 || true
"$herdr_bin" plugin install "$REPO" --yes >/dev/null
"$herdr_bin" plugin action invoke "$PLUGIN_ID.start" >/dev/null
sleep 1
"$herdr_bin" plugin log list --plugin "$PLUGIN_ID" --limit 1 >/dev/null
"$herdr_bin" plugin action invoke "$PLUGIN_ID.status" >/dev/null
echo "installed and started on $(hostname -s)"
REMOTE
  then
    echo "    ok"
  else
    echo "    FAILED" >&2
    failed=$((failed + 1))
  fi
done

if [ "$failed" -gt 0 ]; then
  echo "$failed host(s) failed" >&2
  exit 1
fi
