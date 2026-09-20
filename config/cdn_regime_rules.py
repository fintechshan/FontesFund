"""
config/cdn_regime_rules.py
==========================
Canadian ETF Portfolio (6-ETF, CAD) -- Portfolio B (High-Growth 14.6%), 2026-09-19
Unhedged US Core + Nasdaq AI Tech + Canadian Banks + Gold + Bonds.

Universe B: ZQQ.TO, VFV.TO, ZEB.TO, XBB.TO, CGL-C.TO, XGD.TO
  ZQQ.TO   -- BMO NASDAQ 100 Equity Index ETF -- tech/AI growth engine
  VFV.TO   -- Vanguard S&P 500 Index ETF (Unhedged CAD) -- core US equity + FX alpha
  ZEB.TO   -- BMO Equal Weight Banks ETF -- Cdn banks income & dividend sleeve
  XBB.TO   -- iShares Core Canadian Bond Index -- bond/deflation sleeve
  CGL-C.TO -- iShares Gold Bullion ETF (CAD) -- gold/tail-risk crisis hedge
  XGD.TO   -- iShares S&P/TSX Global Gold Index -- gold miners / inflation spike

Backtest Results (2012-2026):
  CAGR = 14.62%  |  Max Drawdown = 15.53%  |  Sharpe Ratio = 1.16  |  Vol = 10.90%
"""

# -- Regime allocations (weights must sum to 1.0) -------------------------
CDN_REGIME_WEIGHTS = {
    "goldilocks": {
        "ZQQ.TO":   0.35,   # Nasdaq 100 tech/AI engine
        "VFV.TO":   0.25,   # S&P 500 core equity (unhedged)
        "ZEB.TO":   0.20,   # Cdn banks income & quality
        "XBB.TO":   0.08,   # Cdn bonds buffer
        "CGL-C.TO": 0.07,   # Gold tail hedge
        "XGD.TO":   0.05,   # Gold miners
    },
    "reflation": {
        "ZQQ.TO":   0.20,
        "VFV.TO":   0.20,
        "ZEB.TO":   0.15,
        "XBB.TO":   0.05,
        "CGL-C.TO": 0.20,   # Gold surges in reflation
        "XGD.TO":   0.20,   # Miners amplify gold move
    },
    "stagflation": {
        "ZQQ.TO":   0.05,
        "VFV.TO":   0.10,
        "ZEB.TO":   0.10,
        "XBB.TO":   0.20,
        "CGL-C.TO": 0.35,   # Gold primary hedge
        "XGD.TO":   0.20,
    },
    "deflation": {
        "ZQQ.TO":   0.05,
        "VFV.TO":   0.05,
        "ZEB.TO":   0.05,
        "XBB.TO":   0.50,   # Bonds dominate deflation
        "CGL-C.TO": 0.20,
        "XGD.TO":   0.15,
    },
}

# Runtime validation
for _regime, _weights in CDN_REGIME_WEIGHTS.items():
    _s = round(sum(_weights.values()), 10)
    assert _s == 1.0, f"CDN regime {_regime!r} weights sum to {_s}, not 1.0"

CDN_UNIVERSE  = list(CDN_REGIME_WEIGHTS["goldilocks"].keys())
CDN_VERSION   = "v2 (Portfolio B - 14.6% High-Growth)"
CDN_AB_WINNER = "Portfolio B (High-Growth 14.6%)"

