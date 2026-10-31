import pytest
from integrate_recaptured_assets import reviewed_asset_type, reviewed_page, Titles


@pytest.mark.parametrize('kind,title', [
    ('US_ORDINARY_EQUITY', 'Company Common Stock (TEST)'),
    ('US_ORDINARY_EQUITY', 'Company Common Shares (TEST)'),
    ('US_ORDINARY_EQUITY', 'Company Class A Ordinary Shares (TEST)'),
    ('US_ETF', 'Example Fund ETF (TEST)'),
    ('US_ETN', 'Example Exchange Traded Notes (TEST)'),
    ('US_ADR', 'Example American Depositary Shares (TEST)'),
    ('US_PREFERRED', 'Example Preferred Stock (TEST)'),
])
def test_explicit_distinct_asset_titles(kind, title):
    assert reviewed_asset_type(kind, title) == kind
    assert reviewed_asset_type('UNKNOWN', title) is None
    if kind != 'US_ORDINARY_EQUITY':
        assert reviewed_asset_type('US_ORDINARY_EQUITY', title) is None


@pytest.mark.parametrize('kind,title', [
    ('US_ETF', 'Example Trust (TEST)'),
    ('US_ETF', 'Example ETN (TEST)'),
    ('US_ORDINARY_EQUITY', 'Example Common Stock REIT (TEST)'),
    ('US_ETF', 'Example Preferred ETF (TEST)'),
    ('US_ADR', 'Example Ordinary Shares (TEST)'),
    ('US_ORDINARY_EQUITY', 'American Depositary Shares representing Ordinary Shares (TEST)'),
])
def test_ambiguous_or_mismatched_asset_titles_remain_unverified(kind, title):
    assert reviewed_asset_type(kind, title) is None


def test_raw_title_entities_are_preserved_and_titles_not_concatenated():
    parser = Titles()
    parser.feed('<title>A &amp; B Common Stock (TEST)</title><title>TEST | Exchange</title>')
    assert parser.values == ['A &amp; B Common Stock (TEST)', 'TEST | Exchange']


@pytest.mark.parametrize('url', [
    'https://www.nasdaq.com/market-activity/stocks/other',
    'https://www.nasdaq.com.evil.invalid/market-activity/stocks/test',
    'http://www.nasdaq.com/market-activity/stocks/test',
    'https://www.nasdaq.com/market-activity/stocks/test?symbol=other',
])
def test_page_identity_rejects_mismatched_or_untrusted_url(url):
    with pytest.raises(ValueError, match='URL_IDENTITY'):
        reviewed_page(b'<title>Company Common Stock (TEST)</title>',
            symbol='TEST', url=url, expected='US_ORDINARY_EQUITY')


@pytest.mark.parametrize('raw', [
    b'<title>Company Common Stock (OTHER)</title>',
    b'<title>Company Common Stock (TEST)</title><title>Other Common Stock (TEST)</title>',
])
def test_page_requires_one_matching_literal_title(raw):
    with pytest.raises(ValueError, match='TITLE_IDENTITY'):
        reviewed_page(raw, symbol='TEST',
            url='https://www.nasdaq.com/market-activity/stocks/test', expected='US_ORDINARY_EQUITY')


def test_preferred_securities_fund_is_not_a_preferred_stock():
    title = 'Example Preferred Securities ETF (TEST)'
    assert reviewed_asset_type('US_ETF', title) == 'US_ETF'
    assert reviewed_asset_type('US_PREFERRED', title) is None
    with pytest.raises(ValueError, match='ASSET_CLASS'):
        reviewed_page(f'<title>{title}</title>'.encode(), symbol='TEST',
            url='https://www.nasdaq.com/market-activity/etf/test', expected='US_ORDINARY_EQUITY')
