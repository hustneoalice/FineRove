"""The native workbench must ship rendering without private calculations or old auth."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3] / "dashboard" / "financial-workbench"


def test_native_shell_and_entry_exist():
    html = (ROOT / "index.html").read_text()
    for control in (
        'id="kl-period"',
        'id="kl-layout"',
        'id="kl-panels"',
        'id="rightcol"',
        'id="page-watchlist"',
        'id="modal-watch"',
    ):
        assert control in html
    assert 'src="./src/bootstrap.ts"' in html


def test_no_private_calculations_or_legacy_transport():
    files = list((ROOT / "src").rglob("*.ts"))
    assert files
    source = "\n".join(p.read_text() for p in files)
    for forbidden in (
        "sixSegment",
        "estimateFloatShares",
        "accumulationSeries",
        "mainCostSeries",
        "stockOperateSeries",
        "volumeActivitySeries",
        "trendHistogramSeries",
        "strongPullbackSeries",
        "qyjjSeries",
        "chipDistribution",
        "registerTrendChannel",
        "trendDevs",
        "new EventSource",
        "/api/v1",
        "getToken",
        "Storage.prototype",
        "ZY_",
        "众赢",
    ):
        assert forbidden not in source, forbidden
    for p in files:
        assert p.stem not in {
            "accumulation",
            "main-cost",
            "stock-operate",
            "volume-activity",
            "trend-histogram",
            "strong-pullback",
            "qyjj",
            "chips",
            "auth",
            "sse",
            "main-cost-settings",
        }
        assert "fetch(" not in p.read_text(), p
        if p.name != "storage.ts":
            assert "localStorage." not in p.read_text(), p


def test_trusted_bootstrap_before_native_imports():
    source = (ROOT / "src" / "bootstrap.ts").read_text()
    assert "event.origin !== location.origin" in source
    assert "event.source !== parent" in source
    assert source.index("initStorage(") < source.index('import("./main")')
    assert "finerove:finance:init" in source


def test_protected_controls_are_unavailable():
    source = (ROOT / "src" / "pages" / "market.ts").read_text()
    assert "NEO 自研指标尚未接入" in source
    assert 'disabled aria-disabled="true"' in source
