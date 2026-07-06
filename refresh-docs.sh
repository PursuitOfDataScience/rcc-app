#!/usr/bin/env bash
#
# refresh-docs.sh — refresh the docs/ and web/ that the Sage app (app.py) answers from.
#
# The app is RAG-only and reads a bundled snapshot of the RCC User Guide (docs/, markdown)
# and the scraped RCC website (web/, .txt). This keeps the app self-contained/deployable, but
# the snapshot goes stale. This script re-syncs it from the canonical sources and records a
# snapshot stamp (docs_snapshot.json) so staleness is observable in the UI.
#
#   1. User Guide : git pull (or clone) github.com/rcc-uchicago/user-guide  ->  rsync into ./docs
#   2. Website    : (optional --scrape) re-scrape rcc.uchicago.edu, then rsync into ./web
#
# MUST run from a host with outbound internet (RCC compute/login nodes have no egress).
# A backup of the current docs/ and web/ is taken before anything is overwritten.
#
# Usage:
#   ./refresh-docs.sh            # pull User Guide + sync docs/ (and web/ from the mirror if present)
#   ./refresh-docs.sh --scrape   # also re-scrape the website first

set -uo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
UG_REPO="${RCC_USER_GUIDE_REPO:-/project/rcc/youzhi/user-guide}"   # canonical git checkout
UG_REMOTE="https://github.com/rcc-uchicago/user-guide.git"
CANON_WEB="$UG_REPO/web"                                            # scraper output mirror
SCRAPER="${RCC_WEB_SCRAPER:-/home/youzhi/LLM-API/rcc-web-scrape.py}"
BACKUP_DIR="$APP_DIR/.doc-backups"
STAMP="$APP_DIR/docs_snapshot.json"
KEEP_BACKUPS=5
DO_SCRAPE=0
[ "${1:-}" = "--scrape" ] && DO_SCRAPE=1

log()  { printf '\n=== %s ===\n' "$*"; }
warn() { printf 'WARN: %s\n' "$*" >&2; }
fail=0

# mirror SRC/ -> DST/ exactly (removes files deleted upstream). rsync if available, else rm+cp.
mirror() {
    local src="$1" dst="$2"
    if command -v rsync >/dev/null 2>&1; then
        rsync -a --delete --exclude '.git' "$src/" "$dst/"
    else
        rm -rf "$dst" && cp -a "$src" "$dst"
    fi
}

# 0. Connectivity preflight.
log "Connectivity check"
if ! curl -sS -o /dev/null --max-time 15 https://github.com >/dev/null 2>&1; then
    warn "no outbound HTTPS (github.com unreachable). Run from an internet-connected host."
    exit 1
fi
echo "OK: internet reachable."

# 1. User Guide: clone if missing, else fast-forward pull.
log "User Guide: update checkout ($UG_REPO)"
if [ -d "$UG_REPO/.git" ]; then
    before=$(git -C "$UG_REPO" rev-parse --short HEAD 2>/dev/null)
    if git -C "$UG_REPO" pull --ff-only; then
        after=$(git -C "$UG_REPO" rev-parse --short HEAD 2>/dev/null)
        [ "$before" = "$after" ] && echo "Already up to date ($after)." || echo "Updated $before -> $after."
    else
        warn "git pull failed (local changes / diverged history) — using existing checkout."; fail=1
    fi
elif [ -e "$UG_REPO" ]; then
    warn "$UG_REPO exists but is not a git checkout — using its contents as-is."; fail=1
else
    echo "Cloning $UG_REMOTE -> $UG_REPO"
    git clone --depth 1 "$UG_REMOTE" "$UG_REPO" || { warn "clone failed."; exit 1; }
fi

# 2. Optional: re-scrape the website into the canonical mirror.
if [ "$DO_SCRAPE" -eq 1 ]; then
    log "Website: re-scrape rcc.uchicago.edu"
    if ! python3 -c "import requests, bs4" 2>/dev/null; then
        warn "scraper deps missing (need requests, beautifulsoup4) — skipping scrape."; fail=1
    elif [ ! -f "$SCRAPER" ]; then
        warn "scraper not found at $SCRAPER — skipping scrape."; fail=1
    else
        python3 "$SCRAPER" || { warn "scraper failed — keeping previous web mirror."; fail=1; }
    fi
fi

# 3. Back up the app's current docs/ and web/ before overwriting.
log "Backup current docs/ and web/"
mkdir -p "$BACKUP_DIR"
stamp=$(date +%Y%m%d-%H%M%S)
if tar czf "$BACKUP_DIR/docs-web-$stamp.tar.gz" -C "$APP_DIR" docs web 2>/dev/null; then
    echo "Backed up to $BACKUP_DIR/docs-web-$stamp.tar.gz"
    ls -1t "$BACKUP_DIR"/docs-web-*.tar.gz 2>/dev/null | tail -n +$((KEEP_BACKUPS + 1)) | xargs -r rm -f
else
    warn "backup failed — aborting sync to protect the current snapshot."; exit 1
fi

# 4. Sync docs/ from the User Guide checkout, and web/ from the scraped mirror (if present).
log "Sync docs/ from $UG_REPO/docs"
if [ -d "$UG_REPO/docs" ]; then
    mirror "$UG_REPO/docs" "$APP_DIR/docs"
    echo "docs/: $(find "$APP_DIR/docs" -name '*.md' | wc -l) markdown files"
else
    warn "$UG_REPO/docs not found — docs/ left unchanged."; fail=1
fi

log "Sync web/ from $CANON_WEB"
if [ -d "$CANON_WEB" ]; then
    mirror "$CANON_WEB" "$APP_DIR/web"
    echo "web/: $(find "$APP_DIR/web" -name '*.txt' | wc -l) text files"
else
    warn "$CANON_WEB not found — web/ left unchanged (run with --scrape, or check RCC_WEB_SCRAPER)."; fail=1
fi

# 5. Record a snapshot stamp the app surfaces in the UI.
log "Write snapshot stamp ($STAMP)"
ug_commit=$([ -d "$UG_REPO/.git" ] && git -C "$UG_REPO" rev-parse --short HEAD 2>/dev/null || echo "unknown")
cat > "$STAMP" <<JSON
{
  "refreshed_at": "$(date '+%Y-%m-%d %H:%M %Z')",
  "user_guide_commit": "$ug_commit",
  "docs_files": $(find "$APP_DIR/docs" -name '*.md' | wc -l),
  "web_files": $(find "$APP_DIR/web" -name '*.txt' | wc -l)
}
JSON
cat "$STAMP"

log "Done"
if [ "$fail" -ne 0 ]; then
    echo "Completed WITH WARNINGS — see messages above."
    exit 1
fi
echo "Docs refreshed. The app rebuilds its search index on next start (cache cleared on restart)."

# ── Schedule it (weekly, from an internet-connected host) ──────────────────────
#   crontab -e, then add (Mondays 03:00):
#     0 3 * * 1  /project/rcc/youzhi/rcc-app/refresh-docs.sh >> /project/rcc/youzhi/rcc-app/refresh-docs.log 2>&1
