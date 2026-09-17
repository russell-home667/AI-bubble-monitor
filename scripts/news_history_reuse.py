#!/usr/bin/env python3
"""Conservative history reuse, deterministic category locks, and event dedupe.

This layer is intentionally model-free. It runs before DeepSeek and adds:
7. analyzed-history reuse that never treats discovery-only cache rows as analyzed;
8. deterministic category locks for high-confidence macro/credit/policy events;
9. conservative cross-theme / cross-source event dedupe before model analysis.

It does not call any external model API and does not change the public eight-category
schema. Material updates with conflicting/new salient numbers are not history-reused.
"""
from __future__ import annotations

import re

RUN_STATS: dict[str, int] = {}
AI_SENT_URLS: set[str] = set()
CACHE_STATE_BY_URL: dict[str, str] = {}

ANALYZED_STATES = {
    "analyzed_story",
    "analyzed_rejected",
    "history_reused",
}

ENTITY_PATTERNS = {
    "fed": re.compile(r"\b(federal reserve|fomc|powell)\b", re.I),
    "nvidia": re.compile(r"\bnvidia\b", re.I),
    "amd": re.compile(r"\bamd\b", re.I),
    "broadcom": re.compile(r"\bbroadcom\b", re.I),
    "tsmc": re.compile(r"\btsmc\b", re.I),
    "micron": re.compile(r"\bmicron\b", re.I),
    "sk_hynix": re.compile(r"\bsk hynix\b", re.I),
    "microsoft": re.compile(r"\bmicrosoft\b", re.I),
    "meta": re.compile(r"\bmeta\b", re.I),
    "alphabet_google": re.compile(r"\b(alphabet|google)\b", re.I),
    "amazon": re.compile(r"\b(amazon|aws)\b", re.I),
    "oracle": re.compile(r"\boracle\b", re.I),
    "openai": re.compile(r"\bopenai\b", re.I),
    "anthropic": re.compile(r"\banthropic\b", re.I),
    "xai": re.compile(r"\bxai\b", re.I),
    "coreweave": re.compile(r"\bcoreweave\b", re.I),
    "data_center": re.compile(r"\b(data center|data centers|datacenter|datacenters)\b", re.I),
}

MACRO_LOCK_RE = re.compile(
    r"\b(federal reserve|fomc|powell|rate hike|rate cut|interest rates?|dot plot|"
    r"quantitative tightening|quantitative easing|treasury yields?|real yields?|"
    r"financial conditions|sofr|cpi|consumer price index|pce|core inflation|"
    r"payrolls?|unemployment|recession|gdp|ism|pmi|nasdaq|s&p 500|sox|vix|"
    r"risk-off|deleveraging|energy shock)\b",
    re.I,
)
CREDIT_LOCK_RE = re.compile(
    r"\b(high yield spread|hy oas|credit spreads?|private credit|refinancing|"
    r"default|distress|covenant|debt|bond|loan|credit facility|leverage)\b",
    re.I,
)
POLICY_LOCK_RE = re.compile(
    r"\b(export controls?|export restrictions?|sanctions?|tariffs?|antitrust|"
    r"regulation|regulatory|copyright|ai act|government ban)\b",
    re.I,
)


def _text(row):
    return f"{row.get('title', row.get('headline', ''))} | {row.get('description', row.get('summary_zh', ''))}"


def _entities(row):
    text = _text(row)
    return {name for name, pattern in ENTITY_PATTERNS.items() if pattern.search(text)}


def _event_tags(row, selection):
    tags = set(row.get("event_prior_tags") or [])
    if tags:
        return tags
    try:
        _, inferred = selection._event_prior(row)
        return set(inferred or [])
    except Exception:
        return set()


def _numbers_materially_conflict(core, a, b):
    na = core.salient_numbers(_text(a))
    nb = core.salient_numbers(_text(b))
    return bool(na and nb and na != nb)


def _same_event(core, selection, a, b):
    if not core.within_hours(a.get("published_at"), b.get("published_at"), 48):
        return False
    if _numbers_materially_conflict(core, a, b):
        return False

    title_a = a.get("title", a.get("headline", ""))
    title_b = b.get("title", b.get("headline", ""))
    title_sim = core.sim(title_a, title_b)
    tags_a = _event_tags(a, selection)
    tags_b = _event_tags(b, selection)
    shared_tags = tags_a & tags_b
    shared_entities = _entities(a) & _entities(b)

    # Strong semantic evidence: same deterministic event family plus a shared
    # named entity, or sufficiently similar headlines.
    if shared_tags and (shared_entities or title_sim >= 0.62):
        return True

    # Conservative fallback for the same public category. This catches the same
    # event reported with slightly different wording without merging unrelated news.
    if a.get("query_category") == b.get("query_category") and title_sim >= 0.80:
        return True

    return False


def _merge_candidate_metadata(dst, src, expanded):
    try:
        expanded._merge_discovery_metadata(dst, src)
    except Exception:
        pass

    dst["relevance_score"] = max(
        int(dst.get("relevance_score") or 0), int(src.get("relevance_score") or 0)
    )
    dst["event_prior_score"] = max(
        int(dst.get("event_prior_score") or 0), int(src.get("event_prior_score") or 0)
    )
    dst["selection_score"] = max(
        float(dst.get("selection_score") or 0), float(src.get("selection_score") or 0)
    )
    tags = list(dst.get("event_prior_tags") or [])
    for tag in src.get("event_prior_tags") or []:
        if tag not in tags:
            tags.append(tag)
    dst["event_prior_tags"] = tags

    sources = list(dst.get("corroborating_sources") or [])
    candidate_source = {
        "name": src.get("source"),
        "domain": src.get("domain"),
        "url": src.get("url"),
        "published_at": src.get("published_at"),
        "discovered_via": src.get("discovery_source"),
    }
    if candidate_source.get("url") and all(x.get("url") != candidate_source["url"] for x in sources):
        sources.append(candidate_source)
    dst["corroborating_sources"] = sources[:6]


def _dedupe_candidates(core, expanded, selection, rows):
    ordered = sorted(rows, key=selection.candidate_rank, reverse=True)
    kept = []
    merged = 0

    for row in ordered:
        match = next((x for x in kept if _same_event(core, selection, row, x)), None)
        if match is None:
            kept.append(row)
            continue
        _merge_candidate_metadata(match, row, expanded)
        merged += 1

    # Reassign stable per-run candidate ids after merging so the model never sees
    # duplicate or missing candidate ids.
    for idx, row in enumerate(kept, start=1):
        row["id"] = f"c{idx:03d}"

    return kept, merged


def _existing_story_urls(core, stories):
    out = set()
    for story in stories:
        for source in story.get("sources") or []:
            url = core.canon_url(source.get("url"))
            if url:
                out.add(url)
    return out


def _safe_history_cache(core, existing, cache):
    story_urls = _existing_story_urls(core, existing)
    safe = []
    unsafe = 0
    promoted_legacy = 0

    CACHE_STATE_BY_URL.clear()
    for row in cache:
        url = core.canon_url(row.get("url"))
        state = str(row.get("analysis_state") or "").strip()
        if url:
            CACHE_STATE_BY_URL[url] = state

        if state in ANALYZED_STATES:
            safe.append(row)
        elif url and url in story_urls:
            # Legacy rows predate analysis_state. A source URL already attached to a
            # persisted story is objective evidence that it was analyzed/reused.
            clone = dict(row)
            clone["analysis_state"] = "analyzed_story"
            safe.append(clone)
            promoted_legacy += 1
        else:
            unsafe += 1

    return safe, unsafe, promoted_legacy


def _history_event_reuse(core, selection, candidates, safe_cache):
    kept = []
    reused = 0
    exact = 0

    for cand in candidates:
        cu = core.canon_url(cand.get("url"))
        match = None
        for old in safe_cache:
            ou = core.canon_url(old.get("url"))
            if cu and ou and cu == ou:
                match = old
                exact += 1
                break
            if _same_event(core, selection, cand, old):
                match = old
                break
        if match is not None:
            reused += 1
            continue
        kept.append(cand)

    return kept, reused, exact


def _deterministic_category(candidate):
    if candidate.get("category_locked"):
        return None, None

    text = _text(candidate)
    signal = candidate.get("signal_type")
    query_category = candidate.get("query_category")

    if signal == "systemic_macro" and query_category == "Macro / Regulation" and MACRO_LOCK_RE.search(text):
        return "Macro / Regulation", "systemic_macro"

    if signal == "financial_conditions" and query_category == "AI Credit / Debt" and CREDIT_LOCK_RE.search(text):
        return "AI Credit / Debt", "credit_financial_conditions"

    if signal == "policy_geopolitics" and query_category == "Macro / Regulation" and POLICY_LOCK_RE.search(text):
        return "Macro / Regulation", "policy_geopolitics"

    return None, None


def install(core, expanded, selection):
    """Install history reuse, deterministic locks, and cross-theme dedupe."""
    prior_collect = core.collect
    prior_history_filter = core.history_filter
    prior_updated_cache = core.updated_cache
    prior_save = core.save

    def collect(mode):
        rows = prior_collect(mode)
        deduped, merged = _dedupe_candidates(core, expanded, selection, rows)
        RUN_STATS.clear()
        RUN_STATS.update(
            {
                "cross_theme_event_dedupe_input": len(rows),
                "cross_theme_event_dedupe_kept": len(deduped),
                "cross_theme_event_dedupe_merged": merged,
            }
        )
        print(
            "[news] event dedupe input=",
            len(rows),
            "kept=",
            len(deduped),
            "merged=",
            merged,
        )
        return deduped

    def history_filter(cands, existing, cache):
        safe_cache, unsafe_ignored, promoted_legacy = _safe_history_cache(core, existing, cache)
        prefiltered, event_reused, exact_reused = _history_event_reuse(
            core, selection, cands, safe_cache
        )

        ai_cands, stories, stats = prior_history_filter(prefiltered, existing, safe_cache)

        deterministic_locked = 0
        deterministic_macro_locked = 0
        deterministic_credit_locked = 0
        deterministic_policy_locked = 0
        for candidate in ai_cands:
            category, reason = _deterministic_category(candidate)
            if not category:
                continue
            candidate["category_locked"] = True
            candidate["fixed_category"] = category
            candidate["deterministic_lock_reason"] = reason
            deterministic_locked += 1
            if reason == "systemic_macro":
                deterministic_macro_locked += 1
            elif reason == "credit_financial_conditions":
                deterministic_credit_locked += 1
            elif reason == "policy_geopolitics":
                deterministic_policy_locked += 1

        AI_SENT_URLS.clear()
        for candidate in ai_cands:
            url = core.canon_url(candidate.get("url"))
            if url:
                AI_SENT_URLS.add(url)

        stats.update(RUN_STATS)
        stats["discovered_candidates"] = len(cands)
        stats["safe_analyzed_cache_rows"] = len(safe_cache)
        stats["discovery_only_cache_rows_ignored"] = unsafe_ignored
        stats["legacy_cache_rows_promoted_from_story_source"] = promoted_legacy
        stats["event_history_reused_candidates"] = event_reused
        stats["event_history_exact_url_reuse"] = exact_reused
        stats["deterministic_category_locked_candidates"] = deterministic_locked
        stats["deterministic_macro_locked_candidates"] = deterministic_macro_locked
        stats["deterministic_credit_locked_candidates"] = deterministic_credit_locked
        stats["deterministic_policy_locked_candidates"] = deterministic_policy_locked
        stats["category_locked_candidates"] = sum(
            bool(x.get("category_locked")) for x in ai_cands
        )
        stats["category_ai_judgment_candidates"] = len(ai_cands) - stats["category_locked_candidates"]

        print(
            "[news] safe-history event_reused=",
            event_reused,
            "unsafe_cache_ignored=",
            unsafe_ignored,
            "deterministic_locked=",
            deterministic_locked,
        )
        return ai_cands, stories, stats

    def updated_cache(old_cache, cands):
        rows = prior_updated_cache(old_cache, cands)
        # Do not mark analysis state here: at this point the model has not completed.
        # The save wrapper below marks state only after the final payload exists.
        return rows

    def save(mode, stories, cache, run_stats):
        prior_save(mode, stories, cache, run_stats)

        try:
            payload = core.json.loads(core.OUT.read_text(encoding="utf-8"))
            stats = payload.get("stats") or {}
            degraded = bool(stats.get("analysis_degraded"))
            story_urls = _existing_story_urls(core, payload.get("stories") or [])

            for row in payload.get("candidate_cache") or []:
                url = core.canon_url(row.get("url"))
                previous = CACHE_STATE_BY_URL.get(url, "") if url else ""

                if url and url in story_urls:
                    row["analysis_state"] = "analyzed_story"
                elif url and url in AI_SENT_URLS and not degraded:
                    # The candidate reached the model successfully but was not kept
                    # as an importance>=50 story. Reusing this rejection saves cost.
                    row["analysis_state"] = "analyzed_rejected"
                elif previous in ANALYZED_STATES:
                    row["analysis_state"] = previous
                else:
                    row["analysis_state"] = "discovered_only"

            policy = payload.setdefault("policy", {})
            policy["analyzed_history_only_reuse"] = True
            policy["cross_theme_event_dedupe"] = True
            policy["material_number_change_reanalysis"] = True
            policy["deterministic_macro_credit_policy_category_lock"] = True
            policy["discovery_only_cache_is_not_analysis"] = True
            payload["acquisition"] = (
                "Bing News RSS + Google News RSS + GDELT DOC API discovery; expanded macro/AI theme matrix; "
                "trusted-domain whitelist; Python relevance + event prior; cross-theme event dedupe; "
                "analyzed-history-only reuse; deterministic macro/credit/policy category lock; "
                "existing eight-category DeepSeek scoring; fixed one-chunk candidate budget"
            )
            core.OUT.write_text(
                core.json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        except Exception as exc:
            print("[news] warning: could not annotate history/dedupe policy:", exc)

    core.collect = collect
    core.history_filter = history_filter
    core.updated_cache = updated_cache
    core.save = save
    return core
