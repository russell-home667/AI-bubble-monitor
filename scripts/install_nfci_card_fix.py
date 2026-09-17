from pathlib import Path
import re

INDEX = Path('index.html')
text = INDEX.read_text(encoding='utf-8')

# Load the NFCI tile repair directly from index.html so it does not depend on
# another cached frontend asset being refreshed first.
new_tag = '<script src="assets/nfci-card-fix.js?v=20260917b"></script>'

# Replace any older direct NFCI repair tag with the current cache-busted tag.
text = re.sub(
    r'<script\s+src="assets/nfci-card-fix\.js(?:\?v=[^"]*)?"></script>',
    new_tag,
    text,
)

if new_tag not in text:
    needle = '<script src="assets/chart-time-slider.js"></script>'
    if needle not in text:
        raise SystemExit('chart-time-slider script tag not found')
    text = text.replace(needle, needle + '  ' + new_tag, 1)

if text.count('assets/nfci-card-fix.js') != 1:
    raise SystemExit('Expected exactly one direct NFCI repair script tag in index.html')

INDEX.write_text(text, encoding='utf-8')
print('Installed direct NFCI tile repair script with cache busting')
