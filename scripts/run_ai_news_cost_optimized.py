#!/usr/bin/env python3
"""Run AI Bubble news with conservative high-confidence category locking.

The base pipeline already performs history-first incremental filtering. This launcher
adds a second cost optimization: candidates with one unambiguous, strong category
signal that agrees with their discovery query get a fixed category. DeepSeek still
summarizes and scores those candidates, but does not re-classify them. Ambiguous or
cross-category candidates remain fully model-classified.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

import update_ai_news as core  # noqa: E402

LOCK_STATS = {"conflicts": 0}

# Strong, intentionally narrow signals. A candidate is locked only when exactly one
# category hits AND that category agrees with the search query that discovered it.
REVENUE_RE = re.compile(
    r"\b(revenue|revenues|monetization|monetisation|monetize|monetise|"
    r"annual recurring revenue|arr|subscription revenue|subscription sales)\b",
    re.I,
)
CAPEX_RE = re.compile(r"\b(capex|capital expenditure|capital expenditures|capital spending)\b", re.I)
FUNDING_RE = re.compile(
    r"\b(valuation|funding round|venture funding|equity financing|series\s+[a-z]|"
    r"initial public offering|ipo|secondary share sale)\b",
    re.I,
)
RAISES_MONEY_RE = re.compile(
    r"\b(raise|raises|raised|raising)\b.{0,45}(?:[$€£]\s*)?\d+(?:[.,]\d+)?\s*"
    r"(?:million|billion|trillion|mn|bn|m|b)\b",
    re.I,
)
CHIP_ENTITY_RE = re.compile(r"\b(nvidia|amd|broadcom|tsmc|gpu|gpus|hbm|semiconductor|semiconductors|ai chip|ai chips)\b", re.I)
CHIP_MARKET_RE = re.compile(r"\b(demand|orders?|shipments?|supply|sales|backlog|shortage|allocation|capacity)\b", re.I)
DATACENTER_RE = re.compile(r"\b(data center|data centers|datacenter|datacenters)\b", re.I)
POWER_RE = re.compile(
    r"\b(power|electricity|electric|grid|nuclear|energy|utility|utilities|"
    r"megawatt|megawatts|gigawatt|gigawatts|mw|gw|power purchase agreement|ppa)\b",
    re.I,
)
DEBT_RE = re.compile(
    r"\b(debt|bond|bonds|loan|loans|term loan|credit facility|credit facilities|"
    r"borrowing|borrowings|borrowed|leverage|leveraged|convertible debt|notes offering)\b",
    re.I,
)
CUT_RE = re.compile(
    r"\b(layoff|layoffs|job cuts?|workforce reduction|cuts?\s+jobs?|"
    r"cancel(?:s|led|ing)?\s+(?:an?\s+)?(?:ai\s+|data center\s+)?project|"
    r"project\s+(?:is\s+)?cancel(?:led|ed)?|scrap(?:s|ped|ping)?|shelv(?:e|es|ed|ing)|"
    r"shut(?:s|ting)?\s+down|shutdown|project delay|delays?\s+(?:an?\s+)?project)\b",
    re.I,
)
MACRO_RE = re.compile(
    r"\b(regulation|regulatory|export controls?|tariffs?|antitrust|federal reserve|"
    r"fed rate|interest rates?|rate hike|rate hikes|rate cut|rate cuts|government ban|"
    r"executive order|competition authority)\b",
    re.I,
)


def high_confidence_category(candidate: dict) -> str | None:
    text = f"{candidate.get('title', '')} | {candidate.get('description', '')}"
    hits: set[str] = set()

    if REVENUE_RE.search(text):
        hits.add("AI Revenue / Monetization")
    if CAPEX_RE.search(text):
        hits.add("AI CAPEX")
    if FUNDING_RE.search(text) or RAISES_MONEY_RE.search(text):
        hits.add("AI Valuation / Funding")
    if CHIP_ENTITY_RE.search(text) and CHIP_MARKET_RE.search(text):
        hits.add("Semiconductor / GPU Demand")
    if DATACENTER_RE.search(text) and POWER_RE.search(text):
        hits.add("Data Center / Power")
    if DEBT_RE.search(text):
        hits.add("AI Credit / Debt")
    if CUT_RE.search(text):
        hits.add("Layoffs / Project Cancellation")
    if MACRO_RE.search(text):
        hits.add("Macro / Regulation")

    # Conservative lock: one strong category only, and it must independently agree
    # with the discovery query category. Any ambiguity is left to DeepSeek.
    if len(hits) != 1:
        return None
    category = next(iter(hits))
    return category if candidate.get("query_category") == category else None


_original_history_filter = core.history_filter
_original_save = core.save


def locked_history_filter(cands, existing, cache):
    ai_cands, stories, stats = _original_history_filter(cands, existing, cache)
    locked = 0
    for candidate in ai_cands:
        category = high_confidence_category(candidate)
        candidate["category_locked"] = bool(category)
        candidate["fixed_category"] = category or ""
        if category:
            locked += 1
    stats["category_locked_candidates"] = locked
    stats["category_ai_judgment_candidates"] = len(ai_cands) - locked
    print(
        "[news] category lock ai_candidates=",
        len(ai_cands),
        "locked=",
        locked,
        "ai_judgment=",
        len(ai_cands) - locked,
    )
    return ai_cands, stories, stats


def locked_chat_json(key, mode, cands):
    compact = []
    locked_by_id = {}
    for x in cands:
        row = {k: x[k] for k in (
            "id", "title", "source", "domain", "published_at", "description",
            "query_category", "discovery_source",
        )}
        locked = bool(x.get("category_locked")) and x.get("fixed_category") in core.CATS
        row["category_locked"] = locked
        row["fixed_category"] = x.get("fixed_category") if locked else ""
        if locked:
            locked_by_id[x["id"]] = x["fixed_category"]
        compact.append(row)

    system = '''You are the analyst for an AI-bubble risk dashboard. Analyze ONLY the supplied real news candidates. Do not invent events, facts, dates, URLs or candidate IDs. Merge candidates only when they describe the same underlying event.

CATEGORY RULE:
- If category_locked=true, fixed_category is authoritative. Copy that category verbatim and DO NOT spend reasoning effort re-classifying it.
- If category_locked=false, classify the event into exactly one of the eight allowed categories.
- Do not merge candidates that have conflicting non-empty fixed_category values.

For every retained event, regardless of category lock, assess importance_score (0-100) for importance to AI bubble formation/unwind, bubble_risk_score (-100..100; positive means higher bubble/unwind risk, negative means stronger fundamental support/lower bubble risk), bubble_direction, concise Chinese summary_zh and reason_zh, and supported companies. Return only events with importance_score >= 50. Output valid JSON only.'''
    prompt = f'''Allowed categories: {json.dumps(core.CATS, ensure_ascii=False)}
Return exactly this JSON shape: {{"stories":[{{"headline":"...","summary_zh":"...","category":"one allowed category or the authoritative fixed_category","importance_score":80,"bubble_direction":"risk_up|risk_down|neutral","bubble_risk_score":40,"reason_zh":"...","companies":["..."],"candidate_ids":["c001","c002"]}}]}}.
Choose candidate_ids only from the supplied data; the first ID should be the best primary source. Prefer direct publisher/official URLs over aggregator wrapper URLs when duplicates exist, and prefer Reuters/Bloomberg/FT/WSJ/AP/CNBC and official primary sources.
Candidates:
{json.dumps(compact, ensure_ascii=False)}'''
    body = {
        "model": core.MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        "thinking": {"type": "enabled"},
        "reasoning_effort": "max" if mode == "deep" else "high",
        "response_format": {"type": "json_object"},
        "max_tokens": 10000 if mode == "deep" else 7000,
    }
    headers = {"Authorization": "Bearer " + key, "Content-Type": "application/json"}
    for attempt in range(2):
        try:
            response = core.requests.post(core.CHAT_API, headers=headers, json=body, timeout=180)
            response.raise_for_status()
            text = (response.json().get("choices") or [{}])[0].get("message", {}).get("content", "").strip()
            if not text:
                raise ValueError("empty chat completion content")
            data = json.loads(text)

            # Enforce locks after the model response as a safety net. If the model
            # somehow merged conflicting locked categories, leave it unresolved for
            # model classification and surface a diagnostic instead of forcing one.
            for story in data.get("stories", []) or []:
                fixed = {
                    locked_by_id[cid]
                    for cid in (story.get("candidate_ids") or [])
                    if cid in locked_by_id
                }
                if len(fixed) == 1:
                    story["category"] = next(iter(fixed))
                elif len(fixed) > 1:
                    LOCK_STATS["conflicts"] += 1
                    print("[news] category-lock conflict candidate_ids=", story.get("candidate_ids"), "fixed=", sorted(fixed))
            return data
        except Exception as exc:
            if attempt == 1:
                raise
            print("[news] retry DeepSeek analysis:", exc)
            core.time.sleep(2)


def locked_save(mode, stories, cache, run_stats):
    run_stats = dict(run_stats)
    run_stats["category_lock_conflicts"] = LOCK_STATS["conflicts"]
    _original_save(mode, stories, cache, run_stats)
    # Make the optimization self-documenting in the persisted payload.
    try:
        payload = json.loads(core.OUT.read_text(encoding="utf-8"))
        payload.setdefault("policy", {})["high_confidence_category_lock"] = True
        payload["acquisition"] = (
            "Bing News RSS + Google News RSS + GDELT DOC API discovery; trusted-domain whitelist; "
            "history-first incremental filter; conservative Python category lock; "
            "DeepSeek V4.1 Flash analysis for new/materially changed candidates"
        )
        core.OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except Exception as exc:
        print("[news] warning: could not annotate category-lock policy:", exc)


core.history_filter = locked_history_filter
core.chat_json = locked_chat_json
core.save = locked_save

if __name__ == "__main__":
    raise SystemExit(core.main())
