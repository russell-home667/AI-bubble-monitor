#!/usr/bin/env python3
"""Resilient launcher for the AI Bubble News Radar.

Keeps the existing history-first/category-lock pipeline, but prevents one empty
DeepSeek response from aborting the whole refresh. Large model batches are split
into smaller chunks. Each chunk retries with progressively simpler API settings;
a persistently bad chunk is skipped and recorded in run stats instead of killing
the entire workflow.
"""
from __future__ import annotations

import json
import re
from typing import Any

import run_ai_news_cost_optimized as optimized

core = optimized.core

API_STATS = {
    "deepseek_chunks": 0,
    "deepseek_empty_responses": 0,
    "deepseek_fallback_successes": 0,
    "deepseek_failed_chunks": 0,
}


def _compact_candidates(cands: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, str]]:
    compact = []
    locked_by_id: dict[str, str] = {}
    for x in cands:
        row = {
            k: x.get(k, "")
            for k in (
                "id",
                "title",
                "source",
                "domain",
                "published_at",
                "description",
                "query_category",
                "discovery_source",
            )
        }
        locked = bool(x.get("category_locked")) and x.get("fixed_category") in core.CATS
        row["category_locked"] = locked
        row["fixed_category"] = x.get("fixed_category") if locked else ""
        if locked:
            locked_by_id[str(x.get("id"))] = str(x.get("fixed_category"))
        compact.append(row)
    return compact, locked_by_id


def _prompt_for(compact: list[dict[str, Any]]) -> tuple[str, str]:
    system = """You are the analyst for an AI-bubble risk dashboard. Analyze ONLY the supplied real news candidates. Do not invent events, facts, dates, URLs or candidate IDs. Merge candidates only when they describe the same underlying event.

CATEGORY RULE:
- If category_locked=true, fixed_category is authoritative. Copy that category verbatim and DO NOT re-classify it.
- If category_locked=false, classify the event into exactly one of the eight allowed categories.
- Do not merge candidates that have conflicting non-empty fixed_category values.

For every retained event, assess importance_score (0-100) for importance to AI bubble formation/unwind, bubble_risk_score (-100..100; positive means higher bubble/unwind risk, negative means stronger fundamental support/lower bubble risk), bubble_direction, concise Chinese summary_zh and reason_zh, and supported companies. Return only events with importance_score >= 50. Output valid JSON only."""
    prompt = f"""Allowed categories: {json.dumps(core.CATS, ensure_ascii=False)}
Return exactly this JSON shape: {{"stories":[{{"headline":"...","summary_zh":"...","category":"one allowed category or the authoritative fixed_category","importance_score":80,"bubble_direction":"risk_up|risk_down|neutral","bubble_risk_score":40,"reason_zh":"...","companies":["..."],"candidate_ids":["c001","c002"]}}]}}.
Choose candidate_ids only from the supplied data. Prefer official/company primary sources first when directly relevant, then free professional sources such as AP, Reuters, CNBC, TechCrunch, Semafor, The Guardian, The Verge, Yahoo Finance, Investing.com, CNA and 财联社. Bloomberg, WSJ, Barron's, Fortune, FT, The Economist, The Information and New York Times are discovery leads only: do not put one of them first when a free corroborating candidate is available, and include the free corroborating candidate_id for the event whenever available. Prefer direct publisher URLs over aggregator wrappers.
Candidates:
{json.dumps(compact, ensure_ascii=False)}"""
    return system, prompt


def _decode_json(text: str) -> dict[str, Any]:
    text = (text or "").strip()
    if not text:
        API_STATS["deepseek_empty_responses"] += 1
        raise ValueError("empty chat completion content")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.I | re.S).strip()
        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", cleaned, flags=re.S)
            if not match:
                raise
            data = json.loads(match.group(0))
    if not isinstance(data, dict):
        raise ValueError("DeepSeek response is not a JSON object")
    if not isinstance(data.get("stories", []), list):
        raise ValueError("DeepSeek response stories is not a list")
    return data


def _request_chunk(
    key: str,
    mode: str,
    cands: list[dict[str, Any]],
    *,
    thinking: bool,
    json_mode: bool,
    timeout: int,
) -> dict[str, Any]:
    compact, locked_by_id = _compact_candidates(cands)
    system, prompt = _prompt_for(compact)
    body: dict[str, Any] = {
        "model": core.MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": 9000 if mode == "deep" else 6500,
    }
    if thinking:
        body["thinking"] = {"type": "enabled"}
        body["reasoning_effort"] = "max" if mode == "deep" else "high"
    if json_mode:
        body["response_format"] = {"type": "json_object"}

    headers = {"Authorization": "Bearer " + key, "Content-Type": "application/json"}
    response = core.requests.post(core.CHAT_API, headers=headers, json=body, timeout=timeout)
    response.raise_for_status()
    message = (response.json().get("choices") or [{}])[0].get("message", {})
    data = _decode_json(message.get("content", ""))

    # Re-enforce Python category locks after the model response.
    for story in data.get("stories", []) or []:
        fixed = {
            locked_by_id[cid]
            for cid in (story.get("candidate_ids") or [])
            if cid in locked_by_id
        }
        if len(fixed) == 1:
            story["category"] = next(iter(fixed))
        elif len(fixed) > 1:
            optimized.LOCK_STATS["conflicts"] += 1
            print(
                "[news] category-lock conflict candidate_ids=",
                story.get("candidate_ids"),
                "fixed=",
                sorted(fixed),
            )
    return data


def _analyze_chunk(key: str, mode: str, cands: list[dict[str, Any]]) -> dict[str, Any]:
    API_STATS["deepseek_chunks"] += 1
    strategies = (
        # Preferred path: retain strong reasoning on a smaller prompt.
        {"thinking": True, "json_mode": True, "timeout": 120},
        # DeepSeek JSON mode can occasionally return an empty content field.
        {"thinking": False, "json_mode": True, "timeout": 90},
        # Last resort: prompt-enforced JSON without response_format.
        {"thinking": False, "json_mode": False, "timeout": 90},
    )
    last_error: Exception | None = None
    for idx, strategy in enumerate(strategies, start=1):
        try:
            data = _request_chunk(key, mode, cands, **strategy)
            if idx > 1:
                API_STATS["deepseek_fallback_successes"] += 1
                print(f"[news] DeepSeek chunk recovered on fallback strategy {idx}")
            return data
        except Exception as exc:
            last_error = exc
            print(
                f"[news] DeepSeek chunk attempt {idx}/{len(strategies)} failed "
                f"(candidates={len(cands)}): {exc}"
            )
            if idx < len(strategies):
                core.time.sleep(2 * idx)

    API_STATS["deepseek_failed_chunks"] += 1
    print(
        "[news] WARNING: skipping persistently failed DeepSeek chunk "
        f"(candidates={len(cands)}): {last_error}"
    )
    return {"stories": []}


def resilient_chat_json(key: str, mode: str, cands: list[dict[str, Any]]) -> dict[str, Any]:
    # Keep prompts materially smaller than the old 45-candidate deep batch.
    chunk_size = 24 if mode == "deep" else 30
    stories: list[dict[str, Any]] = []
    for start in range(0, len(cands), chunk_size):
        chunk = cands[start : start + chunk_size]
        data = _analyze_chunk(key, mode, chunk)
        stories.extend(data.get("stories", []) or [])
    return {"stories": stories}


_original_save = core.save


def resilient_save(mode, stories, cache, run_stats):
    run_stats = dict(run_stats)
    run_stats.update(API_STATS)
    run_stats["analysis_degraded"] = API_STATS["deepseek_failed_chunks"] > 0
    _original_save(mode, stories, cache, run_stats)


core.chat_json = resilient_chat_json
core.save = resilient_save

if __name__ == "__main__":
    raise SystemExit(core.main())
