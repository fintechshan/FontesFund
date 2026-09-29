"""
scripts/moomoo_rebalance.py
===========================
Paper-trade the US regime sleeve against Moomoo / Futu OpenD.

Run this LOCALLY on the machine where OpenD is running and logged in.
Never run it from Cloud Run. The process only talks to 127.0.0.1 (or the
host you pass) and only places orders with trd_env=SIMULATE.

SAFE BY DEFAULT: dry-run prints the plan and places nothing. ``--execute``
sends orders only when the selected account is SIMULATE. A REAL account
aborts before any order. There is no flag that switches this script to live
trading.

Install (one of these, on the OpenD machine):
  pip install moomoo-api
  pip install futu-api

The script imports ``moomoo`` when that package is present, and otherwise
falls back to ``futu``.

OpenD:
  1) Install OpenD from Moomoo / Futu and log in to the paper (SIMULATE) account.
  2) Leave OpenD running. Default API listen address is 127.0.0.1:11111.
  3) python scripts/moomoo_rebalance.py
     python scripts/moomoo_rebalance.py --execute

Targets are the production overlay (targeted clock + daily overlay), the same
helper ``scripts/ibkr_rebalance.py`` uses. They are not notify's static
``book_weights``.

US sleeve only: QQQ, SOXX, SPY, IEF, GLD, DBMF, AIPO → US.QQQ and so on.
AIPO availability on Moomoo paper has to be confirmed by the operator. If a
code is not tradeable, that name is skipped with a warning. The script does
not invent a substitute ETF.

SIMULATE does not use a trade password in this script. If OpenD asks you to
unlock, unlock in the OpenD window. Do not put a password on the command line
or in the repo.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from config.regime_rules import RISK_LIMITS
from src.execution.moomoo_broker import (
    OpenDError,
    SimulateRequired,
    actionable_orders,
    build_share_plan,
    format_plan_table,
    is_simulate_env,
    open_session,
    pick_simulate_account,
)
from src.execution.overlay_targets import current_regime_and_weights

AIPO_NOTE = (
    "AIPO maps to US.AIPO. Confirm that code is listed on this Moomoo paper "
    "account before --execute. If OpenD rejects a code, that name is skipped. "
    "No substitute ETF is ordered."
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Dry-run (default) or SIMULATE-only US rebalance via Moomoo/Futu OpenD. "
            "OpenD must be running and logged in on this machine. "
            "Install moomoo-api or futu-api. Never run this on Cloud Run. "
            "--execute places orders only with trd_env=SIMULATE and refuses REAL."
        )
    )
    parser.add_argument("--host", default="127.0.0.1", help="OpenD host (default 127.0.0.1)")
    parser.add_argument("--port", type=int, default=11111, help="OpenD API port (default 11111)")
    parser.add_argument(
        "--security-firm",
        default="",
        help="Optional SecurityFirm enum name (for example FUTUINC). Default is the SDK default.",
    )
    parser.add_argument(
        "--max-weight",
        type=float,
        default=RISK_LIMITS.max_single_position,
        help="Per-name cap. Default is RISK_LIMITS.max_single_position.",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="place SIMULATE orders. Refuses any account whose trd_env is not SIMULATE.",
    )
    return parser


def _print_targets(regime: str, vix_now: float, weights: dict) -> None:
    print(f"\nCurrent regime: {regime.upper()}   (VIX {vix_now:.1f})")
    print(
        f"Target sleeves ({len(weights)}): "
        + ", ".join(f"{ticker} {weight:.0%}" for ticker, weight in sorted(weights.items(), key=lambda item: -item[1]))
    )
    print(AIPO_NOTE)


def _rebalance(session, args, weights: dict, prices: dict) -> int:
    try:
        accounts = session.accounts()
    except Exception as exc:
        print(f"\nOpenD answered but get_acc_list failed ({exc}).")
        print("No orders placed.")
        return 1

    account = pick_simulate_account(accounts)
    if account is None:
        print("\nNo SIMULATE US stock paper account in get_acc_list.")
        print("A STOCK_AND_OPTION or STOCK paper account is required. REAL accounts are not used.")
        print("No orders placed.")
        return 1

    trd_env = account.get("trd_env")
    acc_id = int(account["acc_id"])
    sim_type = account.get("sim_acc_type", "")
    label = "SIMULATE" if is_simulate_env(trd_env) else "NOT SIMULATE"
    print(f"\nAccount {acc_id}  sim_acc_type={sim_type}  trd_env={trd_env}  ({label})")
    if not is_simulate_env(trd_env):
        print("Refusing to use an account whose trd_env is not SIMULATE.")
        if args.execute:
            print("Refusing to --execute. REAL trading is disabled.")
        print("No orders placed.")
        return 1

    try:
        nav = session.funds(acc_id)
        positions, non_us = session.positions(acc_id)
    except SimulateRequired as exc:
        print(f"\n{exc}")
        print("No orders placed.")
        return 1
    except Exception as exc:
        print(f"\nCould not read paper NAV or positions ({exc}).")
        print("No orders placed.")
        return 1

    if not nav or nav <= 0:
        print("\nPaper NAV is zero. No orders placed.")
        return 1
    print(f"Paper NAV ${nav:,.0f} (USD)")

    names = list(dict.fromkeys([*weights.keys(), *positions.keys()]))
    try:
        missing, quote_note = session.untradeable(names)
    except Exception as exc:
        missing, quote_note = set(), f"Tradability check failed ({exc})."
    if quote_note:
        print(f"WARNING: {quote_note}")
    if missing:
        shown = ", ".join(f"{name} ({_safe_code(name)})" for name in sorted(missing))
        print(f"WARNING: not tradeable, skipped with no substitute: {shown}")

    plan = build_share_plan(
        nav=nav,
        weights=weights,
        prices=prices,
        positions=positions,
        max_weight=args.max_weight,
        untradeable=missing,
    )
    print()
    print(format_plan_table(plan))
    for code in non_us:
        print(f"WARNING: leaving non-US position {code} unchanged (US sleeve only).")

    orders = actionable_orders(plan)
    if not orders:
        print("\nAlready at target — no SIMULATE orders needed.")
        return 0
    if not args.execute:
        print(
            f"\nDRY-RUN: {len(orders)} orders above would be sent to SIMULATE account {acc_id}. "
            "Nothing was placed. Re-run with --execute to send them. "
            "REAL trading is disabled."
        )
        return 0

    print(f"\nPlacing {len(orders)} orders with trd_env=SIMULATE only...")
    failures = 0
    for row in orders:
        try:
            result = session.place_simulate(
                code=row["code"],
                qty=abs(int(row["delta"])),
                side=row["side"],
                price=float(row["price"] or 0.0),
                acc_id=acc_id,
            )
        except SimulateRequired as exc:
            print(f"\n{exc}")
            print("No further orders placed.")
            return 1
        except Exception as exc:
            failures += 1
            print(f"  WARNING: skip {row['ticker']} ({row['code']}): {exc}")
            print("  No substitute order was sent.")
            continue
        if not result.get("ok"):
            failures += 1
            print(f"  WARNING: skip {row['ticker']} ({row['code']}): {result.get('detail')}")
            print("  No substitute order was sent.")
            continue
        print(
            f"  {row['code']}: {row['side']} {abs(int(row['delta']))} "
            f"{result.get('mode')} → {result.get('detail')}"
        )
    if failures:
        print(f"Finished with {failures} skipped order(s). Check OpenD for orders that were accepted.")
        return 1
    print("Done. Check the OpenD SIMULATE order list for fills.")
    return 0


def _safe_code(ticker: str) -> str:
    try:
        from src.execution.moomoo_broker import moomoo_code
        return moomoo_code(ticker)
    except ValueError:
        return ticker


def run(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        regime, vix_now, weights, prices = current_regime_and_weights()
    except FileNotFoundError as exc:
        print(
            "Price or macro cache is missing, so overlay weights were not computed.\n"
            f"{exc}\n"
            "Refresh the local caches, then run this again on the machine where OpenD is logged in.\n"
            "No orders placed."
        )
        return 1

    _print_targets(regime, vix_now, weights)

    try:
        session = open_session(args.host, args.port, security_firm=args.security_firm)
    except ImportError as exc:
        print(f"\n{exc}")
        print("Weights above came from the local cache. No orders placed.")
        return 1
    except (OpenDError, OSError, ConnectionError) as exc:
        print(f"\nCould not connect to OpenD at {args.host}:{args.port} ({exc}).")
        print("Start OpenD, log in, and confirm the API port (default 11111).")
        print("Weights above came from the local cache. No orders placed.")
        return 1
    except Exception as exc:
        print(f"\nCould not connect to OpenD at {args.host}:{args.port} ({exc}).")
        print("Weights above came from the local cache. No orders placed.")
        return 1

    try:
        return _rebalance(session, args, weights, prices)
    finally:
        session.close()


if __name__ == "__main__":
    sys.exit(run())
