#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: Path, old: str, new: str, label: str):
    text = path.read_text(encoding='utf-8')
    if new in text:
        print(f'{label}: already patched')
        return False
    if old not in text:
        raise SystemExit(f'{label}: anchor not found')
    path.write_text(text.replace(old, new, 1), encoding='utf-8')
    print(f'{label}: patched')
    return True


# 1) Brent frontend: use the actual previous completed close, not rows[-2].
p = ROOT / 'index.html'
text = p.read_text(encoding='utf-8')
old = "const rows=brentPayload.data,last=rows[rows.length-1],prev=rows[rows.length-2];"
new = "const rows=brentPayload.data,last=rows[rows.length-1];"
if old in text:
    text = text.replace(old, new, 1)
old = "const base=Number(prev?.value??last.value),chg=base?((display/base)-1)*100:0;"
new = "const base=Number(quote.previous_close??last.value),chg=base?((display/base)-1)*100:0;"
if old not in text and new not in text:
    raise SystemExit('index.html: Brent baseline anchor not found')
text = text.replace(old, new, 1)
p.write_text(text, encoding='utf-8')
print('index.html: Brent previous-close baseline fixed')

# 2) Gold frontend: prefer explicit previous_close from the quote payload.
p = ROOT / 'assets' / 'chart-time-slider.js'
replace_once(
    p,
    "    const base = Number(last?.value);\n    if (changeEl && Number.isFinite(price) && Number.isFinite(base) && base !== 0) {",
    "    const base = Number(quote.previous_close ?? last?.value);\n    if (changeEl && Number.isFinite(price) && Number.isFinite(base) && base !== 0) {",
    'chart-time-slider.js gold baseline',
)

# 3) Brent quote updater: persist Yahoo's chartPreviousClose / previousClose.
p = ROOT / 'scripts' / 'update_ai_brent_quote.py'
text = p.read_text(encoding='utf-8')
if '"previous_close": round(previous_close, 4)' not in text:
    anchor = "result = (payload.get(\"chart\", {}).get(\"result\") or [None])[0]\nif not result:\n    raise RuntimeError(\"Yahoo Finance returned no BZ=F chart result.\")\n\ntimestamps = result.get(\"timestamp\") or []"
    repl = "result = (payload.get(\"chart\", {}).get(\"result\") or [None])[0]\nif not result:\n    raise RuntimeError(\"Yahoo Finance returned no BZ=F chart result.\")\n\nmeta = result.get(\"meta\") or {}\ntimestamps = result.get(\"timestamp\") or []"
    if anchor not in text:
        raise SystemExit('update_ai_brent_quote.py: meta anchor not found')
    text = text.replace(anchor, repl, 1)

    anchor = "if latest_timestamp is None or latest_price is None:\n    raise RuntimeError(\"Yahoo Finance returned no valid 1-minute BZ=F bars.\")\n\nbjt = ZoneInfo(\"Asia/Shanghai\")"
    repl = "if latest_timestamp is None or latest_price is None:\n    raise RuntimeError(\"Yahoo Finance returned no valid 1-minute BZ=F bars.\")\n\nprevious_close_raw = meta.get(\"chartPreviousClose\")\nif previous_close_raw in (None, 0):\n    previous_close_raw = meta.get(\"previousClose\")\nprevious_close = float(previous_close_raw) if previous_close_raw not in (None, 0) else None\nif previous_close is not None and not 1.0 < previous_close < 1000.0:\n    previous_close = None\nchange_vs_previous_close_pct = (\n    ((latest_price / previous_close) - 1.0) * 100.0 if previous_close else None\n)\n\nbjt = ZoneInfo(\"Asia/Shanghai\")"
    if anchor not in text:
        raise SystemExit('update_ai_brent_quote.py: previous-close anchor not found')
    text = text.replace(anchor, repl, 1)

    anchor = "    \"price\": latest_price,\n    \"timestamp\": quote_iso,"
    repl = "    \"price\": latest_price,\n    \"previous_close\": round(previous_close, 4) if previous_close is not None else None,\n    \"change_vs_previous_close_pct\": round(change_vs_previous_close_pct, 4) if change_vs_previous_close_pct is not None else None,\n    \"previous_close_source\": \"Yahoo Finance BZ=F chart meta\" if previous_close is not None else None,\n    \"timestamp\": quote_iso,"
    if anchor not in text:
        raise SystemExit('update_ai_brent_quote.py: new_quote anchor not found')
    text = text.replace(anchor, repl, 1)
    p.write_text(text, encoding='utf-8')
    print('update_ai_brent_quote.py: previous close persisted')
else:
    print('update_ai_brent_quote.py: already patched')

# 4) Gold updater: scrape Investing.com Prev. Close with hardened transport;
#    fallback only to a sufficiently recent completed daily bar.
p = ROOT / 'scripts' / 'update_ai_gold.py'
text = p.read_text(encoding='utf-8')
if 'fetch_investing_previous_close' not in text:
    text = text.replace('import json\n', 'import json\nimport html as html_lib\nimport re\n', 1)
    text = text.replace(
        'import requests\n',
        "import requests\n\ntry:\n    from curl_cffi import requests as curl_requests\nexcept Exception:\n    curl_requests = None\n",
        1,
    )
    text = text.replace(
        'GOLD_API_SPOT_URL = "https://api.gold-api.com/price/XAU"\n',
        'GOLD_API_SPOT_URL = "https://api.gold-api.com/price/XAU"\nINVESTING_GOLD_URLS = [\n    "https://www.investing.com/currencies/xau-usd",\n    "https://www.investing.com/currencies/xau-usd-candlestick",\n    "https://www.investing.com/currencies/xau-usd-historical-data",\n]\nNY_TZ = ZoneInfo("America/New_York")\nBROWSER_HEADERS = {\n    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/153.0.0.0 Safari/537.36",\n    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",\n    "Accept-Language": "en-US,en;q=0.9",\n    "Cache-Control": "no-cache",\n    "Pragma": "no-cache",\n}\n',
        1,
    )

    anchor = '\ndef fetch_live_quote():\n'
    helper = r'''
def browser_get(url: str, timeout: int = 25):
    errors = []
    if curl_requests is not None:
        try:
            r = curl_requests.get(
                url,
                headers=BROWSER_HEADERS,
                timeout=timeout,
                impersonate="chrome",
                allow_redirects=True,
            )
            if r.status_code == 200 and len(r.text) > 1000:
                return r.text, "curl_cffi/chrome"
            errors.append(f"curl_cffi HTTP {r.status_code} len={len(r.text)}")
        except Exception as exc:
            errors.append(f"curl_cffi {exc}")
    try:
        r = requests.get(url, headers=BROWSER_HEADERS, timeout=timeout, allow_redirects=True)
        if r.status_code == 200 and len(r.text) > 1000:
            return r.text, "requests"
        errors.append(f"requests HTTP {r.status_code} len={len(r.text)}")
    except Exception as exc:
        errors.append(f"requests {exc}")
    raise RuntimeError("; ".join(errors))


def expected_previous_gold_session_date():
    d = datetime.now(NY_TZ).date() - timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def fetch_investing_previous_close(live_price: float | None = None):
    errors = []
    for url in INVESTING_GOLD_URLS:
        try:
            raw, transport = browser_get(url)
            text = html_lib.unescape(re.sub(r"<[^>]+>", " ", raw))
            text = re.sub(r"\s+", " ", text).strip()
            if "XAU/USD" not in text and "Gold Spot US Dollar" not in text:
                raise RuntimeError("unexpected Investing.com instrument page")
            m = re.search(r"Prev\.\s*Close\s+([0-9][0-9,]*(?:\.[0-9]+)?)", text, flags=re.I)
            if not m:
                raise RuntimeError("Prev. Close not found")
            previous_close = float(m.group(1).replace(",", ""))
            if not 100.0 < previous_close < 20000.0:
                raise RuntimeError(f"implausible previous close {previous_close}")
            if live_price and abs(float(live_price) / previous_close - 1.0) > 0.15:
                raise RuntimeError(
                    f"previous close/live quote divergence exceeds 15% ({previous_close} vs {live_price})"
                )
            return {
                "previous_close": round(previous_close, 2),
                "previous_close_source": "Investing.com XAU/USD Prev. Close",
                "previous_close_url": url,
                "previous_close_transport": transport,
                "previous_close_observation_date": expected_previous_gold_session_date().isoformat(),
            }
        except Exception as exc:
            errors.append(f"{url}: {exc}")
    raise RuntimeError(" | ".join(errors))


def fresh_history_previous_close(rows):
    session_date = datetime.now(NY_TZ).date()
    candidates = []
    for row in rows:
        if row.get("frequency") != "daily" or row.get("value") is None or not row.get("date"):
            continue
        try:
            d = datetime.fromisoformat(str(row["date"])[:10]).date()
            value = float(row["value"])
        except Exception:
            continue
        if d < session_date and 100.0 < value < 20000.0:
            candidates.append((d, value, row.get("source") or "stored daily history"))
    if not candidates:
        return None
    d, value, source = max(candidates, key=lambda x: x[0])
    # Friday -> Monday and common one-day market holidays are allowed; anything
    # older is not safe to call the prior completed daily close.
    if (session_date - d).days > 4:
        return None
    return {
        "previous_close": round(value, 2),
        "previous_close_source": source,
        "previous_close_url": None,
        "previous_close_transport": "stored_history",
        "previous_close_observation_date": d.isoformat(),
    }

'''
    if anchor not in text:
        raise SystemExit('update_ai_gold.py: live quote anchor not found')
    text = text.replace(anchor, helper + anchor, 1)

    anchor = '    coverage_has_world_bank = merged[0]["date"] <= "1990-01-01"\n'
    insert = '''    previous_close_warning = None\n    previous_close_info = None\n    try:\n        previous_close_info = fetch_investing_previous_close(float(quote.get("price")))\n    except Exception as exc:\n        previous_close_warning = str(exc)\n        previous_close_info = fresh_history_previous_close(merged)\n        if previous_close_info is None:\n            print(f"Previous-close warning: {exc}; no sufficiently fresh completed daily close available")\n        else:\n            print(f"Previous-close warning: {exc}; using fresh stored daily close {previous_close_info['previous_close_observation_date']}")\n\n    if previous_close_info:\n        quote.update(previous_close_info)\n        previous_close = float(previous_close_info["previous_close"])\n        live_price = float(quote["price"])\n        quote["change_vs_previous_close_pct"] = round((live_price / previous_close - 1.0) * 100.0, 4)\n    else:\n        quote["previous_close"] = None\n        quote["change_vs_previous_close_pct"] = None\n\n'''
    if anchor not in text:
        raise SystemExit('update_ai_gold.py: payload assembly anchor not found')
    text = text.replace(anchor, insert + anchor, 1)

    anchor = '        "history_fetch_warning": history_error,\n        "world_bank_fetch_warning": world_bank_error,\n'
    repl = '        "history_fetch_warning": history_error,\n        "world_bank_fetch_warning": world_bank_error,\n        "previous_close_fetch_warning": previous_close_warning,\n'
    if anchor not in text:
        raise SystemExit('update_ai_gold.py: warning payload anchor not found')
    text = text.replace(anchor, repl, 1)
    p.write_text(text, encoding='utf-8')
    print('update_ai_gold.py: Investing previous-close layer added')
else:
    print('update_ai_gold.py: already patched')

# 5) Gold workflow: install hardened HTTP transport and validate previous_close.
p = ROOT / '.github' / 'workflows' / 'update-ai-gold.yml'
text = p.read_text(encoding='utf-8')
text = text.replace(
    'run: pip install --disable-pip-version-check requests',
    'run: pip install --disable-pip-version-check requests curl_cffi',
)
anchor = "          assert float(quote['price']) > 100\n          assert quote.get('timestamp')\n"
repl = "          assert float(quote['price']) > 100\n          assert float(quote['previous_close']) > 100\n          assert quote.get('previous_close_source')\n          assert isinstance(quote.get('change_vs_previous_close_pct'), (int, float))\n          assert quote.get('timestamp')\n"
if anchor in text:
    text = text.replace(anchor, repl, 1)
elif "assert float(quote['previous_close']) > 100" not in text:
    raise SystemExit('update-ai-gold.yml: validation anchor not found')
p.write_text(text, encoding='utf-8')
print('update-ai-gold.yml: hardened dependencies and validation')

# 6) Brent workflow: changes to the quote script should trigger a refresh, and validate baseline.
p = ROOT / '.github' / 'workflows' / 'update-ai-brent-quote.yml'
text = p.read_text(encoding='utf-8')
path_anchor = "    paths:\n      - '.github/workflows/update-ai-brent-quote.yml'\n"
path_repl = "    paths:\n      - '.github/workflows/update-ai-brent-quote.yml'\n      - 'scripts/update_ai_brent_quote.py'\n      - 'index.html'\n"
if path_anchor in text:
    text = text.replace(path_anchor, path_repl, 1)
elif "- 'scripts/update_ai_brent_quote.py'" not in text:
    raise SystemExit('update-ai-brent-quote.yml: paths anchor not found')

step_anchor = "      - name: Detect changes\n        id: detect\n"
validation_step = "      - name: Validate previous completed close\n        run: |\n          python - <<'PY'\n          import json\n          from pathlib import Path\n          d=json.loads(Path('data/ai_bubble/macro/brent.json').read_text())\n          q=d.get('latest_quote') or {}\n          assert float(q.get('price')) > 1\n          assert float(q.get('previous_close')) > 1\n          assert isinstance(q.get('change_vs_previous_close_pct'), (int,float))\n          print('Brent', q['price'], 'prev', q['previous_close'], 'change%', q['change_vs_previous_close_pct'])\n          PY\n      - name: Detect changes\n        id: detect\n"
if step_anchor in text:
    text = text.replace(step_anchor, validation_step, 1)
elif 'Validate previous completed close' not in text:
    raise SystemExit('update-ai-brent-quote.yml: detect step anchor not found')
p.write_text(text, encoding='utf-8')
print('update-ai-brent-quote.yml: script trigger and validation added')

print('Macro commodity prior-close fixes prepared successfully')
