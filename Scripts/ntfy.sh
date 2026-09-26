#!/usr/bin/env bash
# Post one message to ntfy from a workflow: Scripts/ntfy.sh "deploy ok".
# NTFY_URL is the server and topic (a secret: on ntfy the topic name is the password), NTFY_TOKEN
# an access token when the server wants one. Without NTFY_URL this does nothing. A failed post is
# reported and never fails the job: an alert is not worth a red build.
set -euo pipefail

[ -n "${NTFY_URL:-}" ] || exit 0

args=(-fsS -m 10 -H "Title: jevplays demo" --data-binary "$1")
if [ -n "${NTFY_TOKEN:-}" ]; then
  args+=(-H "Authorization: Bearer ${NTFY_TOKEN}")
fi
curl "${args[@]}" "$NTFY_URL" >/dev/null || echo "ntfy post failed" >&2
