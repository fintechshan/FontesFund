"""
scripts/ibkr_rebalance.py
=========================
Paper-trade the regime strategy against Interactive Brokers (TWS / IB Gateway).

Run this LOCALLY on the machine where TWS is running — never from Cloud Run.
It connects to your PAPER account, reads NAV + current positions, computes the
target weights for the CURRENT macro regime (same logic the dashboard shows),
and prints the exact buy/sell orders to reach that target.

SAFE BY DEFAULT: dry-run (prints the plan, places nothing). Add --execute to
actually send PAPER market orders. Only ever point this at a paper account.

Steps before running:
  1) pip install ib_async
  2) In TWS: 配置/Configure → API → Settings →
       • Enable "ActiveX and Socket Clients"
       • Socket port = 7497 (TWS paper) | 7496 (TWS live) | 4002/4001 (Gateway)
       • Trusted IP: 127.0.0.1
       • Uncheck "Read-Only API" only when you want --execute to place orders
  3) python scripts/ibkr_rebalance.py            # dry-run preview
     python scripts/ibkr_rebalance.py --execute  # send PAPER orders

Usage:
  python scripts/ibkr_rebalance.py [--host 127.0.0.1] [--port 7497]
        [--client-id 7] [--execute]
  # --max-weight defaults to RISK_LIMITS.max_single_position (largest regime sleeve)
"""
import argparse
import math
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from config.regime_rules import REGIME_WEIGHTS, RISK_LIMITS

PRICE_CACHE = ROOT / "data" / "cache" / "price_data.csv"
MACRO_CACHE = ROOT / "data" / "cache" / "macro_data.pkl"


# ──────────────────────────────────────────────────────────────────────
# Current regime + target weights (mirrors the dashboard, lagged macro)
# ──────────────────────────────────────────────────────────────────────
def current_regime_and_weights():
    """Target notionals from the production engine's last day.

    The monthly regime sleeve is not the order. ``run_optimized_regime_backtest``
    then applies the daily overlay: 200-MA blend, portfolio vol scale, and
    portfolio drawdown shrink. The VIX 28→40 cut is not applied.
    This function runs that same engine and reads ``result.overlay``. Names with
    no price are dropped and the sleeve is renormalized inside the engine. They
    are not left as cash. There is no event-only order mode.
    """
    import pickle
    from config.regime_rules import STRATEGY_PARAMS
    from src.backtester.daily_overlay import policy_lines, weights_from_overlay
    from src.backtester.engine import BacktestEngine
    from src.backtester.regime_clock import MODE_TARGETED, classify_regimes

    price = pd.read_csv(PRICE_CACHE, index_col=0, parse_dates=True).ffill()
    macro = pickle.load(open(MACRO_CACHE, "rb"))
    history, current, _info = classify_regimes(macro, price, mode=MODE_TARGETED)
    regime = current.get("regime", "goldilocks")
    vix_now = float(current.get("vix", 0.0))

    available = set(price.columns)
    weights_map = {}
    for name, raw in REGIME_WEIGHTS.items():
        filtered = {k: v for k, v in raw.items() if k in available}
        total = sum(filtered.values())
        weights_map[name] = {k: v / total for k, v in filtered.items()} if total else {}

    ff = macro.get("ff_rate", pd.Series(dtype=float))
    if ff is not None and len(ff):
        ff = ff.copy()
        ff.index = pd.to_datetime(ff.index)
        ff = ff.loc[str(price.index.min().date()):]
        avg_rf = float(ff.mean() / 100.0) if len(ff) else 0.02
    else:
        avg_rf = 0.02
    engine = BacktestEngine(price, initial_capital=100_000, risk_free_rate=avg_rf)
    result = engine.run_optimized_regime_backtest(
        regime_history=history,
        regime_weights=weights_map,
        name="live-overlay",
        vix_data=macro.get("vix"),
        **STRATEGY_PARAMS,
    )
    overlay = result.overlay or {}
    weights = weights_from_overlay(overlay)
    last_px = price.ffill().iloc[-1]
    prices = {t: float(last_px[t]) for t in weights if t in last_px.index and pd.notna(last_px[t])}
    weights = {t: w for t, w in weights.items() if t in prices}
    print("\n".join(policy_lines()))
    print(
        f"\nOverlay as of {overlay.get('as_of')}: "
        f"trend_risk_on={overlay.get('trend_risk_on')} "
        f"equity_scale={float(overlay.get('equity_scale') or 1):.3f} "
        f"(vix={float(overlay.get('vix_scale') or 1):.3f}, "
        f"spy_dd={float(overlay.get('spy_dd_scale') or 1):.3f}) "
        f"vol_scale={overlay.get('vol_scale'):.3f} "
        f"dd_scale={overlay.get('dd_scale'):.3f} "
        f"gross={sum(weights.values()):.3f}"
    )
    return regime, vix_now, weights, prices


# ──────────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=7497, help="7497 TWS paper, 4002 Gateway paper")
    ap.add_argument("--client-id", type=int, default=7)
    ap.add_argument("--max-weight", type=float, default=RISK_LIMITS.max_single_position)
    ap.add_argument("--execute", action="store_true", help="actually send PAPER orders")
    args = ap.parse_args()

    try:
        from ib_async import IB, Stock, MarketOrder
    except ImportError:
        print("ib_async not installed.  Run:  pip install ib_async")
        sys.exit(1)

    regime, vix_now, weights, prices = current_regime_and_weights()
    print(f"\nCurrent regime: {regime.upper()}   (VIX {vix_now:.1f})")
    print(f"Target sleeves ({len(weights)}): " +
          ", ".join(f"{t} {w:.0%}" for t, w in sorted(weights.items(), key=lambda x: -x[1])))

    ib = IB()
    try:
        ib.connect(args.host, args.port, clientId=args.client_id, timeout=10)
    except Exception as e:
        print(f"\nCould not connect to TWS at {args.host}:{args.port} ({e}).")
        print("Enable API in TWS (Configure → API → Settings) and check the port.")
        sys.exit(1)

    acct = {x.tag: x.value for x in ib.accountSummary()}
    nav = float(acct.get("NetLiquidation", 0))
    if not nav or "DU" not in (acct.get("AccountType", "") + str(ib.managedAccounts())):
        # heuristic paper guard: IBKR paper accounts start with 'DU'
        pass
    managed = ib.managedAccounts()
    is_paper = any(a.startswith("DU") for a in managed)
    print(f"\nAccount(s): {managed}  ({'PAPER ✓' if is_paper else 'NON-PAPER ⚠️'})   NAV ${nav:,.0f}")
    if not is_paper and args.execute:
        print("Refusing to --execute on a non-paper account. Aborting.")
        ib.disconnect(); sys.exit(1)

    current = {p.contract.symbol: p.position for p in ib.positions()}

    # Build the order plan
    print(f"\n{'TICKER':8s}{'TARGET%':>9s}{'PRICE':>10s}{'TGT SH':>9s}{'CUR SH':>9s}{'ORDER':>10s}")
    print("-" * 56)
    orders = []
    for t, w in sorted(weights.items(), key=lambda x: -x[1]):
        if w > args.max_weight:
            w = args.max_weight  # risk cap
        px = prices[t]
        tgt_sh = math.floor(nav * w / px) if px > 0 else 0
        cur_sh = int(current.get(t, 0))
        delta = tgt_sh - cur_sh
        action = f"{'BUY' if delta > 0 else 'SELL'} {abs(delta)}" if delta else "—"
        print(f"{t:8s}{w:>8.1%}{px:>10.2f}{tgt_sh:>9d}{cur_sh:>9d}{action:>10s}")
        if delta:
            orders.append((t, delta))
    # Positions to fully exit (held but not in target)
    for sym, sh in current.items():
        if sym not in weights and sh:
            print(f"{sym:8s}{'0.0%':>9s}{'—':>10s}{0:>9d}{int(sh):>9d}{f'SELL {abs(int(sh))}':>10s}")
            orders.append((sym, -int(sh)))

    if not orders:
        print("\nAlready at target — no orders needed.")
        ib.disconnect(); return

    if not args.execute:
        print(f"\nDRY-RUN: {len(orders)} orders above would be sent. "
              f"Re-run with --execute to place them on the PAPER account.")
        ib.disconnect(); return

    print(f"\nPlacing {len(orders)} PAPER market orders...")
    for sym, delta in orders:
        contract = Stock(sym, "SMART", "USD")
        ib.qualifyContracts(contract)
        order = MarketOrder("BUY" if delta > 0 else "SELL", abs(delta))
        trade = ib.placeOrder(contract, order)
        ib.sleep(1)
        print(f"  {sym}: {order.action} {order.totalQuantity} → {trade.orderStatus.status}")
    ib.sleep(2)
    print("Done. Check TWS → Orders/Trades for fills.")
    ib.disconnect()


if __name__ == "__main__":
    main()
