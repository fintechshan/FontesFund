"""Two-day confirmation of the locked QQQ Vegas v9 boolean. Shadow only.

The official signal is still ``risk_on = Vegas tunnel AND rv20 <= expanding Q80``,
confirmed at the close and filled next session (``pos = signal.shift(1)``).
This module does not recompute that boolean and does not write the official pack.

Confirmation rule (entry and exit):

* Start in cash.
* The confirmed state flips only after two consecutive closes on which the
  locked v9 boolean equals the new state.
* A single opposing close does not flip the state, and it resets the streak.
* The shadow position on session t is the confirmed state from the previous
  close (same close-confirm / next-open lag as v9). The first session is cash.

There is no price band and no RV panic exception. The sleeve is still
70% QQQ + 30% QLD versus 100% BIL, and a position change still costs 4 bps.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

CONFIRM_SESSIONS = 2
W_QQQ = 0.7
W_QLD = 0.3
COST = 4.0 / 10_000.0
QLD_FEE = 0.0095 / 252.0

RULE_ZH = (
    "影子 / 实验：锁定 v9 布尔信号（Vegas 隧道 ∧ 扩窗 Q80）须连续两个收盘"
    "同向后，确认状态才翻转。进场和出场都适用。收盘确认，次日持仓"
    "（confirmed.shift(1)）。70% QQQ + 30% QLD，空仓为 BIL。"
    "没有额外价格带，也没有当日波动例外。不是官方卡，不发实盘提醒。"
)
RULE_EN = (
    "Shadow / experiment: the locked v9 boolean (Vegas tunnel AND expanding Q80) "
    "must print the new state on two consecutive closes before the confirmed "
    "state flips. Entry and exit both use that rule. Close confirm, next-session "
    "position (confirmed.shift(1)). 70% QQQ + 30% QLD, otherwise BIL. "
    "No price band and no same-day volatility exception. Not the official card and not a live alert."
)


def confirm_two_day(raw_signal: pd.Series, sessions: int = CONFIRM_SESSIONS) -> pd.Series:
    """Confirmed close state. Flips only after ``sessions`` consecutive new values."""
    if sessions < 2:
        raise ValueError("shadow confirmation requires at least 2 consecutive sessions")
    raw = pd.to_numeric(raw_signal, errors="coerce").fillna(0).astype(int)
    state = 0
    streak = 0
    out = np.zeros(len(raw), dtype=int)
    for i, value in enumerate(raw.to_numpy()):
        value = int(value)
        if value == state:
            streak = 0
        else:
            streak += 1
            if streak >= sessions:
                state = value
                streak = 0
        out[i] = state
    confirmed = pd.Series(out, index=raw.index, name="confirmed_signal")
    return confirmed


def position_from_confirmed(confirmed: pd.Series) -> pd.Series:
    """Next-session position. Session 0 is cash, matching the official pack."""
    pos = confirmed.shift(1)
    if len(pos):
        pos.iloc[0] = 0
    return pos.fillna(0).astype(int).rename("pos")


def shadow_position(raw_signal: pd.Series, sessions: int = CONFIRM_SESSIONS) -> pd.DataFrame:
    """Raw boolean, confirmed close, and the position that earns the next session."""
    raw = pd.to_numeric(raw_signal, errors="coerce").fillna(0).astype(int).rename("raw_signal")
    confirmed = confirm_two_day(raw, sessions=sessions)
    pos = position_from_confirmed(confirmed)
    return pd.DataFrame({"raw_signal": raw, "confirmed_signal": confirmed, "pos": pos})


def _changed(pos: pd.Series) -> pd.Series:
    changed = pos.astype(int).ne(pos.astype(int).shift(1))
    if len(changed):
        changed.iloc[0] = False
    return changed.fillna(False)


def shadow_strategy_return(
    qqq_ret: pd.Series,
    qld_ret: pd.Series,
    cash_ret: pd.Series,
    shadow_pos: pd.Series,
    official_pos: pd.Series,
    official_strat_ret: pd.Series,
    cost: float = COST,
) -> pd.Series:
    """Shadow close-to-close return.

    When the shadow and official positions agree, and they either both trade
    or both hold, use the official ``strat_ret`` so the shared days stay on
    the official rail. Otherwise rebuild 70/30 or cash from the leg returns
    and charge ``cost`` only if the shadow position changed.
    """
    index = shadow_pos.index
    qqq_ret = pd.Series(qqq_ret, index=index, dtype=float)
    qld_ret = pd.Series(qld_ret, index=index, dtype=float)
    cash_ret = pd.Series(cash_ret, index=index, dtype=float)
    official_pos = pd.Series(official_pos, index=index).fillna(0).astype(int)
    official_strat_ret = pd.Series(official_strat_ret, index=index, dtype=float)
    held = shadow_pos.astype(int)
    shadow_changed = _changed(held)
    official_changed = _changed(official_pos)
    gross = np.where(held.to_numpy() == 1, (W_QQQ * qqq_ret + W_QLD * qld_ret).to_numpy(), cash_ret.to_numpy())
    rebuilt = pd.Series(gross, index=index, dtype=float)
    rebuilt = rebuilt - shadow_changed.astype(float) * float(cost)
    same_book = held.eq(official_pos) & shadow_changed.eq(official_changed)
    out = rebuilt.where(~same_book, official_strat_ret)
    if len(out):
        out.iloc[0] = 0.0
    return out.rename("strat_ret")


def leg_returns(official_signal: pd.DataFrame, official_equity: pd.DataFrame, market_qld: pd.Series | None = None) -> dict:
    """QQQ, QLD, and cash daily returns aligned to the official signal index.

    QQQ comes from the official ``qqq_close``. On days the official book is
    long, QLD is the return implied by the official sleeve (4 bps added back
    on official position-change days). On days the official book is cash, QLD
    is the market-price return when that series tracks the implied QLD, else
    the synthetic ``2*QQQ - cash - 0.95%/yr`` leg the official engine uses
    before QLD listed. Cash on long days is forward-filled from cash days.
    """
    signal = official_signal.sort_index()
    equity = official_equity.sort_index()
    qqq_ret = pd.to_numeric(signal["qqq_close"], errors="coerce").pct_change()
    official_pos = pd.to_numeric(signal["pos"], errors="coerce").fillna(0).astype(int)
    strat = pd.to_numeric(equity["strat_ret"], errors="coerce").reindex(signal.index)
    changed = _changed(official_pos)
    gross = strat + changed.astype(float) * COST
    long = official_pos.eq(1)
    qld = pd.Series(np.nan, index=signal.index, dtype=float)
    cash = pd.Series(np.nan, index=signal.index, dtype=float)
    qld.loc[long] = (gross.loc[long] - W_QQQ * qqq_ret.loc[long]) / W_QLD
    cash.loc[~long] = gross.loc[~long]
    cash_observed = int(cash.notna().sum())
    cash = cash.ffill().bfill()
    market_used = False
    market_median_abs = None
    if market_qld is not None and len(market_qld):
        market_ret = pd.to_numeric(market_qld, errors="coerce").pct_change().reindex(signal.index)
        both = qld.notna() & market_ret.notna()
        if int(both.sum()) >= 50:
            market_median_abs = float((qld.loc[both] - market_ret.loc[both]).abs().median())
        # A few basis points of tracking noise is the adjusted-close gap.
        # A large gap means the market file is a different scale. Do not use it.
        if market_median_abs is not None and market_median_abs <= 0.002:
            qld = qld.fillna(market_ret)
            market_used = True
    synth = 2.0 * qqq_ret - cash - QLD_FEE
    qld = qld.fillna(synth)
    qqq_ret = qqq_ret.fillna(0.0)
    qld = qld.fillna(0.0)
    cash = cash.fillna(0.0)
    check = (W_QQQ * qqq_ret + W_QLD * qld - gross).abs()
    check = check.loc[long & gross.notna() & qqq_ret.notna()]
    return {
        "qqq_ret": qqq_ret,
        "qld_ret": qld,
        "cash_ret": cash,
        "diagnostics": {
            "cash_days_observed": cash_observed,
            "market_qld_used_for_gaps": market_used,
            "market_vs_implied_qld_median_abs": market_median_abs,
            "official_long_day_rebuild_max_abs": float(check.max()) if len(check) else None,
        },
    }
