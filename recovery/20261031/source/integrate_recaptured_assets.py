"""Review three newly captured identity originals; never approve publication."""
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import tempfile
import sys
import argparse
import re
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent
CODE = ROOT / "development/workspace"
sys.path.insert(0, str(CODE))
from kquant import options_one_minute as common
from kquant.options_opening_trend_reference import source_review
from kquant.options_price_facts import instrument


class Titles(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.active = False
        self.values = []
    def handle_starttag(self, tag, attrs):
        if tag == "title":
            self.active = True
            self.values.append("")
    def handle_endtag(self, tag):
        if tag == "title":
            self.active = False
    def handle_data(self, data):
        if self.active:
            self.values[-1] += data
    def handle_entityref(self, name):
        self.handle_data("&" + name + ";")
    def handle_charref(self, name):
        self.handle_data("&#" + name + ";")


def reviewed_asset_type(expected, title):
    text = title.lower()
    markers = {
        'US_ETF': bool(re.search(r'\betf\b|exchange.traded fund', text)),
        'US_ETN': bool(re.search(r'\betns?\b|exchange.traded notes?', text)),
        'US_ADR': bool(re.search(r'american deposit[ao]ry', text)),
        'US_PREFERRED': bool(re.search(r'\bpreferred\b', text)) and not bool(
            re.search(r'\bpreferred securities etf\b', text)),
    }
    if expected == 'US_ORDINARY_EQUITY':
        return expected if any(term in text for term in ('common stock', 'common shares', 'ordinary shares')) and not any(markers.values()) and 'reit' not in text else None
    return expected if markers.get(expected) and sum(markers.values()) == 1 else None


def reviewed_page(raw, *, symbol, url, expected):
    if not re.fullmatch(r'[A-Z0-9.-]+', symbol) or not 0 < len(raw) <= 1048576:
        raise ValueError('SOURCE_SIZE_OR_IDENTITY_UNCONFIRMED')
    parsed = urlsplit(url)
    paths = {f'/market-activity/{route}/{symbol.lower()}' for route in ('stocks', 'etf')}
    if (parsed.scheme != 'https' or parsed.netloc != 'www.nasdaq.com'
            or parsed.path not in paths or parsed.query or parsed.fragment):
        raise ValueError('SOURCE_URL_IDENTITY_MISMATCH')
    text = raw.decode('utf-8')
    parser = Titles()
    parser.feed(text)
    titles = [title for title in parser.values if '(' + symbol + ')' in title]
    if len(titles) != 1 or titles[0] not in text:
        raise ValueError('SOURCE_TITLE_IDENTITY_UNCONFIRMED')
    kind = reviewed_asset_type(expected, titles[0])
    if kind is None:
        raise ValueError('SEPARATE_ASSET_CLASS_REVIEW_REQUIRED')
    return kind, titles[0]


def main():
    arguments = argparse.ArgumentParser()
    arguments.add_argument('--label', default='asset-recapture-20261010')
    arguments.add_argument('--review-label')
    arguments.add_argument('--symbols', nargs='+')
    arguments.add_argument('--dry-run', action='store_true')
    args = arguments.parse_args()
    if not args.label or any(c not in 'abcdefghijklmnopqrstuvwxyz0123456789-' for c in args.label):
        raise ValueError('INVALID_OUTPUT_LABEL')
    evidence = ROOT / 'evidence/new-machine-20261008' / args.label
    receipt = json.loads((evidence / "receipt.json").read_text())
    capture_root = evidence.resolve()
    if args.review_label:
        if any(c not in 'abcdefghijklmnopqrstuvwxyz0123456789-' for c in args.review_label):
            raise ValueError('INVALID_REVIEW_LABEL')
        evidence = ROOT / 'evidence/new-machine-20261008' / args.review_label
        evidence.mkdir(exist_ok=False)
    config = CODE / "config/review_acceptances/options_opening_trend_reference_sources.json"
    before = config.read_bytes()
    updated = json.loads(before)
    now = datetime.now(UTC)
    results = []
    deferred = []
    for item in receipt["attempts"]:
        symbol = item["symbol"]
        if args.symbols and symbol not in args.symbols:
            continue
        if symbol not in updated['instrument_facts']:
            raise ValueError('UNKNOWN_INSTRUMENT')
        if item['status'] != 'CAPTURED_PENDING_REVIEW':
            deferred.append({'symbol': symbol, 'reason': item['status']})
            continue
        if symbol in {'DLR', 'EQIX', 'DXYZ', 'IRM'}:
            deferred.append({'symbol': symbol, 'reason': 'ISSUER_CLASS_REQUIRES_SEPARATE_REVIEW'})
            continue
        expected_url = updated['instrument_facts'][symbol]['source_url']
        if item['source_url'] != expected_url or item.get('final_url') != expected_url:
            deferred.append({'symbol': symbol, 'reason': 'SOURCE_URL_CHANGED_REVIEW_REQUIRED'})
            continue
        source = (ROOT / item["source_path"]).resolve()
        if not source.is_relative_to(capture_root):
            raise ValueError("CAPTURE_PATH_ESCAPE")
        raw = source.read_bytes()
        if sha256(raw).hexdigest() != item["source_sha256"]:
            raise ValueError("CAPTURE_CHANGED")
        try:
            asset_type, excerpt = reviewed_page(raw, symbol=symbol, url=item['source_url'],
                expected=updated['instrument_facts'][symbol].get('asset_type'))
        except ValueError as exc:
            deferred.append({'symbol': symbol, 'reason': str(exc)})
            continue
        if args.dry_run:
            results.append({'symbol': symbol, 'asset_type': asset_type,
                            'source_sha256': item['source_sha256'],
                            'document_review_only': True})
            continue
        relative = Path("outputs/r58/20261010/recaptured-assets") / source.name
        target = CODE / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            if target.read_bytes() != raw:
                raise ValueError("ORIGINAL_COLLISION")
        else:
            with target.open("xb") as handle:
                handle.write(raw)
        claim = {"underlying": symbol, "asset_type": asset_type, "official_title": excerpt}
        fact = {"status": "APPROVED", "source_kind": "OFFICIAL_INTERFACE_FACT",
                "fact_type": "INSTRUMENT_ASSET_IDENTITY", "interface": "EXCHANGE_INSTRUMENT_TITLE",
                "underlying": symbol, "asset_type": asset_type,
                "reviewer": "KQUANT_CODEX_EXCHANGE_TITLE_REVIEW_20261010",
                "review_method": "PROGRAMMATIC_DOCUMENT_REVIEW", "reviewed_at": now.isoformat(),
                "valid_until": (now + timedelta(days=7)).isoformat(),
                "source_url": item["source_url"], "source_path": relative.as_posix(),
                "source_sha256": item["source_sha256"], "excerpt": excerpt,
                "claim": claim, "claim_hash": common.digest(claim),
                "assertion_limits": ["IDENTITY_ONLY_NOT_PRICE_BASIS_OR_ACTION_COVERAGE", "NOT_DEPTH_UNITS", "NOT_OWNER_APPROVAL"]}
        assert source_review(fact, root=CODE, now=now) is not None
        assert source_review({**fact, "source_sha256": "0" * 64}, root=CODE, now=now) is None
        observed = instrument({"symbol": symbol}, now=now, reviews={"instrument_facts": {symbol: fact}}, root=CODE)
        assert observed["classification_status"] == "VERIFIED" and observed["status"] == "UNVERIFIED"
        results.append({"symbol": symbol, "old_fact": updated["instrument_facts"][symbol],
                        "new_fact": fact, "classification_verified": True,
                        "native_identity_currency_verified": False, "tampered_hash_rejected": True})
        updated["instrument_facts"][symbol] = fact
    if args.dry_run:
        if config.read_bytes() != before:
            raise ValueError('CONFIG_CHANGED_DURING_REVIEW')
        report = {'dry_run': True, 'config_unchanged': True,
                  'config_sha256': sha256(before).hexdigest(),
                  'owner_approval': False, 'results': results, 'deferred': deferred,
                  'unavailable': {k: v.get('unavailable_reason') for k, v in
                                  updated['instrument_facts'].items()
                                  if v.get('status') == 'UNAVAILABLE'}}
        print(json.dumps(report))
        return
    # Preserve the original configuration and refuse concurrent replacement.
    with (evidence / "reference-config-before.json").open("xb") as handle:
        handle.write(before)
    if config.read_bytes() != before:
        raise ValueError("CONFIG_CHANGED_DURING_REVIEW")
    data = (json.dumps(updated, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    fd, temporary = tempfile.mkstemp(dir=config.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if config.read_bytes() != before:
            raise ValueError("CONFIG_CHANGED_DURING_REVIEW")
        os.replace(temporary, config)
    finally:
        if Path(temporary).exists():
            Path(temporary).unlink()
    report = {"reviewed_at": now.isoformat(), "owner_approval": False,
              "before_sha256": sha256(before).hexdigest(), "after_sha256": sha256(data).hexdigest(), "results": results, 'deferred': deferred}
    with (evidence / "integration-review.json").open("x", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2)
    print(json.dumps({"integrated": len(results), 'deferred': deferred, "owner_approval": False, "native_identity_currency_verified": False}))


if __name__ == "__main__":
    main()
