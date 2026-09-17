#!/usr/bin/env python3
"""Static integrity guard for the AI Bubble News Radar pipeline.

This module is model-free. It tightens three interactions discovered during the
1-12 pipeline audit:
- exact-URL history reuse must still verify title/number compatibility so an
  updated article with materially changed facts can be re-analysed;
- cross-source event dedupe requires meaningful headline similarity instead of
  merging merely because a broad event tag and entity match;
- corroborating sources merged before DeepSeek are preserved on final stories.

The module does not call DeepSeek or any external API.
"""
from __future__ import annotations

CORROBORATING_BY_URL: dict[str, list[dict]] = {}
RUN_STATS: dict[str, int] = {}


def _row_text(history, row):
    return history._text(row)


def _safer_same_event(core, history, selection, a, b):
    if not core.within_hours(a.get("published_at"), b.get("published_at"), 48):
        return False

    text_a = _row_text(history, a)
    text_b = _row_text(history, b)
    nums_a = core.salient_numbers(text_a)
    nums_b = core.salient_numbers(text_b)
    # If both reports contain concrete numbers and they differ, treat the newer
    # report as potentially material rather than collapsing it into history.
    if nums_a and nums_b and nums_a != nums_b:
        return False

    title_a = a.get("title", a.get("headline", ""))
    title_b = b.get("title", b.get("headline", ""))
    title_sim = core.sim(title_a, title_b)
    tags_a = history._event_tags(a, selection)
    tags_b = history._event_tags(b, selection)
    shared_tags = tags_a & tags_b
    shared_entities = history._entities(a) & history._entities(b)

    # A shared broad event family + entity is not enough by itself. Requiring a
    # headline-similarity floor prevents, for example, two unrelated NVIDIA demand
    # stories within 48 hours from being merged solely because both are tagged as
    # ai_compute_demand_supply.
    if shared_tags and shared_entities and title_sim >= 0.42:
        return True
    if shared_tags and title_sim >= 0.68:
        return True
    if a.get("query_category") == b.get("query_category") and title_sim >= 0.84:
        return True
    return False


def _safe_history_reuse(core, history, candidates, safe_cache):
    """Reuse only strong cache matches; leave cross-source story enrichment to core.

    The base core.history_filter already knows how to attach a new source to an
    existing story. Therefore this prefilter intentionally avoids broad cross-domain
    reuse, which previously could discard a useful corroborating source before the
    core had a chance to attach it.
    """
    kept = []
    reused = 0
    exact = 0

    for cand in candidates:
        cu = core.canon_url(cand.get("url"))
        ctitle = cand.get("title", "")
        ctext = _row_text(history, cand)
        match = None

        for old in safe_cache:
            ou = core.canon_url(old.get("url"))
            otitle = old.get("title", "")
            otext = _row_text(history, old)

            if cu and ou and cu == ou:
                # Same URL is reusable only when the article still looks like the
                # same factual version. A changed headline or salient number forces
                # re-analysis instead of silently reusing stale judgment.
                if core.sim(ctitle, otitle) >= 0.72 and core.numbers_compatible(ctext, otext):
                    match = old
                    exact += 1
                    break
                continue

            # Conservative same-publisher fallback. Cross-publisher candidates are
            # deliberately left for the base history filter so it can enrich the
            # persisted story with the new source when appropriate.
            if (
                cand.get("domain")
                and cand.get("domain") == old.get("domain")
                and core.within_hours(cand.get("published_at"), old.get("published_at"), 96)
                and core.sim(ctitle, otitle) >= 0.92
                and core.numbers_compatible(ctext, otext)
            ):
                match = old
                break

        if match is not None:
            reused += 1
        else:
            kept.append(cand)

    return kept, reused, exact


def install(core, expanded, selection, history):
    """Install audit fixes after history layer and before scan-policy layer."""
    prior_collect = core.collect
    prior_save = core.save

    # Existing history-layer closures resolve these module globals at runtime, so
    # replacing them here tightens both same-run event dedupe and cache prefiltering
    # without adding another model call or rebuilding the pipeline.
    history._same_event = lambda core_arg, selection_arg, a, b: _safer_same_event(
        core_arg, history, selection_arg, a, b
    )
    history._history_event_reuse = (
        lambda core_arg, selection_arg, candidates, safe_cache: _safe_history_reuse(
            core_arg, history, candidates, safe_cache
        )
    )

    def collect(mode):
        rows = prior_collect(mode)
        CORROBORATING_BY_URL.clear()
        merged_source_count = 0
        for row in rows:
            url = core.canon_url(row.get("url"))
            sources = [dict(x) for x in (row.get("corroborating_sources") or []) if x.get("url")]
            if url and sources:
                CORROBORATING_BY_URL[url] = sources
                merged_source_count += len(sources)
        RUN_STATS.clear()
        RUN_STATS["corroborating_sources_buffered"] = merged_source_count
        return rows

    def save(mode, stories, cache, run_stats):
        run_stats = dict(run_stats)
        run_stats.update(RUN_STATS)
        prior_save(mode, stories, cache, run_stats)

        try:
            payload = core.json.loads(core.OUT.read_text(encoding="utf-8"))
            appended = 0
            for story in payload.get("stories") or []:
                existing_sources = [dict(x) for x in (story.get("sources") or [])]
                seen = {core.canon_url(x.get("url")) for x in existing_sources if x.get("url")}
                extras = []
                for source in existing_sources:
                    primary_url = core.canon_url(source.get("url"))
                    for extra in CORROBORATING_BY_URL.get(primary_url, []):
                        extra_url = core.canon_url(extra.get("url"))
                        if not extra_url or extra_url in seen:
                            continue
                        # All candidates entering cross-source dedupe have already
                        # passed the trusted-source whitelist, but re-check here to
                        # keep this enrichment invariant explicit.
                        if not core.trusted_source_obj(extra):
                            continue
                        seen.add(extra_url)
                        extras.append(dict(extra))
                        appended += 1
                if extras:
                    story["sources"] = (existing_sources + extras)[:4]

            # Preserve corroboration metadata on the primary cache row as an audit
            # trail even though aliases are not treated as independently analysed.
            for row in payload.get("candidate_cache") or []:
                url = core.canon_url(row.get("url"))
                extras = CORROBORATING_BY_URL.get(url, [])
                if extras:
                    row["corroborating_sources"] = extras[:6]

            payload.setdefault("stats", {})["corroborating_sources_preserved"] = appended
            policy = payload.setdefault("policy", {})
            policy["exact_url_material_change_reanalysis"] = True
            policy["conservative_cross_source_event_merge"] = True
            policy["corroborating_sources_preserved"] = True
            core.OUT.write_text(
                core.json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        except Exception as exc:
            print("[news] warning: integrity-guard annotation failed:", exc)

    core.collect = collect
    core.save = save
    return core
