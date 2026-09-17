#!/usr/bin/env python3
"""Tiered scan policy, auditable run statistics, and discovery health diagnostics.

This layer is model-free and does not call DeepSeek. It adds the remaining scan
controls around the already-installed discovery/selection/history pipeline:
10. deep vs incremental discovery scope: 08:00 deep runs the full query matrix;
    incremental scans keep full coverage for fast-moving themes and one highest-
    priority query for slower themes. Existing 7d/30h windows and Bing page depth
    remain unchanged in the expanded discovery layer.
11. auditable per-run statistics covering active query specs, themes, sources,
    domains, signal types, and downstream model-budget utilization.
12. discovery-health diagnostics for Bing News RSS, Google News RSS and GDELT,
    including call/success/failure/row counts and non-fatal health alerts.

The DeepSeek candidate budget remains controlled by news_candidate_selection.py.
"""
from __future__ import annotations

from collections import Counter

# Fast-moving themes keep every configured query on 12:30 / 19:00 incremental runs.
# Slower-moving themes still keep their single highest-priority query, so no theme is
# completely blind between the 08:00 deep scans.
INCREMENTAL_FULL_THEMES = {
    "Rates / Liquidity",
    "Credit / Financial Stress",
    "Market Valuation / Risk Appetite",
    "AI CAPEX",
    "Compute Supply / Chips / Custom Silicon",
    "Data Center / Power",
    "Enterprise Adoption / Monetization",
    "Regulation / Geopolitics",
    "Asset Economics / Capacity Cuts",
}

SOURCE_FUNCTIONS = {
    "Bing News RSS": "bing_page",
    "Google News RSS": "google_page",
    "GDELT DOC API": "gdelt_page",
}

RUN_AUDIT: dict = {}
SOURCE_HEALTH: dict[str, dict[str, int]] = {}


def _specs_for_mode(expanded, mode: str):
    all_specs = list(expanded.DISCOVERY_MATRIX)
    if mode == "deep":
        return all_specs

    # Keep all queries for fast-moving themes. For slower themes, choose the one
    # highest-priority query; ties keep the first configured query for stability.
    best_by_theme = {}
    active = []
    for spec in all_specs:
        theme = spec.get("theme")
        if theme in INCREMENTAL_FULL_THEMES:
            active.append(spec)
            continue
        previous = best_by_theme.get(theme)
        if previous is None or int(spec.get("priority") or 0) > int(previous.get("priority") or 0):
            best_by_theme[theme] = spec

    active.extend(best_by_theme.values())
    # Preserve deterministic ordering based on the full matrix rather than priority
    # sorting, because the expanded collector already handles event priority later.
    active_ids = {id(x) for x in active}
    return [x for x in all_specs if id(x) in active_ids]


def _reset_source_health():
    SOURCE_HEALTH.clear()
    for source in SOURCE_FUNCTIONS:
        SOURCE_HEALTH[source] = {
            "calls": 0,
            "successes": 0,
            "failures": 0,
            "returned_rows": 0,
        }


def _instrument_sources(core):
    originals = {}
    for source, attr in SOURCE_FUNCTIONS.items():
        original = getattr(core, attr)
        originals[attr] = original

        def wrapper(*args, _source=source, _original=original, **kwargs):
            stats = SOURCE_HEALTH[_source]
            stats["calls"] += 1
            try:
                rows = _original(*args, **kwargs)
                stats["successes"] += 1
                stats["returned_rows"] += len(rows or [])
                return rows
            except Exception:
                stats["failures"] += 1
                raise

        setattr(core, attr, wrapper)
    return originals


def _restore_sources(core, originals):
    for attr, original in originals.items():
        setattr(core, attr, original)


def _count_multi(rows, plural_key, singular_key):
    counter = Counter()
    for row in rows:
        values = row.get(plural_key) or []
        if not values and row.get(singular_key):
            values = [row.get(singular_key)]
        for value in values:
            if value:
                counter[str(value)] += 1
    return dict(sorted(counter.items(), key=lambda item: (-item[1], item[0])))


def _health(mode: str, rows, active_specs):
    alerts = []
    severity = "healthy"

    for source, stats in SOURCE_HEALTH.items():
        calls = int(stats.get("calls") or 0)
        successes = int(stats.get("successes") or 0)
        failures = int(stats.get("failures") or 0)
        returned = int(stats.get("returned_rows") or 0)

        if calls and successes == 0:
            alerts.append(f"{source}: all discovery calls failed")
            severity = "degraded"
        elif calls and failures / calls >= 0.25:
            alerts.append(f"{source}: elevated discovery failure ratio ({failures}/{calls})")
            if severity != "degraded":
                severity = "warning"

        if successes and returned == 0:
            alerts.append(f"{source}: successful calls returned zero trusted rows")
            if severity == "healthy":
                severity = "warning"

    if not rows:
        alerts.append("Final pre-model candidate set is empty")
        severity = "degraded"

    active_themes = {str(x.get("theme")) for x in active_specs if x.get("theme")}
    observed_themes = set()
    for row in rows:
        observed_themes.update(str(x) for x in (row.get("discovery_themes") or []) if x)
        if row.get("discovery_theme"):
            observed_themes.add(str(row.get("discovery_theme")))
    missing = sorted(active_themes - observed_themes)

    # Missing themes are observational, not automatically errors: a quiet theme can
    # legitimately have no relevant trusted news in the time window. Escalate only
    # when a deep scan sees less than half of configured themes represented.
    if mode == "deep" and active_themes and len(observed_themes) < max(1, len(active_themes) // 2):
        alerts.append(
            f"Deep scan represented only {len(observed_themes)}/{len(active_themes)} active themes"
        )
        if severity == "healthy":
            severity = "warning"

    return {
        "status": severity,
        "alerts": alerts,
        "source_health": {k: dict(v) for k, v in SOURCE_HEALTH.items()},
        "active_theme_count": len(active_themes),
        "observed_theme_count": len(observed_themes),
        "missing_observed_themes": missing,
    }


def install(core, expanded, selection):
    """Install tiered scanning and audit/health reporting around the final pipeline."""
    prior_collect = core.collect
    prior_save = core.save

    def collect(mode):
        original_matrix = expanded.DISCOVERY_MATRIX
        active_specs = _specs_for_mode(expanded, mode)
        expanded.DISCOVERY_MATRIX = active_specs
        _reset_source_health()
        originals = _instrument_sources(core)

        try:
            rows = prior_collect(mode)
        finally:
            _restore_sources(core, originals)
            expanded.DISCOVERY_MATRIX = original_matrix

        all_themes = sorted({str(x.get("theme")) for x in original_matrix if x.get("theme")})
        active_themes = sorted({str(x.get("theme")) for x in active_specs if x.get("theme")})
        health = _health(mode, rows, active_specs)

        RUN_AUDIT.clear()
        RUN_AUDIT.update(
            {
                "scan_mode": mode,
                "query_specs_total": len(original_matrix),
                "query_specs_active": len(active_specs),
                "themes_total": len(all_themes),
                "themes_active": active_themes,
                "incremental_full_themes": sorted(INCREMENTAL_FULL_THEMES),
                "candidate_count_pre_model_pipeline": len(rows),
                "candidates_by_theme": _count_multi(rows, "discovery_themes", "discovery_theme"),
                "candidates_by_signal_type": _count_multi(rows, "signal_types", "signal_type"),
                "candidates_by_discovery_source": dict(
                    sorted(
                        Counter(str(x.get("discovery_source") or "unknown") for x in rows).items(),
                        key=lambda item: (-item[1], item[0]),
                    )
                ),
                "candidates_by_domain": dict(
                    sorted(
                        Counter(str(x.get("domain") or "unknown") for x in rows).items(),
                        key=lambda item: (-item[1], item[0]),
                    )
                ),
                "systemic_macro_candidates": sum(bool(x.get("systemic_macro")) for x in rows),
                "discovery_health": health,
            }
        )

        print(
            "[news] scan policy mode=",
            mode,
            "query_specs=",
            f"{len(active_specs)}/{len(original_matrix)}",
            "themes=",
            len(active_themes),
            "health=",
            health["status"],
        )
        return rows

    def save(mode, stories, cache, run_stats):
        enriched_stats = dict(run_stats)
        enriched_stats["scan_query_specs_total"] = int(RUN_AUDIT.get("query_specs_total") or 0)
        enriched_stats["scan_query_specs_active"] = int(RUN_AUDIT.get("query_specs_active") or 0)
        enriched_stats["scan_themes_total"] = int(RUN_AUDIT.get("themes_total") or 0)
        enriched_stats["scan_themes_active"] = len(RUN_AUDIT.get("themes_active") or [])
        enriched_stats["discovery_health_status"] = (
            (RUN_AUDIT.get("discovery_health") or {}).get("status") or "unknown"
        )
        prior_save(mode, stories, cache, enriched_stats)

        try:
            payload = core.json.loads(core.OUT.read_text(encoding="utf-8"))
            audit = dict(RUN_AUDIT)
            stats = payload.get("stats") or {}
            audit["downstream"] = {
                "history_reused_candidates": int(stats.get("reused_history_candidates") or 0),
                "event_history_reused_candidates": int(stats.get("event_history_reused_candidates") or 0),
                "cross_theme_event_dedupe_merged": int(stats.get("cross_theme_event_dedupe_merged") or 0),
                "relevance_filtered_candidates": int(stats.get("relevance_filtered_candidates") or 0),
                "deepseek_candidate_budget": int(stats.get("deepseek_candidate_budget") or selection.MODEL_CANDIDATE_BUDGET.get(mode, 0)),
                "deepseek_candidates_post_selection": int(stats.get("deepseek_candidates_post_selection") or stats.get("ai_candidates") or 0),
                "deepseek_chunks": int(stats.get("deepseek_chunks") or 0),
                "analysis_degraded": bool(stats.get("analysis_degraded")),
            }
            payload["news_run_audit"] = audit
            payload["discovery_health"] = audit.get("discovery_health") or {}

            policy = payload.setdefault("policy", {})
            policy["tiered_deep_incremental_discovery"] = True
            policy["deep_scan_full_query_matrix"] = True
            policy["incremental_fast_theme_full_slow_theme_best_query"] = True
            policy["auditable_news_run_stats"] = True
            policy["discovery_health_diagnostics"] = True
            policy["discovery_health_is_nonfatal_except_existing_empty_deep_guard"] = True

            payload["acquisition"] = (
                "Bing News RSS + Google News RSS + GDELT DOC API; tiered deep/incremental query scope; "
                "expanded macro/AI theme matrix; trusted-domain whitelist; Python relevance + event prior; "
                "cross-theme dedupe; analyzed-history reuse; deterministic category lock; fixed one-chunk "
                "DeepSeek budget; auditable discovery-health diagnostics"
            )
            core.OUT.write_text(
                core.json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        except Exception as exc:
            print("[news] warning: could not annotate scan audit/health policy:", exc)

    core.collect = collect
    core.save = save
    return core
