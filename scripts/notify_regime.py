#!/usr/bin/env python3
"""
notify_regime.py — 象限 / VIX 跨档提醒（GitHub Issue → 邮件）。

    python scripts/notify_regime.py --dry-run
    python scripts/notify_regime.py --refresh --dry-run
    python scripts/notify_regime.py --refresh --github-issue
    python scripts/notify_regime.py --refresh --github-issue --force

发信条件（满足其一才开 Issue）:
  1. Merrill 象限变了（src.backtester.regime_clock，mode=targeted）
  2. 最新 VIX 跨档：0-20 / 20-28 / 28-30 / 30-40 / 40+

同一档内的 VIX 波动、以及象限未变，都静默退出。首次运行只写
data/notify_state.json 基线，不开 Issue；--force 用于测试发信。

targeted 与仪表盘、ibkr_rebalance 相同：CPI +1 个月，GDP +4 个月，
VIX 月均和 12 个月动量再 shift(1)。不 import run_dashboard（那会跑启动逻辑）。
"""
from __future__ import annotations

import argparse
import json
import os
import pickle
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
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


def die(msg: str, code: int = 1) -> None:
    print(msg, file=sys.stderr)
    raise SystemExit(code)


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
        '下面的 VIX 档位用最新收盘；同一档内的波动不单独发信。',
        '',
        '### 执行提醒',
        '- 上表是四象限目标权重。日频股票敞口由引擎按 VIX 与回撤计算；本提醒标出跨档。',
        '- 这是信号提醒，供人工调仓参考，不构成投资建议，也不会自动下单。',
    ]


def build_message(prev, cur: dict, reasons: dict) -> tuple[str, str]:
    old_regime = (prev or {}).get('regime')
    if 'regime' in reasons:
        title = f"[调仓] {old_regime or '?'} → {cur['regime']}（{cur['price_asof']}）"
    elif 'vix' in reasons:
        title = f"[风险档位] VIX {cur['vix']} → {cur['vix_band_name']}（{cur['price_asof']}）"
    else:
        title = f"[测试] 象限 {cur['regime']} / VIX {cur['vix']}（{cur['price_asof']}）"

    body = ['### 触发原因', '\n'.join(f'- {text}' for text in reasons.values()), '']
    if 'regime' in reasons:
        body.append(f"当前象限：**{cur['regime']}**（原 {old_regime or '无记录'}）")
        body.append(weight_table(old_regime, cur['regime']))
    elif 'init' in reasons or 'forced' in reasons:
        body.append(f"当前象限：**{cur['regime']}**")
        body.append('下面是当前目标权重，供对照。这不是一笔已发生的调仓差额。')
        body.append(weight_table(None, cur['regime']))
    else:
        body.append(f"象限未变：**{cur['regime']}**。目标权重不变。")
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


def ensure_rebalance_label(repo: str, token: str) -> None:
    base = f'https://api.github.com/repos/{repo}/labels'
    try:
        _github('GET', f'{base}/rebalance', token)
        return
    except GitHubAPIError as exc:
        if exc.code != 404:
            raise
    _github('POST', base, token, {
        'name': 'rebalance',
        'color': 'D93F0B',
        'description': 'Merrill regime or VIX band change / 象限或 VIX 跨档',
    })
    print('已创建 GitHub 标签 rebalance')


def open_issue(title: str, body: str) -> None:
    repo = os.environ.get('GITHUB_REPOSITORY', '')
    token = os.environ.get('GITHUB_TOKEN', '')
    if not (repo and token):
        die('缺少 GITHUB_REPOSITORY / GITHUB_TOKEN（应由 Actions 注入）。')
    try:
        ensure_rebalance_label(repo, token)
    except GitHubAPIError as exc:
        die(f'创建或确认标签 rebalance 失败 HTTP {exc.code}: {exc.body[:400]}')
    url = f'https://api.github.com/repos/{repo}/issues'
    owner = repo.split('/')[0]
    payload = {'title': title, 'body': body, 'labels': ['rebalance']}
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
        return
    print(f"已创建 Issue: {data.get('html_url')}")


def parse_args(argv=None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description='象限 / VIX 跨档提醒。没变化则静默退出。')
    ap.add_argument('--dry-run', action='store_true', help='打印邮件，不发 Issue，不写状态')
    ap.add_argument('--github-issue', action='store_true', help='有信号时开 GitHub Issue')
    ap.add_argument('--force', action='store_true', help='忽略去重，用于测试发信')
    ap.add_argument(
        '--refresh', action='store_true',
        help='用 FRED + yfinance 刷新宏观与 SPY（不跑完整回测）',
    )
    return ap.parse_args(argv)


def execute(args: argparse.Namespace, opener=None) -> str:
    if args.refresh:
        refresh_caches()
    cur = current_state()
    prev = read_state()
    action, reasons = classify_change(prev, cur, force=args.force)

    if action == 'silent':
        print(
            f"无变化：{cur['regime']} / VIX {cur['vix']}（{cur['vix_band']} {cur['vix_band_name']}）"
            '—— 不发送。'
        )
        return action

    if action == 'baseline':
        print(f"首次运行，写入基线：{cur['regime']} / VIX 档位 {cur['vix_band']}（不发送）")
        if not args.dry_run:
            write_state(cur)
        return action

    title, body = build_message(prev, cur, reasons)
    if args.dry_run:
        print('=' * 72)
        print('标题:', title)
        print('=' * 72)
        print(body)
        print('=' * 72)
        print('(--dry-run：未发送，状态未写入)')
        return action

    if args.github_issue:
        (opener or open_issue)(title, body)
    else:
        print('标题:', title)
        print(body)
        print('（未加 --github-issue：只打印，未开 Issue）')
    write_state(cur)
    return action


def main(argv=None) -> None:
    execute(parse_args(argv))


if __name__ == '__main__':
    main()
