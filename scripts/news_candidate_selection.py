#!/usr/bin/env python3
"""Deterministic pre-DeepSeek selection for the AI Bubble News Radar.

This layer runs after expanded discovery and before model analysis. It:
4. scores concrete AI-bubble relevance in Python and filters low-signal candidates;
5. assigns deterministic event-importance priors for systemically important events;
6. enforces a fixed DeepSeek candidate budget so broader discovery cannot create
   additional normal model-analysis chunks.

No new fields from this module are added to the DeepSeek prompt; they are selection
metadata only.
"""
from __future__ import annotations

import re

MODEL_CANDIDATE_BUDGET = {"deep": 24, "incremental": 30}
RELEVANCE_MIN_SCORE = {"deep": 54, "incremental": 58}
HIGH_PRIOR_OVERRIDE = 92

RUN_STATS: dict[str, int | float] = {}

AI_CONTEXT_RE = re.compile(
    r"\b(ai|artificial intelligence|openai|anthropic|xai|nvidia|gpu|gpus|hbm|"
    r"data center|data centers|datacenter|datacenters|hyperscaler|copilot|chatgpt|"
    r"claude|gemini|semiconductor|tsmc|broadcom|amd|oracle|microsoft|meta|"
    r"alphabet|google|amazon|coreweave)\b",
    re.I,
)

SYSTEMIC_MACRO_RE = re.compile(
    r"\b(federal reserve|fomc|powell|rate hike|rate cut|interest rates?|dot plot|"
    r"quantitative tightening|quantitative easing|treasury yields?|real yields?|"
    r"financial conditions|sofr|cpi|consumer price index|pce|core inflation|"
    r"payrolls?|unemployment|recession|gdp|ism|pmi|high yield spread|hy oas|"
    r"credit spreads?|private credit|refinancing|default|distress|nasdaq|s&p 500|"
    r"semiconductor index|sox|vix|selloff|deleveraging|risk-off|oil prices?|"
    r"natural gas|electricity prices?|energy shock)\b",
    re.I,
)

SIGNAL_BASE = {
    "systemic_macro": 56,
    "financial_conditions": 55,
    "industry_financing": 52,
    "industry_fundamental": 58,
    "compute_supply": 57,
    "physical_constraint": 58,
    "technology_efficiency": 52,
    "adoption_monetization": 56,
    "policy_geopolitics": 55,
    "asset_economics": 58,
}

CONCRETE_SIGNAL_PATTERNS = {
    "systemic_macro": [
        re.compile(r"\b(federal reserve|fomc|powell)\b", re.I),
        re.compile(r"\b(rate hike|rate cut|interest rates?|dot plot|quantitative tightening|quantitative easing)\b", re.I),
        re.compile(r"\b(treasury yields?|real yields?|financial conditions|sofr)\b", re.I),
        re.compile(r"\b(cpi|consumer price index|pce|core inflation|payrolls?|unemployment|recession|gdp|ism|pmi)\b", re.I),
        re.compile(r"\b(nasdaq|s&p 500|sox|vix)\b.{0,80}\b(selloff|correction|crash|volatility|deleveraging|risk-off)\b", re.I),
        re.compile(r"\b(oil prices?|natural gas|electricity prices?|energy shock)\b", re.I),
    ],
    "financial_conditions": [
        re.compile(r"\b(high yield spread|hy oas|credit spreads?|private credit|refinancing|default|distress|covenant)\b", re.I),
        re.compile(r"\b(debt|bond|bonds|loan|loans|credit facility|financing|leverage)\b", re.I),
        re.compile(r"\b(valuation|fund flows?|positioning|selloff|risk appetite|risk-off)\b", re.I),
    ],
    "industry_financing": [
        re.compile(r"\b(funding round|funding|valuation|venture funding|equity financing|ipo|initial public offering|secondary sale|secondary share sale)\b", re.I),
        re.compile(r"\b(raise|raises|raised|raising)\b.{0,45}(?:[$€£]\s*)?\d+(?:[.,]\d+)?\s*(?:million|billion|trillion|mn|bn|m|b)\b", re.I),
    ],
    "industry_fundamental": [
        re.compile(r"\b(capex|capital expenditure|capital expenditures|capital spending|infrastructure spending|data center spending)\b", re.I),
        re.compile(r"\b(guidance|outlook)\b.{0,60}\b(raise|raises|raised|increase|cut|cuts|reduce|lower)\b", re.I),
    ],
    "compute_supply": [
        re.compile(r"\b(nvidia|amd|broadcom|tsmc|micron|sk hynix|samsung|asml|gpu|gpus|hbm|accelerator|custom silicon|asic|tpu|trainium|maia|mtia)\b", re.I),
        re.compile(r"\b(demand|orders?|shipments?|supply|backlog|inventory|shortage|allocation|capacity)\b", re.I),
    ],
    "physical_constraint": [
        re.compile(r"\b(data center|data centers|datacenter|datacenters)\b", re.I),
        re.compile(r"\b(power|electricity|grid|nuclear|transformer|interconnection|water|moratorium|shortage|curtailment|connection delay|power constraint)\b", re.I),
    ],
    "technology_efficiency": [
        re.compile(r"\b(inference cost|training cost|token price|compute efficiency|distillation|quantization|mixture of experts|compression)\b", re.I),
        re.compile(r"\b(cheaper|cost reduction|cost decline|efficiency gain|fewer gpus?|less compute)\b", re.I),
    ],
    "adoption_monetization": [
        re.compile(r"\b(revenue|revenues|monetization|monetisation|arr|subscription|adoption|seats?|usage|renewal|churn)\b", re.I),
        re.compile(r"\b(productivity|roi|return on investment|payback|pilot|production deployment|revenue per employee|automation)\b", re.I),
    ],
    "policy_geopolitics": [
        re.compile(r"\b(export controls?|export restrictions?|sanctions?|tariffs?|antitrust|regulation|regulatory|copyright|ai act|government ban)\b", re.I),
        re.compile(r"\b(china|taiwan|united states|u\.s\.)\b.{0,80}\b(nvidia|tsmc|semiconductor|chip|ai chip)\b", re.I),
    ],
    "asset_economics": [
        re.compile(r"\b(cancel|cancellation|cancelled|canceled|delay|shelve|shelved|scale back|capacity cut|overcapacity|shutdown)\b", re.I),
        re.compile(r"\b(impairment|writedown|write-down|write off|write-off|depreciation|useful life|resale value|stranded asset)\b", re.I),
        re.compile(r"\b(layoffs?|job cuts?|workforce reduction)\b", re.I),
    ],
}

NOISE_RE = re.compile(
    r"\b(opinion|commentary|podcast|newsletter|what to know|what you need to know|"
    r"could be|might be|may be|explainer|roundup|live blog|live updates)\b",
    re.I,
)

SOURCE_PREMIUM = {
    "reuters.com": 8,
    "bloomberg.com": 8,
    "ft.com": 7,
    "wsj.com": 7,
    "apnews.com": 7,
    "cnbc.com": 6,
    "federalreserve.gov": 9,
    "sec.gov": 9,
    "commerce.gov": 9,
    "energy.gov": 9,
    "whitehouse.gov": 8,
    "congress.gov": 8,
    "europa.eu": 8,
    "ec.europa.eu": 8,
    "gov.uk": 8,
}

EVENT_PRIORS = [
    (
        "fed_policy_decision",
        100,
        re.compile(
            r"\b(federal reserve|fomc)\b.{0,120}\b(raises?|raised|hikes?|hiked|cuts?|cut|"
            r"holds?|held|keeps?|kept|target range|dot plot|quantitative tightening|"
            r"quantitative easing|balance sheet)\b",
            re.I,
        ),
    ),
    (
        "treasury_real_yield_shock",
        96,
        re.compile(
            r"\b(10-year treasury|10y treasury|treasury yields?|real yields?)\b.{0,100}"
            r"\b(surge|surges|jump|jumps|spike|spikes|soar|soars|record|highest|lowest|plunge|plunges|fall sharply)\b",
            re.I,
        ),
    ),
    (
        "credit_stress",
        97,
        re.compile(
            r"\b(high yield spread|hy oas|credit spreads?|private credit|refinancing|"
            r"default|distress|covenant)\b.{0,100}\b(widen|widens|spike|stress|tighten|"
            r"freeze|default|distress|restructur|bankrupt)\w*",
            re.I,
        ),
    ),
    (
        "market_risk_off",
        94,
        re.compile(
            r"\b(nasdaq|s&p 500|sox|semiconductor index|vix)\b.{0,100}\b(selloff|"
            r"correction|crash|volatility|deleveraging|risk-off|plunge|slump)\b",
            re.I,
        ),
    ),
    (
        "inflation_policy_shock",
        92,
        re.compile(
            r"\b(cpi|consumer price index|pce|core inflation)\b.{0,100}\b(hotter|"
            r"cooler|accelerat|surge|jump|unexpected|above forecast|below forecast|"
            r"sticky|record)\w*",
            re.I,
        ),
    ),
    (
        "growth_recession_shock",
        91,
        re.compile(
            r"\b(payrolls?|unemployment|recession|gdp|ism|pmi)\b.{0,100}\b(surprise|"
            r"unexpected|contract|contraction|plunge|drop|weak|weaker|recession|"
            r"jobless|highest|lowest)\w*",
            re.I,
        ),
    ),
    (
        "hyperscaler_capex_guidance",
        99,
        re.compile(
            r"\b(microsoft|meta|alphabet|google|amazon|oracle)\b.{0,140}\b(capex|"
            r"capital spending|capital expenditure|data center spending|infrastructure spending)\b",
            re.I,
        ),
    ),
    (
        "ai_compute_demand_supply",
        96,
        re.compile(
            r"\b(nvidia|amd|broadcom|tsmc|micron|sk hynix|gpu|gpus|hbm)\b.{0,120}\b(demand|orders?|backlog|"
            r"inventory|shortage|allocation|capacity|shipment|supply)\b",
            re.I,
        ),
    ),
    (
        "data_center_physical_constraint",
        97,
        re.compile(
            r"\b(data center|data centers|datacenter|datacenters)\b.{0,140}\b(moratorium|"
            r"power constraint|grid|interconnection|transformer|shortage|curtailment|"
            r"connection delay|electricity shortage|water shortage)\b",
            re.I,
        ),
    ),
    (
        "ai_monetization_adoption",
        94,
        re.compile(
            r"\b(chatgpt|claude|gemini|copilot|enterprise ai|openai|anthropic)\b.{0,140}"
            r"\b(revenue|arr|subscription|adoption|seats?|usage|renewal|churn|monetization)\b",
            re.I,
        ),
    ),
    (
        "ai_efficiency_shift",
        93,
        re.compile(
            r"\b(inference cost|training cost|token price|compute efficiency|distillation|"
            r"quantization|mixture of experts)\b.{0,120}\b(cut|cuts|decline|cheaper|"
            r"reduce|reduction|improve|efficiency|fewer|less compute)\w*",
            re.I,
        ),
    ),
    (
        "export_control_geopolitics",
        96,
        re.compile(
            r"\b(export controls?|export restrictions?|sanctions?|tariffs?)\b.{0,140}"
            r"\b(nvidia|tsmc|semiconductor|chip|ai chip|china|taiwan)\b",
            re.I,
        ),
    ),
    (
        "capacity_unwind_impairment",
        98,
        re.compile(
            r"\b(ai|artificial intelligence|gpu|data center|datacenter|ai infrastructure)\b"
            r".{0,140}\b(cancel|cancellation|shelve|scale back|capacity cut|overcapacity|"
            r"shutdown|impairment|writedown|write-down|stranded asset)\w*",
            re.I,
        ),
    ),
    (
        "major_ai_funding",
        88,
        re.compile(
            r"\b(openai|anthropic|xai|mistral|cohere)\b.{0,120}\b(funding|valuation|"
            r"financing|ipo|secondary sale|raises?|raised)\b",
            re.I,
        ),
    ),
]


def _text(candidate):
    return f"{candidate.get('title', '')} | {candidate.get('description', '')}"


def _source_bonus(candidate):
    domain = str(candidate.get("domain") or "").lower()
    if domain.endswith(".gov"):
        return 9
    return SOURCE_PREMIUM.get(domain, 0)


def _concrete_hits(candidate):
    text = _text(candidate)
    patterns = CONCRETE_SIGNAL_PATTERNS.get(candidate.get("signal_type"), [])
    return [p.pattern for p in patterns if p.search(text)]


def _relevance_score(candidate):
    text = _text(candidate)
    signal_type = candidate.get("signal_type")
    score = SIGNAL_BASE.get(signal_type, 50)
    hits = _concrete_hits(candidate)

    score += min(22, len(hits) * 9)
    if AI_CONTEXT_RE.search(text):
        score += 8
    if signal_type == "systemic_macro" and SYSTEMIC_MACRO_RE.search(text):
        score += 12
    score += _source_bonus(candidate)

    # Search engines sometimes return broad explainers/commentary for a valid query.
    # Penalize those, but do not hard-ban them because a real event can be described
    # in an analysis piece from a top-tier source.
    if NOISE_RE.search(candidate.get("title", "")):
        score -= 14
    if not hits:
        score -= 20

    return max(0, min(100, int(score))), hits


def _event_prior(candidate):
    text = _text(candidate)
    best = 0
    tags = []
    for tag, score, pattern in EVENT_PRIORS:
        if pattern.search(text):
            tags.append(tag)
            best = max(best, score)

    # Theme-level fallback prior: important enough to rank, but below named event
    # shocks/decisions so concrete events win limited model slots.
    if not best:
        theme_priority = int(candidate.get("discovery_priority") or 0)
        best = max(45, min(86, theme_priority - 10))

    return best, tags


def _recency_bonus(core, candidate):
    published = core.dtparse(candidate.get("published_at"))
    if not published:
        return 0
    hours = max(0.0, (core.NOW - published).total_seconds() / 3600)
    if hours <= 6:
        return 8
    if hours <= 24:
        return 6
    if hours <= 48:
        return 4
    if hours <= 96:
        return 2
    return 0


def _score_candidate(core, candidate):
    relevance, rule_hits = _relevance_score(candidate)
    prior, prior_tags = _event_prior(candidate)
    recency = _recency_bonus(core, candidate)
    discovery = int(candidate.get("discovery_priority") or 0)

    # Relevance dominates; event prior is next. Discovery priority is only a small
    # tie-breaking component because it is query-level, not event-level evidence.
    selection = round(
        0.52 * relevance
        + 0.32 * prior
        + 0.08 * discovery
        + recency,
        2,
    )
    selection = max(0.0, min(100.0, selection))

    candidate["relevance_score"] = relevance
    candidate["relevance_rule_hits"] = rule_hits
    candidate["event_prior_score"] = prior
    candidate["event_prior_tags"] = prior_tags
    candidate["selection_score"] = selection
    return candidate


def candidate_rank(candidate):
    return (
        float(candidate.get("selection_score") or 0),
        int(candidate.get("event_prior_score") or 0),
        int(candidate.get("relevance_score") or 0),
        int(candidate.get("discovery_priority") or 0),
        candidate.get("published_at", ""),
    )


def _resolved_mode(core):
    mode = core.os.getenv("NEWS_SCAN_MODE", "auto").lower()
    if mode == "auto":
        mode = "deep" if core.NOW.hour == 8 else "incremental"
    return mode if mode in ("deep", "incremental") else "incremental"


def install(core, expanded):
    """Install deterministic relevance/prior selection after expanded discovery."""
    prior_collect = core.collect
    prior_history_filter = core.history_filter
    prior_updated_cache = core.updated_cache
    prior_save = core.save

    # The expanded layer already enforces the same 24/30 model budget. Replacing
    # its ranking function means that hard cap is now driven by event-level evidence
    # rather than only query-level discovery priority.
    expanded._candidate_rank = candidate_rank

    def collect(mode):
        rows = prior_collect(mode)
        threshold = RELEVANCE_MIN_SCORE[mode]
        kept = []
        filtered = 0
        prior_override = 0

        for row in rows:
            _score_candidate(core, row)
            keep = (
                int(row["relevance_score"]) >= threshold
                or int(row["event_prior_score"]) >= HIGH_PRIOR_OVERRIDE
            )
            if keep:
                if int(row["relevance_score"]) < threshold:
                    prior_override += 1
                kept.append(row)
            else:
                filtered += 1

        kept.sort(key=candidate_rank, reverse=True)
        RUN_STATS.clear()
        RUN_STATS.update(
            {
                "relevance_input_candidates": len(rows),
                "relevance_kept_candidates": len(kept),
                "relevance_filtered_candidates": filtered,
                "high_prior_relevance_overrides": prior_override,
                "high_prior_candidates": sum(
                    int(x.get("event_prior_score") or 0) >= HIGH_PRIOR_OVERRIDE
                    for x in kept
                ),
            }
        )
        print(
            "[news] relevance prefilter input=",
            len(rows),
            "kept=",
            len(kept),
            "filtered=",
            filtered,
            "prior_override=",
            prior_override,
        )
        return kept

    def history_filter(cands, existing, cache):
        ai_cands, stories, stats = prior_history_filter(cands, existing, cache)
        mode = _resolved_mode(core)
        budget = MODEL_CANDIDATE_BUDGET[mode]

        # Strict second guard. The expanded layer should already have applied this
        # cap; keeping it here prevents later refactors from silently increasing
        # normal DeepSeek chunk count.
        ai_cands.sort(key=candidate_rank, reverse=True)
        hard_dropped = max(0, len(ai_cands) - budget)
        if hard_dropped:
            ai_cands = ai_cands[:budget]

        stats.update(RUN_STATS)
        stats["deepseek_candidate_budget"] = budget
        stats["deepseek_candidates_post_selection"] = len(ai_cands)
        stats["deepseek_hard_guard_dropped"] = hard_dropped
        stats["deepseek_max_normal_chunks_per_scan"] = 1
        stats["selected_high_prior_candidates"] = sum(
            int(x.get("event_prior_score") or 0) >= HIGH_PRIOR_OVERRIDE
            for x in ai_cands
        )
        stats["selected_systemic_macro_candidates"] = sum(
            bool(x.get("systemic_macro")) for x in ai_cands
        )
        return ai_cands, stories, stats

    def updated_cache(old_cache, cands):
        rows = prior_updated_cache(old_cache, cands)
        meta_by_url = {
            core.canon_url(x.get("url")): x
            for x in list(cands) + list(old_cache)
            if x.get("url")
        }
        for row in rows:
            src = meta_by_url.get(core.canon_url(row.get("url")))
            if not src:
                continue
            row["relevance_score"] = int(src.get("relevance_score") or 0)
            row["event_prior_score"] = int(src.get("event_prior_score") or 0)
            row["event_prior_tags"] = src.get("event_prior_tags") or []
            row["selection_score"] = float(src.get("selection_score") or 0)
        return rows

    def save(mode, stories, cache, run_stats):
        run_stats = dict(run_stats)
        run_stats.update(RUN_STATS)
        run_stats["deepseek_candidate_budget"] = MODEL_CANDIDATE_BUDGET[mode]
        run_stats["deepseek_max_normal_chunks_per_scan"] = 1
        prior_save(mode, stories, cache, run_stats)

        # Persist policy metadata without changing public categories or the model
        # prompt. This write only annotates the already-produced local JSON.
        try:
            payload = core.json.loads(core.OUT.read_text(encoding="utf-8"))
            policy = payload.setdefault("policy", {})
            policy["python_relevance_prefilter"] = True
            policy["relevance_min_score"] = RELEVANCE_MIN_SCORE
            policy["event_importance_prior"] = True
            policy["high_prior_override_score"] = HIGH_PRIOR_OVERRIDE
            policy["fixed_deepseek_candidate_budget"] = MODEL_CANDIDATE_BUDGET
            policy["max_normal_deepseek_chunks_per_scan"] = 1
            payload["acquisition"] = (
                "Bing News RSS + Google News RSS + GDELT DOC API discovery; expanded macro/AI theme matrix; "
                "trusted-domain whitelist; systemic-macro gate; Python relevance prefilter; deterministic "
                "event-importance prior; history-first incremental filter; existing eight-category analysis; "
                "fixed one-chunk DeepSeek candidate budget"
            )
            core.OUT.write_text(
                core.json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        except Exception as exc:
            print("[news] warning: could not annotate deterministic selection policy:", exc)

    core.collect = collect
    core.history_filter = history_filter
    core.updated_cache = updated_cache
    core.save = save
    return core
