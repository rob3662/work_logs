#!/bin/bash

LOG_FILE="work_log.json"
NOW=$(date +%s)
DEFAULT_PROJECT=$(basename "$PWD")

# Default values
CUSTOM_PROJECT=""
TIME_ARGS=()

# Parse arguments
for arg in "$@"; do
    if [[ "$arg" == --project=* ]]; then
        CUSTOM_PROJECT="${arg#--project=}"
    else
        TIME_ARGS+=("$arg")
    fi
done

# Determine start time
if [ ${#TIME_ARGS[@]} -gt 0 ]; then
    PARSED_DATE=$(date -d "${TIME_ARGS[*]}" "+%F")
    PARSED_TIME=$(date -d "${TIME_ARGS[*]}" "+%H:%M")
    SESSION_ID=$(date -d "${TIME_ARGS[*]}" +%s)
else
    PARSED_DATE=$(date +%F)
    PARSED_TIME=$(date +%H:%M)
    SESSION_ID=$NOW
fi

PROJECT_NAME=${CUSTOM_PROJECT:-$DEFAULT_PROJECT}

# Ensure log exists
[[ ! -f "$LOG_FILE" ]] && echo "[]" > "$LOG_FILE"

# Create new session entry
NEW_ENTRY=$(jq -n \
    --arg date "$PARSED_DATE" \
    --arg session_id "$SESSION_ID" \
    --arg start_time "$PARSED_TIME" \
    --arg end_time "NONE" \
    --arg hours_worked "NONE" \
    --arg notes "NONE" \
    --arg project "$PROJECT_NAME" \
    '{date: $date, session_id: ($session_id | tonumber), start_time: $start_time, end_time: $end_time, hours_worked: $hours_worked, notes: $notes, project: $project}')

# Append to log
TMP_FILE=$(mktemp)
jq ". + [$NEW_ENTRY]" "$LOG_FILE" > "$TMP_FILE" && mv "$TMP_FILE" "$LOG_FILE"

# Clean up any old task files and create a new one
rm -f .session_tasks_*.txt
touch ".session_tasks_${SESSION_ID}.txt"

echo "Started new work session for project '$PROJECT_NAME' at $PARSED_TIME (session_id: $SESSION_ID)"

