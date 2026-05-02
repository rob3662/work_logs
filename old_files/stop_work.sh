#!/bin/bash

LOG_FILE="work_log.json"

# Determine end time
if [ -n "$1" ]; then
    END_TIME=$(date -d "$*" +%H:%M)
    END_SECONDS=$(date -d "$*" +%s)
else
    END_TIME=$(date +%H:%M)
    END_SECONDS=$(date +%s)
fi

# Sanity checks
if [ ! -f "$LOG_FILE" ]; then
    echo "Error: Missing log file."
    exit 1
fi

# Get last session info
LAST_ENTRY=$(jq '.[-1]' "$LOG_FILE")

if [ "$(echo "$LAST_ENTRY" | jq -r '.end_time')" != "NONE" ]; then
    echo "Error: Last session already completed."
    exit 1
fi

SESSION_ID=$(echo "$LAST_ENTRY" | jq -r '.session_id')
START_TIME=$(echo "$LAST_ENTRY" | jq -r '.start_time')
START_SECONDS=$(date -d "$START_TIME" +%s)

if [ "$END_SECONDS" -lt "$START_SECONDS" ]; then
    END_SECONDS=$((END_SECONDS + 86400))
fi

WORKED_SECONDS=$((END_SECONDS - START_SECONDS))
WORKED_HOURS=$(echo "scale=2; $WORKED_SECONDS / 3600" | bc)

# Read tasks from session task file
TASK_FILE=".session_tasks_${SESSION_ID}.txt"
TASK_NOTES=""

if [ -f "$TASK_FILE" ]; then
    echo ""
    echo "Tasks completed during this session:"
    echo "------------------------------------"
    cat "$TASK_FILE"
    echo "------------------------------------"

    read -p "Add additional notes? (leave blank to skip): " additional_notes

    TASK_NOTES=$(cat "$TASK_FILE")

    if [[ -n "$additional_notes" ]]; then
        # Ensure it starts with "- "
        if [[ "$additional_notes" != -* ]]; then
            additional_notes="- $additional_notes"
        fi
        TASK_NOTES="$TASK_NOTES"$'\n'"$additional_notes"
    fi

    rm "$TASK_FILE"
else
    read -p "Notes for this session: " TASK_NOTES
    if [[ -n "$TASK_NOTES" && "$TASK_NOTES" != -* ]]; then
        TASK_NOTES="- $TASK_NOTES"
    fi
fi

# Update log
TMP_FILE=$(mktemp)
# Escape notes for JSON
ESCAPED_NOTES=$(printf "%s" "$TASK_NOTES" | jq -Rs '.')

jq --arg end_time "$END_TIME" \
   --argjson hours_worked "$WORKED_HOURS" \
   --arg notes "$ESCAPED_NOTES" \
   "map(if .session_id == $SESSION_ID then 
       . + {end_time: \$end_time, hours_worked: \$hours_worked, notes: (\$notes | fromjson)} 
    else . end)" "$LOG_FILE" > "$TMP_FILE" && mv "$TMP_FILE" "$LOG_FILE"


# Show summary
PROJECT_NAME=$(jq -r '.[-1].project' "$LOG_FILE")
TOTAL_HOURS=$(jq --arg project "$PROJECT_NAME" \
    '[.[] | select(.project == $project and .hours_worked != "NONE") | .hours_worked | tonumber] | add' \
    "$LOG_FILE")

echo "Finished work session:"
echo "  Session ID  : $SESSION_ID"
echo "  Project     : $PROJECT_NAME"
echo "  Start Time  : $START_TIME"
echo "  End Time    : $END_TIME"
echo "  Worked      : $WORKED_HOURS hours"
echo "  Total Hours : $TOTAL_HOURS"

