#!/usr/bin/env python3
"""180-day story archive and analyzed-history index for AI Bubble News Radar.

This layer is model-free. It does not widen discovery windows or DeepSeek candidate
budgets. It only:
1) reuses exact previously analyzed URLs from a 180-day lightweight history index;
2) appends validated current stories into a 180-day archive for news.html;
3) persists analyzed/rejected candidate states so repeated URLs do not consume API.
"""
from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

ARCHIVE_DAYS = 180
ARCHIVE = Path("data/ai_bubble/news/archive_180d.json")
INDEX = Path("data/ai_bubble/news/analyzed_history_index.json")
ANALYZED_STATES = {"analyzed_story", "analyzed_rejected", "history_reused"}


def _read(path: Path, fallback):
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"[news] warning: could not read {path}: {exc}")
    return fallback


def _canon(core, url):
    try:
        return core.canon_url(url)
    except Exception:
        return str(url or "").strip()


def _story_match(core, a, b):
    if a.get("id") and a.get("id") == b.get("id"):
        return True
    au = {_canon(core, x.get("url")) for x in (a.get("sources") or []) if x.get("url")}
    bu = {_canon(core, x.get("url")) for x in (b.get("sources") or []) if x.get("url")}
    if au & bu:
        return True
    # Conservative cross-run fallback: only near-identical titles within 96 hours.
    try:
        if core.within_hours(a.get("published_at"), b.get("published_at"), 96):
            return core.sim(a.get("headline", ""), b.get("headline", "")) >= 0.92
    except Exception:
        pass
    return False


def _merge_story(core, dst, src, now_iso):
    # Prefer current analysis fields while preserving the richest source set.
    merged = dict(dst)
    for key in (
        "headline", "summary_zh", "category", "importance_score", "bubble_direction",
        "bubble_risk_score", "reason_zh", "companies", "critical", "published_at",
    ):
        if src.get(key) not in (None, "", []):
            merged[key] = src.get(key)

    sources = {}
    for item in list(dst.get("sources") or []) + list(src.get("sources") or []):
        url = _canon(core, item.get("url"))
        if not url:
            continue
        sources[url] = item
    merged["sources"] = list(sources.values())[:8]
    merged["first_archived_at"] = dst.get("first_archived_at") or src.get("first_archived_at") or now_iso
    merged["last_seen_at"] = now_iso
    return merged


def _archive_stories(core, current, now):
    cutoff = now - timedelta(days=ARCHIVE_DAYS)
    old = _read(ARCHIVE, {}).get("stories") or []
    pool = []

    for story in old:
        dt = core.dtparse(story.get("published_at"))
        if dt and dt >= cutoff:
            pool.append(dict(story))

    now_iso = now.isoformat(timespec="seconds")
    for story in current:
        dt = core.dtparse(story.get("published_at"))
        if not dt or dt < cutoff:
            continue
        incoming = dict(story)
        match_idx = next((i for i, old_story in enumerate(pool) if _story_match(core, incoming, old_story)), None)
        if match_idx is None:
            incoming["first_archived_at"] = incoming.get("first_archived_at") or now_iso
            incoming["last_seen_at"] = now_iso
            pool.append(incoming)
        else:
            pool[match_idx] = _merge_story(core, pool[match_idx], incoming, now_iso)

    pool.sort(
        key=lambda s: (str(s.get("published_at") or ""), int(s.get("importance_score") or 0)),
        reverse=True,
    )
    return pool


def _history_entries(core, payload, archive_stories, now):
    cutoff = now - timedelta(days=ARCHIVE_DAYS)
    old = _read(INDEX, {}).get("entries") or []
    rows = []

    def keep(row):
        dt = core.dtparse(row.get("published_at"))
        return bool(dt and dt >= cutoff)

    for row in old:
        if keep(row) and str(row.get("analysis_state") or "") in ANALYZED_STATES:
            rows.append(dict(row))

    # Persist all analyzed candidate states, including rejected candidates, beyond
    # candidate_cache's short retention window.
    for row in payload.get("candidate_cache") or []:
        if str(row.get("analysis_state") or "") not in ANALYZED_STATES or not keep(row):
            continue
        rows.append(dict(row))

    # Every archived story source is known to have produced an analyzed story.
    for story in archive_stories:
        for source in story.get("sources") or []:
            published = source.get("published_at") or story.get("published_at")
            row = {
                "url": source.get("url"),
                "title": story.get("headline"),
                "description": story.get("summary_zh") or "",
                "domain": source.get("domain"),
                "source": source.get("name"),
                "published_at": published,
                "query_category": story.get("category"),
                "analysis_state": "analyzed_story",
                "story_id": story.get("id"),
                "last_seen_at": story.get("last_seen_at") or now.isoformat(timespec="seconds"),
            }
            if row.get("url") and keep(row):
                rows.append(row)

    # Deduplicate primarily by canonical URL. Entries without URLs use a conservative
    # title/date key, so the index stays compact without inventing event matches.
    dedup = {}
    for row in rows:
        url = _canon(core, row.get("url"))
        if url:
            key = "url:" + url
        else:
            title = " ".join(str(row.get("title") or "").lower().split())
            key = "title:" + title + "|" + str(row.get("published_at") or "")[:10]
        if not key or key == "title:|":
            continue
        existing = dedup.get(key)
        if existing is None:
            dedup[key] = row
            continue
        # Prefer analyzed_story over rejected/reused when the same URL has both states.
        rank = {"analyzed_story": 3, "history_reused": 2, "analyzed_rejected": 1}
        if rank.get(str(row.get("analysis_state")), 0) >= rank.get(str(existing.get("analysis_state")), 0):
            dedup[key] = row

    out = list(dedup.values())
    out.sort(key=lambda x: str(x.get("published_at") or ""), reverse=True)
    return out


def install(core):
    prior_history_filter = core.history_filter
    prior_save = core.save

    def history_filter(cands, existing, cache):
        history = _read(INDEX, {}).get("entries") or []
        # Feed the lightweight 180-day analyzed index into the existing safe-history
        # reuse layer. This does not send history to DeepSeek; it only prevents repeats.
        merged = []
        seen = set()
        for row in list(cache) + list(history):
            url = _canon(core, row.get("url"))
            key = url or (" ".join(str(row.get("title") or "").lower().split()) + "|" + str(row.get("published_at") or "")[:10])
            if key and key in seen:
                continue
            if key:
                seen.add(key)
            merged.append(row)
        return prior_history_filter(cands, existing, merged)

    def save(mode, stories, cache, run_stats):
        prior_save(mode, stories, cache, run_stats)
        try:
            payload = json.loads(core.OUT.read_text(encoding="utf-8"))
            now = core.NOW
            archive_stories = _archive_stories(core, payload.get("stories") or [], now)
            history_entries = _history_entries(core, payload, archive_stories, now)

            ARCHIVE.parent.mkdir(parents=True, exist_ok=True)
            ARCHIVE.write_text(
                json.dumps(
                    {
                        "generated_at_sgt": now.isoformat(timespec="seconds"),
                        "timezone": "Asia/Singapore",
                        "retention_days": ARCHIVE_DAYS,
                        "display_policy": "All validated stories retained regardless of importance score; news.html may filter client-side.",
                        "stories": archive_stories,
                    },
                    ensure_ascii=False,
                    indent=2,
                ) + "\n",
                encoding="utf-8",
            )
            INDEX.write_text(
                json.dumps(
                    {
                        "generated_at_sgt": now.isoformat(timespec="seconds"),
                        "timezone": "Asia/Singapore",
                        "retention_days": ARCHIVE_DAYS,
                        "purpose": "Model-free exact-URL/analyzed-state reuse; not a display feed.",
                        "entries": history_entries,
                    },
                    ensure_ascii=False,
                    indent=2,
                ) + "\n",
                encoding="utf-8",
            )

            policy = payload.setdefault("policy", {})
            policy["story_archive_days"] = ARCHIVE_DAYS
            policy["more_page_archive_includes_all_validated_stories"] = True
            policy["analyzed_history_index_days"] = ARCHIVE_DAYS
            policy["archive_does_not_expand_deepseek_candidate_budget"] = True
            stats = payload.setdefault("stats", {})
            stats["archive_180d_stories"] = len(archive_stories)
            stats["analyzed_history_index_entries"] = len(history_entries)
            core.OUT.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            print(
                "[news] archive180 stories=",
                len(archive_stories),
                "history_index=",
                len(history_entries),
            )
        except Exception as exc:
            print("[news] warning: 180-day archive/history update failed:", exc)

    core.history_filter = history_filter
    core.save = save
    return core
