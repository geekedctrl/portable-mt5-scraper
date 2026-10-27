#!/usr/bin/env bash
set -uo pipefail

DEPLOY_DIR="${MT5SCRAPER_DEPLOY_DIR:-/opt/mt5scraper-deploy}"
PROJECT="mt5scraper-portable"
CONTAINER="mt5-market-scraper"
SUMMARY="$DEPLOY_DIR/history-scrape-summary.log"
LOG="$DEPLOY_DIR/eurusd-m1-repair.log"
MARKER="/var/lib/mt5scraper/eurusd-m1-repair.done"
DISK_FLOOR_KIB=$((15 * 1024 * 1024))
restore_live=0

log() { printf '%s %s\n' "$(date -Is)" "$*" | tee -a "$LOG"; }

compose_mode() {
    local mode="$1"
    shift
    sudo -n env MT5_MODE="$mode" SCRAPE_MAX_BARS=0 docker compose \
        --project-directory "$DEPLOY_DIR" -p "$PROJECT" \
        -f "$DEPLOY_DIR/compose.yaml" \
        -f "$DEPLOY_DIR/compose.slate-local.yaml" "$@"
}

restore_live() {
    local status=$?
    trap - EXIT TERM INT
    if (( restore_live )); then
        if compose_mode live up -d --force-recreate mt5 >> "$LOG" 2>&1; then
            log "Live collection restored (repair_status=$status)"
        else
            log 'ERROR: failed to restore live collection after EURUSD_M1 repair'
            return 1
        fi
    fi
}

mkdir -p "$(dirname "$MARKER")"
if [[ -f "$MARKER" ]]; then
    log 'EURUSD_M1 repair already completed; nothing to do'
    exit 0
fi

log 'Waiting for the active full-history controller to finish'
while pgrep -f '[r]un-history-and-restore.sh' >/dev/null; do sleep 30; done

if ! grep -Fq 'FAILED: EURUSD_M1:' "$SUMMARY" 2>/dev/null; then
    log 'No EURUSD_M1 failure found in the completed scrape summary; skipping repair'
    exit 0
fi

state="$(sudo -n docker inspect -f '{{.State.Status}}' "$CONTAINER" 2>/dev/null || true)"
mode="$(sudo -n docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' "$CONTAINER" 2>/dev/null \
    | grep '^MT5_MODE=' | tail -n 1 || true)"
if [[ "$state" != running || "$mode" != 'MT5_MODE=live' ]]; then
    log "ERROR: expected restored live container before repair (state=${state:-missing}, mode=${mode:-unknown})"
    exit 1
fi

free_kib="$(df -Pk "$DEPLOY_DIR" | awk 'NR==2 {print $4}')"
if [[ ! "$free_kib" =~ ^[0-9]+$ ]] || (( free_kib < DISK_FLOOR_KIB )); then
    log 'ERROR: free disk is below the 15 GiB safety floor; repair not started'
    exit 1
fi

trap restore_live EXIT
trap 'exit 143' TERM
trap 'exit 130' INT
restore_live=1
log 'Stopping live collector gracefully for a single-terminal EURUSD_M1 retry'
if ! compose_mode live stop -t 90 mt5 >> "$LOG" 2>&1; then
    log 'ERROR: could not stop live collector; skipping repair'
    exit 1
fi

log 'Retrying only EURUSD_M1 against the existing market database'
if compose_mode scrape run --rm --no-deps --name mt5-history-repair mt5 \
    --max-bars-per-table 0 --db Z:/data/market.db --symbols EURUSD --timeframes M1 \
    >> "$LOG" 2>&1; then
    touch "$MARKER"
    log 'EURUSD_M1 retry completed successfully'
    curl --fail --silent --show-error --max-time 15 \
        -H 'Title: MT5 history repair complete' \
        -H 'Tags: white_check_mark' \
        --data-binary 'EURUSD_M1 historical retry completed successfully. Live collection is being restored.' \
        'https://ntfy.sh/mt5-scraper' >/dev/null || log 'WARNING: repair succeeded but ntfy notification failed'
else
    status=$?
    log "ERROR: EURUSD_M1 retry failed (status=$status); live collection will be restored"
    exit "$status"
fi
