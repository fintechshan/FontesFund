"""Point-in-time Merrill four-quadrant clock.

The production default is ``targeted``:

* CPI is lagged **+1 month** and GDP **+4 months** (publication semantics).
  Those offsets are not shortened.
* VIX (monthly mean) and SPY 12-month momentum are dated on the **month-end
  they describe**. A month-start rebalance therefore sees only the prior
  month. The previous production path stamped those same-month values on
  month-start, so January's regime was built with January's closing prices
  and January's average VIX.

Other modes exist only for comparison. They are not the live default.

``vintage`` replaces the fixed CPI/GDP offset with first-release values
indexed by release time. With ``FRED_API_KEY``, that is fredapi
``get_series_first_release`` / ``get_series_all_releases`` (ALFRED) for
GDPC1 and CPIAUCSL. Without a key, the same clock is built from the
Philadelphia Fed Real-Time Data Set (RTDSM), which is itself an ALFRED
archive: monthly CPI vintages (``pcpiMvMd``) and monthly real-GDP
vintages (``routputMvQd``). A vintage column is dated the 15th of that
month (the RTDSM mid-month snapshot). Market signals stay on the
targeted rule. If every vintage source fails, callers fall back to
``targeted`` and set ``vintage_fallback``.
"""
from __future__ import annotations

import logging
import os
import pickle
import re
from pathlib import Path

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

CPI_RELEASE_LAG_M = 1
GDP_RELEASE_LAG_M = 4

MODE_UNLAGGED = "unlagged"
MODE_LOOKAHEAD = "lookahead"
MODE_TARGETED = "targeted"
MODE_AUDITOR = "auditor"
MODE_VINTAGE = "vintage"

HONESTY_MODES = (
    MODE_TARGETED,
    MODE_LOOKAHEAD,
    MODE_UNLAGGED,
    MODE_AUDITOR,
    MODE_VINTAGE,
)

# Revised GDP series used with the fixed +4 month offset (already a YoY %).
GDP_YOY_SERIES = "A191RL1Q225SBEA"
# First-release levels. YoY is computed from the vintage, not from this id's latest print.
GDP_LEVEL_SERIES = "GDPC1"
CPI_LEVEL_SERIES = "CPIAUCSL"

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
VINTAGE_CACHE = _PROJECT_ROOT / "data" / "cache" / "vintage_clock.pkl"
# Committed release-dated YoY (not the raw ALFRED archive). Lets the dashboard
# and CI compare first-release vs the fixed offset without a network call.
VINTAGE_TABLE = _PROJECT_ROOT / "data" / "backtest_results" / "vintage_release_yoy.csv"
ALFRED_DIR = _PROJECT_ROOT / "data" / "cache" / "alfred_vintages"
# A one-row or collapsed file is not a real-time clock. Real CPI/GDP
# first-release histories have decades of release dates.
MIN_VINTAGE_RELEASES = 24
PHILLY_DIR = _PROJECT_ROOT / "data" / "cache" / "philly_rtdsm"
PHILLY_CPI_PAGE = "https://www.philadelphiafed.org/surveys-and-data/real-time-data-research/pcpi"
PHILLY_GDP_PAGE = "https://www.philadelphiafed.org/surveys-and-data/real-time-data-research/routput"
PHILLY_CPI_FILE = "pcpiMvMd.xlsx"
PHILLY_GDP_FILE = "routputMvQd.xlsx"
_PHILLY_VINTAGE_RE = re.compile(r"^(?:PCPI|ROUTPUT)(\d{2})M(\d{1,2})$", re.IGNORECASE)
_PHILLY_MONTH_RE = re.compile(r"^(\d{4}):(\d{2})$")
_PHILLY_QUARTER_RE = re.compile(r"^(\d{4}):Q([1-4])$")


def _as_dt_index(series: pd.Series) -> pd.Series:
    out = series.copy()
    if len(out) == 0:
        return out
    out.index = pd.to_datetime(out.index)
    if getattr(out.index, "tz", None) is not None:
        out.index = out.index.tz_localize(None)
    return out.sort_index()


def market_signals(vix: pd.Series, spy: pd.Series, same_month: bool) -> tuple[pd.Series, pd.Series]:
    """VIX monthly mean and SPY 12-month momentum.

    ``same_month=True`` reproduces the old bug: the full calendar month is
    labeled on month-start, so a decision on the 1st sees the month-end.
    ``same_month=False`` labels those statistics on month-end. ``asof`` at
    the next month-start is the first time they are knowable.
    """
    vix_m = pd.Series(dtype=float)
    spy_m = pd.Series(dtype=float)
    if vix is not None and len(vix) > 0:
        vix = _as_dt_index(vix.dropna())
        rule = "MS" if same_month else "ME"
        vix_m = vix.resample(rule).mean()
    if spy is not None and len(spy) > 0:
        spy = _as_dt_index(spy.dropna())
        rule = "MS" if same_month else "ME"
        spy_m = spy.resample(rule).last().pct_change(12)
    return vix_m, spy_m


def publication_lagged_macro(cpi: pd.Series, gdp: pd.Series, apply_lag: bool):
    """CPI YoY (%) and GDP YoY (%) on a month-start index.

    GDP is the published year-ago percent (``A191RL1Q225SBEA``), not a level.
    ``apply_lag`` shifts CPI by +1 month and GDP by +4 months. It does not
    change those offsets.
    """
    cpi_yoy = pd.Series(dtype=float)
    gdp_out = pd.Series(dtype=float)
    if cpi is not None and len(cpi) > 12:
        cpi = _as_dt_index(cpi.dropna())
        cpi_yoy = (cpi / cpi.shift(12) - 1.0) * 100.0
        cpi_yoy = cpi_yoy.dropna()
        if apply_lag and len(cpi_yoy):
            cpi_yoy.index = cpi_yoy.index + pd.DateOffset(months=CPI_RELEASE_LAG_M)
    if gdp is not None and len(gdp) > 0:
        gdp_out = _as_dt_index(gdp.dropna())
        if apply_lag and len(gdp_out):
            gdp_out.index = gdp_out.index + pd.DateOffset(months=GDP_RELEASE_LAG_M)
    cpi_monthly = (
        cpi_yoy.resample("MS").last().ffill() if len(cpi_yoy) else pd.Series(dtype=float)
    )
    gdp_monthly = (
        gdp_out.resample("MS").last().ffill() if len(gdp_out) else pd.Series(dtype=float)
    )
    return cpi_yoy, gdp_out, cpi_monthly, gdp_monthly


def _asof_value(series: pd.Series, date, default: float) -> float:
    if series is None or len(series) == 0:
        return default
    val = series.asof(pd.Timestamp(date))
    if pd.isna(val):
        return default
    return float(val)


def _classify_one(date, gdp_monthly, spy_m, cpi_monthly, vix_m, vix_defensive: float) -> str:
    gdp_val = _asof_value(gdp_monthly, date, 2.0)
    spy_val = _asof_value(spy_m, date, 0.05)
    growth_rising = (gdp_val > 1.5) or (spy_val > 0.05)

    cpi_val = _asof_value(cpi_monthly, date, 2.0)
    cpi_3m = _asof_value(cpi_monthly, pd.Timestamp(date) - pd.DateOffset(months=3), 2.0)
    inflation_rising = (cpi_val > 3.0) and (cpi_val > cpi_3m)

    vix_val = _asof_value(vix_m, date, 15.0)
    if vix_val > vix_defensive:
        return "deflation"
    if growth_rising and not inflation_rising:
        return "goldilocks"
    if growth_rising and inflation_rising:
        return "reflation"
    if (not growth_rising) and inflation_rising:
        return "stagflation"
    return "deflation"


def yoy_on_release_dates(
    all_releases: pd.DataFrame,
    periods: int,
    first_release_values: pd.Series | None = None,
) -> pd.Series:
    """Percent change known on each observation's first release date.

    ``all_releases`` has columns ``date`` (observation), ``realtime_start``
    (when that print was published), and ``value``. The current observation
    uses the first print. The base ``periods`` observations earlier uses the
    vintage available on that same release date (what a reader could have
    computed that day), which is the ``get_series_as_of_date`` filter.

    The result is indexed by release time, not by the observation date.
    """
    if all_releases is None or len(all_releases) == 0:
        return pd.Series(dtype=float)
    df = all_releases.dropna(subset=["value"]).copy()
    df["date"] = pd.to_datetime(df["date"])
    df["realtime_start"] = pd.to_datetime(df["realtime_start"])
    df = df.sort_values(["realtime_start", "date"])

    if first_release_values is not None and len(first_release_values):
        first_release_values = _as_dt_index(first_release_values)

    first_rt = df.groupby("date")["realtime_start"].min()
    pending: dict[pd.Timestamp, list] = {}
    for obs, released in first_rt.items():
        pending.setdefault(pd.Timestamp(released), []).append(pd.Timestamp(obs))

    levels: dict[pd.Timestamp, float] = {}
    points: dict[pd.Timestamp, float] = {}
    for released, chunk in df.groupby("realtime_start", sort=True):
        released = pd.Timestamp(released)
        for row in chunk.itertuples(index=False):
            levels[pd.Timestamp(row.date)] = float(row.value)
        new_obs = pending.get(released)
        if not new_obs:
            continue
        obs = max(new_obs)
        ordered = sorted(levels)
        loc = ordered.index(obs) if obs in levels else -1
        if loc < periods:
            continue
        base = levels[ordered[loc - periods]]
        cur = levels[obs]
        if first_release_values is not None and obs in first_release_values.index:
            fr = first_release_values.loc[obs]
            if isinstance(fr, pd.Series):
                fr = fr.iloc[0]
            if pd.notna(fr):
                cur = float(fr)
        if not np.isfinite(base) or base == 0.0 or not np.isfinite(cur):
            continue
        points[released] = (cur / base - 1.0) * 100.0

    if not points:
        return pd.Series(dtype=float)
    out = pd.Series(points).sort_index()
    out.index = pd.to_datetime(out.index)
    return out


def releases_from_monthend_vintages(frames: list[tuple[pd.Timestamp, pd.Series]]) -> pd.DataFrame:
    """Turn as-of month-end snapshots into an all-releases frame.

    Each snapshot is the vintage a reader had at that month-end (the public
    ``vintage_date`` file, or ``get_series_as_of_date``). Rows are tagged with
    that month-end as ``realtime_start``. First-release selection then keeps
    the first month-end on which each observation exists. For a monthly
    rebalance, a mid-month release and that month's month-end fall in the
    same decision bucket.
    """
    rows = []
    for stamp, series in frames:
        series = _as_dt_index(series.dropna())
        for obs, val in series.items():
            rows.append({"date": obs, "realtime_start": pd.Timestamp(stamp), "value": float(val)})
    if not rows:
        return pd.DataFrame(columns=["date", "realtime_start", "value"])
    return pd.DataFrame(rows)


def _read_vintage_csv(path: Path) -> pd.Series:
    df = pd.read_csv(path)
    df.columns = ["date", "value"]
    df["date"] = pd.to_datetime(df["date"])
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    return df.dropna(subset=["value"]).set_index("date")["value"]


def load_monthend_vintage_dir(directory: Path, series_id: str) -> pd.DataFrame:
    folder = Path(directory) / series_id
    frames = []
    if not folder.exists():
        return pd.DataFrame(columns=["date", "realtime_start", "value"])
    for path in sorted(folder.glob("*.csv")):
        try:
            stamp = pd.Timestamp(path.stem)
        except Exception:
            continue
        frames.append((stamp, _read_vintage_csv(path)))
    return releases_from_monthend_vintages(frames)


def _vintage_usable(payload: dict | None) -> bool:
    if not payload:
        return False
    cpi = payload.get("cpi_yoy_release")
    gdp = payload.get("gdp_yoy_release")
    if cpi is None or gdp is None:
        return False
    return (
        int(cpi.dropna().shape[0]) >= MIN_VINTAGE_RELEASES
        and int(gdp.dropna().shape[0]) >= MIN_VINTAGE_RELEASES
    )


def philly_vintage_stamp(name: str) -> pd.Timestamp | None:
    """RTDSM column ``PCPI20M4`` → 2020-04-15 (mid-month snapshot)."""
    match = _PHILLY_VINTAGE_RE.match(str(name).strip())
    if not match:
        return None
    yy = int(match.group(1))
    month = int(match.group(2))
    if not 1 <= month <= 12:
        return None
    year = 1900 + yy if yy >= 60 else 2000 + yy
    return pd.Timestamp(year=year, month=month, day=15)


def philly_obs_date(label) -> pd.Timestamp | None:
    """``2020:03`` or ``2020:Q1`` → the observation period start."""
    text = str(label).strip()
    month = _PHILLY_MONTH_RE.match(text)
    if month:
        mm = int(month.group(2))
        if 1 <= mm <= 12:
            return pd.Timestamp(year=int(month.group(1)), month=mm, day=1)
        return None
    quarter = _PHILLY_QUARTER_RE.match(text)
    if quarter:
        start_month = (int(quarter.group(2)) - 1) * 3 + 1
        return pd.Timestamp(year=int(quarter.group(1)), month=start_month, day=1)
    return None


def releases_from_philly_sheet(df: pd.DataFrame) -> pd.DataFrame:
    """Wide RTDSM sheet → all-releases rows (observation, vintage date, value)."""
    empty = pd.DataFrame(columns=["date", "realtime_start", "value"])
    if df is None or df.empty or df.shape[1] < 2:
        return empty
    obs = df.iloc[:, 0].map(philly_obs_date)
    dates: list[np.ndarray] = []
    stamps: list[np.ndarray] = []
    values: list[np.ndarray] = []
    for col in df.columns[1:]:
        stamp = philly_vintage_stamp(str(col))
        if stamp is None:
            continue
        vals = pd.to_numeric(df[col], errors="coerce")
        mask = vals.notna().to_numpy() & pd.notna(obs).to_numpy()
        if not mask.any():
            continue
        dates.append(pd.to_datetime(obs).to_numpy()[mask])
        values.append(vals.to_numpy()[mask])
        stamps.append(np.full(int(mask.sum()), np.datetime64(stamp, "ns")))
    if not dates:
        return empty
    return pd.DataFrame({
        "date": np.concatenate(dates),
        "realtime_start": np.concatenate(stamps),
        "value": np.concatenate(values).astype(float),
    })


def _download_bytes(url: str, dest: Path) -> None:
    import urllib.request

    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        dest.write_bytes(resp.read())


def _philly_workbook_url(page_url: str, filename: str) -> str:
    import html as html_lib
    import urllib.request

    req = urllib.request.Request(page_url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        page = resp.read().decode("utf-8", errors="replace")
    for href in re.findall(r'href="([^"]+)"', page):
        if filename.lower() in href.lower():
            href = html_lib.unescape(href)
            if href.startswith("/"):
                return "https://www.philadelphiafed.org" + href
            return href
    raise FileNotFoundError(f"{filename} is not linked from {page_url}")


def fetch_philadelphia_vintage(
    cpi_path: Path | None = None,
    gdp_path: Path | None = None,
    download: bool = True,
) -> dict:
    """First-release YoY from Philadelphia Fed RTDSM monthly vintages.

    CPI is the index level (PCPI, same family as CPIAUCSL); YoY uses 12
    months. GDP is the real output level (ROUTPUT, same family as GDPC1);
    YoY uses 4 quarters. The value on a vintage date is the first print of
    a newly published observation, and the base is that same vintage's
    history (what a reader could have computed that day). No extra CPI+1
    or GDP+4 shift is applied on top of the vintage date.
    """
    cpi_path = Path(cpi_path) if cpi_path else PHILLY_DIR / PHILLY_CPI_FILE
    gdp_path = Path(gdp_path) if gdp_path else PHILLY_DIR / PHILLY_GDP_FILE
    if download and (not cpi_path.exists() or not gdp_path.exists()):
        if not cpi_path.exists():
            _download_bytes(_philly_workbook_url(PHILLY_CPI_PAGE, PHILLY_CPI_FILE), cpi_path)
        if not gdp_path.exists():
            _download_bytes(_philly_workbook_url(PHILLY_GDP_PAGE, PHILLY_GDP_FILE), gdp_path)
    cpi_df = pd.read_excel(cpi_path, sheet_name=0, header=0)
    gdp_df = pd.read_excel(gdp_path, sheet_name=0, header=0)
    payload = {
        "cpi_yoy_release": yoy_on_release_dates(releases_from_philly_sheet(cpi_df), 12),
        "gdp_yoy_release": yoy_on_release_dates(releases_from_philly_sheet(gdp_df), 4),
        "source": "philadelphia_fed_rtdsm",
    }
    if not _vintage_usable(payload):
        raise ValueError(
            "Philadelphia Fed vintage is too short to be a real-time clock "
            f"(CPI {len(payload['cpi_yoy_release'])} releases, "
            f"GDP {len(payload['gdp_yoy_release'])} releases)."
        )
    return payload


def fetch_fredapi_vintage(api_key: str) -> dict:
    """First-release clock via fredapi.

    Calls ``get_series_first_release`` for GDPC1 and CPIAUCSL, and
    ``get_series_all_releases`` for true ``realtime_start``. The base of each
    YoY uses the as-of vintage on that release date (the same filter as
    ``get_series_as_of_date``).
    """
    from fredapi import Fred

    fred = Fred(api_key=api_key)
    cpi_first = fred.get_series_first_release(CPI_LEVEL_SERIES)
    gdp_first = fred.get_series_first_release(GDP_LEVEL_SERIES)
    cpi_all = fred.get_series_all_releases(CPI_LEVEL_SERIES)
    gdp_all = fred.get_series_all_releases(GDP_LEVEL_SERIES)
    # One as-of call so the code path is the library method, not only a copy
    # of its filter. The full history still comes from the cached all-releases
    # frame (as-of on every release date would re-download the whole archive).
    _ = fred.get_series_as_of_date(CPI_LEVEL_SERIES, "2020-02-14")
    return {
        "cpi_yoy_release": yoy_on_release_dates(cpi_all, 12, cpi_first),
        "gdp_yoy_release": yoy_on_release_dates(gdp_all, 4, gdp_first),
        "source": "fredapi_first_release",
    }


def fetch_public_vintage(directory: Path = ALFRED_DIR) -> dict:
    """Build the clock from month-end ALFRED CSV snapshots already on disk."""
    cpi_all = load_monthend_vintage_dir(directory, CPI_LEVEL_SERIES)
    gdp_all = load_monthend_vintage_dir(directory, GDP_LEVEL_SERIES)
    if len(cpi_all) == 0 or len(gdp_all) == 0:
        raise FileNotFoundError(
            f"No month-end ALFRED snapshots in {directory}. "
            "Set FRED_API_KEY or download vintage_date files first."
        )
    return {
        "cpi_yoy_release": yoy_on_release_dates(cpi_all, 12),
        "gdp_yoy_release": yoy_on_release_dates(gdp_all, 4),
        "source": "public_monthend_vintage",
    }


def vintage_table_payload(path: Path | None = None) -> dict | None:
    path = Path(path) if path else VINTAGE_TABLE
    if not path.exists():
        return None
    df = pd.read_csv(path, parse_dates=["release_date"])
    if "cpi_yoy" not in df.columns or "gdp_yoy" not in df.columns:
        return None
    cpi = df.dropna(subset=["cpi_yoy"]).set_index("release_date")["cpi_yoy"]
    gdp = df.dropna(subset=["gdp_yoy"]).set_index("release_date")["gdp_yoy"]
    source = "vintage_release_yoy.csv"
    if "source" in df.columns and df["source"].notna().any():
        source = str(df["source"].dropna().iloc[0])
    payload = {
        "cpi_yoy_release": cpi,
        "gdp_yoy_release": gdp,
        "source": source,
    }
    if not _vintage_usable(payload):
        logger.warning(
            "Vintage table %s is too short to use (CPI %d, GDP %d).",
            path, len(cpi), len(gdp),
        )
        return None
    return payload


def write_vintage_table(payload: dict, path: Path | None = None) -> None:
    path = Path(path) if path else VINTAGE_TABLE
    cpi = payload["cpi_yoy_release"]
    gdp = payload["gdp_yoy_release"]
    idx = cpi.index.union(gdp.index).sort_values()
    df = pd.DataFrame({
        "release_date": idx,
        "cpi_yoy": cpi.reindex(idx).values,
        "gdp_yoy": gdp.reindex(idx).values,
        "source": payload.get("source") or "",
    })
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)


def load_realtime_vintage(
    api_key: str | None = None,
    cache_path: Path | None = None,
    refresh: bool = False,
) -> dict | None:
    """Load the first-release clock. Never raises — returns None on failure.

    Order: a usable pickle, the committed ``vintage_release_yoy.csv``,
    fredapi when ``FRED_API_KEY`` is set, Philadelphia Fed RTDSM monthly
    vintages, then local month-end snapshots. A table with fewer than
    ``MIN_VINTAGE_RELEASES`` points is ignored (that is how a collapsed
    "latest print" download is rejected).
    """
    cache_path = Path(cache_path) if cache_path else VINTAGE_CACHE
    if cache_path.exists() and not refresh:
        try:
            with open(cache_path, "rb") as fh:
                payload = pickle.load(fh)
            if _vintage_usable(payload):
                return payload
            logger.warning("Vintage cache at %s is too short; ignoring it.", cache_path)
        except Exception as exc:
            logger.warning("Vintage cache unreadable (%s); refetching.", exc)

    if not refresh:
        table = vintage_table_payload()
        if table is not None:
            return table

    api_key = api_key if api_key is not None else os.getenv("FRED_API_KEY", "")
    errors = []
    payload = None
    if api_key:
        try:
            payload = fetch_fredapi_vintage(api_key)
            if not _vintage_usable(payload):
                raise ValueError("fredapi vintage is too short")
        except Exception as exc:
            payload = None
            errors.append(f"fredapi: {exc}")
            logger.warning("FRED vintage API failed: %s", exc)
    if payload is None:
        try:
            payload = fetch_philadelphia_vintage()
        except Exception as exc:
            payload = None
            errors.append(f"philadelphia fed: {exc}")
            logger.warning("Philadelphia Fed vintage unavailable: %s", exc)
    if payload is None:
        try:
            payload = fetch_public_vintage()
            if not _vintage_usable(payload):
                raise ValueError("public month-end snapshots collapsed to a latest print")
        except Exception as exc:
            payload = None
            errors.append(f"public snapshots: {exc}")
            logger.warning("Public vintage snapshots unavailable: %s", exc)
    if payload is None:
        table = vintage_table_payload()
        if table is not None:
            logger.warning(
                "Real-time vintage refresh failed (%s); using the saved release table.",
                "; ".join(errors) or "no source",
            )
            return table
        logger.warning("Real-time vintage unavailable (%s).", "; ".join(errors) or "no source")
        return None
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        with open(cache_path, "wb") as fh:
            pickle.dump(payload, fh)
    except Exception as exc:
        logger.warning("Could not write vintage cache: %s", exc)
    try:
        write_vintage_table(payload)
    except Exception as exc:
        logger.warning("Could not write vintage release table: %s", exc)
    return payload


def _decision_dates(price_data: pd.DataFrame, vix: pd.Series) -> pd.DatetimeIndex:
    if price_data is not None and not price_data.empty:
        end = price_data.index.max()
    elif vix is not None and len(vix):
        end = _as_dt_index(vix).index.max()
    else:
        return pd.DatetimeIndex([])
    return pd.date_range(start="2005-06-01", end=end, freq="MS")


def _snapshot(records, vix, t10y, t2y, cpi_yoy, gdp, spy_daily, vix_defensive: float) -> dict:
    current = {
        "regime": records[-1]["regime"] if records else "goldilocks",
        "vix": float(vix.iloc[-1]) if vix is not None and len(vix) else 0.0,
        "yield_curve": 0.0,
        "cpi_yoy": float(cpi_yoy.iloc[-1]) if cpi_yoy is not None and len(cpi_yoy) else 0.0,
        "gdp": float(gdp.iloc[-1]) if gdp is not None and len(gdp) else 0.0,
        "spy_momentum": float(spy_daily.iloc[-1]) if spy_daily is not None and len(spy_daily) else 0.0,
    }
    if (
        t10y is not None and t2y is not None and len(t10y) and len(t2y)
    ):
        current["yield_curve"] = float(t10y.iloc[-1] - t2y.iloc[-1])
    # Latest VIX print is knowable today. It can force deflation on the live
    # label without using any later print. Historical month rows stay monthly.
    if current["vix"] > vix_defensive:
        current["regime"] = "deflation"
        current["vix_live_override"] = True
    else:
        current["vix_live_override"] = False

    confidence = 50.0
    regime = current["regime"]
    if regime == "goldilocks":
        if current["gdp"] > 2.0:
            confidence += 15
        if current["spy_momentum"] > 0.10:
            confidence += 15
        if current["vix"] < 18:
            confidence += 10
        if current["cpi_yoy"] < 3.0:
            confidence += 10
    elif regime == "reflation":
        if current["gdp"] > 2.0:
            confidence += 15
        if current["cpi_yoy"] > 3.5:
            confidence += 15
        if current["spy_momentum"] > 0:
            confidence += 10
    elif regime == "stagflation":
        if current["gdp"] < 1.0:
            confidence += 15
        if current["cpi_yoy"] > 4.0:
            confidence += 15
        if current["vix"] > 25:
            confidence += 10
    elif regime == "deflation":
        if current["gdp"] < 1.0:
            confidence += 15
        if current["vix"] > 25:
            confidence += 15
        if current["yield_curve"] < 0:
            confidence += 10
    current["confidence"] = min(100.0, confidence)
    return current


def classify_regimes(
    macro: dict,
    price_data: pd.DataFrame,
    mode: str = MODE_TARGETED,
    apply_lag: bool | None = None,
    use_realtime_vintage: bool = False,
    vintage: dict | None = None,
    vix_defensive: float | None = None,
):
    """Classify each month-start.

    Parameters
    ----------
    mode
        ``targeted`` (default), ``lookahead``, ``unlagged``, ``auditor``,
        or ``vintage``.
    apply_lag
        Legacy switch. ``False`` selects ``unlagged``. ``True`` selects
        ``targeted`` (publication lag, no month-end look-ahead). Ignored
        when ``mode`` is passed explicitly as something other than the default
        together with a non-None ``apply_lag`` of False — False always wins
        and means unlagged, matching older call sites.
    use_realtime_vintage
        When True, try the first-release clock. On failure, return the
        targeted regimes and ``info['vintage_fallback']=True``.
    vintage
        Optional prebuilt clock ``{'cpi_yoy_release', 'gdp_yoy_release'}``.
        Tests inject this so they do not touch the network.
    """
    from config.regime_rules import REGIME_VIX_DEFENSIVE

    if vix_defensive is None:
        vix_defensive = REGIME_VIX_DEFENSIVE

    if apply_lag is False and mode == MODE_TARGETED:
        mode = MODE_UNLAGGED
    if use_realtime_vintage and mode == MODE_TARGETED:
        mode = MODE_VINTAGE

    info = {
        "mode": mode,
        "cpi_lag_months": CPI_RELEASE_LAG_M,
        "gdp_lag_months": GDP_RELEASE_LAG_M,
        "vintage_fallback": False,
        "vintage_source": None,
        "vintage_error": None,
    }

    if mode == MODE_AUDITOR:
        history, current, base_info = classify_regimes(
            macro, price_data, mode=MODE_LOOKAHEAD, vix_defensive=vix_defensive,
        )
        history = history.copy()
        history["regime"] = history["regime"].shift(1).bfill()
        base_info["mode"] = MODE_AUDITOR
        base_info["auditor_note"] = (
            "Extra month on the old month-stamped regime. Overly conservative. "
            "Not the production default."
        )
        return history, current, base_info

    if mode == MODE_VINTAGE:
        payload = vintage
        if payload is None:
            payload = load_realtime_vintage()
        if not payload or payload.get("cpi_yoy_release") is None or len(payload.get("cpi_yoy_release", [])) == 0:
            history, current, fb = classify_regimes(
                macro, price_data, mode=MODE_TARGETED, vix_defensive=vix_defensive,
            )
            fb["vintage_fallback"] = True
            fb["vintage_error"] = "first-release vintage unavailable; used targeted CPI+1/GDP+4"
            fb["requested_mode"] = MODE_VINTAGE
            return history, current, fb
        info["vintage_source"] = payload.get("source")
        cpi_monthly = _as_dt_index(payload["cpi_yoy_release"]).dropna()
        gdp_monthly = _as_dt_index(payload["gdp_yoy_release"]).dropna()
        cpi_yoy = cpi_monthly
        gdp = gdp_monthly
        same_month = False
        apply_pub = False  # release dates already encode timing; do not add +1/+4
    else:
        same_month = mode in (MODE_UNLAGGED, MODE_LOOKAHEAD)
        apply_pub = mode != MODE_UNLAGGED
        cpi = macro.get("cpi", pd.Series(dtype=float))
        gdp_raw = macro.get("gdp", pd.Series(dtype=float))
        cpi_yoy, gdp, cpi_monthly, gdp_monthly = publication_lagged_macro(
            cpi, gdp_raw, apply_lag=apply_pub,
        )

    vix = macro.get("vix", pd.Series(dtype=float))
    spy = pd.Series(dtype=float)
    if price_data is not None and not price_data.empty and "SPY" in price_data.columns:
        spy = price_data["SPY"]
    vix_m, spy_m = market_signals(vix, spy, same_month=same_month)

    spy_daily = pd.Series(dtype=float)
    if len(spy):
        spy_daily = (_as_dt_index(spy) / _as_dt_index(spy).shift(252) - 1.0).dropna()

    dates = _decision_dates(price_data if price_data is not None else pd.DataFrame(), vix)
    records = []
    for date in dates:
        records.append({
            "date": pd.Timestamp(date),
            "regime": _classify_one(date, gdp_monthly, spy_m, cpi_monthly, vix_m, vix_defensive),
        })
    history = pd.DataFrame(records, columns=["date", "regime"])
    current = _snapshot(
        records,
        _as_dt_index(vix) if vix is not None and len(vix) else vix,
        macro.get("t10y"),
        macro.get("t2y"),
        cpi_yoy,
        gdp,
        spy_daily,
        vix_defensive,
    )
    info.update({
        "cpi_yoy": cpi_yoy,
        "cpi_monthly": cpi_monthly,
        "gdp_monthly": gdp_monthly,
        "vix_monthly": vix_m,
        "spy_mom_monthly": spy_m,
        "same_month_market": same_month,
        "publication_lag": apply_pub if mode != MODE_VINTAGE else False,
    })
    return history, current, info
