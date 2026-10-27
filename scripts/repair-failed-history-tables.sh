#!/usr/bin/env bash
set -uo pipefail

DEPLOY_DIR="${MT5SCRAPER_DEPLOY_DIR:-/opt/mt5scraper-deploy}"
PROJECT="mt5scraper-portable"
CONTAINER="mt5-market-scraper"
SUMMARY="$DEPLOY_DIR/history-scrape-summary.log"
LOG="$DEPLOY_DIR/history-repair.log"
MARKER_DIR="/var/lib/mt5scraper/history-repair"
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

restore_live_collection() {
    local status=$?
    trap - EXIT TERM INT
    if (( restore_live )); then
        if compose_mode live up -d --force-recreate mt5 >> "$LOG" 2>&1; then
            log "Live collection restored (repair_status=$status)"
        else
            log 'ERROR: failed to restore live collection after history repair'
            return 1
        fi
    fi
}

mkdir -p "$MARKER_DIR"
if [[ -f /var/lib/mt5scraper/eurusd-m1-repair.done ]]; then
    touch "$MARKER_DIR/EURUSD_M1.done"
fi
if [[ ! -f "$SUMMARY" ]]; then
    log 'ERROR: completed history summary not found; repair not started'
    exit 1
fi

declare -A frames_by_symbol=()
while IFS= read -r table; do
    [[ -n "$table" ]] || continue
    [[ -f "$MARKER_DIR/$table.done" ]] && continue
    symbol="${table%_*}"
    frame="${table##*_}"
    frames_by_symbol["$symbol"]+=" $frame"
done < <(sed -nE 's/^FAILED: ([A-Z0-9_]+):.*/\1/p' "$SUMMARY" | sort -u)

if (( ${#frames_by_symbol[@]} == 0 )); then
    log 'No unrepaired failed tables found; nothing to do'
    exit 0
fi

while pgrep -f '[r]un-history-and-restore.sh' >/dev/null; do sleep 30; done
state="$(sudo -n docker inspect -f '{{.State.Status}}' "$CONTAINER" 2>/dev/null || true)"
mode="$(sudo -n docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' "$CONTAINER" 2>/dev/null \
    | grep '^MT5_MODE=' | tail -n 1 || true)"
if [[ "$state" != running || "$mode" != 'MT5_MODE=live' ]]; then
    log "ERROR: expected restored live container before repair (state=${state:-missing}, mode=${mode:-unknown})"
    exit 1
fi

check_disk_floor() {
    local free_kib
    free_kib="$(df -Pk "$DEPLOY_DIR" | awk 'NR==2 {print $4}')"
    [[ "$free_kib" =~ ^[0-9]+$ ]] && (( free_kib >= DISK_FLOOR_KIB ))
}
if ! check_disk_floor; then
    log 'ERROR: free disk is below the 15 GiB safety floor; repair not started'
    exit 1
fi

trap restore_live_collection EXIT
trap 'exit 143' TERM
trap 'exit 130' INT
restore_live=1
log 'Stopping live collector gracefully for single-terminal failed-history retries'
if ! compose_mode live stop -t 90 mt5 >> "$LOG" 2>&1; then
    log 'ERROR: could not stop live collector; retrying live restoration'
    exit 1
fi

failed_count=0
success_count=0
for symbol in "${!frames_by_symbol[@]}"; do
    read -r -a frames <<< "${frames_by_symbol[$symbol]}"
    group_log="$DEPLOY_DIR/history-repair-$symbol.log"
    log "Retrying $symbol timeframes: ${frames[*]}"
    compose_mode scrape run --rm --no-deps --name "mt5-history-repair-$symbol" mt5 \
        --max-bars-per-table 0 --db Z:/data/market.db --symbols "$symbol" --timeframes "${frames[@]}" \
        > "$group_log" 2>&1
    run_status=$?

    for frame in "${frames[@]}"; do
        table="${symbol}_${frame}"
        if grep -Fq "\"table\": \"$table\"" "$group_log" && ! grep -Fq "FAILED: $table:" "$group_log"; then
            touch "$MARKER_DIR/$table.done"
            ((success_count+=1))
            log "$table repaired successfully"
        else
            ((failed_count+=1))
            log "$table repair failed (group_status=$run_status); see $(basename "$group_log")"
        fi
    done

    if ! check_disk_floor; then
        log 'ERROR: free disk fell below the 15 GiB floor; stopping further retries'
        break
    fi
done

log "Repair pass complete: $success_count succeeded, $failed_count still failed"
if (( failed_count == 0 )); then
    curl --fail --silent --show-error --max-time 15 \
        -H 'Title: MT5 history repairs complete' \
        -H 'Tags: white_check_mark' \
        --data-binary "Repaired $success_count previously failed history tables. Live collection is being restored." \
        'https://ntfy.sh/mt5-scraper' >/dev/null || log 'WARNING: ntfy notification failed'
fi
