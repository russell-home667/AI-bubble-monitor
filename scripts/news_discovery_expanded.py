#!/usr/bin/env python3
'''Expanded discovery layer for the AI Bubble News Radar.

This module intentionally changes discovery/selection only:
1. expand the search surface from eight broad queries to a macro + AI theme matrix;
2. attach Python-side discovery_theme / signal_type metadata while preserving the
   existing eight public categories;
3. admit high-systemic-impact macro events even when their title/description has
   no explicit AI keyword, subject to a concrete macro-signal gate.

DeepSeek cost is protected by a fixed candidate budget aligned with one resilient
analysis chunk per scan. The model prompt schema is not expanded by this module.
'''
from __future__ import annotations

import json
import re
import time
from datetime import timedelta

DISCOVERY_MATRIX = [
    # Macro / liquidity transmission. These deliberately do not require "AI".
    {
        "theme": "Rates / Liquidity",
        "signal_type": "systemic_macro",
        "category": "Macro / Regulation",
        "priority": 100,
        "query": '(Federal Reserve OR FOMC OR Powell) ("rate hike" OR "rate cut" OR "interest rates" OR "monetary policy" OR "dot plot" OR "balance sheet" OR "quantitative tightening" OR "quantitative easing")',
    },
    {
        "theme": "Rates / Liquidity",
        "signal_type": "systemic_macro",
        "category": "Macro / Regulation",
        "priority": 100,
        "query": '("10-year Treasury" OR "10Y Treasury" OR "Treasury yields" OR "real yield" OR "financial conditions" OR SOFR) (surge OR jump OR rise OR fall OR tighten OR ease OR record)',
    },
    {
        "theme": "Inflation / Energy",
        "signal_type": "systemic_macro",
        "category": "Macro / Regulation",
        "priority": 96,
        "query": '(CPI OR "consumer price index" OR PCE OR "core inflation" OR wages) (inflation OR Federal Reserve OR rates OR yields)',
    },
    {
        "theme": "Inflation / Energy",
        "signal_type": "systemic_macro",
        "category": "Macro / Regulation",
        "priority": 94,
        "query": '("oil prices" OR "natural gas" OR electricity OR power) (surge OR spike OR shortage OR shock) (inflation OR rates OR "data center")',
    },
    {
        "theme": "Macro Growth / Recession",
        "signal_type": "systemic_macro",
        "category": "Macro / Regulation",
        "priority": 98,
        "query": '(GDP OR payrolls OR unemployment OR recession OR ISM OR PMI) ("United States" OR US OR economy OR Federal Reserve)',
    },
    {
        "theme": "Macro Growth / Recession",
        "signal_type": "systemic_macro",
        "category": "Macro / Regulation",
        "priority": 92,
        "query": '("IT spending" OR "technology spending" OR "CIO budget" OR "enterprise software spending") (cut OR slowdown OR contraction OR growth)',
    },
    {
        "theme": "Credit / Financial Stress",
        "signal_type": "financial_conditions",
        "category": "AI Credit / Debt",
        "priority": 99,
        "query": '("high yield spread" OR "HY OAS" OR "credit spreads" OR "private credit" OR refinancing OR default OR distress) (widen OR stress OR tighten OR financing OR debt)',
    },
    {
        "theme": "Credit / Financial Stress",
        "signal_type": "financial_conditions",
        "category": "AI Credit / Debt",
        "priority": 96,
        "query": '("data center" OR "AI infrastructure") (debt OR bond OR loan OR "private credit" OR financing OR leverage)',
    },
    {
        "theme": "Market Valuation / Risk Appetite",
        "signal_type": "systemic_macro",
        "category": "Macro / Regulation",
        "priority": 97,
        "query": '(Nasdaq OR "S&P 500" OR SOX OR "semiconductor index" OR VIX) (selloff OR correction OR volatility OR crash OR deleveraging OR "risk-off")',
    },
    {
        "theme": "Market Valuation / Risk Appetite",
        "signal_type": "financial_conditions",
        "category": "AI Valuation / Funding",
        "priority": 91,
        "query": '("AI stocks" OR semiconductors OR megacap OR "technology stocks") (valuation OR selloff OR "fund flows" OR positioning OR bubble)',
    },

    # AI financing and capital spending.
    {
        "theme": "AI Funding / Private Markets",
        "signal_type": "industry_financing",
        "category": "AI Valuation / Funding",
        "priority": 86,
        "query": '(OpenAI OR Anthropic OR xAI OR Mistral OR Cohere OR "AI startup") (funding OR valuation OR financing OR IPO OR "secondary sale")',
    },
    {
        "theme": "AI Funding / Private Markets",
        "signal_type": "industry_financing",
        "category": "AI Valuation / Funding",
        "priority": 84,
        "query": '("AI startup" OR "foundation model") ("funding round" OR valuation OR venture OR IPO OR financing)',
    },
    {
        "theme": "AI CAPEX",
        "signal_type": "industry_fundamental",
        "category": "AI CAPEX",
        "priority": 92,
        "query": '(Microsoft OR Meta OR Alphabet OR Google OR Amazon OR Oracle) (capex OR "capital spending" OR "data center spending" OR "infrastructure spending")',
    },
    {
        "theme": "AI CAPEX",
        "signal_type": "industry_fundamental",
        "category": "AI CAPEX",
        "priority": 90,
        "query": '("AI infrastructure" OR "data center") (investment OR capex OR spending) (increase OR raise OR cut OR reduce OR guidance)',
    },

    # Compute supply and physical infrastructure.
    {
        "theme": "Compute Supply / Chips / Custom Silicon",
        "signal_type": "compute_supply",
        "category": "Semiconductor / GPU Demand",
        "priority": 92,
        "query": '(Nvidia OR AMD OR Broadcom OR TSMC OR Micron OR "SK Hynix" OR Samsung OR ASML) (AI OR GPU OR HBM OR accelerator) (demand OR orders OR supply OR backlog OR inventory OR capacity)',
    },
    {
        "theme": "Compute Supply / Chips / Custom Silicon",
        "signal_type": "compute_supply",
        "category": "Semiconductor / GPU Demand",
        "priority": 88,
        "query": '("Google TPU" OR Trainium OR Maia OR MTIA OR "custom silicon" OR ASIC) (AI OR inference OR training OR demand OR deployment)',
    },
    {
        "theme": "Data Center / Power",
        "signal_type": "physical_constraint",
        "category": "Data Center / Power",
        "priority": 92,
        "query": '("data center" OR datacenter) (power OR electricity OR grid OR nuclear OR transformer OR interconnection OR water) (AI OR hyperscaler OR cloud)',
    },
    {
        "theme": "Data Center / Power",
        "signal_type": "physical_constraint",
        "category": "Data Center / Power",
        "priority": 94,
        "query": '("data center" OR datacenter) (moratorium OR delay OR connection OR grid OR shortage OR curtailment OR "power constraint")',
    },

    # Efficiency, adoption, monetization and ROI.
    {
        "theme": "AI Technology / Compute Efficiency",
        "signal_type": "technology_efficiency",
        "category": "Semiconductor / GPU Demand",
        "priority": 87,
        "query": '(AI OR "large language model" OR LLM) ("inference cost" OR "training cost" OR efficiency OR distillation OR quantization OR "mixture of experts")',
    },
    {
        "theme": "AI Technology / Compute Efficiency",
        "signal_type": "technology_efficiency",
        "category": "Semiconductor / GPU Demand",
        "priority": 85,
        "query": '("token price" OR "compute efficiency" OR "AI inference") (cut OR decline OR cheaper OR efficiency OR compression)',
    },
    {
        "theme": "Enterprise Adoption / Monetization",
        "signal_type": "adoption_monetization",
        "category": "AI Revenue / Monetization",
        "priority": 90,
        "query": '("artificial intelligence" OR AI) (revenue OR monetization OR ARR OR subscription) (OpenAI OR Anthropic OR Microsoft OR Google OR Meta OR Amazon)',
    },
    {
        "theme": "Enterprise Adoption / Monetization",
        "signal_type": "adoption_monetization",
        "category": "AI Revenue / Monetization",
        "priority": 91,
        "query": '(Copilot OR ChatGPT OR Claude OR Gemini OR "enterprise AI") (adoption OR seats OR usage OR renewal OR churn OR monetization OR revenue)',
    },
    {
        "theme": "Enterprise Adoption / Monetization",
        "signal_type": "adoption_monetization",
        "category": "AI Revenue / Monetization",
        "priority": 89,
        "query": '("AI revenue" OR "AI ARR" OR "AI subscription" OR "AI usage") (Microsoft OR Google OR OpenAI OR Anthropic OR Amazon OR Meta)',
    },
    {
        "theme": "AI Productivity / ROI",
        "signal_type": "adoption_monetization",
        "category": "AI Revenue / Monetization",
        "priority": 88,
        "query": '(AI OR "artificial intelligence") (productivity OR ROI OR "return on investment" OR automation OR "revenue per employee")',
    },
    {
        "theme": "AI Productivity / ROI",
        "signal_type": "adoption_monetization",
        "category": "AI Revenue / Monetization",
        "priority": 86,
        "query": '("enterprise AI") (pilot OR production OR deployment) (ROI OR productivity OR adoption OR payback)',
    },

    # Policy, geopolitics and asset/capacity unwind signals.
    {
        "theme": "Regulation / Geopolitics",
        "signal_type": "policy_geopolitics",
        "category": "Macro / Regulation",
        "priority": 91,
        "query": '(AI OR semiconductor OR chip) ("export controls" OR sanctions OR tariff OR antitrust OR regulation OR copyright OR "AI Act")',
    },
    {
        "theme": "Regulation / Geopolitics",
        "signal_type": "policy_geopolitics",
        "category": "Macro / Regulation",
        "priority": 93,
        "query": '(China OR Taiwan OR "United States") (Nvidia OR TSMC OR semiconductor OR "AI chip") (export OR restriction OR sanction OR tariff)',
    },
    {
        "theme": "Asset Economics / Capacity Cuts",
        "signal_type": "asset_economics",
        "category": "Layoffs / Project Cancellation",
        "priority": 89,
        "query": '(AI OR "artificial intelligence" OR "data center") (layoffs OR "job cuts" OR "workforce reduction" OR cancellation OR cancelled OR canceled OR delay OR shutdown)',
    },
    {
        "theme": "Asset Economics / Capacity Cuts",
        "signal_type": "asset_economics",
        "category": "Layoffs / Project Cancellation",
        "priority": 90,
        "query": '(GPU OR "data center" OR "AI infrastructure") (impairment OR writedown OR "write-down" OR depreciation OR "useful life" OR "resale value")',
    },
    {
        "theme": "Asset Economics / Capacity Cuts",
        "signal_type": "asset_economics",
        "category": "Layoffs / Project Cancellation",
        "priority": 93,
        "query": '(AI OR "data center") (cancel OR cancellation OR delay OR shelve OR "scale back" OR "capacity cut" OR overcapacity OR shutdown)',
    },
]

SYSTEMIC_MACRO_RE = re.compile(
    r"\b("
    r"federal reserve|fomc|powell|rate hike|rate cut|interest rates?|dot plot|"
    r"quantitative tightening|quantitative easing|treasury yields?|real yields?|"
    r"financial conditions|sofr|cpi|consumer price index|pce|core inflation|"
    r"payrolls?|unemployment|recession|gdp|ism|pmi|"
    r"high yield spread|hy oas|credit spreads?|private credit|refinancing|default|distress|"
    r"nasdaq|s&p 500|semiconductor index|sox|vix|selloff|deleveraging|risk-off|"
    r"oil prices?|natural gas|electricity prices?|energy shock"
    r")\b",
    re.I,
)
AI_CONTEXT_RE = re.compile(
    r"\b(ai|artificial intelligence|openai|anthropic|xai|nvidia|gpu|hbm|"
    r"data center|datacenter|hyperscaler|copilot|chatgpt|claude|gemini|"
    r"semiconductor|tsmc|broadcom|amd|oracle|microsoft|meta|alphabet|google|amazon)\b",
    re.I,
)

# One resilient chunk maximum. This reduces the old worst-case model-call envelope
# even though discovery is materially broader.
MODEL_CANDIDATE_BUDGET = {"deep": 24, "incremental": 30}


def _candidate_text(candidate):
    return f"{candidate.get('title', '')} | {candidate.get('description', '')}"


def _systemic_macro_allowed(candidate):
    if candidate.get("signal_type") != "systemic_macro":
        return True
    text = _candidate_text(candidate)
    return bool(AI_CONTEXT_RE.search(text) or SYSTEMIC_MACRO_RE.search(text))


def _merge_discovery_metadata(dst, src):
    themes = list(dst.get("discovery_themes") or [dst.get("discovery_theme")])
    signals = list(dst.get("signal_types") or [dst.get("signal_type")])
    for value, bucket in (
        (src.get("discovery_theme"), themes),
        (src.get("signal_type"), signals),
    ):
        if value and value not in bucket:
            bucket.append(value)
    dst["discovery_themes"] = [x for x in themes if x]
    dst["signal_types"] = [x for x in signals if x]
    dst["discovery_priority"] = max(
        int(dst.get("discovery_priority") or 0),
        int(src.get("discovery_priority") or 0),
    )
    if int(src.get("discovery_priority") or 0) > int(dst.get("primary_query_priority") or 0):
        dst["query_category"] = src.get("query_category")
        dst["discovery_theme"] = src.get("discovery_theme")
        dst["signal_type"] = src.get("signal_type")
        dst["systemic_macro"] = bool(src.get("systemic_macro"))
        dst["primary_query_priority"] = int(src.get("discovery_priority") or 0)


def _expanded_collect(core, mode):
    deep = mode == "deep"
    interval = "8" if deep else "7"
    offsets = [1, 11] if deep else [1]
    cut = core.NOW - (timedelta(days=7, hours=6) if deep else timedelta(hours=30))
    raw = []
    discovery_counts = {"Bing News RSS": 0, "Google News RSS": 0, "GDELT DOC API": 0}
    theme_counts = {}

    for spec in DISCOVERY_MATRIX:
        cat = spec["category"]
        query = spec["query"]
        label = spec["theme"]
        batches = []

        for first in offsets:
            try:
                batches.append(core.bing_page(query, interval, first))
            except Exception as exc:
                print("[news] Bing RSS error", label, first, exc)
        try:
            batches.append(core.google_page(query, deep))
        except Exception as exc:
            print("[news] Google News RSS error", label, exc)
        try:
            batches.append(core.gdelt_page(query, deep))
        except Exception as exc:
            print("[news] GDELT error", label, exc)

        for batch in batches:
            for row in batch:
                when = core.dtparse(row["published_at"])
                if not when or when < cut:
                    continue
                row["query_category"] = cat
                row["discovery_theme"] = spec["theme"]
                row["signal_type"] = spec["signal_type"]
                row["discovery_priority"] = int(spec["priority"])
                row["primary_query_priority"] = int(spec["priority"])
                row["systemic_macro"] = spec["signal_type"] == "systemic_macro"
                if not _systemic_macro_allowed(row):
                    continue
                raw.append(row)
                discovery_counts[row["discovery_source"]] = discovery_counts.get(row["discovery_source"], 0) + 1
                theme_counts[label] = theme_counts.get(label, 0) + 1
        time.sleep(0.20)

    # Systemic-impact prior first; recency is the tie-breaker. A per-theme cap stops
    # macro coverage from crowding out the AI fundamental themes.
    raw.sort(
        key=lambda row: (
            int(row.get("discovery_priority") or 0),
            row.get("published_at", ""),
        ),
        reverse=True,
    )

    result = []
    by_url = {}
    per_domain = {}
    per_theme = {}
    domain_cap = 28 if deep else 14
    theme_cap = 36 if deep else 18
    limit = 260 if deep else 150

    for row in raw:
        url_key = core.canon_url(row["url"])
        if url_key and url_key in by_url:
            _merge_discovery_metadata(by_url[url_key], row)
            continue

        similar = next(
            (
                existing
                for existing in result[-120:]
                if core.sim(row["title"], existing["title"]) > 0.90
            ),
            None,
        )
        if similar is not None:
            _merge_discovery_metadata(similar, row)
            continue

        theme = row.get("discovery_theme") or "Unknown"
        if per_domain.get(row["domain"], 0) >= domain_cap:
            continue
        if per_theme.get(theme, 0) >= theme_cap:
            continue

        per_domain[row["domain"]] = per_domain.get(row["domain"], 0) + 1
        per_theme[theme] = per_theme.get(theme, 0) + 1
        row["id"] = f"c{len(result) + 1:03d}"
        row["discovery_themes"] = [row["discovery_theme"]]
        row["signal_types"] = [row["signal_type"]]
        result.append(row)
        if url_key:
            by_url[url_key] = row
        if len(result) >= limit:
            break

    print("[news] discovery raw=", discovery_counts)
    print(
        "[news] discovery themes=",
        dict(sorted(theme_counts.items(), key=lambda item: (-item[1], item[0]))),
    )
    print(
        "[news] trusted candidates=",
        len(result),
        "systemic_macro=",
        sum(bool(row.get("systemic_macro")) for row in result),
        "domains=",
        dict(sorted(per_domain.items(), key=lambda item: -item[1])),
    )
    return result


def _candidate_rank(candidate):
    return (
        int(candidate.get("discovery_priority") or 0),
        1 if candidate.get("systemic_macro") else 0,
        candidate.get("published_at", ""),
    )


def _resolved_mode(core):
    mode = core.os.getenv("NEWS_SCAN_MODE", "auto").lower()
    if mode == "auto":
        mode = "deep" if core.NOW.hour == 8 else "incremental"
    return mode if mode in ("deep", "incremental") else "incremental"


def install(core):
    '''Install expanded discovery on an already configured core pipeline.'''
    prior_history_filter = core.history_filter
    prior_updated_cache = core.updated_cache
    prior_save = core.save

    def collect(mode):
        return _expanded_collect(core, mode)

    def history_filter(cands, existing, cache):
        ai_cands, stories, stats = prior_history_filter(cands, existing, cache)
        mode = _resolved_mode(core)
        budget = MODEL_CANDIDATE_BUDGET[mode]

        # New macro/financial stories can displace lower-priority candidates, but
        # expanded discovery cannot create another normal DeepSeek analysis chunk.
        ai_cands.sort(key=_candidate_rank, reverse=True)
        dropped = max(0, len(ai_cands) - budget)
        if dropped:
            ai_cands = ai_cands[:budget]

        locked = sum(bool(x.get("category_locked")) for x in ai_cands)
        stats["ai_candidates"] = len(ai_cands)
        stats["category_locked_candidates"] = locked
        stats["category_ai_judgment_candidates"] = len(ai_cands) - locked
        stats["deepseek_candidate_budget"] = budget
        stats["deepseek_candidates_dropped_by_budget"] = dropped
        stats["systemic_macro_ai_candidates"] = sum(bool(x.get("systemic_macro")) for x in ai_cands)
        print(
            "[news] expanded selection ai_candidates=",
            len(ai_cands),
            "budget=",
            budget,
            "dropped=",
            dropped,
            "systemic_macro=",
            stats["systemic_macro_ai_candidates"],
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
            row["discovery_theme"] = src.get("discovery_theme")
            row["signal_type"] = src.get("signal_type")
            row["discovery_themes"] = src.get("discovery_themes") or []
            row["signal_types"] = src.get("signal_types") or []
            row["discovery_priority"] = int(src.get("discovery_priority") or 0)
            row["systemic_macro"] = bool(src.get("systemic_macro"))
        return rows

    def save(mode, stories, cache, run_stats):
        prior_save(mode, stories, cache, run_stats)
        try:
            payload = json.loads(core.OUT.read_text(encoding="utf-8"))
            policy = payload.setdefault("policy", {})
            policy["expanded_discovery_matrix"] = True
            policy["systemic_macro_without_ai_keyword"] = True
            policy["deepseek_candidate_budget"] = MODEL_CANDIDATE_BUDGET
            payload["discovery_themes"] = sorted({x["theme"] for x in DISCOVERY_MATRIX})
            payload["acquisition"] = (
                "Bing News RSS + Google News RSS + GDELT DOC API discovery; expanded macro/AI theme matrix; "
                "trusted-domain whitelist; systemic-macro gate and priority; history-first incremental filter; "
                "existing eight-category analysis; fixed DeepSeek candidate budget"
            )
            core.OUT.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        except Exception as exc:
            print("[news] warning: could not annotate expanded discovery policy:", exc)

    core.collect = collect
    core.history_filter = history_filter
    core.updated_cache = updated_cache
    core.save = save
    return core
