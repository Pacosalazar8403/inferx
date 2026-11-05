#!/usr/bin/env bash
# Sends a mix of chat requests to a running InferX, so the metrics have
# something to show. Prints how many responses came back with each status.
#
#   scripts/demo_traffic.sh
#   REQUESTS=500 scripts/demo_traffic.sh
#
# Out of every 10 requests: 6 short prompts (routed to the small backend),
# 3 long prompts (routed to the large backend), and 1 sent directly to the
# "broken" backend from config/compose-demo.toml.

set -euo pipefail

URL="${INFERX_URL:-http://127.0.0.1:8000}/v1/chat/completions"
REQUESTS="${REQUESTS:-200}"

# 300 characters, longer than the 200 character routing threshold.
LONG_PROMPT=$(printf 'x%.0s' $(seq 1 300))

send() {
  curl -s -o /dev/null -w "%{http_code}\n" "$URL" \
    -H "Content-Type: application/json" \
    -d "$1"
}

for i in $(seq 1 "$REQUESTS"); do
  case $((i % 10)) in
    0) send '{"model": "broken", "messages": [{"role": "user", "content": "hi"}]}' ;;
    1 | 2 | 3) send "{\"model\": \"auto\", \"messages\": [{\"role\": \"user\", \"content\": \"$LONG_PROMPT\"}]}" ;;
    *) send '{"model": "auto", "messages": [{"role": "user", "content": "hi"}]}' ;;
  esac
done | sort | uniq -c