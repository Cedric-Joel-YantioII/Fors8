"""
Real-time financial market data fetcher using yfinance.

Provides oil prices, defense stocks, GCC markets, shipping rates,
and safe-haven indicators relevant to Iran conflict analysis.
"""

import time
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Module-level cache
_cache: Dict[str, Any] = {}
_cache_timestamp: float = 0.0
_CACHE_TTL_SECONDS = 300  # 5 minutes


class MarketDataFetcher:
    """Fetches real-time financial market data relevant to the Iran conflict."""

    def fetch_all(self) -> dict:
        """Returns a dict with all market data, cached for 5 minutes."""
        global _cache, _cache_timestamp

        now = time.time()
        if _cache and (now - _cache_timestamp) < _CACHE_TTL_SECONDS:
            return _cache

        result = {}
        for key, method in [
            ("oil", self.fetch_oil_prices),
            ("defense_stocks", self.fetch_defense_stocks),
            ("gcc", self.fetch_gcc_markets),
            ("shipping", self.fetch_shipping_rates),
            ("safe_havens", self.fetch_gold_and_safe_havens),
        ]:
            try:
                result[key] = method()
            except Exception as e:
                logger.warning("MarketDataFetcher.%s failed: %s", key, e)
                result[key] = {"error": str(e)}

        _cache = result
        _cache_timestamp = time.time()
        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _safe_download(tickers: str, period: str = "1mo") -> Optional[Any]:
        """Download ticker data via yfinance, returning None on failure."""
        try:
            import yfinance as yf

            df = yf.download(tickers, period=period, progress=False, threads=False)
            if df is None or df.empty:
                return None
            return df
        except Exception as e:
            logger.warning("yfinance download failed for %s: %s", tickers, e)
            return None

    @staticmethod
    def _pct_change(current: float, previous: float) -> Optional[float]:
        if previous and previous != 0:
            return round(((current - previous) / previous) * 100, 2)
        return None

    @staticmethod
    def _extract_price_and_changes(df, ticker: str) -> dict:
        """Extract current price, 1-week change, 1-month change from a DataFrame."""
        try:
            # Handle both single-ticker and multi-ticker DataFrames
            if isinstance(df.columns, __import__("pandas").MultiIndex):
                close = df["Close"][ticker].dropna()
            else:
                close = df["Close"].dropna()

            if close.empty:
                return {"error": "no data"}

            current = round(float(close.iloc[-1]), 2)
            result: Dict[str, Any] = {"current": current}

            # 1-week change (approx 5 trading days)
            if len(close) >= 5:
                week_ago = round(float(close.iloc[-5]), 2)
                result["1w_change_pct"] = MarketDataFetcher._pct_change(current, week_ago)
            # 1-month change (first value in the period)
            if len(close) >= 2:
                month_ago = round(float(close.iloc[0]), 2)
                result["1mo_change_pct"] = MarketDataFetcher._pct_change(current, month_ago)

            return result
        except Exception as e:
            return {"error": str(e)}

    # ------------------------------------------------------------------
    # Public fetchers
    # ------------------------------------------------------------------

    def fetch_oil_prices(self) -> dict:
        """Brent crude (BZ=F), WTI (CL=F) — current price, 1-week change, 1-month change."""
        tickers = "BZ=F CL=F"
        df = self._safe_download(tickers)
        if df is None:
            return {"error": "yfinance returned no data for oil tickers"}

        brent = self._extract_price_and_changes(df, "BZ=F")
        wti = self._extract_price_and_changes(df, "CL=F")

        return {
            "brent_current": brent.get("current"),
            "brent_1w_change": brent.get("1w_change_pct"),
            "brent_1mo_change": brent.get("1mo_change_pct"),
            "wti_current": wti.get("current"),
            "wti_1w_change": wti.get("1w_change_pct"),
            "wti_1mo_change": wti.get("1mo_change_pct"),
        }

    def fetch_defense_stocks(self) -> dict:
        """Key defense contractors: LMT, RTX, NOC, GD, BA — current price + % change."""
        symbols = ["LMT", "RTX", "NOC", "GD", "BA"]
        tickers = " ".join(symbols)
        df = self._safe_download(tickers)
        if df is None:
            return {"error": "yfinance returned no data for defense stocks"}

        result = {}
        for sym in symbols:
            data = self._extract_price_and_changes(df, sym)
            result[sym] = {
                "price": data.get("current"),
                "1w_change_pct": data.get("1w_change_pct"),
                "1mo_change_pct": data.get("1mo_change_pct"),
            }
        return result

    def fetch_gcc_markets(self) -> dict:
        """GCC stock indices and key companies."""
        symbols_map = {
            "^TASI": "Saudi Tadawul",
            "DFMGI.AE": "Dubai DFM",
            "ADI.AE": "Abu Dhabi ADX",
            "GNRI.QA": "Qatar QSE",
            "BK.KW": "Kuwait BK",
            "2222.SR": "Saudi Aramco",
            "ADNOCDIST.AE": "ADNOC Distribution",
            "ENBD.AE": "Emirates NBD",
        }
        tickers = " ".join(symbols_map.keys())
        df = self._safe_download(tickers)
        if df is None:
            return {"error": "yfinance returned no data for GCC tickers"}

        entries = {}
        up_count = 0
        down_count = 0
        for sym, label in symbols_map.items():
            data = self._extract_price_and_changes(df, sym)
            entries[sym] = {
                "label": label,
                "price": data.get("current"),
                "1w_change_pct": data.get("1w_change_pct"),
                "1mo_change_pct": data.get("1mo_change_pct"),
            }
            wk = data.get("1w_change_pct")
            if wk is not None:
                if wk >= 0:
                    up_count += 1
                else:
                    down_count += 1

        # Build a one-line summary for the LLM prompt
        if up_count + down_count > 0:
            if up_count > down_count:
                summary = f"GCC markets mostly up ({up_count}/{up_count+down_count} tickers positive this week)"
            elif down_count > up_count:
                summary = f"GCC markets mostly down ({down_count}/{up_count+down_count} tickers negative this week)"
            else:
                summary = "GCC markets mixed this week"
        else:
            summary = "GCC market data unavailable"

        return {"tickers": entries, "summary": summary}

    def fetch_shipping_rates(self) -> dict:
        """Baltic Dry Index proxy via shipping ETFs (BDRY, SFL)."""
        symbols = ["BDRY", "SFL"]
        tickers = " ".join(symbols)
        df = self._safe_download(tickers)
        if df is None:
            return {"error": "yfinance returned no data for shipping tickers"}

        result = {}
        for sym in symbols:
            data = self._extract_price_and_changes(df, sym)
            result[sym] = {
                "price": data.get("current"),
                "1w_change_pct": data.get("1w_change_pct"),
                "1mo_change_pct": data.get("1mo_change_pct"),
            }
        return result

    def fetch_gold_and_safe_havens(self) -> dict:
        """Gold (GC=F), USD Index (DX-Y.NYB), VIX (^VIX), 10Y Treasury (^TNX)."""
        symbols_map = {
            "GC=F": "gold",
            "DX-Y.NYB": "usd_index",
            "^VIX": "vix",
            "^TNX": "treasury_10y",
        }
        tickers = " ".join(symbols_map.keys())
        df = self._safe_download(tickers)
        if df is None:
            return {"error": "yfinance returned no data for safe-haven tickers"}

        result = {}
        for sym, key in symbols_map.items():
            data = self._extract_price_and_changes(df, sym)
            result[f"{key}_current"] = data.get("current")
            result[f"{key}_1w_change"] = data.get("1w_change_pct")
            result[f"{key}_1mo_change"] = data.get("1mo_change_pct")

        return result
