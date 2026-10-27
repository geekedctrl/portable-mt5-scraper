#!/usr/bin/env bash
set -uo pipefail

# Periodically publish historical scraper progress to ntfy.sh.
# Install on the VM alongside the deployment at /opt/mt5scraper-deploy.

DEPLOY_DIR="${MT5SCRAPER_DEPLOY_DIR:-/opt/mt5scraper-deploy}"
CONTAINER="${MT5SCRAPER_CONTAINER:-mt5-market-scraper}"
NTFY_TOPIC="${NTFY_TOPIC:-mt5-scraper}"
INTERVAL_SECONDS="${INTERVAL_SECONDS:-300}"
TOTAL_TABLES="${TOTAL_TABLES:-126}"
VOLUME_PATH="${MT5SCRAPER_DATA_PATH:-/mnt/dietpi_userdata/docker-data/volumes/mt5scraper-portable_mt5-data/_data}"
LOCK_FILE="${MT5SCRAPER_PROGRESS_LOCK:-/run/lock/mt5scraper-progress-notifier.lock}"

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
    echo 'Another history progress reporter is already running.' >&2
    exit 1
fi

human_size() {
    numfmt --to=iec-i --suffix=B "${1:-0}" 2>/dev/null || printf '%s bytes' "${1:-0}"
}

while :; do
    stamp="$(date -u '+%Y-%m-%d %H:%M:%S UTC')"
    state="$(sudo -n docker inspect -f '{{.State.Status}}' "$CONTAINER" 2>/dev/null || printf 'missing')"
    container_logs="$(sudo -n docker logs --tail 200 "$CONTAINER" 2>&1 || true)"
    summary="$DEPLOY_DIR/history-scrape-summary.log"
    base_completed="$(sed -nE 's/^Finished: ([0-9]+) tables,.*/\1/p' "$summary" 2>/dev/null | tail -n 1)"
    [[ "$base_completed" =~ ^[0-9]+$ ]] || base_completed=0
    failed_tables="$(sed -nE 's/^FAILED: ([A-Z0-9_]+):.*/\1/p' "$summary" 2>/dev/null | sort -u)"
    failed_total="$(printf '%s\n' "$failed_tables" | awk 'NF {n++} END {print n+0}')"
    marker_dir=/var/lib/mt5scraper/history-repair
    declare -A repaired=()
    for marker in "$marker_dir"/*.done; do
        [[ -f "$marker" ]] || continue
        repaired["$(basename "$marker" .done)"]=1
    done
    if [[ -f /var/lib/mt5scraper/eurusd-m1-repair.done ]]; then repaired[EURUSD_M1]=1; fi

    repair_active="$(systemctl is-active mt5scraper-history-repair.service 2>/dev/null || true)"
    repair_logs=''
    repair_containers="$(sudo -n docker ps --format '{{.Names}}' | grep '^mt5-history-repair-' || true)"
    while IFS= read -r repair_container; do
        [[ -n "$repair_container" ]] || continue
        repair_logs+="$(sudo -n docker logs "$repair_container" 2>&1 || true)"$'\n'
    done <<< "$repair_containers"
    progress="$(printf '%s\n' "$repair_logs" \
        | grep -E 'downloaded through|reached confirmed start' | tail -n 1 || true)"
    if [[ -z "$progress" ]]; then
        progress="$(printf '%s\n' "$container_logs" \
            | grep -E 'downloaded through|Finished:|FAILED:|Scrape complete\.' | tail -n 1 || true)"
    fi
    active_repair_tables="$(printf '%s\n' "$repair_logs" \
        | grep -oE '"table":[[:space:]]*"[A-Z0-9_]+"' \
        | sed -E 's/.*"([A-Z0-9_]+)"/\1/' | sort -u)"
    repair_success_count=${#repaired[@]}
    while IFS= read -r table; do
        [[ -n "$table" ]] || continue
        if [[ -z "${repaired[$table]+x}" ]] && printf '%s\n' "$failed_tables" | grep -Fxq "$table"; then
            repaired["$table"]=1
            ((repair_success_count+=1))
        fi
    done <<< "$active_repair_tables"
    completed_count=$((base_completed + repair_success_count))
    failed_count=$((failed_total - repair_success_count))
    (( failed_count < 0 )) && failed_count=0
    if [[ "$TOTAL_TABLES" =~ ^[1-9][0-9]*$ ]]; then
        percent="$(awk -v c="$completed_count" -v t="$TOTAL_TABLES" 'BEGIN {printf "%.1f", 100*c/t}')"
        filled=$((completed_count * 10 / TOTAL_TABLES))
    else
        percent='0.0'
        filled=0
    fi
    (( filled > 10 )) && filled=10
    bar=""
    for ((i=0; i<10; i++)); do
        if (( i < filled )); then bar+="🟩"; else bar+="⬜"; fi
    done
    current_table='Waiting for table progress'
    reached='—'
    if [[ "$progress" == *'downloaded through'* ]]; then
        current_table="${progress%%: downloaded through*}"
        reached="${progress##*downloaded through }"
    elif [[ -n "$progress" ]]; then
        current_table="$progress"
    fi
    db_path="$VOLUME_PATH/market.db"
    if [[ -f "$db_path" ]]; then
        db_size="$(stat -c '%s' "$db_path" 2>/dev/null || printf '0')"
        db_text="$(human_size "$db_size")"
    else
        db_text='not found'
    fi
    free_text="$(df -hP "$DEPLOY_DIR" 2>/dev/null | awk 'NR==2 {print $4 " free"}')"
    [[ -n "$free_text" ]] || free_text='unknown free space'
    runner="running"
    pgrep -f '[r]un-history-and-restore.sh' >/dev/null || runner='not running'
    if [[ "$repair_active" == active || "$repair_active" == activating ]]; then
        runner='repair active'
        if [[ -n "$repair_containers" ]]; then
            state='repairing'
            current_table="$(printf '%s\n' "$repair_containers" | tail -n 1 | sed 's/^mt5-history-repair-//')"
        elif [[ -n "$progress" ]]; then
            state='repairing'
        fi
    fi

    message="📊 HISTORICAL BACKFILL
$bar  ${percent}%

Tables complete  $completed_count / $TOTAL_TABLES
Tables failed   $failed_count
Processing      $current_table
Reached         $reached

Database        $db_text
Disk available  $free_text
Services        scraper $state · controller $runner
Updated         $stamp"

    curl --fail --silent --show-error --max-time 15 \
        -H "Title: MT5 history · ${percent}% complete" \
        -H 'Tags: bar_chart,chart_with_upwards_trend' \
        -H 'Priority: default' \
        --data-binary "$message" "https://ntfy.sh/$NTFY_TOPIC" \
        >/dev/null || echo "$(date -Is) failed to publish ntfy update" >&2

    sleep "$INTERVAL_SECONDS"
done
