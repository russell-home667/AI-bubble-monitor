#!/usr/bin/env python3
"""Free-access source policy for the AI Bubble News Radar.

Paid-wall publishers remain valid discovery leads, but they are never emitted as
Dashboard story sources. A story must have at least one trusted, non-paywall source
to survive final merge. Preferred free professional media and official/IR sources
are ranked ahead of other trusted free sources.

This module is model-free and does not call DeepSeek or any external API.
"""
from __future__ import annotations

RUN_STATS: dict[str, int] = {}

# User-selected free/professional media pool. Domains are deliberately narrow where
# possible (for example finance.yahoo.com rather than all of yahoo.com).
FREE_MEDIA = {
    "apnews.com": "Associated Press",
    "cnbc.com": "CNBC",
    "techcrunch.com": "TechCrunch",
    "semafor.com": "Semafor",
    "theguardian.com": "The Guardian",
    "theverge.com": "The Verge",
    "finance.yahoo.com": "Yahoo Finance",
    "investing.com": "Investing.com",
    "channelnewsasia.com": "CNA",
    "reuters.com": "Reuters",
    "cls.cn": "财联社",
}

# These remain in the discovery whitelist only. They cannot appear in final story
# links and cannot, by themselves, make an event eligible for the dashboard.
DISCOVERY_ONLY_PAYWALL = {
    "bloomberg.com": "Bloomberg",
    "wsj.com": "Wall Street Journal",
    "barrons.com": "Barron's",
    "fortune.com": "Fortune",
    "ft.com": "Financial Times",
    "economist.com": "The Economist",
    "theinformation.com": "The Information",
    "nytimes.com": "New York Times",
}

# Display preference within the free pool. Official/company primary sources are
# handled separately and rank above media when they directly support the event.
FREE_MEDIA_PRIORITY = {
    "apnews.com": 116,
    "reuters.com": 115,
    "cnbc.com": 112,
    "techcrunch.com": 108,
    "semafor.com": 108,
    "theguardian.com": 106,
    "theverge.com": 106,
    "channelnewsasia.com": 105,
    "cls.cn": 105,
    "finance.yahoo.com": 102,
    "investing.com": 100,
}


def _domain(core, source_or_candidate) -> str:
    domain = str((source_or_candidate or {}).get("domain") or "").lower().strip().removeprefix("www.")
    if domain:
        return domain
    try:
        return (core.urlparse(str((source_or_candidate or {}).get("url") or "")).hostname or "").lower().removeprefix("www.")
    except Exception:
        return ""


def _matches(domain: str, roots) -> str | None:
    for root in roots:
        if domain == root or domain.endswith("." + root):
            return root
    return None


def is_paywall(core, source_or_candidate) -> bool:
    return bool(_matches(_domain(core, source_or_candidate), DISCOVERY_ONLY_PAYWALL))


def is_display_eligible(core, source_or_candidate) -> bool:
    return bool(core.trusted_source_obj(source_or_candidate)) and not is_paywall(core, source_or_candidate)


def display_rank(core, source) -> int:
    domain = _domain(core, source)
    root = _matches(domain, FREE_MEDIA_PRIORITY)
    if root:
        return FREE_MEDIA_PRIORITY[root]

    # Official government and company/IR sources already present in TRUST remain
    # free display sources and are preferred when they are the primary evidence.
    trusted = core.trusted_source_obj(source)
    if not trusted:
        return -1000
    if domain.endswith(".gov") or domain in {
        "federalreserve.gov", "sec.gov", "commerce.gov", "energy.gov",
        "whitehouse.gov", "congress.gov", "europa.eu", "ec.europa.eu", "gov.uk",
    }:
        return 125
    if domain in {
        "openai.com", "anthropic.com", "x.ai", "microsoft.com", "abc.xyz",
        "blog.google", "google.com", "aboutamazon.com", "amazon.com", "meta.com",
        "about.fb.com", "oracle.com", "nvidia.com", "amd.com", "broadcom.com",
        "tsmc.com", "coreweave.com",
    }:
        return 122
    return 90


def _source_obj(core, row):
    return core.source_from_candidate(row)


def _clean_story(core, story):
    free_sources = []
    seen = set()
    removed_paywall = 0
    for source in story.get("sources") or []:
        url = core.canon_url(source.get("url"))
        if not is_display_eligible(core, source):
            if is_paywall(core, source):
                removed_paywall += 1
            continue
        if url and url in seen:
            continue
        if url:
            seen.add(url)
        free_sources.append(dict(source))

    if not free_sources:
        return None, removed_paywall

    free_sources.sort(key=lambda src: display_rank(core, src), reverse=True)
    out = dict(story)
    out["sources"] = free_sources[:4]
    return out, removed_paywall


def install(core, selection, history):
    """Install free-source preference and paywall discovery-only enforcement."""
    # Expand trusted discovery pool with the user's preferred free media while
    # retaining paywall publishers as discovery leads.
    core.TRUST.update(FREE_MEDIA)
    core.TRUST.update(DISCOVERY_ONLY_PAYWALL)

    # Python-side ranking: free professional media win limited model slots more
    # often; paywall leads remain eligible but receive a negative source bonus.
    for domain, score in {
        "apnews.com": 10,
        "reuters.com": 10,
        "cnbc.com": 9,
        "techcrunch.com": 8,
        "semafor.com": 8,
        "theguardian.com": 8,
        "theverge.com": 8,
        "channelnewsasia.com": 8,
        "cls.cn": 8,
        "finance.yahoo.com": 7,
        "investing.com": 7,
    }.items():
        selection.SOURCE_PREMIUM[domain] = score
    for domain in DISCOVERY_ONLY_PAYWALL:
        selection.SOURCE_PREMIUM[domain] = -6

    # If cross-source event dedupe merges a paywall lead with a free report, promote
    # the free report to be the surviving primary candidate. Preserve the paid lead
    # only as internal corroboration metadata; it will not be displayed.
    prior_merge_metadata = history._merge_candidate_metadata

    def merge_candidate_metadata(dst, src, expanded):
        dst_paid = is_paywall(core, dst)
        src_free = is_display_eligible(core, src)
        old_dst_source = _source_obj(core, dst) if dst_paid else None

        prior_merge_metadata(dst, src, expanded)

        if dst_paid and src_free:
            # Keep merged discovery/event metadata, but replace article-facing fields
            # with the free candidate so the model and downstream story builder have
            # a directly accessible primary source.
            for key in (
                "title", "description", "source", "domain", "url", "published_at",
                "discovery_source", "query_category", "discovery_theme", "signal_type",
                "systemic_macro", "primary_query_priority",
            ):
                if key in src:
                    dst[key] = src.get(key)

            extras = []
            primary_url = core.canon_url(dst.get("url"))
            for item in list(dst.get("corroborating_sources") or []) + ([old_dst_source] if old_dst_source else []):
                if not item or not item.get("url"):
                    continue
                if core.canon_url(item.get("url")) == primary_url:
                    continue
                if all(core.canon_url(x.get("url")) != core.canon_url(item.get("url")) for x in extras):
                    extras.append(dict(item))
            dst["corroborating_sources"] = extras[:6]

    history._merge_candidate_metadata = merge_candidate_metadata

    prior_collect = core.collect
    prior_merge = core.merge
    prior_save = core.save

    def collect(mode):
        rows = prior_collect(mode)
        RUN_STATS.clear()
        RUN_STATS["preferred_free_media_candidates"] = sum(
            bool(_matches(_domain(core, row), FREE_MEDIA)) for row in rows
        )
        RUN_STATS["paywall_discovery_lead_candidates"] = sum(
            is_paywall(core, row) for row in rows
        )
        return rows

    def merge(new, existing):
        stories = prior_merge(new, existing)
        kept = []
        paywall_only_dropped = 0
        paywall_sources_removed = 0

        for story in stories:
            cleaned, removed = _clean_story(core, story)
            paywall_sources_removed += removed
            if cleaned is None:
                paywall_only_dropped += 1
                continue
            kept.append(cleaned)

        RUN_STATS["paywall_only_stories_dropped"] = paywall_only_dropped
        RUN_STATS["paywall_sources_removed_from_display"] = paywall_sources_removed
        RUN_STATS["stories_with_free_display_source"] = len(kept)
        return kept

    def save(mode, stories, cache, run_stats):
        enriched = dict(run_stats)
        enriched.update(RUN_STATS)
        prior_save(mode, stories, cache, enriched)
        try:
            payload = core.json.loads(core.OUT.read_text(encoding="utf-8"))

            # Integrity/history save wrappers can append corroborating sources after
            # merge. Re-sanitize the final payload here so paywall publishers remain
            # truly discovery-only and never reappear as dashboard links.
            final_stories = []
            removed_after_save = 0
            dropped_after_save = 0
            for story in payload.get("stories") or []:
                cleaned, removed = _clean_story(core, story)
                removed_after_save += removed
                if cleaned is None:
                    dropped_after_save += 1
                    continue
                final_stories.append(cleaned)
            payload["stories"] = final_stories

            stats = payload.setdefault("stats", {})
            stats["paywall_sources_removed_after_save"] = removed_after_save
            stats["paywall_only_stories_dropped_after_save"] = dropped_after_save
            stats["stored_stories"] = len(final_stories)
            stats["important_7d"] = sum(int(s.get("importance_score", 0)) >= 60 for s in final_stories)
            stats["critical_7d"] = sum(bool(s.get("critical")) for s in final_stories)

            policy = payload.setdefault("policy", {})
            policy["free_source_first"] = True
            policy["paywall_publishers_discovery_only"] = sorted(DISCOVERY_ONLY_PAYWALL)
            policy["preferred_free_media"] = sorted(FREE_MEDIA)
            policy["dashboard_requires_free_trusted_source"] = True
            policy["paywall_sources_hidden_from_dashboard"] = True
            payload["source_policy"] = {
                "preferred_free_media": FREE_MEDIA,
                "discovery_only_paywall": DISCOVERY_ONLY_PAYWALL,
                "official_and_company_primary_sources_allowed": True,
            }
            core.OUT.write_text(
                core.json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        except Exception as exc:
            print("[news] warning: could not enforce/annotate source policy:", exc)

    core.collect = collect
    core.merge = merge
    core.save = save
    return core
