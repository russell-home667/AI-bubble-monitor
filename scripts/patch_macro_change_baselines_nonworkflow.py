#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Gold: use an explicit validated previous_close only; never silently fall back
# to a stale history row while claiming it is the prior completed close.
p = ROOT / 'assets' / 'chart-time-slider.js'
s = p.read_text(encoding='utf-8')
old = "    const base = Number(quote.previous_close ?? last?.value);\n    if (changeEl && Number.isFinite(price) && Number.isFinite(base) && base !== 0) {\n      const change = (price / base - 1) * 100;\n      changeEl.textContent = `${change >= 0 ? '+' : ''}${change.toFixed(2)}% vs prior completed daily close`;\n      changeEl.style.color = change > 0 ? 'var(--green)' : change < 0 ? 'var(--red)' : 'var(--muted)';\n    }"
new = "    const base = Number(quote.previous_close);\n    if (changeEl && Number.isFinite(price) && Number.isFinite(base) && base !== 0) {\n      const change = (price / base - 1) * 100;\n      changeEl.textContent = `${change >= 0 ? '+' : ''}${change.toFixed(2)}% vs prior completed daily close`;\n      changeEl.style.color = change > 0 ? 'var(--green)' : change < 0 ? 'var(--red)' : 'var(--muted)';\n    } else if (changeEl) {\n      changeEl.textContent = '— vs prior completed daily close';\n      changeEl.style.color = 'var(--muted)';\n    }"
if old in s:
    s = s.replace(old, new, 1)
elif new not in s:
    raise SystemExit('Gold frontend strict-baseline anchor not found')
p.write_text(s, encoding='utf-8')

# Gold data updater: Investing.com remains first choice, but GitHub runners can
# receive 403s. Use XAUS's free daily-history endpoint as the robust fallback.
p = ROOT / 'scripts' / 'update_ai_gold.py'
s = p.read_text(encoding='utf-8')

if 'XAUS_HISTORY_URL' not in s:
    anchor = 'XAUS_SPOT_URL = "https://xaus.com/api/v1/spot?compact=1"\n'
    if anchor not in s:
        raise SystemExit('XAUS_SPOT_URL anchor not found')
    s = s.replace(anchor, anchor + 'XAUS_HISTORY_URL = "https://xaus.com/api/v1/history"\n', 1)

if 'def fetch_xaus_previous_close' not in s:
    anchor = '\ndef fresh_history_previous_close(rows):\n'
    helper = r'''
def fetch_xaus_previous_close(live_price: float | None = None):
    """Return the latest completed XAU/USD daily close from XAUS history."""
    payload = request_json(XAUS_HISTORY_URL, 35)
    points = payload.get("points") or []
    today = datetime.now(NY_TZ).date()
    candidates = []
    for point in points:
        raw_date = point.get("d") or point.get("date")
        raw_close = point.get("c") if point.get("c") is not None else point.get("close")
        if not raw_date or raw_close is None:
            continue
        try:
            d = datetime.fromisoformat(str(raw_date)[:10]).date()
            close = float(raw_close)
        except Exception:
            continue
        # Exclude the current calendar/session date: the card is explicitly
        # comparing to the prior *completed* daily close.
        if d >= today or not 100.0 < close < 20000.0:
            continue
        candidates.append((d, close))
    if not candidates:
        raise RuntimeError("XAUS history returned no completed daily close")
    d, previous_close = max(candidates, key=lambda x: x[0])
    # Normal weekend / long-weekend gaps are acceptable, but an older series is not.
    if (today - d).days > 4:
        raise RuntimeError(f"XAUS prior completed close is stale: {d}")
    if live_price and abs(float(live_price) / previous_close - 1.0) > 0.15:
        raise RuntimeError(
            f"XAUS previous close/live quote divergence exceeds 15% ({previous_close} vs {live_price})"
        )
    return {
        "previous_close": round(previous_close, 2),
        "previous_close_source": "XAUS Gold Data API daily history",
        "previous_close_url": XAUS_HISTORY_URL,
        "previous_close_transport": "requests_json",
        "previous_close_observation_date": d.isoformat(),
    }

'''
    if anchor not in s:
        raise SystemExit('fresh_history_previous_close anchor not found')
    s = s.replace(anchor, '\n' + helper + 'def fresh_history_previous_close(rows):\n', 1)

old = '''    try:
        previous_close_info = fetch_investing_previous_close(float(quote.get("price")))
    except Exception as exc:
        previous_close_warning = str(exc)
        previous_close_info = fresh_history_previous_close(merged)
        if previous_close_info is None:
            print(f"Previous-close warning: {exc}; no sufficiently fresh completed daily close available")
        else:
            print(f"Previous-close warning: {exc}; using fresh stored daily close {previous_close_info['previous_close_observation_date']}")
'''
new = '''    try:
        previous_close_info = fetch_investing_previous_close(float(quote.get("price")))
    except Exception as investing_exc:
        previous_close_warning = f"Investing.com: {investing_exc}"
        try:
            previous_close_info = fetch_xaus_previous_close(float(quote.get("price")))
            print(
                f"Previous-close fallback: Investing.com unavailable; using XAUS daily close "
                f"{previous_close_info['previous_close_observation_date']}"
            )
        except Exception as xaus_exc:
            previous_close_warning += f" | XAUS history: {xaus_exc}"
            previous_close_info = fresh_history_previous_close(merged)
            if previous_close_info is None:
                print(
                    f"Previous-close warning: {previous_close_warning}; "
                    "no validated prior completed daily close available"
                )
            else:
                print(
                    f"Previous-close fallback: {previous_close_warning}; using stored daily close "
                    f"{previous_close_info['previous_close_observation_date']}"
                )
'''
if old in s:
    s = s.replace(old, new, 1)
elif new not in s:
    raise SystemExit('previous-close fallback block anchor not found')

# Tighten the final stored-history fallback: it must actually be the expected
# prior weekday session, otherwise return None rather than mislabel an old bar.
old = '''    d, value, source = max(candidates, key=lambda x: x[0])
    if (session_date - d).days > 4:
        return None
    return {
'''
new = '''    d, value, source = max(candidates, key=lambda x: x[0])
    expected = expected_previous_gold_session_date()
    if d != expected:
        return None
    return {
'''
if old in s:
    s = s.replace(old, new, 1)
elif new not in s:
    raise SystemExit('stored-history strict-date anchor not found')

p.write_text(s, encoding='utf-8')
print('Gold prior-close source hardened: Investing -> XAUS history -> exact-date stored fallback')
