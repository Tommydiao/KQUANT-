from __future__ import annotations

from kquant_crypto.universe_catalog import configured_cex_symbols, cex_symbol_tiers, load_universe_catalog


def test_default_catalog_has_separate_cex_tiers_and_dex_chains(tmp_path):
    catalog = load_universe_catalog(tmp_path)

    assert catalog["version"] == "crypto_universe_v1.1.0"
    assert catalog["cex"]["CORE"][:3] == ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    assert "MEME" in catalog["cex"]
    assert catalog["dex_chains"] == ["solana", "ethereum", "base", "bsc"]
    assert len(configured_cex_symbols(tmp_path)) >= 20


def test_catalog_normalizes_duplicates_and_rejects_invalid_symbols(tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "crypto_universe.yml").write_text(
        "version: test_v1\ncex:\n  CORE: [btc/usdt, BTCUSDT, '?']\ndex_chains: [Solana, solana]\n",
        encoding="utf-8",
    )

    assert configured_cex_symbols(tmp_path) == ("BTCUSDT",)
    assert cex_symbol_tiers(tmp_path) == {"BTCUSDT": "CORE"}
