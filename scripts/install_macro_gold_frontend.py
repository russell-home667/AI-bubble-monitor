from pathlib import Path

INDEX = Path('index.html')
SOURCES = Path('assets/source-links.js')

index_text = INDEX.read_text(encoding='utf-8')
source_text = SOURCES.read_text(encoding='utf-8')

index_replacements = {
    'Gold Spot XAU/USD · Investing.com': 'Gold Spot XAU/USD · XAUS Gold Data API',
    'Yahoo Finance · Investing.com': 'Yahoo Finance · XAUS',
}

index_changed = False
for old, new in index_replacements.items():
    if old in index_text:
        index_text = index_text.replace(old, new)
        index_changed = True

source_definition_old = "    investingGold: {label:'Investing.com · XAU/USD', url:'https://www.investing.com/currencies/xau-usd'},"
source_definition_new = "    xausGold: {label:'XAUS · XAU/USD Spot', url:'https://xaus.com/'},"
if source_definition_old in source_text:
    source_text = source_text.replace(source_definition_old, source_definition_new)

# Migrate all commodity lineage rules to the new source key.
if 'S.investingGold' in source_text:
    source_text = source_text.replace('S.investingGold', 'S.xausGold')

# If a previous partial migration removed the old definition but did not add XAUS,
# insert it beside the Brent definition to preserve the AI Bubble Monitor source-link format.
if 'xausGold:' not in source_text:
    needle = "    yahooBrent: {label:'Yahoo Finance · BZ=F', url:'https://finance.yahoo.com/quote/BZ=F/'},\n"
    if needle not in source_text:
        raise SystemExit('Yahoo Brent source definition not found')
    source_text = source_text.replace(
        needle,
        needle + "    xausGold: {label:'XAUS · XAU/USD Spot', url:'https://xaus.com/'},\n",
        1,
    )

# Required frontend invariants.
required_index = [
    'Gold XAU/USD',
    'Gold USD/oz',
    'gold_xauusd.json',
    'XAUS Gold Data API',
]
for token in required_index:
    if token not in index_text:
        raise SystemExit(f'Frontend invariant missing: {token}')

required_sources = ['xausGold:', 'S.xausGold', 'https://xaus.com/']
for token in required_sources:
    if token not in source_text:
        raise SystemExit(f'Source-link invariant missing: {token}')

INDEX.write_text(index_text, encoding='utf-8')
SOURCES.write_text(source_text, encoding='utf-8')

print('Macro Commodity frontend aligned to XAUS XAU/USD while preserving AI Bubble Monitor layout and source-link conventions')
