#!/usr/bin/env bash
set -euo pipefail

# Publish generated dashboard data safely when multiple workflows finish close
# together. We first rebase onto the newest main. If the rebase conflicts only
# in generated JSON/CSV files under data/, resolve those files deterministically:
#   - JSON: keep the document with the newest embedded date/timestamp; ties favor
#     the current workflow's freshly generated version.
#   - CSV: merge rows using date/time + entity columns as a composite key; the
#     current workflow wins only for the same logical row.
# Conflicts in code, HTML, workflows, or other non-data files still fail loudly.
MAX_ATTEMPTS="${GIT_PUSH_MAX_ATTEMPTS:-6}"

resolve_generated_data_conflicts() {
  mapfile -t conflicts < <(git diff --name-only --diff-filter=U)
  if [ "${#conflicts[@]}" -eq 0 ]; then
    return 1
  fi

  printf '[git-publish] rebase conflict in:'
  printf ' %s' "${conflicts[@]}"
  printf '\n'

  for path in "${conflicts[@]}"; do
    case "$path" in
      data/*.json|data/*/*.json|data/*/*/*.json|data/*/*/*/*.json|data/*/*/*/*/*.json)
        kind="json"
        ;;
      data/*.csv|data/*/*.csv|data/*/*/*.csv|data/*/*/*/*.csv|data/*/*/*/*/*.csv)
        kind="csv"
        ;;
      *)
        echo "[git-publish] unsupported conflict outside generated data: $path"
        return 1
        ;;
    esac

    python - "$path" "$kind" <<'PY'
import csv
import io
import json
import re
import subprocess
import sys
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path

path = sys.argv[1]
kind = sys.argv[2]


def stage_text(stage: int) -> str:
    proc = subprocess.run(
        ["git", "show", f":{stage}:{path}"],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return proc.stdout.decode("utf-8")


remote = stage_text(2)  # upstream/main during a rebase
local = stage_text(3)   # current workflow's commit being replayed


def parse_dt(value):
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not re.match(
        r"^\d{4}-\d{2}-\d{2}(?:[T ][0-9]{2}:[0-9]{2}(?::[0-9]{2}(?:\.\d+)?)?(?:Z|[+-][0-9]{2}:[0-9]{2})?)?$",
        s,
    ):
        return None
    try:
        if len(s) == 10:
            return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None


def newest_dt(obj):
    best = None
    stack = [obj]
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            stack.extend(cur.values())
        elif isinstance(cur, list):
            stack.extend(cur)
        else:
            dt = parse_dt(cur)
            if dt is not None and (best is None or dt > best):
                best = dt
    return best


out = None
reason = ""
if kind == "json":
    remote_obj = json.loads(remote)
    local_obj = json.loads(local)
    remote_dt = newest_dt(remote_obj)
    local_dt = newest_dt(local_obj)

    # Favor the current run on equal/unknown freshness. Prefer upstream only
    # when it is demonstrably newer than the data this run generated.
    if remote_dt is not None and local_dt is not None and remote_dt > local_dt:
        out = remote
        reason = f"remote newer ({remote_dt.isoformat()} > {local_dt.isoformat()})"
    else:
        out = local
        reason = (
            "local current-run version selected "
            f"(remote={remote_dt}, local={local_dt})"
        )
else:
    def read_csv(text):
        reader = csv.reader(io.StringIO(text))
        rows = list(reader)
        if not rows:
            raise ValueError("empty CSV")
        return rows[0], rows[1:]

    remote_header, remote_rows = read_csv(remote)
    local_header, local_rows = read_csv(local)
    if remote_header != local_header:
        raise SystemExit(f"CSV header mismatch for {path}")

    header = remote_header
    key_idx = []
    for i, name in enumerate(header):
        n = name.strip().lower()
        if (
            "date" in n
            or "time" in n
            or n
            in {
                "gpu",
                "platform",
                "ticker",
                "symbol",
                "company",
                "metric",
                "series",
                "source_series",
            }
        ):
            key_idx.append(i)

    # If the file has no obvious logical-key columns, de-duplicate exact rows.
    if not key_idx:
        key_idx = list(range(len(header)))

    def key(row):
        padded = row + [""] * max(0, len(header) - len(row))
        return tuple(padded[i] for i in key_idx)

    merged = OrderedDict()
    for row in remote_rows:
        merged[key(row)] = row
    for row in local_rows:
        merged[key(row)] = row

    buf = io.StringIO(newline="")
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(merged.values())
    out = buf.getvalue()
    reason = (
        f"merged {len(remote_rows)} remote + {len(local_rows)} local rows "
        f"-> {len(merged)} logical rows"
    )

Path(path).write_text(out, encoding="utf-8", newline="")
print(f"[git-publish] resolved {path}: {reason}")
PY

    git add -- "$path"
  done

  if ! GIT_EDITOR=true git rebase --continue; then
    echo "[git-publish] conflict resolution could not complete rebase"
    return 1
  fi

  return 0
}

for attempt in $(seq 1 "$MAX_ATTEMPTS"); do
  echo "[git-publish] attempt ${attempt}/${MAX_ATTEMPTS}"

  if ! git pull --rebase origin main; then
    if ! resolve_generated_data_conflicts; then
      echo "[git-publish] rebase conflict could not be safely auto-resolved; aborting"
      git rebase --abort >/dev/null 2>&1 || true
      exit 1
    fi
  fi

  if git push origin HEAD:main; then
    echo "[git-publish] push succeeded"
    exit 0
  fi

  if [ "$attempt" -lt "$MAX_ATTEMPTS" ]; then
    sleep_seconds=$((attempt * 2 + RANDOM % 3))
    echo "[git-publish] push raced with another writer; retrying in ${sleep_seconds}s"
    sleep "$sleep_seconds"
  fi
done

echo "[git-publish] failed after ${MAX_ATTEMPTS} attempts"
exit 1
