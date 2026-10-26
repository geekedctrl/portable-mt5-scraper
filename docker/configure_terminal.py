"""Persist the chart limit before MT5 starts, preserving unrelated settings."""
import os
from pathlib import Path
import re

limit = os.environ.get('MT5_MAX_BARS', '100000000')
if not limit.isdecimal() or int(limit) < 1:
    raise SystemExit('MT5_MAX_BARS must be a positive integer')
path = Path('/state/terminal/Config/common.ini')
# MT5 creates config/ in lowercase on some installations.
lower = Path('/state/terminal/config/common.ini')
if lower.exists():
    path = lower
path.parent.mkdir(parents=True, exist_ok=True)
raw = path.read_bytes() if path.exists() else b''
encoding = 'utf-16' if raw.startswith((b'\xff\xfe', b'\xfe\xff')) else 'utf-8-sig'
text = raw.decode(encoding) if raw else ''
section = re.search(r'(?ims)^\[Charts\][ \t]*\r?\n(.*?)(?=^\[|\Z)', text)
if section:
    body = section.group(1)
    if re.search(r'(?im)^MaxBars\s*=', body):
        body = re.sub(r'(?im)^MaxBars\s*=.*$', 'MaxBars=' + limit, body)
    else:
        body += '\nMaxBars=' + limit + '\n'
    text = text[:section.start(1)] + body + text[section.end(1):]
else:
    text += '\n[Charts]\nMaxBars=' + limit + '\n'
path.write_text(text, encoding=encoding)
print('Configured persistent MT5 chart limit:', limit, flush=True)
