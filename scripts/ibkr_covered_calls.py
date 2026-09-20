"""
scripts/ibkr_covered_calls.py
=============================
Covered-call overlay on the income/defensive sleeves, with monthly roll.

Strategy (from the covered-call study, dashboard Portfolio tab):
  • Write ~30-45 DTE calls ONLY on the income/defensive sleeves (SPY, GLD, IEF).
    NEVER on QQQ/SOXX/AIPO (their upside is the point of the strategy); SPYI is
    already an options-income fund; DBMF options are too illiquid.
  • Strike ≈ 0.30-delta proxy via a per-ticker OTM%% band (vol-scaled).
  • Contracts = floor(shares / 100) — always fully covered, never naked.
  • Roll: buy-to-close any existing short calls, then sell the next monthly.

Run monthly on the 2nd (the day AFTER the rebalance) so contract counts are
sized against post-rebalance share counts. If shares were assigned away at
expiry, the monthly rebalance naturally re-buys them — self-healing.

SAFE BY DEFAULT: dry-run prints the plan. --execute places PAPER orders only
(hard-refuses accounts not starting with "DU", same guard as ibkr_rebalance.py).

Usage:
  python scripts/ibkr_covered_calls.py [--port 7497] [--execute]
"""
import argparse
import json
import math
import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SNAPSHOT = ROOT / "data" / "cache" / "ibkr_account.json"

# Ticker -> OTM band for the short strike (rough 0.30-delta proxy at ~35 DTE,
# scaled to each ETF's vol: GLD ~27% vol -> 5%; SPY ~12% -> 3%; IEF ~7% -> 2.0%).
WRITE_ON = {"SPY": 0.030, "GLD": 0.050, "IEF": 0.020}
MIN_DTE, MAX_DTE = 25, 60


def pick_expiry(expirations):
    """Nearest monthly expiration >= MIN_DTE days out (IBKR gives YYYYMMDD strings)."""
    today = date.today()
    cands = []
    for e in sorted(expirations):
        d = datetime.strptime(e, "%Y%m%d").date()
        dte = (d - today).days
        if MIN_DTE <= dte <= MAX_DTE:
            # prefer the standard monthly (3rd Friday): weekday 4, day 15-21
            monthly = (d.weekday() == 4 and 15 <= d.day <= 21)
            cands.append((not monthly, dte, e))   # monthlies sort first
    if not cands:
        return None, 0
    cands.sort()
    _, dte, e = cands[0]
    return e, dte


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=7497)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--client-id", type=int, default=9)
    ap.add_argument("--execute", action="store_true", help="place PAPER option orders")
    args = ap.parse_args()

    try:
        from ib_async import IB, Stock, Option, MarketOrder
    except ImportError:
        print("ib_async not installed.  Run:  pip install ib_async"); sys.exit(1)

    ib = IB()
    try:
        ib.connect(args.host, args.port, clientId=args.client_id, timeout=10)
    except Exception as e:
        print(f"Could not connect to TWS/Gateway at {args.host}:{args.port} ({e})."); sys.exit(1)

    managed = ib.managedAccounts()
    is_paper = any(a.startswith("DU") for a in managed)
    print(f"Account(s): {managed}  ({'PAPER' if is_paper else 'NON-PAPER'})")
    if not is_paper and args.execute:
        print("Refusing to --execute options on a non-paper account. Aborting.")
        ib.disconnect(); sys.exit(1)

    # Current holdings: shares (STK) and existing short calls (OPT)
    shares, short_calls = {}, []
    for p in ib.positions():
        c = p.contract
        if c.secType == "STK" and c.symbol in WRITE_ON:
            shares[c.symbol] = int(p.position)
        elif c.secType == "OPT" and c.right == "C" and p.position < 0 and c.symbol in WRITE_ON:
            short_calls.append((c, int(p.position)))

    # Spot prices: snapshot JSON (refreshed daily at 9:00) with delayed-data fallback
    spots = {}
    try:
        snap = json.loads(SNAPSHOT.read_text())
        spots = {p["ticker"]: float(p["market_price"]) for p in snap.get("positions", [])}
    except Exception:
        pass

    plan = []          # (action, contract, qty, note)

    # 1) Roll out: buy-to-close every existing short call on our underlyings
    for c, pos in short_calls:
        plan.append(("BUY", c, abs(pos), f"close short {c.symbol} {c.lastTradeDateOrContractMonth} C{c.strike}"))

    # 2) Write new monthlies sized to current shares
    for sym, otm in WRITE_ON.items():
        n = math.floor(shares.get(sym, 0) / 100)
        if n <= 0:
            print(f"{sym}: {shares.get(sym, 0)} shares -> 0 contracts, skip")
            continue
        stk = Stock(sym, "SMART", "USD")
        ib.qualifyContracts(stk)
        spot = spots.get(sym, 0.0)
        if not spot:
            ib.reqMarketDataType(3)  # delayed
            t = ib.reqMktData(stk, "", False, False); ib.sleep(2)
            spot = t.marketPrice() or t.close or 0.0
            ib.cancelMktData(stk)
        if not spot or spot != spot:
            print(f"{sym}: no spot price available, skip"); continue

        chains = ib.reqSecDefOptParams(stk.symbol, "", stk.secType, stk.conId)
        # Prefer the standard class (tradingClass == symbol): SPY's SMART entry is
        # the quarterly '2SPY' class whose 2 expirations can all miss the DTE window.
        chain = (next((ch for ch in chains if ch.exchange == "SMART" and ch.tradingClass == sym), None)
                 or next((ch for ch in chains if ch.tradingClass == sym), None)
                 or (chains[0] if chains else None))
        if not chain:
            print(f"{sym}: no option chain, skip"); continue
        expiry, dte = pick_expiry(chain.expirations)
        if not expiry:
            print(f"{sym}: no expiration in {MIN_DTE}-{MAX_DTE} DTE window, skip"); continue
        target = spot * (1 + otm)
        strikes = sorted(s for s in chain.strikes if s >= target)
        if not strikes:
            print(f"{sym}: no strike >= {target:.2f}, skip"); continue
        strike = strikes[0]
        opt = Option(sym, expiry, strike, "C", "SMART", tradingClass=chain.tradingClass)
        try:
            ib.qualifyContracts(opt)
        except Exception as e:
            print(f"{sym}: could not qualify {expiry} C{strike} ({e}), skip"); continue
        plan.append(("SELL", opt, n,
                     f"write {n}x {sym} {expiry} C{strike} ({dte}d, spot {spot:.2f}, {otm:.1%} OTM)"))

    if not plan:
        print("Nothing to do."); ib.disconnect(); return

    print("\nPLAN:")
    for action, _c, qty, note in plan:
        print(f"  {action:4s} {qty:3d}  {note}")

    if not args.execute:
        print(f"\nDRY-RUN: {len(plan)} orders above would be sent. Re-run with --execute.")
        ib.disconnect(); return

    print(f"\nPlacing {len(plan)} PAPER option orders (market orders; if the market is "
          f"closed they queue and fill at the open)...")
    for action, c, qty, note in plan:
        trade = ib.placeOrder(c, MarketOrder(action, qty))
        ib.sleep(1)
        print(f"  {action} {qty} {c.symbol} -> {trade.orderStatus.status}")
    ib.sleep(2)
    print("Done. Check TWS -> Orders/Trades; tomorrow's 9AM snapshot reflects the fills.")
    ib.disconnect()


if __name__ == "__main__":
    main()
