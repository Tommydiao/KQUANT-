"""Bounded new official originals; no configuration changes or approvals."""
from datetime import UTC, datetime
from hashlib import sha256
from html.parser import HTMLParser
import importlib.util
import json
from pathlib import Path
from urllib.request import Request, build_opener
from urllib.error import HTTPError
import argparse
from time import monotonic

ROOT = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("prior_capture", ROOT / "evidence/source-material-recovery-20261007-v1/capture_remaining_candidate_asset_sources.py")
PRIOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PRIOR)


class Title(HTMLParser):
    def __init__(self):
        super().__init__()
        self.active = False
        self.parts = []
    def handle_starttag(self, tag, attrs):
        if tag == "title":
            self.active = True
    def handle_endtag(self, tag):
        if tag == "title":
            self.active = False
    def handle_data(self, data):
        if self.active:
            self.parts.append(data)


def main():
    arguments = argparse.ArgumentParser()
    arguments.add_argument('--missing', action='store_true')
    arguments.add_argument('--limit', type=int, default=20, choices=range(1, 21))
    arguments.add_argument('--label', default='asset-recapture-20261010')
    args = arguments.parse_args()
    if not args.label or any(c not in 'abcdefghijklmnopqrstuvwxyz0123456789-' for c in args.label):
        raise ValueError('INVALID_OUTPUT_LABEL')
    targets = [(s, 'https://www.nasdaq.com/market-activity/stocks/' + s.lower()) for s in ('MSTR', 'HOOD', 'COIN')]
    if args.missing:
        import prepare_local_entry as entry
        _, issues = entry.source_inventory(entry.configuration_files())
        config = json.loads((entry.CODE / 'config/review_acceptances/options_opening_trend_reference_sources.json').read_bytes())
        targets = []
        attempted = set()
        for prior in (ROOT / 'evidence/new-machine-20261008').glob('asset-recapture*/receipt.json'):
            for item in json.loads(prior.read_bytes()).get('attempts', []):
                if item.get('status') != 'NOT_REQUESTED_SERIES_BUDGET':
                    attempted.add((item.get('symbol'), item.get('source_url')))
        for issue in issues:
            parts = issue['json_pointer'].split('/')
            if len(parts) == 3 and parts[1] == 'instrument_facts':
                symbol = parts[2].replace('~1', '/').replace('~0', '~')
                url = config['instrument_facts'][symbol]['source_url']
                if not PRIOR.valid_url(url):
                    continue
                if (symbol, url) in attempted:
                    continue
                targets.append((symbol, url))
        targets = targets[:args.limit]
    out = ROOT / 'evidence/new-machine-20261008' / args.label
    out.mkdir(exist_ok=False)
    opener = build_opener(PRIOR.OfficialRedirect())
    rows = []
    started = monotonic()
    for symbol, url in targets:
        if not symbol or any(c not in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-' for c in symbol):
            raise ValueError('INVALID_SYMBOL')
        row = {"symbol": symbol, "source_url": url,
               "requested_at": datetime.now(UTC).isoformat(), "approved": False}
        try:
            if monotonic() - started >= 90:
                row.update(status='NOT_REQUESTED_SERIES_BUDGET')
                rows.append(row)
                continue
            request = Request(url, headers={"User-Agent": "KQUANT-public-document-audit/1.0", "Accept-Encoding": "identity"})
            with opener.open(request, timeout=4) as response:
                raw = response.read(PRIOR.MAX_BYTES + 1)
                if not PRIOR.valid_url(response.url) or not 0 < len(raw) <= PRIOR.MAX_BYTES:
                    raise ValueError("SOURCE_BOUNDARY_FAILED")
                if "text/html" not in response.headers.get("Content-Type", ""):
                    raise ValueError("HTML_REQUIRED")
                parser = Title()
                parser.feed(raw.decode("utf-8"))
                digest = sha256(raw).hexdigest()
                target = out / (symbol + "-" + digest + ".html")
                with target.open("xb") as handle:
                    handle.write(raw)
                row.update(status="CAPTURED_PENDING_REVIEW", http_status=response.status,
                           final_url=response.url, source_path=str(target.relative_to(ROOT)),
                           source_sha256=digest, title="".join(parser.parts), bytes=len(raw))
        except (OSError, ValueError, UnicodeError) as exc:
            row.update(status="PUBLIC_SOURCE_UNAVAILABLE", error_type=type(exc).__name__)
            if isinstance(exc, HTTPError):
                row["http_status"] = exc.code
        row["completed_at"] = datetime.now(UTC).isoformat()
        rows.append(row)
    report = {"new_capture_not_restoration": True, "configuration_changed": False,
              "sdk_connections": 0, "attempts": rows}
    with (out / "receipt.json").open("x", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2)
    print(json.dumps(report))


if __name__ == "__main__":
    main()
