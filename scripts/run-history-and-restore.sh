#!/usr/bin/env bash
set -uo pipefail

DEPLOY_DIR="${MT5SCRAPER_DEPLOY_DIR:-/opt/mt5scraper-deploy}"
PROJECT="mt5scraper-portable"
CONTAINER="mt5-market-scraper"
LOG="$DEPLOY_DIR/history-runner.log"
SUMMARY="$DEPLOY_DIR/history-scrape-summary.log"
DISK_FLOOR_KIB=$((15 * 1024 * 1024))
restore_live=0

log() {
    printf '%s %s\n' "$(date -Is)" "$*" >> "$LOG"
}

compose_mode() {
    local mode="$1"
    shift
    sudo -n env MT5_MODE="$mode" SCRAPE_MAX_BARS=0 docker compose \
        --project-directory "$DEPLOY_DIR" -p "$PROJECT" \
        -f "$DEPLOY_DIR/compose.yaml" \
        -f "$DEPLOY_DIR/compose.slate-local.yaml" "$@"
}

restore_live_collection() {
    local status=$?
    trap - EXIT
    if (( restore_live )); then
        sudo -n docker logs --tail 5000 "$CONTAINER" 2>&1 \
            | grep -E '^(MT5 connected|Finished:|FAILED:|Scrape complete\.)' > "$SUMMARY" || true
        if compose_mode live up -d --force-recreate mt5 >> "$LOG" 2>&1; then
            log "Live collection restored after history run (runner_status=$status)"
        else
            log "ERROR: history ended (runner_status=$status) and live collection could not be restored"
            return 1
        fi
    fi
}

mkdir -p "$DEPLOY_DIR"
trap restore_live_collection EXIT
restore_live=1

log 'Starting full-history scrape for the configured default 7 FX + 7 metals across all supported intervals'
if ! compose_mode stack up -d --force-recreate mt5 >> "$LOG" 2>&1; then
    log 'ERROR: could not start the full-history container'
    exit 1
fi

while :; do
    logs="$(sudo -n docker logs --tail 5000 "$CONTAINER" 2>&1 || true)"
    if [[ "$logs" == *'Scrape complete.'* ]]; then
        log 'Scrape completed successfully; restoring live collection'
        exit 0
    fi

    state="$(sudo -n docker inspect -f '{{.State.Status}}' "$CONTAINER" 2>/dev/null || true)"
    if [[ "$state" != running ]]; then
        code="$(sudo -n docker inspect -f '{{.State.ExitCode}}' "$CONTAINER" 2>/dev/null || printf 'unknown')"
        log "Scrape container stopped early (state=${state:-missing}, exit=${code}); restoring live collection"
        exit 1
    fi

    free_kib="$(df -Pk "$DEPLOY_DIR" | awk 'NR==2 {print $4}')"
    if [[ "$free_kib" =~ ^[0-9]+$ ]] && (( free_kib < DISK_FLOOR_KIB )); then
        log "Free disk below 15 GiB (${free_kib} KiB); stopping history before restoring live collection"
        sudo -n docker stop --timeout 90 "$CONTAINER" >> "$LOG" 2>&1 || true
        exit 1
    fi
    sleep 30
done
