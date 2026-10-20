"""Notify-only risk scorecard: A_vol, B_crowd, C_put.

Paper, dashboard, and notify only. These flags do not size, pause, or cash
any position. This module does not read the regime weight table, the QQQ
Vegas sleeve, or the rebalance script, and those paths do not read it.

Lag is one trading day: each published flag is the raw condition from the
previous session (``shift(1)``). Expanding windows use only observations up
to that session.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DIR = ROOT / 'data' / 'risk_flags'
SNAPSHOT_NAME = 'flags.json'

FLAG_IDS = ('A_vol', 'B_crowd', 'C_put')
RV_WINDOW = 20
Q80_MIN_PERIODS = 252
Q80 = 0.80
MEDIAN_MIN_PERIODS = 10
RANGE_WINDOW = 10
STREAK_MIN = 4
FFILL_LIMIT = 3
FRESH_MAX_AGE_DAYS = 7
ANN_FACTOR = float(np.sqrt(252))

BANNER_ZH = '通知 / 不改仓'
BANNER_EN = 'Notify only. Does not change positions, weights, or orders.'
NOTE_ZH = (
    '回测表明按这些旗标减仓会伤害收益。'
    '此处只做研究/纸面记分和通知，不改仓位、权重或订单。'
)
NOTE_EN = (
    'A backtest showed that sizing the live book down on these flags hurt returns. '
    'Research and paper scorecard only. Notify does not change positions.'
)

RULES = {
    'A_vol': {
        'rule_en': (
            'SOXX RV20 > expanding Q80 (min_periods=252) OR VXN > expanding Q80 '
            '(min_periods=252). Lag 1 trading day.'
        ),
        'rule_zh': (
            'SOXX 的 20 日实现波动率高于扩窗 80% 分位（min_periods=252），'
            '或 VXN 高于自身扩窗 80% 分位（min_periods=252）。滞后 1 个交易日。'
        ),
        'fallback_en': (
            'SOXX and VXN unavailable. Degraded to VIX ≥ 30 only. Lag 1 trading day.'
        ),
        'fallback_zh': 'SOXX 与 VXN 不可用，降级为仅 VIX≥30。滞后 1 个交易日。',
    },
    'B_crowd': {
        'rule_en': (
            'Price proxy, not GS HF flow: (SOXX 5d ≤ −8% OR 10d ≤ −12%) AND '
            '10d range/close > expanding median (min_periods=10), OR '
            '(down-streak ≥ 4 AND 5d ≤ −5%). Lag 1 trading day.'
        ),
        'rule_zh': (
            '价格代理，不是高盛对冲基金资金流：'
            '（SOXX 5 日 ≤ −8% 或 10 日 ≤ −12%）且 10 日振幅/收盘 > 扩窗中位数'
            '（min_periods=10），或（连跌 ≥ 4 日且 5 日 ≤ −5%）。滞后 1 个交易日。'
        ),
    },
    'C_put': {
        'rule_en': (
            'VIX ≥ 25 AND VIX rising over 5 sessions AND SOXX < SMA50 AND '
            'SOXX 10d ≤ −8%. Sell-put checklist hint only. Lag 1 trading day.'
        ),
        'rule_zh': (
            'VIX≥25 且 VIX 较 5 个交易日前上升，且 SOXX < SMA50，'
            '且 SOXX 10 日 ≤ −8%。只是卖 Put 清单提示，不下单。滞后 1 个交易日。'
        ),
    },
}


def flags_path() -> Path:
    override = (os.environ.get('RISK_FLAGS_PATH') or '').strip()
    if override:
        return Path(override)
    return DEFAULT_DIR / SNAPSHOT_NAME


def _prepare(series) -> pd.Series | None:
    if series is None:
        return None
    if isinstance(series, pd.DataFrame):
        if series.shape[1] != 1:
            return None
        series = series.iloc[:, 0]
    out = pd.to_numeric(pd.Series(series), errors='coerce')
    out.index = pd.to_datetime(out.index)
    if getattr(out.index, 'tz', None) is not None:
        out.index = out.index.tz_localize(None)
    out = out.sort_index()
    out = out[~out.index.duplicated(keep='last')].dropna()
    if out.empty:
        return None
    out.name = getattr(series, 'name', None) or out.name
    return out


def _on_index(series: pd.Series | None, index: pd.DatetimeIndex) -> pd.Series:
    if series is None:
        return pd.Series(np.nan, index=index, dtype=float)
    aligned = series.reindex(index)
    if aligned.isna().any():
        aligned = aligned.ffill(limit=FFILL_LIMIT)
    return aligned.astype(float)


def realized_vol(close: pd.Series, window: int = RV_WINDOW) -> pd.Series:
    """Annualized close-to-close vol. ``std`` is the sample std (ddof=1)."""
    returns = close.pct_change()
    return returns.rolling(window).std() * ANN_FACTOR


def expanding_quantile(series: pd.Series, q: float = Q80, min_periods: int = Q80_MIN_PERIODS) -> pd.Series:
    """Expanding quantile. Pandas skips NaN and counts only real observations."""
    numeric = pd.to_numeric(series, errors='coerce')
    return numeric.expanding(min_periods=min_periods).quantile(q)


def expanding_median(series: pd.Series, min_periods: int = MEDIAN_MIN_PERIODS) -> pd.Series:
    numeric = pd.to_numeric(series, errors='coerce')
    return numeric.expanding(min_periods=min_periods).median()


def down_streak(close: pd.Series) -> pd.Series:
    """Consecutive sessions with a lower close. A flat day resets the streak."""
    down = close.diff() < 0
    down = down.fillna(False)
    groups = (~down).cumsum()
    return down.groupby(groups).cumsum().astype(float)


def range_over_close(close: pd.Series, high=None, low=None, window: int = RANGE_WINDOW):
    """10-session (high−low)/close. Close-only when high/low are missing."""
    high_s = _prepare(high)
    low_s = _prepare(low)
    if high_s is None or low_s is None:
        basis = 'close'
        hi = close
        lo = close
    else:
        hi = _on_index(high_s, close.index)
        lo = _on_index(low_s, close.index)
        if int(hi.notna().sum()) < window or int(lo.notna().sum()) < window:
            basis = 'close'
            hi = close
            lo = close
        else:
            basis = 'high_low'
    width = (hi.rolling(window).max() - lo.rolling(window).min()) / close
    return width, basis


def _blank_frame(index: pd.DatetimeIndex) -> pd.DataFrame:
    columns = [
        'soxx_rv20', 'soxx_q80', 'vxn', 'vxn_q80', 'ret_5', 'ret_10',
        'range_ratio', 'range_median', 'streak', 'vix', 'vix_lag5',
        'sma50', 'soxx_close',
        'A_vol_raw', 'B_crowd_raw', 'C_put_raw',
        'A_vol', 'B_crowd', 'C_put',
    ]
    frame = pd.DataFrame(index=index, columns=columns, dtype=float)
    return frame


def compute_flag_frame(soxx, vix, vxn=None, soxx_high=None, soxx_low=None):
    """Causal flag frame. Boolean columns are lagged one trading day.

    Returns ``(frame, meta)``. ``frame`` is empty when nothing was supplied.
    """
    soxx_s = _prepare(soxx)
    vix_s = _prepare(vix)
    vxn_s = _prepare(vxn)
    meta = {
        'soxx': soxx_s is not None,
        'vix': vix_s is not None,
        'vxn': vxn_s is not None,
        'range_basis': None,
        'modes': {},
    }
    if soxx_s is None and vxn_s is None and vix_s is None:
        meta['modes'] = {key: 'skipped' for key in FLAG_IDS}
        return _blank_frame(pd.DatetimeIndex([])), meta

    if soxx_s is not None:
        index = soxx_s.index
    elif vxn_s is not None:
        index = vxn_s.index
    else:
        index = vix_s.index

    frame = _blank_frame(index)
    vix_on = _on_index(vix_s, index)
    vxn_on = _on_index(vxn_s, index)
    frame['vix'] = vix_on
    frame['vix_lag5'] = vix_on.shift(5)
    frame['vxn'] = vxn_on

    soxx_hit = pd.Series(False, index=index)
    vxn_hit = pd.Series(False, index=index)
    if soxx_s is not None:
        close = soxx_s.reindex(index)
        frame['soxx_close'] = close
        rv = realized_vol(close)
        q80 = expanding_quantile(rv)
        frame['soxx_rv20'] = rv
        frame['soxx_q80'] = q80
        soxx_hit = (rv > q80).fillna(False)
        ret5 = close.pct_change(5)
        ret10 = close.pct_change(10)
        frame['ret_5'] = ret5
        frame['ret_10'] = ret10
        width, basis = range_over_close(close, soxx_high, soxx_low)
        meta['range_basis'] = basis
        median = expanding_median(width)
        frame['range_ratio'] = width
        frame['range_median'] = median
        streak = down_streak(close)
        frame['streak'] = streak
        sma = close.rolling(50).mean()
        frame['sma50'] = sma
        wide = (width > median).fillna(False)
        leg_drop = ((ret5 <= -0.08) | (ret10 <= -0.12)).fillna(False)
        leg_streak = ((streak >= STREAK_MIN) & (ret5 <= -0.05)).fillna(False)
        b_raw = (leg_drop & wide) | leg_streak
        c_ready = vix_s is not None
        if c_ready:
            rising = (vix_on > vix_on.shift(5)).fillna(False)
            c_raw = (
                (vix_on >= 25).fillna(False)
                & rising
                & (close < sma).fillna(False)
                & (ret10 <= -0.08).fillna(False)
            )
        else:
            c_raw = pd.Series(False, index=index)
        frame['B_crowd_raw'] = b_raw.astype(float)
        frame['C_put_raw'] = c_raw.astype(float)
        meta['modes']['B_crowd'] = 'full'
        meta['modes']['C_put'] = 'full' if c_ready else 'skipped'
    else:
        frame['B_crowd_raw'] = 0.0
        frame['C_put_raw'] = 0.0
        meta['modes']['B_crowd'] = 'skipped'
        meta['modes']['C_put'] = 'skipped'

    if vxn_s is not None:
        vxn_q = expanding_quantile(vxn_s).reindex(index)
        if vxn_q.isna().any():
            vxn_q = vxn_q.ffill(limit=FFILL_LIMIT)
        frame['vxn_q80'] = vxn_q
        vxn_hit = (vxn_on > vxn_q).fillna(False)

    if soxx_s is not None and vxn_s is not None:
        a_mode = 'full'
        a_raw = soxx_hit | vxn_hit
    elif soxx_s is not None:
        a_mode = 'soxx_only'
        a_raw = soxx_hit
    elif vxn_s is not None:
        a_mode = 'vxn_only'
        a_raw = vxn_hit
    elif vix_s is not None:
        a_mode = 'vix30_fallback'
        a_raw = (vix_on >= 30).fillna(False)
    else:
        a_mode = 'skipped'
        a_raw = pd.Series(False, index=index)
    meta['modes']['A_vol'] = a_mode
    frame['A_vol_raw'] = a_raw.astype(float)

    for key in FLAG_IDS:
        raw = frame[f'{key}_raw'].fillna(0.0)
        if meta['modes'].get(key) == 'skipped':
            frame[key] = np.nan
        else:
            frame[key] = raw.shift(1)
    return frame, meta


def _num(value, digits: int = 4):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:  # NaN
        return None
    return round(number, digits)


def _pct(value) -> str:
    number = _num(value, 6)
    if number is None:
        return 'n/a'
    return f'{number * 100:.1f}%'


def _level(value) -> str:
    number = _num(value, 2)
    if number is None:
        return 'n/a'
    return f'{number:.2f}'


def _date(value) -> str | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        return None
    try:
        return pd.Timestamp(value).date().isoformat()
    except (TypeError, ValueError):
        return None


def _detail_a(row, mode: str) -> str:
    if mode == 'vix30_fallback':
        return f"降级：VIX {_level(row.get('vix'))} ≥ 30（SOXX 与 VXN 都不可用）"
    if mode == 'skipped':
        return 'SOXX、VXN、VIX 都不可用，跳过 A_vol。'
    bits = []
    if mode in {'full', 'soxx_only'}:
        bits.append(f"SOXX RV20 {_pct(row.get('soxx_rv20'))} vs Q80 {_pct(row.get('soxx_q80'))}")
    else:
        bits.append('SOXX 不可用')
    if mode in {'full', 'vxn_only'}:
        bits.append(f"VXN {_level(row.get('vxn'))} vs Q80 {_level(row.get('vxn_q80'))}")
    else:
        bits.append('VXN 不可用，未改用 VIX≥30')
    return '；'.join(bits)


def _detail_b(row, mode: str, basis: str | None) -> str:
    if mode == 'skipped':
        return 'SOXX 不可用，跳过 B_crowd。'
    basis_label = '高低价' if basis == 'high_low' else '收盘'
    streak = _num(row.get('streak'), 0)
    streak_txt = 'n/a' if streak is None else str(int(round(streak)))
    return (
        f"5日 {_pct(row.get('ret_5'))} · 10日 {_pct(row.get('ret_10'))} · "
        f"振幅/收盘 {_level(row.get('range_ratio'))} vs 中位数 {_level(row.get('range_median'))}"
        f"（{basis_label}）· 连跌 {streak_txt} 日"
    )


def _detail_c(row, mode: str) -> str:
    if mode == 'skipped':
        return '缺少 SOXX 或 VIX，跳过 C_put。卖 Put 清单提示，不下单。'
    return (
        f"VIX {_level(row.get('vix'))} vs 5日前 {_level(row.get('vix_lag5'))} · "
        f"SOXX {_level(row.get('soxx_close'))} vs SMA50 {_level(row.get('sma50'))} · "
        f"10日 {_pct(row.get('ret_10'))} · 卖Put清单提示，不下单"
    )


def _rule_pair(key: str, mode: str) -> tuple[str, str]:
    spec = RULES[key]
    if key == 'A_vol' and mode == 'vix30_fallback':
        return spec['fallback_en'], spec['fallback_zh']
    return spec['rule_en'], spec['rule_zh']


def _flag_payload(key: str, mode: str, lagged, signal_row, basis: str | None) -> dict:
    rule_en, rule_zh = _rule_pair(key, mode)
    if mode == 'skipped':
        status, on = 'skipped', False
    elif lagged is None or (isinstance(lagged, float) and lagged != lagged) or pd.isna(lagged):
        status, on = 'off', False
    else:
        on = bool(lagged)
        status = 'on' if on else 'off'
    if key == 'A_vol':
        detail = _detail_a(signal_row, mode)
    elif key == 'B_crowd':
        detail = _detail_b(signal_row, mode, basis)
    else:
        detail = _detail_c(signal_row, mode)
    return {
        'name': key,
        'on': on,
        'status': status,
        'mode': mode,
        'rule_en': rule_en,
        'rule_zh': rule_zh,
        'detail': detail,
    }


def snapshot_from_frame(frame: pd.DataFrame, meta: dict | None = None, today=None) -> dict:
    """Latest lagged scorecard. ``today`` is only used for the stale check."""
    meta = meta or {}
    modes = meta.get('modes') or {key: 'skipped' for key in FLAG_IDS}
    basis = meta.get('range_basis')
    if frame is None or frame.empty:
        snap = unavailable_snapshot('没有价格，跳过三面旗。')
        return mark_freshness(snap, today=today)

    as_of_label = frame.index[-1]
    signal_label = frame.index[-2] if len(frame) >= 2 else None
    signal_row = frame.iloc[-2] if signal_label is not None else pd.Series(dtype=float)
    last = frame.iloc[-1]
    flags = {}
    for key in FLAG_IDS:
        flags[key] = _flag_payload(key, modes.get(key, 'skipped'), last.get(key), signal_row, basis)
    snap = {
        'schema': 1,
        'purpose': 'notify_only',
        'effect': 'none',
        'orders': False,
        'weights': False,
        'banner_zh': BANNER_ZH,
        'banner_en': BANNER_EN,
        'note_zh': NOTE_ZH,
        'note_en': NOTE_EN,
        'as_of': _date(as_of_label),
        'signal_date': _date(signal_label),
        'lag_trading_days': 1,
        'unavailable': False,
        'range_basis': basis,
        'inputs': {
            'soxx': bool(meta.get('soxx')),
            'vxn': bool(meta.get('vxn')),
            'vix': bool(meta.get('vix')),
        },
        'flags': flags,
        'generated_at': datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC'),
    }
    return mark_freshness(snap, today=today)


def unavailable_snapshot(reason: str = '尚未刷新') -> dict:
    flags = {}
    for key in FLAG_IDS:
        rule_en, rule_zh = _rule_pair(key, 'skipped')
        flags[key] = {
            'name': key,
            'on': False,
            'status': 'skipped',
            'mode': 'skipped',
            'rule_en': rule_en,
            'rule_zh': rule_zh,
            'detail': reason,
        }
    return {
        'schema': 1,
        'purpose': 'notify_only',
        'effect': 'none',
        'orders': False,
        'weights': False,
        'banner_zh': BANNER_ZH,
        'banner_en': BANNER_EN,
        'note_zh': NOTE_ZH,
        'note_en': NOTE_EN,
        'as_of': None,
        'signal_date': None,
        'lag_trading_days': 1,
        'unavailable': True,
        'stale': False,
        'range_basis': None,
        'inputs': {'soxx': False, 'vxn': False, 'vix': False},
        'flags': flags,
        'generated_at': None,
    }


def mark_freshness(snapshot: dict, today=None, max_age_days: int = FRESH_MAX_AGE_DAYS) -> dict:
    as_of = snapshot.get('as_of')
    if not as_of or snapshot.get('unavailable'):
        snapshot['stale'] = False
        snapshot['age_days'] = None
        return snapshot
    anchor = pd.Timestamp(today).normalize() if today is not None else pd.Timestamp.now().normalize()
    age = int((anchor - pd.Timestamp(as_of)).days)
    snapshot['age_days'] = age
    snapshot['stale'] = age > max_age_days
    return snapshot


def compute_snapshot(soxx, vix, vxn=None, soxx_high=None, soxx_low=None, today=None) -> dict:
    frame, meta = compute_flag_frame(soxx, vix, vxn, soxx_high, soxx_low)
    return snapshot_from_frame(frame, meta, today=today)


def load_snapshot(path=None) -> dict:
    target = Path(path) if path is not None else flags_path()
    if not target.is_file():
        return unavailable_snapshot('尚未生成 data/risk_flags/flags.json')
    try:
        data = json.loads(target.read_text(encoding='utf-8'))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return unavailable_snapshot('flags.json 无法读取')
    if not isinstance(data, dict) or not isinstance(data.get('flags'), dict):
        return unavailable_snapshot('flags.json 格式不对')
    for key in FLAG_IDS:
        data['flags'].setdefault(key, unavailable_snapshot()['flags'][key])
    data.setdefault('banner_zh', BANNER_ZH)
    data.setdefault('purpose', 'notify_only')
    data.setdefault('orders', False)
    data.setdefault('weights', False)
    return data


def notify_block(snapshot: dict) -> dict | None:
    """Compact on/off block stored in ``notify_state.json``. None when unusable."""
    if not isinstance(snapshot, dict):
        return None
    if snapshot.get('unavailable') or snapshot.get('stale') or not snapshot.get('as_of'):
        return None
    flags = snapshot.get('flags') or {}
    block = {
        'as_of': snapshot.get('as_of'),
        'signal_date': snapshot.get('signal_date'),
        'status': {},
        'mode': {},
        'detail': {},
        'rule_zh': {},
    }
    for key in FLAG_IDS:
        item = flags.get(key) if isinstance(flags.get(key), dict) else {}
        status = item.get('status') or 'skipped'
        on = bool(item.get('on')) and status == 'on'
        block[key] = on
        block['status'][key] = status
        block['mode'][key] = item.get('mode') or 'skipped'
        block['detail'][key] = item.get('detail') or ''
        block['rule_zh'][key] = item.get('rule_zh') or RULES[key]['rule_zh']
    return block


def load_notify_block(path=None) -> dict | None:
    return notify_block(load_snapshot(path))


def rising_flag_ids(prev_block, cur_block) -> list[str]:
    """Flags that moved to ON. A missing previous block is a baseline, not an edge."""
    if not isinstance(prev_block, dict) or not isinstance(cur_block, dict):
        return []
    risen = []
    for key in FLAG_IDS:
        if bool(cur_block.get(key)) and not bool(prev_block.get(key)):
            risen.append(key)
    return risen


def risk_flags_changed(prev_block, cur_block) -> bool:
    """True when on/off or skipped/live status changed. As-of alone does not count."""
    if not isinstance(cur_block, dict):
        return False
    if not isinstance(prev_block, dict):
        return True
    for key in FLAG_IDS:
        if bool(prev_block.get(key)) != bool(cur_block.get(key)):
            return True
        prev_status = (prev_block.get('status') or {}).get(key)
        cur_status = (cur_block.get('status') or {}).get(key)
        if prev_status != cur_status:
            return True
    return False


def write_snapshot(snapshot: dict, path=None) -> Path:
    target = Path(path) if path is not None else flags_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + '.tmp')
    tmp.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    tmp.replace(target)
    return target
