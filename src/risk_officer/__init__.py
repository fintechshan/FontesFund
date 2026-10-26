"""Notify-only structural flags. They do not size or trade.

D_capex, E_credit, and F_conc are merged onto ``data/risk_flags/flags.json``
by ``scripts/refresh_risk_flags.py``. Merrill weights, QQQ Vegas, and the
broker scripts do not import this package.
"""
from __future__ import annotations

from pathlib import Path

from src.risk_flags import STRUCTURAL_FLAG_IDS, _blank_flag
from src.risk_officer.capex_analyzer import (
    TEMPLATE_NAME,
    evaluate_capex_sources,
)
from src.risk_officer.concentration_analyzer import evaluate_concentration_source
from src.risk_officer.credit_analyzer import evaluate_credit_source

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TEMPLATE = ROOT / 'data' / 'risk_flags' / TEMPLATE_NAME


def _previous_flag(previous, key):
    if not isinstance(previous, dict):
        return None
    flags = previous.get('flags')
    if not isinstance(flags, dict):
        return None
    item = flags.get(key)
    return item if isinstance(item, dict) else None


def _safe(key: str, fn):
    try:
        payload = fn()
    except Exception as exc:  # noqa: BLE001 — one leg must not drop the scorecard
        payload = _blank_flag(key, f'{key} 计算失败（{exc.__class__.__name__}），保留上一份。')
        payload['inherit_previous'] = True
        return payload, f'{key}: {exc.__class__.__name__}'
    if not isinstance(payload, dict):
        payload = _blank_flag(key, f'{key} 没有返回旗标。')
        payload['inherit_previous'] = True
    return payload, None


def build_structural_flags(previous=None, directory=None, fetch: bool = True, template_path=None) -> dict:
    """Return ``{'flags': {D,E,F}, 'notes': [...]}``.

    ``fetch=False`` reads only local files. A failed live source sets
    ``inherit_previous`` so a blip does not clear a stored ON.
    """
    directory = Path(directory) if directory is not None else DEFAULT_TEMPLATE.parent
    template = Path(template_path) if template_path is not None else DEFAULT_TEMPLATE
    notes = []

    def capex():
        return evaluate_capex_sources(
            template,
            directory / 'capex_official.csv',
            _previous_flag(previous, 'D_capex'),
            fetch=fetch,
        )

    def credit():
        return evaluate_credit_source(directory / 'credit_oas.csv', fetch=fetch)

    def concentration():
        return evaluate_concentration_source(
            directory / 'spy_mag7_weight.csv',
            directory / 'spy_holdings.xlsx',
            fetch=fetch,
        )

    flags = {}
    for key, fn in (
        ('D_capex', capex),
        ('E_credit', credit),
        ('F_conc', concentration),
    ):
        payload, note = _safe(key, fn)
        flags[key] = payload
        if note:
            notes.append(note)
        elif payload.get('inherit_previous'):
            notes.append(f'{key}: kept previous ({payload.get("detail") or "source missing"})')
    missing = [key for key in STRUCTURAL_FLAG_IDS if key not in flags]
    for key in missing:
        flags[key] = _blank_flag(key)
    return {'flags': flags, 'notes': notes}
