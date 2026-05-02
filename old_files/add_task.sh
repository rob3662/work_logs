#!/bin/bash

SESSION_FILE=$(ls .session_tasks_*.txt 2>/dev/null | head -n 1)

if [ -z "$SESSION_FILE" ]; then
    echo "No active session task file found."
    exit 1
fi

echo "- $*" >> "$SESSION_FILE"
echo "Task added: $*"

