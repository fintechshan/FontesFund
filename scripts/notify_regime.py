#!/usr/bin/env python3
"""
notify_regime.py — 象限 / VIX 跨档提醒（GitHub Issue → 邮件）。

    python scripts/notify_regime.py --dry-run
    python scripts/notify_regime.py --refresh --dry-run
    python scripts/notify_regime.py --refresh --github-issue
    python scripts/notify_regime.py --refresh --github-issue --force
    python scripts/notify_regime.py --audit

发信条件（满足其一才开 Issue）:
  1. Merrill 象限变了（src.backtester.regime_clock，mode=targeted）
  2. 最新 VIX 跨档：0-20 / 20-28 / 28-30 / 30-40 / 40+

同一档内的 VIX 波动、以及象限未变，都静默退出。首次运行只写
data/notify_state.json 基线，不开 Issue；--force 用于测试发信。

象限变了时，Issue 先写组合变化：旧→新、需要调仓（任一标的 |差额|≥1%）、
美加风险姿态、权重表、减持/增持清单、怎么执行。只跨 VIX 档时写需要调仓：否，
并说明防御应收紧或可放松；不改目标权重。

targeted 与仪表盘、ibkr_rebalance、moomoo_rebalance 相同：CPI +1 个月，GDP +4 个月，
VIX 月均和 12 个月动量再 shift(1)。不 import run_dashboard（那会跑启动逻辑）。

审计：象限变化、VIX 跨档或 --force 应发信时，必须创建 rebalance Issue。
创建失败、Actions 上漏了 --github-issue，或响应里没有 number / html_url，
都不写入新的象限状态（避免下次被去重静默），并以非零退出。
--audit 核对本次 data/notify_audit.json 或状态里的 last_delivery。
记下的 issue number 只要 Issue 还在就通过（改标题、关 Issue 都不算漏报）。
没有编号时，只认 7 日内同标题且带 rebalance 标签的 Issue。
漏报会再开一张 [审计]（标签 notify-audit，同一指纹不重复）。
邮件仍是 GitHub 通知，不是 SMTP。
"""
from __future__ import annotations

import argparse
import json
import os
import pickle
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# 最新 VIX 收盘所在档。日频敞口仍由引擎按 VIX 与回撤连续计算；
# 这里只报告跨档。30 以上与 REGIME_VIX_DEFENSIVE（月均 VIX>30 强制 deflation）同一量级。
VIX_BANDS = (
    (0.0, 20.0, '0-20', '正常'),
    (20.0, 28.0, '20-28', '偏高'),
    (28.0, 30.0, '28-30', '开始降敞口'),
    (30.0, 40.0, '30-40', '大幅降敞口 / 象限转 deflation'),
    (40.0, None, '40+', '接近清仓股票'),
)

# 任一标的 |新-旧| 达到这一档才算「需要调仓」，并写入建议清单。
REBALANCE_EPS = 0.01

# 按标题回查 Issue 时的窗口。已记下的 issue number 不受这个窗口限制。
AUDIT_WINDOW_DAYS = 7
AUDIT_FINGERPRINT_PREFIX = 'audit-fingerprint:'

# 风险姿态一行。未列入的标的不会被静默丢掉：建议清单仍按全部差额生成。
US_EQUITY = ('QQQ', 'SOXX', 'SPY', 'AIPO')
US_DEFENSIVE = ('IEF', 'GLD', 'DBMF')
CDN_EQUITY = ('ZQQ.TO', 'VFV.TO', 'ZEB.TO', 'XGD.TO')
CDN_DEFENSIVE = ('XBB.TO', 'CGL-C.TO')
POSTURE_BASKETS = {
    'US': (US_EQUITY, US_DEFENSIVE),
    'CDN': (CDN_EQUITY, CDN_DEFENSIVE),
}

FRED_SERIES = (
    ('vix', 'VIXCLS'),
    ('gdp', 'A191RL1Q225SBEA'),
    ('cpi', 'CPIAUCSL'),
    ('t10y', 'DGS10'),
    ('t2y', 'DGS2'),
)

_CLASSIFIER = None


class GitHubAPIError(Exception):
    def __init__(self, code: int, body: str):
        super().__init__(f'HTTP {code}: {body[:300]}')
        self.code = code
        self.body = body


def cache_dir() -> Path:
    return Path(os.environ.get('NOTIFY_CACHE_DIR', str(ROOT / 'data' / 'cache')))


def state_path() -> Path:
    return Path(os.environ.get('NOTIFY_STATE_PATH', str(ROOT / 'data' / 'notify_state.json')))


def audit_path() -> Path:
    return Path(os.environ.get('NOTIFY_AUDIT_PATH', str(ROOT / 'data' / 'notify_audit.json')))


def die(msg: str, code: int = 1) -> None:
    print(msg, file=sys.stderr)
    if os.environ.get('GITHUB_ACTIONS') == 'true':
        flat = ' '.join(str(msg).split())
        print(f'::error::{flat}', file=sys.stderr)
    raise SystemExit(code)


def set_github_output(name: str, value: str) -> None:
    path = os.environ.get('GITHUB_OUTPUT')
    if not path:
        return
    with open(path, 'a', encoding='utf-8') as fh:
        fh.write(f'{name}={value}\n')


def vix_band(vix: float) -> tuple[str, str]:
    """Return (band key, Chinese label). Band on a 1-decimal print so the email number matches the band."""
    v = round(float(vix), 1)
    for lo, hi, key, name in VIX_BANDS:
        if hi is None:
            if v >= lo:
                return key, name
        elif lo <= v < hi:
            return key, name
    return '?', '?'


def format_pct(x: float, signed: bool = False) -> str:
    pct_value = float(x) * 100.0
    whole = abs(pct_value - round(pct_value)) < 0.05
    if signed:
        spec = '+.0f' if whole else '+.1f'
    else:
        spec = '.0f' if whole else '.1f'
    return f'{pct_value:{spec}}%'


def load_classifier():
    """Production clock. Importing run_dashboard would run its startup path."""
    global _CLASSIFIER
    if _CLASSIFIER is not None:
        return _CLASSIFIER
    from src.backtester.regime_clock import (
        CPI_RELEASE_LAG_M,
        GDP_RELEASE_LAG_M,
        MODE_TARGETED,
        classify_regimes,
    )
    if CPI_RELEASE_LAG_M != 1 or GDP_RELEASE_LAG_M != 4:
        die('regime_clock 的 CPI/GDP 滞后已不是 +1 / +4，拒绝发信。')
    _CLASSIFIER = (classify_regimes, MODE_TARGETED)
    return _CLASSIFIER


def _series(macro: dict, key: str) -> pd.Series:
    raw = macro.get(key, pd.Series(dtype=float))
    if not isinstance(raw, pd.Series):
        raw = pd.Series(raw)
    return raw.dropna()


def validate_inputs(macro: dict, price: pd.DataFrame) -> None:
    """Refuse to classify thin data. A short cache looks like a regime change."""
    problems = []
    if len(_series(macro, 'vix')) < 100:
        problems.append(f"VIX {len(_series(macro, 'vix'))} 点（需要 ≥100）")
    if len(_series(macro, 'cpi')) < 100:
        problems.append(f"CPI {len(_series(macro, 'cpi'))} 点（需要 ≥100）")
    if len(_series(macro, 'gdp')) < 40:
        problems.append(f"GDP {len(_series(macro, 'gdp'))} 点（需要 ≥40）")
    if price.empty or 'SPY' not in price.columns or price['SPY'].dropna().shape[0] < 252:
        n = 0 if price.empty or 'SPY' not in price.columns else int(price['SPY'].dropna().shape[0])
        problems.append(f'SPY {n} 行（需要 ≥252）')
    if problems:
        die('数据不足，拒绝判断，避免误报：' + '；'.join(problems), code=2)


def _num(value, ndigits: int):
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    if x != x:  # NaN
        return None
    return round(x, ndigits)


def compute_state(macro: dict, price: pd.DataFrame) -> dict:
    validate_inputs(macro, price)
    classify, mode = load_classifier()
    _history, cur, info = classify(macro, price, mode=mode)
    if (
        not info
        or info.get('mode') != mode
        or not info.get('publication_lag')
        or info.get('same_month_market')
    ):
        die(
            '时钟不是 targeted（需要 CPI+1、GDP+4，且 VIX/动量再滞后 1 个月）。'
            f" mode={None if not info else info.get('mode')}",
            code=2,
        )
    regime = (cur or {}).get('regime')
    if not regime:
        die('分类结果为空。', code=2)
    vix_raw = _series(macro, 'vix')
    vix_last = round(float(vix_raw.iloc[-1]), 1)
    band, band_name = vix_band(vix_last)
    asof = price.index.max()
    asof_txt = pd.Timestamp(asof).date().isoformat()
    return {
        'schema': 1,
        'clock': mode,
        'regime': str(regime),
        'vix_band': band,
        'vix_band_name': band_name,
        'vix': vix_last,
        'cpi_yoy': _num((cur or {}).get('cpi_yoy'), 2),
        'gdp': _num((cur or {}).get('gdp'), 2),
        'spy_momentum': _num((cur or {}).get('spy_momentum'), 4),
        'price_asof': asof_txt,
        'checked_at': datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC'),
    }


def _normalize_index(obj):
    if isinstance(obj, pd.Series):
        obj = obj.copy()
        obj.index = pd.to_datetime(obj.index)
        if getattr(obj.index, 'tz', None) is not None:
            obj.index = obj.index.tz_localize(None)
        return obj.sort_index()
    if isinstance(obj, pd.DataFrame):
        obj = obj.copy()
        obj.index = pd.to_datetime(obj.index)
        if getattr(obj.index, 'tz', None) is not None:
            obj.index = obj.index.tz_localize(None)
        return obj.sort_index()
    return obj


def load_inputs() -> tuple[dict, pd.DataFrame]:
    price_path = cache_dir() / 'price_data.csv'
    macro_path = cache_dir() / 'macro_data.pkl'
    if not price_path.exists() or not macro_path.exists():
        die(
            f'缺少 {price_path.name} 或 {macro_path.name}（目录 {cache_dir()}）。'
            'Actions 使用 --refresh；本地预览也可先 --refresh。'
        )
    price = pd.read_csv(price_path, index_col=0, parse_dates=True)
    price = _normalize_index(price)
    price = price[~price.index.duplicated(keep='last')]
    with open(macro_path, 'rb') as fh:
        macro = pickle.load(fh)
    if not isinstance(macro, dict):
        die('macro_data.pkl 不是 dict。', code=2)
    macro = {k: _normalize_index(v) if isinstance(v, pd.Series) else v for k, v in macro.items()}
    return macro, price


def current_state() -> dict:
    macro, price = load_inputs()
    return compute_state(macro, price)


def read_state():
    path = state_path()
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding='utf-8'))


def write_state(cur: dict) -> None:
    path = state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cur, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')


def classify_change(prev, cur: dict, force: bool = False) -> tuple[str, dict]:
    """Return (action, reasons). action is 'silent', 'baseline', or 'notify'."""
    reasons: dict[str, str] = {}
    if prev is None:
        reasons['init'] = f"首次运行，记录当前象限 **{cur['regime']}**（本次不视为调仓信号）"
        if force:
            reasons['forced'] = '（--force 测试。尚无基线，这封是试发，不是已发生的切换）'
            return 'notify', reasons
        return 'baseline', reasons
    if prev.get('regime') != cur['regime']:
        reasons['regime'] = f"象限切换：**{prev.get('regime')} → {cur['regime']}**"
    if prev.get('vix_band') != cur['vix_band']:
        reasons['vix'] = (
            f"VIX 跨档：{prev.get('vix_band')} {prev.get('vix_band_name')} → "
            f"**{cur['vix_band']} {cur['vix_band_name']}**"
            f"（VIX {prev.get('vix', '?')} → {cur['vix']}）"
        )
    if force and not reasons:
        reasons['forced'] = '（--force 测试，象限与 VIX 档位都没有变化）'
    if not reasons:
        return 'silent', reasons
    return 'notify', reasons


def delivery_kind(reasons: dict) -> str:
    if 'regime' in reasons and 'vix' in reasons:
        return 'regime+vix'
    if 'regime' in reasons:
        return 'regime'
    if 'vix' in reasons:
        return 'vix'
    return 'force'


def delivery_fingerprint(prev, cur: dict, reasons: dict) -> str:
    """Stable id for one should-fire event. Force includes the check date."""
    kind = delivery_kind(reasons)
    day = cur.get('price_asof') or ''
    if kind == 'force':
        checked = (cur.get('checked_at') or '')[:10]
        return f"force|{cur.get('regime')}|{cur.get('vix_band')}|{day}|{checked}"
    prev_regime = (prev or {}).get('regime') or ''
    prev_band = (prev or {}).get('vix_band') or ''
    return f"{kind}|{prev_regime}>{cur.get('regime')}|{prev_band}>{cur.get('vix_band')}|{day}"


def blank_audit(action: str, cur: dict | None) -> dict:
    cur = cur or {}
    return {
        'schema': 1,
        'action': action,
        'should_fire': False,
        'kind': None,
        'title': None,
        'fingerprint': None,
        'delivery': 'not_required',
        'issue_number': None,
        'issue_url': None,
        'checked_at': cur.get('checked_at'),
        'checked_at_iso': None,
        'price_asof': cur.get('price_asof'),
        'error': None,
    }


def write_audit(record: dict) -> None:
    path = audit_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')


def read_audit():
    path = audit_path()
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding='utf-8'))


def coerce_created_issue(opened) -> dict | None:
    """Return number + html_url, or None when the create call did not actually open an Issue."""
    if not isinstance(opened, dict):
        return None
    number = opened.get('number')
    url = opened.get('html_url') or opened.get('issue_url')
    if number is None or not url:
        return None
    try:
        number = int(number)
    except (TypeError, ValueError):
        return None
    if number <= 0:
        return None
    return {'number': number, 'html_url': str(url), 'title': opened.get('title')}


def parse_utc(text) -> datetime | None:
    if not text or not isinstance(text, str):
        return None
    raw = text.strip()
    if raw.endswith(' UTC'):
        raw = raw[:-4].strip().replace(' ', 'T') + 'Z'
    elif ' ' in raw and 'T' not in raw:
        raw = raw.replace(' ', 'T')
    if raw.endswith('Z'):
        raw = raw[:-1] + '+00:00'
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def within_audit_window(issue_created, checked_at, days: int = AUDIT_WINDOW_DAYS) -> bool:
    created = parse_utc(issue_created)
    anchor = parse_utc(checked_at)
    if created is None or anchor is None:
        return False
    return abs((created - anchor).total_seconds()) <= days * 86400


def _label_names(issue: dict) -> list[str]:
    names = []
    for lab in issue.get('labels') or []:
        name = lab.get('name') if isinstance(lab, dict) else lab
        if name:
            names.append(str(name))
    return names


def issue_satisfies(issue, record: dict, *, numbered: bool) -> bool:
    """True when `issue` is the rebalance Issue this record expected.

    A stored issue number is the send itself: any age, closed, retitled, or
    unlabeled still counts. A title search (no number, or that number 404s)
    only counts inside AUDIT_WINDOW_DAYS, with the same title and the
    `rebalance` label, so an older test Issue cannot cover a new miss.
    """
    if not isinstance(issue, dict) or issue.get('pull_request'):
        return False
    if numbered:
        expected_number = record.get('issue_number')
        if expected_number is None:
            return False
        try:
            return int(issue.get('number')) == int(expected_number)
        except (TypeError, ValueError):
            return False
    expected = record.get('title')
    if not expected or issue.get('title') != expected:
        return False
    if 'rebalance' not in _label_names(issue):
        return False
    anchor = record.get('checked_at_iso') or record.get('checked_at')
    return within_audit_window(issue.get('created_at'), anchor)


_MISS_DELIVERIES = ('failed', 'skipped', 'printed_only', 'missing')


def expectation_to_verify(run_record, state) -> dict | None:
    """Record that must match a rebalance Issue, or None when audit stays quiet."""
    if isinstance(run_record, dict) and run_record.get('should_fire'):
        if run_record.get('delivery') == 'dry_run':
            return None
        return run_record
    last = state.get('last_delivery') if isinstance(state, dict) else None
    if not isinstance(last, dict):
        return None
    if last.get('delivery') == 'created':
        return last
    if last.get('should_fire') and last.get('delivery') in _MISS_DELIVERIES:
        return last
    return None


_KIND_ZH = {
    'regime': '象限切换',
    'vix': 'VIX 跨档',
    'regime+vix': '象限切换与 VIX 跨档',
    'force': '强制测试',
}


def audit_issue_title(record: dict) -> str:
    kind = _KIND_ZH.get(record.get('kind') or '', '调仓')
    day = record.get('price_asof') or (record.get('checked_at') or '')[:10] or '未知日期'
    return f'[审计] 未发出{kind}提醒（{day}）'


def audit_issue_body(record: dict, detail: str) -> str:
    fingerprint = record.get('fingerprint') or ''
    expected = record.get('title') or '（无标题）'
    url = record.get('issue_url') or '（没有）'
    number = record.get('issue_number')
    number_s = f'#{number}' if number else '（没有）'
    return '\n'.join([
        '### 审计',
        '这次应该打开一个标签为 `rebalance` 的 GitHub Issue（并指派仓库所有者），'
        '由 GitHub 通知发邮件。没有找到对应 Issue。',
        '这里不走 SMTP。邮件只来自 GitHub 的 Watch / assignee 通知。',
        '',
        f'- 预期标题：{expected}',
        f'- 记录的 Issue：{number_s} {url}',
        f'- 投递状态：{record.get("delivery")}',
        f'- 原因：{detail}',
        '',
        '同一指纹已有未关闭的审计 Issue 时，不会再开一封。',
        '补上真正的 `rebalance` Issue，或确认是误报之后，可以关闭本 Issue。',
        '',
        f'<!-- {AUDIT_FINGERPRINT_PREFIX} {fingerprint} -->',
    ])


def audit_miss_detail(record: dict) -> str:
    delivery = record.get('delivery')
    if delivery == 'created':
        return '状态记录了已创建的 Issue，但在 GitHub 上没有对得上的 rebalance Issue。'
    if delivery == 'failed':
        return '发信时创建 Issue 失败，而且窗口内没有相同标题的 rebalance Issue。'
    if delivery == 'skipped':
        return '这次应该发信，但没有调用 GitHub Issue（例如 Actions 上漏了 --github-issue）。'
    if delivery == 'printed_only':
        return '这次应该发信，但只在本地打印，没有创建 rebalance Issue。'
    if delivery == 'missing':
        return '应发记录没有 Issue 编号。'
    return f'投递状态为 {delivery}，没有找到对应的 rebalance Issue。'


def book_weights(regime: str) -> tuple[dict, list]:
    out: dict[str, dict] = {}
    missing = []
    try:
        from config.regime_rules import REGIME_WEIGHTS
        out['US'] = dict(REGIME_WEIGHTS.get(regime, {}))
    except ImportError:
        missing.append('US')
    try:
        from config.cdn_regime_rules import CDN_REGIME_WEIGHTS
        out['CDN'] = dict(CDN_REGIME_WEIGHTS.get(regime, {}))
    except ImportError:
        missing.append('CDN')
    return out, missing


def material_deltas(old_w: dict, new_w: dict, eps: float = REBALANCE_EPS) -> list:
    """Sleeves whose weight moved by at least eps. Cuts first, then adds."""
    rows = []
    for ticker in set(old_w) | set(new_w):
        old = float(old_w.get(ticker, 0.0))
        new = float(new_w.get(ticker, 0.0))
        delta = new - old
        if abs(delta) + 1e-12 >= eps:
            rows.append((ticker, old, new, delta))
    rows.sort(key=lambda row: (row[3] >= 0, abs(row[3]) * -1, row[0]))
    return rows


def needs_rebalance(old_w: dict, new_w: dict, eps: float = REBALANCE_EPS) -> bool:
    return bool(material_deltas(old_w, new_w, eps))


def _bucket_sum(weights: dict, names) -> float:
    return sum(float(weights.get(name, 0.0)) for name in names)


def posture_line(book: str, old_w: dict, new_w: dict) -> str:
    equity_names, defensive_names = POSTURE_BASKETS[book]
    old_eq, new_eq = _bucket_sum(old_w, equity_names), _bucket_sum(new_w, equity_names)
    old_def, new_def = _bucket_sum(old_w, defensive_names), _bucket_sum(new_w, defensive_names)
    eq_label = '+'.join(equity_names)
    def_label = '+'.join(defensive_names)
    return (
        f'**{book} 风险姿态：** 股票仓 {format_pct(old_eq)} → {format_pct(new_eq)}'
        f'（{format_pct(new_eq - old_eq, signed=True)}）；'
        f'防御仓 {format_pct(old_def)} → {format_pct(new_def)}'
        f'（{format_pct(new_def - old_def, signed=True)}）。'
        f'股票仓 = {eq_label}；防御仓 = {def_label}。'
    )


def trade_line(ticker: str, old: float, new: float) -> str:
    delta = new - old
    verb = '增持' if delta > 0 else '减持'
    return f'{verb} {ticker} {format_pct(old)} → {format_pct(new)}（{format_pct(delta, signed=True)}）'


def vix_direction(prev_band, cur_band) -> str:
    ranks = {key: i for i, (_lo, _hi, key, _name) in enumerate(VIX_BANDS)}
    old = ranks.get(prev_band)
    new = ranks.get(cur_band)
    if old is None or new is None or old == new:
        return 'same'
    return 'tighten' if new > old else 'ease'


def _ops_regime() -> list[str]:
    return [
        '',
        '### 怎么执行',
        '- 上面是目标权重差额，不是已成交。这封邮件不会下单。',
        '- 本机 TWS 或 Gateway 开着时，先跑 `python scripts/ibkr_rebalance.py`（默认 dry-run，只打印计划）。',
        '- 本机 OpenD 已登录时，美股模拟盘可跑 `python scripts/moomoo_rebalance.py`（默认 dry-run，只打印计划；`--execute` 只允许 SIMULATE）。',
        '- 核对纸账户计划后，再加 `--execute` 才会发单。IBKR 脚本拒绝向非纸账户 `--execute`；Moomoo 脚本拒绝 REAL。',
        '- 对照仪表盘 **Regime Monitor**（当前象限）和 **Portfolio**（目标权重）。',
    ]


def _ops_vix_only() -> list[str]:
    return [
        '',
        '### 怎么执行',
        '- **月中再平衡：不建议。** 观察为主，不改四象限目标权重。',
        '- 日频股票敞口由引擎按 VIX 与回撤缩放。这一档只说明 overlay 应收紧还是可放松。',
        '- 若要核对账户是否偏离当前象限目标，本机跑 `python scripts/ibkr_rebalance.py`（默认 dry-run）。不要为了这一档加上 `--execute`。',
        '- Moomoo 美股模拟盘同样只核对：`python scripts/moomoo_rebalance.py`（默认 dry-run）。不要为了这一档加上 `--execute`。',
        '- 对照仪表盘 **Regime Monitor** 和 **Portfolio**。',
        '- 打印出来的是目标，不是已成交。',
    ]


def weight_table(old_regime, new_regime: str) -> str:
    """US + CDN target weights. With a previous regime, the last column is the delta."""
    lines = []
    new_w, missing = book_weights(new_regime)
    old_w, _old_missing = book_weights(old_regime) if old_regime else ({}, [])
    labels = {
        'US': 'US 目标权重（REGIME_WEIGHTS）',
        'CDN': 'CDN 目标权重（CDN_REGIME_WEIGHTS）',
    }
    for book in ('US', 'CDN'):
        if book in missing:
            lines.append(f'\n**{labels[book]}**\n\n配置模块未能导入。')
            continue
        nw = new_w.get(book, {})
        ow = old_w.get(book, {})
        lines.append(f'\n**{labels[book]}**\n')
        if not nw and not ow:
            lines.append(f'象限 `{new_regime}` 在该账本中没有权重。')
            continue
        lines.append('| 标的 | 原 | 新 | 变化 |')
        lines.append('|---|---:|---:|---:|')
        names = sorted(set(nw) | set(ow), key=lambda t: (-nw.get(t, 0.0), t))
        for ticker in names:
            a = float(ow.get(ticker, 0.0))
            b = float(nw.get(ticker, 0.0))
            if abs(a) < 1e-12 and abs(b) < 1e-12:
                continue
            if old_regime:
                lines.append(
                    f'| {ticker} | {format_pct(a)} | {format_pct(b)} | {format_pct(b - a, signed=True)} |'
                )
            else:
                lines.append(f'| {ticker} | — | {format_pct(b)} | — |')
    return '\n'.join(lines)


def _rebalance_flag(old_regime, new_regime: str) -> tuple[str, dict]:
    new_w, _missing = book_weights(new_regime)
    old_w, _old_missing = book_weights(old_regime) if old_regime else ({}, [])
    flags = {}
    any_move = False
    for book in ('US', 'CDN'):
        moved = needs_rebalance(old_w.get(book, {}), new_w.get(book, {}))
        flags[book] = moved
        any_move = any_move or moved
    return ('是' if any_move else '否'), flags


def _suggestion_block(old_regime, new_regime: str) -> list[str]:
    new_w, missing = book_weights(new_regime)
    old_w, _old_missing = book_weights(old_regime) if old_regime else ({}, [])
    lines = ['', '### 建议操作（目标差额，尚未下单）']
    for book in ('US', 'CDN'):
        lines.append(f'**{book}**')
        if book in missing:
            lines.append('- 配置模块未能导入，没有清单。')
            continue
        rows = material_deltas(old_w.get(book, {}), new_w.get(book, {}))
        if not rows:
            lines.append('- 没有达到 1% 的权重变化。')
            continue
        for ticker, old, new, _delta in rows:
            lines.append(f'- {trade_line(ticker, old, new)}')
    lines.extend(_ops_regime())
    return lines


def _vix_only_block(prev, cur: dict) -> list[str]:
    direction = vix_direction((prev or {}).get('vix_band'), cur.get('vix_band'))
    if direction == 'tighten':
        posture = '**防御姿态：应收紧**（VIX 档位升高，日频 overlay 降低股票敞口）'
    elif direction == 'ease':
        posture = '**防御姿态：可放松**（VIX 档位回落，日频 overlay 可以恢复股票敞口）'
    else:
        posture = '**防御姿态：与上一档相同**'
    return [
        '### 组合变化',
        f"象限未变：**{cur['regime']}**。目标权重不变。",
        '**需要调仓：否**',
        posture,
        '**月中再平衡：不建议（观察为主，不改目标权重）**',
        *_ops_vix_only(),
    ]


def _fmt_snapshot(cur: dict) -> list[str]:
    cpi = cur.get('cpi_yoy')
    gdp = cur.get('gdp')
    mom = cur.get('spy_momentum')
    cpi_s = f'{cpi:.2f}%' if isinstance(cpi, (int, float)) else 'n/a'
    gdp_s = f'{gdp:.2f}%' if isinstance(gdp, (int, float)) else 'n/a'
    mom_s = f'{mom:.1%}' if isinstance(mom, (int, float)) else 'n/a'
    return [
        '\n### 判定依据',
        f"- VIX {cur['vix']}（档位 {cur['vix_band']} · {cur['vix_band_name']}）",
        f'- CPI YoY {cpi_s} · GDP {gdp_s} · SPY 12 月动量 {mom_s}',
        f"- 价格数据截至 {cur['price_asof']}；检查时间 {cur['checked_at']}",
        '',
        '象限与仪表盘相同，用 targeted 时钟：CPI 滞后 1 个月，GDP 滞后 4 个月，'
        'VIX 月均和 12 个月动量再滞后 1 个月。最新 VIX 高于 30 时，当日标签改为 deflation。'
        'VIX 档位用最新收盘；同一档内的波动不单独发信。',
        '',
        '本邮件是信号提醒，不是成交回执，也不构成投资建议。',
    ]


def build_message(prev, cur: dict, reasons: dict) -> tuple[str, str]:
    old_regime = (prev or {}).get('regime')
    if 'regime' in reasons:
        title = f"[调仓] {old_regime or '?'} → {cur['regime']}（{cur['price_asof']}）"
    elif 'vix' in reasons:
        title = f"[风险档位] VIX {cur['vix']} → {cur['vix_band_name']}（{cur['price_asof']}）"
    else:
        title = f"[测试] 象限 {cur['regime']} / VIX {cur['vix']}（{cur['price_asof']}）"

    if 'regime' in reasons:
        flag, _books = _rebalance_flag(old_regime, cur['regime'])
        new_w, _missing = book_weights(cur['regime'])
        old_w, _old_missing = book_weights(old_regime) if old_regime else ({}, [])
        body = [
            '### 组合变化',
            f"象限：**{old_regime or '无记录'} → {cur['regime']}**",
            f'**需要调仓：{flag}**（任一标的权重变化达到 1% 为「是」）',
        ]
        if 'vix' in reasons:
            direction = vix_direction((prev or {}).get('vix_band'), cur.get('vix_band'))
            if direction == 'tighten':
                body.append('同日 VIX 升档：日频 overlay 另应收紧。目标权重仍按新象限调整。')
            elif direction == 'ease':
                body.append('同日 VIX 降档：日频 overlay 可放松。目标权重仍按新象限调整。')
        for book in ('US', 'CDN'):
            if book in new_w:
                body.append(posture_line(book, old_w.get(book, {}), new_w.get(book, {})))
        body.append(weight_table(old_regime, cur['regime']))
        body.extend(_suggestion_block(old_regime, cur['regime']))
    elif 'vix' in reasons:
        body = _vix_only_block(prev, cur)
    elif 'init' in reasons or 'forced' in reasons:
        body = [
            '### 组合变化',
            f"当前象限：**{cur['regime']}**",
            '**需要调仓：否**（试发或首次基线，没有上一档可比）',
            '下面是当前目标权重，供对照。这不是一笔已发生的调仓差额。',
            weight_table(None, cur['regime']),
        ]
    else:
        body = [
            '### 组合变化',
            f"象限未变：**{cur['regime']}**。目标权重不变。",
            '**需要调仓：否**',
        ]
    body.extend(_fmt_snapshot(cur))
    return title, '\n'.join(body)


def _dotenv_fred() -> str:
    path = ROOT / '.env'
    if not path.exists():
        return ''
    for line in path.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        if key.strip() == 'FRED_API_KEY':
            return value.strip().strip('"').strip("'")
    return ''


def fred_api_key() -> str:
    return (os.environ.get('FRED_API_KEY') or '').strip() or _dotenv_fred()


def _fred_get(fred, series_id: str) -> pd.Series:
    last_err = None
    for attempt in range(3):
        try:
            series = fred.get_series(series_id, observation_start='2000-01-01').dropna()
            series.index = pd.to_datetime(series.index)
            if getattr(series.index, 'tz', None) is not None:
                series.index = series.index.tz_localize(None)
            return series.sort_index()
        except Exception as exc:  # noqa: BLE001 — retry network/API errors
            last_err = exc
            time.sleep(2 * (attempt + 1))
    die(f'FRED {series_id} 拉取失败：{last_err}', code=2)
    raise AssertionError('unreachable')


def _close_series(df: pd.DataFrame) -> pd.Series:
    if isinstance(df.columns, pd.MultiIndex):
        levels0 = df.columns.get_level_values(0)
        if 'Close' in levels0:
            close = df['Close']
        elif 'Close' in df.columns.get_level_values(-1):
            close = df.xs('Close', axis=1, level=-1)
        else:
            close = df.iloc[:, 0]
        if isinstance(close, pd.DataFrame):
            close = close.iloc[:, 0]
        return close
    if 'Close' in df.columns:
        return df['Close']
    return df.iloc[:, 0]


def _download_spy() -> pd.Series:
    import yfinance as yf

    last_err = None
    for attempt in range(3):
        try:
            df = yf.download(
                'SPY', start='2005-01-01', auto_adjust=True, progress=False, threads=False,
            )
            if df is not None and not getattr(df, 'empty', True):
                spy = _close_series(df).dropna()
                if len(spy) >= 252:
                    spy.name = 'SPY'
                    spy.index = pd.to_datetime(spy.index)
                    if getattr(spy.index, 'tz', None) is not None:
                        spy.index = spy.index.tz_localize(None)
                    return spy.sort_index()
        except Exception as exc:  # noqa: BLE001
            last_err = exc
        time.sleep(2 * (attempt + 1))
    die(f'SPY 下载失败：{last_err}', code=2)
    raise AssertionError('unreachable')


def refresh_caches() -> None:
    """Light refresh: FRED macro + SPY. Enough for classify_regimes. Not a full backtest."""
    key = fred_api_key()
    if not key:
        die(
            '缺少 FRED_API_KEY。在仓库 Secrets 或本地 .env 中设置后再 --refresh。'
            '说明见 docs/notify.md。'
        )
    from fredapi import Fred

    fred = Fred(api_key=key)
    macro = {name: _fred_get(fred, series_id) for name, series_id in FRED_SERIES}
    spy = _download_spy()
    last_price = pd.Timestamp(spy.index.max()).normalize()
    last_vix = pd.Timestamp(macro['vix'].index.max()).normalize()
    today = pd.Timestamp.now().normalize()
    stale = []
    if (today - last_price).days > 7:
        stale.append(f'SPY 截至 {last_price.date()}')
    if (today - last_vix).days > 7:
        stale.append(f'VIX 截至 {last_vix.date()}')
    if stale:
        die('行情过旧，拒绝覆盖缓存：' + '；'.join(stale), code=2)
    price = spy.to_frame()
    price.index.name = 'Date'
    validate_inputs(macro, price)
    dest = cache_dir()
    dest.mkdir(parents=True, exist_ok=True)
    with open(dest / 'macro_data.pkl', 'wb') as fh:
        pickle.dump(macro, fh)
    price.to_csv(dest / 'price_data.csv')
    print(
        f"已刷新宏观与 SPY：VIX {len(macro['vix'])} 点，"
        f"价格截至 {last_price.date()}（目录 {dest}）"
    )


def _github(method: str, url: str, token: str, payload: dict | None = None):
    headers = {
        'Authorization': f'Bearer {token}',
        'Accept': 'application/vnd.github+json',
        'User-Agent': 'notify-regime',
        'X-GitHub-Api-Version': '2022-11-28',
    }
    data = None
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        headers['Content-Type'] = 'application/json; charset=utf-8'
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode('utf-8')
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode('utf-8', errors='replace')
        raise GitHubAPIError(exc.code, body) from exc


def _repo_token() -> tuple[str, str]:
    repo = os.environ.get('GITHUB_REPOSITORY', '')
    token = os.environ.get('GITHUB_TOKEN', '')
    if not (repo and token):
        die('缺少 GITHUB_REPOSITORY / GITHUB_TOKEN（应由 Actions 注入）。')
    return repo, token


def ensure_label(repo: str, token: str, name: str, color: str, description: str) -> None:
    base = f'https://api.github.com/repos/{repo}/labels'
    try:
        _github('GET', f'{base}/{urllib.parse.quote(name)}', token)
        return
    except GitHubAPIError as exc:
        if exc.code != 404:
            raise
    _github('POST', base, token, {
        'name': name,
        'color': color,
        'description': description,
    })
    print(f'已创建 GitHub 标签 {name}')


def ensure_rebalance_label(repo: str, token: str) -> None:
    ensure_label(
        repo, token, 'rebalance', 'D93F0B',
        'Merrill regime or VIX band change / 象限或 VIX 跨档',
    )


def ensure_audit_label(repo: str, token: str) -> None:
    ensure_label(
        repo, token, 'notify-audit', 'B60205',
        'Missing rebalance alert / 应发的调仓提醒缺失',
    )


def create_github_issue(title: str, body: str, labels: list[str]) -> dict:
    repo, token = _repo_token()
    url = f'https://api.github.com/repos/{repo}/issues'
    owner = repo.split('/')[0]
    payload = {'title': title, 'body': body, 'labels': labels}
    try:
        data = _github('POST', url, token, {**payload, 'assignees': [owner]})
    except GitHubAPIError as exc:
        if exc.code not in (403, 422):
            die(f'创建 Issue 失败 HTTP {exc.code}: {exc.body[:400]}')
        try:
            data = _github('POST', url, token, payload)
        except GitHubAPIError as exc2:
            die(f'创建 Issue 失败 HTTP {exc2.code}: {exc2.body[:400]}')
        print(f"已创建 Issue（未指派）: {data.get('html_url')}")
        return data
    print(f"已创建 Issue: {data.get('html_url')}")
    return data


def open_issue(title: str, body: str) -> dict:
    repo, token = _repo_token()
    try:
        ensure_rebalance_label(repo, token)
    except GitHubAPIError as exc:
        die(f'创建或确认标签 rebalance 失败 HTTP {exc.code}: {exc.body[:400]}')
    data = create_github_issue(title, body, ['rebalance'])
    issue = coerce_created_issue(data)
    if issue is None:
        die('创建 Issue 的响应缺少 number 或 html_url，视为未发出。')
    return issue


def _issues_page(repo: str, token: str, labels: str, state: str, since: str | None = None) -> list:
    query = f'state={urllib.parse.quote(state)}&labels={urllib.parse.quote(labels)}&per_page=100'
    if since:
        query += '&since=' + urllib.parse.quote(since)
    data = _github('GET', f'https://api.github.com/repos/{repo}/issues?{query}', token)
    return data if isinstance(data, list) else []


def github_find_rebalance(record: dict):
    """Return the matching rebalance Issue, or None. LookupError if GitHub cannot be checked."""
    try:
        return _github_find_rebalance(record)
    except LookupError:
        raise
    except GitHubAPIError as exc:
        raise LookupError(f'HTTP {exc.code}') from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise LookupError(str(exc)) from exc


def _get_issue(repo: str, token: str, number: int):
    """GET one Issue. A fresh 404 is retried twice; replication lag is not a miss."""
    url = f'https://api.github.com/repos/{repo}/issues/{number}'
    for attempt in range(3):
        try:
            return _github('GET', url, token)
        except GitHubAPIError as exc:
            if exc.code != 404:
                raise
            if attempt < 2:
                time.sleep(1)
    return None


def _github_find_rebalance(record: dict):
    repo, token = _repo_token()
    number = record.get('issue_number')
    data = None
    if number not in (None, ''):
        try:
            number_i = int(number)
        except (TypeError, ValueError):
            number_i = 0
        if number_i > 0:
            data = _get_issue(repo, token, number_i)
    if isinstance(data, dict) and issue_satisfies(data, record, numbered=True):
        return data
    anchor = parse_utc(record.get('checked_at_iso') or record.get('checked_at'))
    since = None
    if anchor is not None:
        since = (anchor - timedelta(days=AUDIT_WINDOW_DAYS)).strftime('%Y-%m-%dT%H:%M:%SZ')
    page = _issues_page(repo, token, 'rebalance', 'all', since=since)
    for item in page:
        if issue_satisfies(item, record, numbered=False):
            return item
    return None


def github_find_open_audit(fingerprint: str):
    if not fingerprint:
        return None
    repo, token = _repo_token()
    marker = f'{AUDIT_FINGERPRINT_PREFIX} {fingerprint}'
    try:
        page = _issues_page(repo, token, 'notify-audit', 'open')
    except GitHubAPIError as exc:
        if exc.code == 404:
            return None
        raise LookupError(f'HTTP {exc.code}') from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise LookupError(str(exc)) from exc
    for item in page:
        if item.get('pull_request'):
            continue
        if marker in (item.get('body') or ''):
            return item
    return None


def github_open_audit(record: dict, detail: str) -> dict:
    repo, token = _repo_token()
    try:
        ensure_audit_label(repo, token)
    except GitHubAPIError as exc:
        die(f'创建或确认标签 notify-audit 失败 HTTP {exc.code}: {exc.body[:400]}')
    data = create_github_issue(
        audit_issue_title(record),
        audit_issue_body(record, detail),
        ['notify-audit'],
    )
    issue = coerce_created_issue(data)
    if issue is None:
        die('审计 Issue 的响应缺少 number 或 html_url。')
    return issue


def run_audit(finder=None, alerter=None, find_audit=None) -> str:
    """Verify the latest should-fire event has a rebalance Issue.

    Returns 'ok' or 'already_alerted'. A confirmed miss raises SystemExit(1)
    after opening one [审计] Issue. An already-open audit Issue for the same
    fingerprint is not opened again.
    """
    finder = finder or github_find_rebalance
    alerter = alerter or github_open_audit
    find_audit = find_audit or github_find_open_audit
    record = expectation_to_verify(read_audit(), read_state())
    if record is None:
        set_github_output('confirmed_miss', 'false')
        print('审计：没有待核对的发信。')
        return 'ok'
    try:
        found = finder(record)
    except LookupError as exc:
        set_github_output('confirmed_miss', 'false')
        die(f'审计无法访问 GitHub，不能确认 Issue 是否存在：{exc}')
    if isinstance(found, dict) and found.get('number') and (found.get('html_url') or found.get('issue_url')):
        number = found.get('number')
        url = found.get('html_url') or found.get('issue_url') or ''
        set_github_output('confirmed_miss', 'false')
        print(f'审计通过：rebalance Issue #{number} {url}')
        return 'ok'
    detail = audit_miss_detail(record)
    fingerprint = str(record.get('fingerprint') or '')
    existing = None
    try:
        existing = find_audit(fingerprint) if fingerprint else None
    except LookupError as exc:
        set_github_output('confirmed_miss', 'true')
        die(f'确认漏报，但无法查询已有审计 Issue：{exc}。{detail}')
    except GitHubAPIError as exc:
        set_github_output('confirmed_miss', 'true')
        die(f'确认漏报，但查询审计 Issue 失败 HTTP {exc.code}。{detail}')
    if existing:
        url = existing.get('html_url') or ''
        # A delivery=created record we still cannot see must not be committed
        # as the new baseline. An older miss (create failed, baseline untouched)
        # can stay quiet once its audit Issue is open.
        if record.get('delivery') == 'created':
            set_github_output('confirmed_miss', 'true')
        else:
            set_github_output('confirmed_miss', 'false')
        print(f'审计：漏报仍在，已有未关闭的审计 Issue，不再重复开。{url}')
        print(detail)
        return 'already_alerted'
    try:
        opened = alerter(record, detail)
    except SystemExit:
        set_github_output('confirmed_miss', 'true')
        raise
    set_github_output('confirmed_miss', 'true')
    opened_issue = coerce_created_issue(opened) if opened else None
    extra = ''
    if opened_issue:
        extra = f" 已开审计 Issue #{opened_issue['number']} {opened_issue['html_url']}"
    die('漏报：应发的 rebalance Issue 不存在。' + detail + extra)


def parse_args(argv=None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description='象限 / VIX 跨档提醒。没变化则静默退出。')
    ap.add_argument('--dry-run', action='store_true', help='打印邮件，不发 Issue，不写状态')
    ap.add_argument('--github-issue', action='store_true', help='有信号时开 GitHub Issue')
    ap.add_argument('--force', action='store_true', help='忽略去重，用于测试发信')
    ap.add_argument(
        '--audit', action='store_true',
        help='核对最近一次应发的 rebalance Issue 是否存在；漏报则失败并开 [审计] Issue',
    )
    ap.add_argument(
        '--refresh', action='store_true',
        help='用 FRED + yfinance 刷新宏观与 SPY（不跑完整回测）',
    )
    return ap.parse_args(argv)


def _stamp_expectation(audit: dict, prev, cur: dict, reasons: dict, title: str) -> None:
    audit['should_fire'] = True
    audit['kind'] = delivery_kind(reasons)
    audit['title'] = title
    audit['fingerprint'] = delivery_fingerprint(prev, cur, reasons)
    audit['checked_at_iso'] = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def execute(args: argparse.Namespace, opener=None) -> str:
    if args.refresh:
        refresh_caches()
    cur = current_state()
    prev = read_state()
    action, reasons = classify_change(prev, cur, force=args.force)
    audit = blank_audit(action, cur)

    if action == 'silent':
        print(
            f"无变化：{cur['regime']} / VIX {cur['vix']}（{cur['vix_band']} {cur['vix_band_name']}）"
            '—— 不发送。'
        )
        write_audit(audit)
        return action

    if action == 'baseline':
        print(f"首次运行，写入基线：{cur['regime']} / VIX 档位 {cur['vix_band']}（不发送）")
        if not args.dry_run:
            write_state(cur)
        write_audit(audit)
        return action

    title, body = build_message(prev, cur, reasons)
    _stamp_expectation(audit, prev, cur, reasons, title)
    if args.dry_run:
        print('=' * 72)
        print('标题:', title)
        print('=' * 72)
        print(body)
        print('=' * 72)
        print('(--dry-run：未发送，状态未写入)')
        return action

    if args.github_issue:
        try:
            opened = (opener or open_issue)(title, body)
        except SystemExit:
            audit['delivery'] = 'failed'
            audit['error'] = '创建 Issue 失败'
            write_audit(audit)
            raise
        except Exception as exc:
            audit['delivery'] = 'failed'
            audit['error'] = f'{type(exc).__name__}: {exc}'
            write_audit(audit)
            die(f'创建 Issue 失败：{exc}')
        issue = coerce_created_issue(opened)
        if issue is None:
            audit['delivery'] = 'failed'
            audit['error'] = 'opener 没有返回 number 和 html_url'
            write_audit(audit)
            die('应发信，但 Issue 没有创建成功（缺少 number 或 html_url）。拒绝写入状态。')
        audit['delivery'] = 'created'
        audit['issue_number'] = issue['number']
        audit['issue_url'] = issue['html_url']
        cur = dict(cur)
        cur['last_delivery'] = dict(audit)
        write_state(cur)
        write_audit(audit)
        print(f"发信记录：Issue #{issue['number']} {issue['html_url']}")
        return action

    if os.environ.get('GITHUB_ACTIONS') == 'true':
        audit['delivery'] = 'skipped'
        audit['error'] = 'Actions 上应发信但没有 --github-issue'
        write_audit(audit)
        die('Actions 上应发信，但没有 --github-issue。拒绝写入状态，避免静默漏报。')

    print('标题:', title)
    print(body)
    print('（未加 --github-issue：只打印，未开 Issue，状态未写入，下次仍会提醒）')
    audit['delivery'] = 'printed_only'
    write_audit(audit)
    return action


def main(argv=None) -> None:
    args = parse_args(argv)
    if args.audit:
        run_audit()
        return
    execute(args)


if __name__ == '__main__':
    main()
