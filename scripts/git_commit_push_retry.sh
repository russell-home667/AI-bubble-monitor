#!/usr/bin/env bash
set -euo pipefail

# Serialize repository publication optimistically: data workflows may finish at the
# same time, so a push can lose a race even when the workflows changed different
# files. Rebase onto the newest main and retry non-fast-forward pushes. A genuine
# content conflict is never auto-resolved; fail loudly instead of risking data loss.
MAX_ATTEMPTS="${GIT_PUSH_MAX_ATTEMPTS:-6}"

for attempt in $(seq 1 "$MAX_ATTEMPTS"); do
  echo "[git-publish] attempt ${attempt}/${MAX_ATTEMPTS}"

  if ! git pull --rebase origin main; then
    echo "[git-publish] rebase conflict; aborting rather than auto-overwriting data"
    git rebase --abort >/dev/null 2>&1 || true
    exit 1
  fi

  if git push origin HEAD:main; then
    echo "[git-publish] push succeeded"
    exit 0
  fi

  if [ "$attempt" -lt "$MAX_ATTEMPTS" ]; then
    # Small deterministic backoff plus jitter prevents two writers from repeatedly
    # colliding after they finish at nearly the same instant.
    sleep_seconds=$((attempt * 2 + RANDOM % 3))
    echo "[git-publish] push raced with another writer; retrying in ${sleep_seconds}s"
    sleep "$sleep_seconds"
  fi
done

echo "[git-publish] failed after ${MAX_ATTEMPTS} attempts"
exit 1
