#!/usr/bin/env python3
"""Fetch the latest quote for each ETF in DATA.tickers and write prices.json.

Tickers are parsed out of index.html so the script never falls out of sync
with the dashboard's own list.

PRIMARY source: yfinance (https://pypi.org/project/yfinance/). It handles
Yahoo's cookie/crumb session flow internally, which is what lets it get
through Yahoo's IP-level rate limits on shared CI runners; those same IPs
will 429 a naive HTTP request to the v8 chart endpoint.

FALLBACK source: raw Yahoo v8 chart endpoint. Cheap insurance; usually only
useful when running locally.

Run by .github/workflows/refresh-prices.yml on a weekday-evening cron and on
manual workflow_dispatch.
"""

from __future__ import annotations

import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
INDEX_HTML = REPO_ROOT / "index.html"
PRICES_JSON = REPO_ROOT / "prices.json"
HISTORY_JSON = REPO_ROOT / "history.json"

# How far back to pull daily closes each run. Only missing dates get appended,
# so a generous window simply backfills any gap left by skipped/failed runs
# (e.g. if the workflow was paused for a few weeks) without duplicating data.
HISTORY_PERIOD = "3mo"

YAHOO_URL = (
    "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
    "?range=1d&interval=1d"
)

YAHOO_HISTORY_URL = (
    "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
    "?range={range}&interval=1d"
)

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


def parse_tickers(html: str) -> list[str]:
    """Extract the keys of the `tickers: { ... }` block in index.html."""
    block = re.search(r"tickers:\s*\{(.+?)\n\s*\},", html, re.S)
    if not block:
        raise RuntimeError("Couldn't locate `tickers: { ... }` block in index.html")
    return re.findall(r'"([A-Z0-9.\-]+)"\s*:', block.group(1))


def fetch_quote_yfinance(ticker: str) -> dict:
    """Return {'price': float, 'asOf': iso8601-string} via the yfinance package.

    yfinance manages a full session with Yahoo (cookies + crumb token) and
    usually succeeds where naive HTTP doesn't.
    """
    import yfinance as yf  # local import: workflow installs this before running

    t = yf.Ticker(ticker)

    # Pull the last 5 trading days so we always have at least one row even on
    # weekends/holidays. .history() is reliable and doesn't require crumbs.
    hist = t.history(period="5d", interval="1d", auto_adjust=False)
    if hist is None or hist.empty:
        raise RuntimeError(f"{ticker}: yfinance returned empty history")

    last = hist.iloc[-1]
    close = last.get("Close")
    if close is None or (isinstance(close, float) and (close != close)):  # NaN check
        raise RuntimeError(f"{ticker}: no Close in yfinance history row")

    # The DataFrame index is a tz-aware Timestamp. Normalize to UTC ISO string.
    idx = hist.index[-1]
    try:
        as_of = idx.tz_convert("UTC").isoformat().replace("+00:00", "Z")
    except Exception:
        as_of = idx.isoformat()

    return {"price": float(close), "asOf": as_of}


def fetch_quote_yahoo_raw(ticker: str) -> dict:
    """Return {'price': float, 'asOf': iso8601-string} via raw Yahoo v8.

    Used as a fallback only. Usually 429s on GitHub-runner IPs but works
    fine locally.
    """
    req = urllib.request.Request(
        YAHOO_URL.format(ticker=urllib.parse.quote(ticker)),
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        payload = json.load(resp)

    result = payload.get("chart", {}).get("result")
    if not result:
        raise RuntimeError(f"{ticker}: no chart.result in Yahoo response")
    meta = result[0].get("meta", {})
    price = meta.get("regularMarketPrice")
    ts = meta.get("regularMarketTime")
    if price is None:
        raise RuntimeError(f"{ticker}: no regularMarketPrice in meta")
    as_of = (
        datetime.fromtimestamp(ts, tz=timezone.utc).isoformat().replace("+00:00", "Z")
        if ts is not None
        else None
    )
    return {"price": float(price), "asOf": as_of}


def fetch_quote(ticker: str) -> tuple[dict, str]:
    """Try yfinance first, then raw Yahoo. Returns (quote, source_name)."""
    try:
        return fetch_quote_yfinance(ticker), "yfinance"
    except (urllib.error.URLError, RuntimeError, ValueError, ImportError) as yf_exc:
        print(f"  {ticker}: yfinance failed ({yf_exc}); trying raw yahoo…")
        try:
            return fetch_quote_yahoo_raw(ticker), "yahoo-raw"
        except (urllib.error.URLError, RuntimeError, ValueError) as yh_exc:
            raise RuntimeError(
                f"both sources failed: yfinance: {yf_exc}; yahoo-raw: {yh_exc}"
            ) from yh_exc


def fetch_history_yfinance(ticker: str, period: str = HISTORY_PERIOD) -> dict[str, float]:
    """Return {YYYY-MM-DD: close} for the last `period` of daily closes via yfinance."""
    import yfinance as yf  # local import: workflow installs this before running

    t = yf.Ticker(ticker)
    hist = t.history(period=period, interval="1d", auto_adjust=False)
    if hist is None or hist.empty:
        raise RuntimeError(f"{ticker}: yfinance returned empty history")

    out: dict[str, float] = {}
    for idx, row in hist.iterrows():
        close = row.get("Close")
        if close is None or (isinstance(close, float) and close != close):  # NaN
            continue
        out[idx.strftime("%Y-%m-%d")] = round(float(close), 4)
    if not out:
        raise RuntimeError(f"{ticker}: no usable closes in yfinance history")
    return out


def fetch_history_yahoo_raw(ticker: str, period: str = HISTORY_PERIOD) -> dict[str, float]:
    """Return {YYYY-MM-DD: close} via the raw Yahoo v8 chart endpoint (fallback)."""
    req = urllib.request.Request(
        YAHOO_HISTORY_URL.format(ticker=urllib.parse.quote(ticker), range=period),
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        payload = json.load(resp)

    result = payload.get("chart", {}).get("result")
    if not result:
        raise RuntimeError(f"{ticker}: no chart.result in Yahoo history response")
    res = result[0]
    timestamps = res.get("timestamp") or []
    closes = (res.get("indicators", {}).get("quote") or [{}])[0].get("close") or []
    out: dict[str, float] = {}
    for ts, close in zip(timestamps, closes):
        if close is None:
            continue
        d = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
        out[d] = round(float(close), 4)
    if not out:
        raise RuntimeError(f"{ticker}: no usable closes in Yahoo history")
    return out


def fetch_history(ticker: str) -> dict[str, float]:
    """Try yfinance first, then raw Yahoo, for a ticker's recent daily closes."""
    try:
        return fetch_history_yfinance(ticker)
    except (urllib.error.URLError, RuntimeError, ValueError, ImportError) as yf_exc:
        print(f"  {ticker}: yfinance history failed ({yf_exc}); trying raw yahoo…")
        return fetch_history_yahoo_raw(ticker)


def update_history(tickers: list[str]) -> bool:
    """Merge recent daily closes into history.json (the chart's daily series).

    history.json holds {dates: [...], prices: {ticker: [aligned closes]}}. We load
    it, overlay any newly fetched closes (which backfills gaps and adds new days),
    then rewrite aligned arrays. Existing data is never lost: only missing/newer
    dates are added. Returns True if the file was written.
    """
    existing_dates: list[str] = []
    existing: dict[str, list] = {}
    if HISTORY_JSON.exists():
        h = json.loads(HISTORY_JSON.read_text(encoding="utf-8"))
        existing_dates = h.get("dates", [])
        existing = h.get("prices", {})

    # date -> {ticker: close}
    dmap: dict[str, dict[str, float]] = {d: {} for d in existing_dates}
    for t, arr in existing.items():
        for i, d in enumerate(existing_dates):
            if i < len(arr) and arr[i] is not None:
                dmap[d][t] = arr[i]

    fetched_any = False
    for t in tickers:
        try:
            recent = fetch_history(t)
            for d, px in recent.items():
                dmap.setdefault(d, {})[t] = px
            fetched_any = True
            print(f"  history {t}: merged {len(recent)} daily closes")
        except (urllib.error.URLError, RuntimeError, ValueError, ImportError) as exc:
            print(f"  history {t}: ERROR: {exc}", file=sys.stderr)
        time.sleep(1.0)

    if not fetched_any and not existing_dates:
        print("No history fetched and no existing history; skipping history.json")
        return False

    all_dates = sorted(dmap.keys())
    all_tickers = sorted(set(list(existing.keys()) + list(tickers)))
    out_prices: dict[str, list] = {t: [] for t in all_tickers}
    last: dict[str, float | None] = {t: None for t in all_tickers}
    for d in all_dates:
        for t in all_tickers:
            v = dmap[d].get(t)
            if v is None:
                v = last[t]  # carry forward across any missing cell
            else:
                last[t] = v
            out_prices[t].append(v)

    payload = {
        "generatedAt": datetime.now(tz=timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z"),
        "dates": all_dates,
        "prices": out_prices,
    }
    HISTORY_JSON.write_text(
        json.dumps(payload, separators=(",", ":")) + "\n", encoding="utf-8"
    )
    print(
        f"Wrote {HISTORY_JSON.relative_to(REPO_ROOT)} "
        f"({len(all_dates)} dates, last {all_dates[-1]})"
    )
    return True


def main() -> int:
    html = INDEX_HTML.read_text(encoding="utf-8")
    tickers = parse_tickers(html)
    if not tickers:
        print("No tickers parsed from index.html", file=sys.stderr)
        return 1
    print(f"Refreshing prices for: {', '.join(tickers)}")

    prices: dict[str, dict] = {}
    sources: dict[str, str] = {}
    errors: list[str] = []
    for t in tickers:
        try:
            quote, source = fetch_quote(t)
            prices[t] = quote
            sources[t] = source
            print(f"  {t}: {quote['price']} via {source} (as of {quote['asOf']})")
        except (urllib.error.URLError, RuntimeError, ValueError) as exc:
            errors.append(f"{t}: {exc}")
            print(f"  {t}: ERROR: {exc}", file=sys.stderr)
        # Be polite to upstream.
        time.sleep(1.0)

    if not prices:
        # Bail without writing; this keeps the last good prices.json in place.
        print("No prices fetched; refusing to overwrite prices.json", file=sys.stderr)
        return 1

    payload = {
        "generatedAt": datetime.now(tz=timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z"),
        "sources": sources,
        "prices": prices,
        "errors": errors,
    }
    PRICES_JSON.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {PRICES_JSON.relative_to(REPO_ROOT)} ({len(prices)} tickers)")

    # Maintain the daily-series history that the chart actually draws. This is
    # what fills in each day so the line stays detailed instead of running
    # straight from the last baked date to today. A failure here shouldn't fail
    # the whole run; prices.json is still good.
    try:
        update_history(tickers)
    except Exception as exc:  # noqa: BLE001 - best-effort, never fail the run
        print(f"history update failed (non-fatal): {exc}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
