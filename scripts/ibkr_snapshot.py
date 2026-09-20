"""
scripts/ibkr_snapshot.py
========================
Read-only snapshot of your IBKR account → feeds the dashboard's Execution tab.

Run this LOCALLY where TWS / IB Gateway is running. It connects to the account,
reads NAV + positions + P&L (it NEVER places an order), and writes two files the
deployed dashboard reads to show *live* paper/real performance:

    data/cache/ibkr_account.json         # full snapshot (NAV, positions, weights, P&L)
    data/cache/ibkr_equity_history.csv   # one NAV row per snapshot day (for the curve)

Workflow:
    1) pip install ib_async
    2) In TWS: Configure → API → Settings → enable "ActiveX and Socket Clients",
       socket port 7497 (TWS paper) / 7496 (live) / 4002 (Gateway paper), Trusted IP 127.0.0.1.
       (Read-Only API can stay CHECKED — this script only reads.)
    3) python scripts/ibkr_snapshot.py            # paper account
       python scripts/ibkr_snapshot.py --allow-live   # later, for the REAL account
    4) Redeploy the dashboard (or just restart it locally) to pick up the new snapshot.

The JSON schema is account-agnostic: when you switch to the real account, the same
command writes the same files and the dashboard analysis works unchanged. The only
guard is --allow-live, which you must pass for a non-paper ("DU"-less) account.
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

ACCOUNT_JSON = ROOT / "data" / "cache" / "ibkr_account.json"
EQUITY_CSV = ROOT / "data" / "cache" / "ibkr_equity_history.csv"


def _f(d, key, default=0.0):
    try:
        return float(d.get(key, default))
    except (TypeError, ValueError):
        return default


def main():
    default_host = os.environ.get("IBKR_HOST", "127.0.0.1")
    default_port = int(os.environ.get("IBKR_PORT", "7497"))
    default_client_id = int(os.environ.get("IBKR_SNAP_CLIENT_ID", "99"))

    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default=default_host)
    ap.add_argument("--port", type=int, default=default_port, help="7497 TWS paper, 7496 live, 4002 Gateway")
    ap.add_argument("--client-id", type=int, default=default_client_id)
    ap.add_argument("--inception-nav", type=float, default=None,
                    help="Override the inception NAV (default: keep the value already in the JSON, "
                         "else use the current NAV).")
    ap.add_argument("--allow-live", action="store_true",
                    help="Permit snapshotting a non-paper account (account id not starting with 'DU').")
    args = ap.parse_args()

    try:
        from ib_async import IB
    except ImportError:
        print("ib_async not installed.  Run:  pip install ib_async")
        sys.exit(1)

    ib = IB()
    try:
        ib.connect(args.host, args.port, clientId=args.client_id, timeout=15)
    except Exception as e:
        print(f"Could not connect to TWS at {args.host}:{args.port} ({e}).")
        print("Enable API in TWS (Configure → API → Settings) and check the port.")
        sys.exit(1)

    managed = ib.managedAccounts()
    acct_id = managed[0] if managed else "UNKNOWN"
    is_paper = any(a.startswith("DU") for a in managed)
    if not is_paper and not args.allow_live:
        print(f"Account {managed} is NOT a paper account. Re-run with --allow-live to snapshot it.")
        ib.disconnect(); sys.exit(1)

    rows = ib.accountSummary()
    summary = {x.tag: x.value for x in rows}
    # Base currency = the currency attribute of the NetLiquidation row (the
    # "Currency" tag is unreliable and previously mislabeled a CAD account as USD).
    base_ccy = next((x.currency for x in rows
                     if x.tag == "NetLiquidation" and x.currency), None) \
               or summary.get("Currency", "USD")
    nav = _f(summary, "NetLiquidation")
    gross = _f(summary, "GrossPositionValue")
    cash = _f(summary, "TotalCashValue")
    unreal = _f(summary, "UnrealizedPnL")
    leverage = summary.get("Leverage-S", summary.get("Leverage", ""))

    # Positions: equities drive the drift/weights panel; options (covered calls)
    # are listed separately so short calls never distort the equity book.
    port = ib.portfolio()
    stk = [p for p in port if p.contract.secType == "STK"]
    opt = [p for p in port if p.contract.secType == "OPT"]
    positions, option_positions = [], []
    total_mv = sum(abs(p.marketValue) for p in stk) or 1.0
    for p in stk:
        positions.append({
            "ticker": p.contract.symbol,
            "qty": int(p.position),
            "market_price": round(float(p.marketPrice), 4),
            "market_value": round(float(p.marketValue), 2),
            "avg_price": round(float(p.averageCost), 4),
            "unrealized_pnl": round(float(p.unrealizedPNL), 2),
            "daily_pnl": None,
            "currency": p.contract.currency,
            "weight": round(abs(p.marketValue) / total_mv, 4),
        })
    positions.sort(key=lambda x: -x["weight"])
    for p in opt:
        c = p.contract
        option_positions.append({
            "symbol": c.symbol, "right": c.right, "strike": float(c.strike),
            "expiry": c.lastTradeDateOrContractMonth, "qty": int(p.position),
            "market_value": round(float(p.marketValue), 2),
            "avg_price": round(float(p.averageCost), 4),
            "unrealized_pnl": round(float(p.unrealizedPNL), 2),
        })

    # Pending option orders (e.g. covered calls placed while the market is closed
    # sit as PreSubmitted until the open) — surfaced so the dashboard shows the
    # overlay immediately, not only after the fill.
    option_orders = []
    try:
        for tr in ib.reqAllOpenOrders():
            c = tr.contract
            if c.secType == "OPT":
                option_orders.append({
                    "symbol": c.symbol, "right": c.right, "strike": float(c.strike),
                    "expiry": c.lastTradeDateOrContractMonth,
                    "action": tr.order.action, "qty": int(tr.order.totalQuantity),
                    "status": tr.orderStatus.status,
                })
    except Exception:
        pass

    # The UnrealizedPnL summary tag is often absent from accountSummary(); fall
    # back to the sum of per-position P&L so the dashboard card isn't stuck at 0.
    if not unreal and positions:
        unreal = round(sum(p["unrealized_pnl"] for p in positions), 2)

    # Preserve inception NAV / date across snapshots; default to today's NAV on first run.
    prev = {}
    if ACCOUNT_JSON.exists():
        try:
            prev = json.loads(ACCOUNT_JSON.read_text())
        except Exception:
            prev = {}
    today = datetime.now().strftime("%Y-%m-%d")
    inception_nav = args.inception_nav or prev.get("inception_nav") or nav
    inception_date = prev.get("inception_date", today)

    # Append today's NAV to the equity history (one row per day; overwrite same day).
    if EQUITY_CSV.exists():
        hist = pd.read_csv(EQUITY_CSV)
    else:
        hist = pd.DataFrame(columns=["date", "nav"])
    hist = hist[hist["date"] != today]
    hist = pd.concat([hist, pd.DataFrame([{"date": today, "nav": round(nav, 2)}])], ignore_index=True)
    hist = hist.sort_values("date").reset_index(drop=True)
    hist.to_csv(EQUITY_CSV, index=False)

    twr = (nav / inception_nav - 1.0) if inception_nav else 0.0

    snapshot = {
        "account_id": acct_id,
        "is_paper": is_paper,
        "base_currency": base_ccy,
        "source": "tws",
        "as_of": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "inception_date": inception_date,
        "inception_nav": round(inception_nav, 2),
        "nav": round(nav, 2),
        "gross_position_value": round(gross, 2),
        "total_cash": round(cash, 2),
        "unrealized_pnl": round(unreal, 2),
        "leverage": float(leverage) if str(leverage).replace(".", "").isdigit() else leverage,
        "twr_since_inception": round(twr, 6),
        "positions": positions,
        "option_positions": option_positions,
        "option_orders": option_orders,
        "equity_history": hist.to_dict(orient="records"),
    }
    ACCOUNT_JSON.write_text(json.dumps(snapshot, indent=2))
    ib.disconnect()

    print(f"Account {acct_id} ({'PAPER' if is_paper else 'LIVE'})  base {base_ccy}")
    print(f"NAV {nav:,.2f}   since inception {twr:+.2%}   unrealized {unreal:+,.2f}")
    print(f"Wrote {ACCOUNT_JSON.relative_to(ROOT)} ({len(positions)} positions) "
          f"and {EQUITY_CSV.relative_to(ROOT)} ({len(hist)} days).")

    # Push to GCS so the deployed (Cloud Run) dashboard picks it up without a redeploy.
    # No-op unless GCS_BUCKET is set (and the machine has GCS credentials).
    if os.getenv("GCS_BUCKET"):
        try:
            from src.dashboard.gcs_sync import upload_ibkr
            pushed = upload_ibkr()
            print(f"Pushed to GCS: {pushed}. The live dashboard will show it on its next start.")
        except Exception as e:
            print(f"GCS push skipped ({e}). Redeploy/restart the dashboard to show the snapshot.")
    else:
        print("Set GCS_BUCKET (+ gcloud creds) to auto-push to the live dashboard, "
              "or redeploy/restart it to show the updated snapshot.")


if __name__ == "__main__":
    main()
