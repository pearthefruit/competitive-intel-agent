"""Stock market data via yfinance — price, market cap, valuation metrics, financial statements."""

import yfinance as yf
import pandas as pd

# Well-known companies and their Yahoo Finance tickers (fast-path cache).
# yf.Search is used as a fallback for anything not here.
KNOWN_TICKERS = {
    # --- US-listed (ADR or direct) ---
    "samsung": "005930.KS",
    "samsung electronics": "005930.KS",
    "toyota": "TM",
    "toyota motor": "TM",
    "sony": "SONY",
    "sony group": "SONY",
    "alibaba": "BABA",
    "tencent": "TCEHY",
    "tsmc": "TSM",
    "taiwan semiconductor": "TSM",
    "novartis": "NVS",
    "roche": "RHHBY",
    "shell": "SHEL",
    "bp": "BP",
    "hsbc": "HSBC",
    "unilever": "UL",
    "astrazeneca": "AZN",
    "sap": "SAP",
    "asml": "ASML",
    "novo nordisk": "NVO",
    "baidu": "BIDU",
    "jd.com": "JD",
    "pinduoduo": "PDD",
    "pdd holdings": "PDD",
    "infosys": "INFY",
    "wipro": "WIT",
    "honda": "HMC",
    "shopify": "SHOP",
    "spotify": "SPOT",
    "diageo": "DEO",
    "rio tinto": "RIO",
    "bhp": "BHP",
    "ab inbev": "BUD",
    "anheuser-busch": "BUD",
    "stellantis": "STLA",
    "ferrari": "RACE",
    "philips": "PHG",
    "barclays": "BCS",
    "deutsche bank": "DB",
    "hdfc bank": "HDB",
    "icici bank": "IBN",
    "mitsubishi ufj": "MUFG",
    # --- European primary listings ---
    "nestle": "NESN.SW",
    "nestlé": "NESN.SW",
    "danone": "BN.PA",
    "lvmh": "MC.PA",
    "loreal": "OR.PA",
    "l'oreal": "OR.PA",
    "l'oréal": "OR.PA",
    "totalenergies": "TTE.PA",
    "total": "TTE.PA",
    "sanofi": "SAN.PA",
    "hermes": "RMS.PA",
    "hermès": "RMS.PA",
    "kering": "KER.PA",
    "schneider electric": "SU.PA",
    "schneider": "SU.PA",
    "airbus": "AIR.PA",
    "bnp paribas": "BNP.PA",
    "siemens": "SIE.DE",
    "allianz": "ALV.DE",
    "bayer": "BAYN.DE",
    "basf": "BAS.DE",
    "adidas": "ADS.DE",
    "volkswagen": "VOW3.DE",
    "bmw": "BMW.DE",
    "mercedes": "MBG.DE",
    "mercedes-benz": "MBG.DE",
    "heineken": "HEIA.AS",
    "glencore": "GLEN.L",
    # --- Asian primary listings ---
    "reliance": "RELIANCE.NS",
    "tata": "TCS.NS",
    "tata consultancy": "TCS.NS",
    "softbank": "9984.T",
    "nintendo": "7974.T",
    "mitsubishi": "8058.T",
    "byd": "1211.HK",
    "xiaomi": "1810.HK",
    "hyundai": "005380.KS",
    "sk hynix": "000660.KS",
}

# Session cache for dynamic lookups (avoid repeated API calls)
_search_cache = {}


def search_ticker(company_name):
    """Search Yahoo Finance globally for a company ticker.

    Uses yf.Search to find tickers on any exchange worldwide.
    Results are cached for the session to avoid repeated API calls.
    Returns ticker string or None.
    """
    name_lower = company_name.strip().lower()
    if name_lower in _search_cache:
        return _search_cache[name_lower]

    try:
        results = yf.Search(company_name)
        quotes = results.quotes if hasattr(results, "quotes") else []
        for quote in quotes:
            if quote.get("quoteType") == "EQUITY" and quote.get("isYahooFinance"):
                ticker = quote["symbol"]
                print(f"[stock] Yahoo Finance search: {company_name} → {ticker} ({quote.get('exchDisp', '')}, {quote.get('longname', '')})")
                _search_cache[name_lower] = ticker
                return ticker
    except Exception as e:
        print(f"[stock] Yahoo Finance search failed for '{company_name}': {e}")

    _search_cache[name_lower] = None
    return None


def lookup_ticker(company_name):
    """Try to find a Yahoo Finance ticker for a company name.

    Three-tier lookup:
    1. Known tickers map (instant, no API call)
    2. Direct ticker validation (for short names that might be tickers)
    3. Yahoo Finance search (global, finds any exchange)

    Returns ticker string or None.
    """
    name_lower = company_name.strip().lower()

    # Tier 1: Check known tickers (exact match)
    if name_lower in KNOWN_TICKERS:
        return KNOWN_TICKERS[name_lower]

    # Tier 1b: Partial matches (e.g., "Samsung" matches "samsung electronics")
    for key, ticker in KNOWN_TICKERS.items():
        if name_lower in key or key in name_lower:
            return ticker

    # Tier 2: Try the company name as a ticker directly (works for many US stocks)
    test_ticker = company_name.strip().upper().replace(" ", "")
    if len(test_ticker) <= 5:
        try:
            stock = yf.Ticker(test_ticker)
            info = stock.info
            if info and (info.get("currentPrice") or info.get("regularMarketPrice")):
                return test_ticker
        except Exception:
            pass

    # Tier 3: Dynamic Yahoo Finance search (global — any exchange)
    return search_ticker(company_name)


def get_stock_data(ticker):
    """Fetch current market data for a ticker symbol.

    Returns dict with price, market_cap, pe_ratio, etc. or None on failure.
    """
    try:
        stock = yf.Ticker(ticker)
        info = stock.info

        if not info or info.get("trailingPegRatio") is None and info.get("currentPrice") is None:
            # yfinance sometimes returns empty info for invalid tickers
            # Try fast_info as fallback
            try:
                fi = stock.fast_info
                price = getattr(fi, "last_price", None)
                market_cap = getattr(fi, "market_cap", None)
                if price or market_cap:
                    return {
                        "price": price,
                        "market_cap": market_cap,
                        "currency": getattr(fi, "currency", "USD"),
                        "exchange": getattr(fi, "exchange", ""),
                        "fifty_two_week_high": getattr(fi, "year_high", None),
                        "fifty_two_week_low": getattr(fi, "year_low", None),
                        "source": "Yahoo Finance",
                    }
            except Exception:
                pass
            return None

        data = {
            "price": info.get("currentPrice") or info.get("regularMarketPrice"),
            "market_cap": info.get("marketCap"),
            "currency": info.get("currency", "USD"),
            "exchange": info.get("exchange", ""),
            "exchange_name": info.get("exchangeTimezoneName", ""),
            "pe_ratio": info.get("trailingPE"),
            "forward_pe": info.get("forwardPE"),
            "price_to_book": info.get("priceToBook"),
            "ev_to_ebitda": info.get("enterpriseToEbitda"),
            "enterprise_value": info.get("enterpriseValue"),
            "dividend_yield": info.get("dividendYield"),
            "beta": info.get("beta"),
            "fifty_two_week_high": info.get("fiftyTwoWeekHigh"),
            "fifty_two_week_low": info.get("fiftyTwoWeekLow"),
            "avg_volume": info.get("averageVolume"),
            "sector": info.get("sector"),
            "industry": info.get("industry"),
            "source": "Yahoo Finance",
        }

        # Only return if we got meaningful data
        if data["price"] or data["market_cap"]:
            return data

        return None

    except Exception as e:
        print(f"[stock] Error fetching data for {ticker}: {e}")
        return None


def format_stock_data_for_prompt(stock_data):
    """Format stock market data into a string for the LLM prompt."""
    if not stock_data:
        return ""

    lines = ["\n### Market Data (Live)"]

    price = stock_data.get("price")
    currency = stock_data.get("currency", "USD")
    if price:
        lines.append(f"  Stock Price: {currency} {price:,.2f}")

    market_cap = stock_data.get("market_cap")
    if market_cap:
        if market_cap >= 1_000_000_000_000:
            lines.append(f"  Market Cap: {currency} {market_cap / 1_000_000_000_000:.2f}T")
        elif market_cap >= 1_000_000_000:
            lines.append(f"  Market Cap: {currency} {market_cap / 1_000_000_000:.2f}B")
        elif market_cap >= 1_000_000:
            lines.append(f"  Market Cap: {currency} {market_cap / 1_000_000:.1f}M")
        else:
            lines.append(f"  Market Cap: {currency} {market_cap:,.0f}")

    ev = stock_data.get("enterprise_value")
    if ev:
        if ev >= 1_000_000_000_000:
            lines.append(f"  Enterprise Value: {currency} {ev / 1_000_000_000_000:.2f}T")
        elif ev >= 1_000_000_000:
            lines.append(f"  Enterprise Value: {currency} {ev / 1_000_000_000:.2f}B")

    pe = stock_data.get("pe_ratio")
    if pe:
        lines.append(f"  P/E Ratio (trailing): {pe:.1f}")

    fpe = stock_data.get("forward_pe")
    if fpe:
        lines.append(f"  P/E Ratio (forward): {fpe:.1f}")

    pb = stock_data.get("price_to_book")
    if pb:
        lines.append(f"  Price/Book: {pb:.2f}")

    ev_ebitda = stock_data.get("ev_to_ebitda")
    if ev_ebitda:
        lines.append(f"  EV/EBITDA: {ev_ebitda:.1f}")

    dy = stock_data.get("dividend_yield")
    if dy:
        # yfinance dividendYield can be a fraction (<1) or already a percentage (>1)
        pct = dy if dy > 1 else dy * 100
        lines.append(f"  Dividend Yield: {pct:.2f}%")

    beta = stock_data.get("beta")
    if beta:
        lines.append(f"  Beta: {beta:.2f}")

    high = stock_data.get("fifty_two_week_high")
    low = stock_data.get("fifty_two_week_low")
    if high and low:
        lines.append(f"  52-Week Range: {currency} {low:,.2f} — {currency} {high:,.2f}")

    sector = stock_data.get("sector")
    industry = stock_data.get("industry")
    if sector and industry:
        lines.append(f"  Sector: {sector} / {industry}")

    exchange = stock_data.get("exchange_name") or stock_data.get("exchange")
    if exchange:
        lines.append(f"  Exchange: {exchange}")

    lines.append(f"  Source: Yahoo Finance (live)")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Extended financials — statements, analyst data, news
# ---------------------------------------------------------------------------

def _fmt_num(val, currency=""):
    """Format a number for display (T/B/M)."""
    if val is None:
        return "—"
    try:
        if pd.isna(val):
            return "—"
    except (TypeError, ValueError):
        pass
    prefix = f"{currency} " if currency else ""
    neg = val < 0
    abs_val = abs(val)
    if abs_val >= 1_000_000_000_000:
        s = f"{prefix}{abs_val / 1_000_000_000_000:.1f}T"
    elif abs_val >= 1_000_000_000:
        s = f"{prefix}{abs_val / 1_000_000_000:.1f}B"
    elif abs_val >= 1_000_000:
        s = f"{prefix}{abs_val / 1_000_000:.0f}M"
    else:
        s = f"{prefix}{abs_val:,.0f}"
    return f"-{s}" if neg else s


def _extract_row(df, keywords):
    """Find a row in a DataFrame by matching keywords against the index (case/space insensitive)."""
    for kw in keywords:
        kw_clean = kw.lower().replace(" ", "")
        for idx in df.index:
            if kw_clean == str(idx).lower().replace(" ", ""):
                return df.loc[idx]
    # Fallback: partial match
    for kw in keywords:
        kw_clean = kw.lower().replace(" ", "")
        for idx in df.index:
            if kw_clean in str(idx).lower().replace(" ", ""):
                return df.loc[idx]
    return None


def _yoy_growth(row, n_years):
    """Calculate YoY growth rates from a row of annual values (newest first)."""
    growths = []
    for i in range(n_years):
        if i >= len(row) - 1:
            growths.append("—")
            continue
        curr, prev = row.iloc[i], row.iloc[i + 1]
        try:
            if pd.isna(curr) or pd.isna(prev) or prev == 0:
                growths.append("—")
            else:
                growths.append(f"{(curr - prev) / abs(prev) * 100:+.1f}%")
        except (TypeError, ValueError):
            growths.append("—")
    return growths


def get_extended_financials(ticker):
    """Fetch financial statements, analyst estimates, upgrades, and news for a ticker.

    Returns dict with available data, or None if nothing could be fetched.
    """
    stock = yf.Ticker(ticker)
    data = {}

    # Annual income statement (5 years)
    try:
        inc = stock.income_stmt
        if inc is not None and not inc.empty:
            data["income_stmt"] = inc
            print(f"[stock] Got annual income statement: {inc.shape[1]} years")
    except Exception:
        pass

    # Annual balance sheet
    try:
        bs = stock.balance_sheet
        if bs is not None and not bs.empty:
            data["balance_sheet"] = bs
            print(f"[stock] Got balance sheet: {bs.shape[1]} years")
    except Exception:
        pass

    # Annual cash flow
    try:
        cf = stock.cash_flow
        if cf is not None and not cf.empty:
            data["cash_flow"] = cf
            print(f"[stock] Got cash flow: {cf.shape[1]} years")
    except Exception:
        pass

    # Revenue estimates (forward consensus)
    try:
        rev = stock.revenue_estimate
        if rev is not None and not rev.empty:
            data["revenue_estimate"] = rev
    except Exception:
        pass

    # Growth estimates
    try:
        ge = stock.growth_estimates
        if ge is not None and not ge.empty:
            data["growth_estimates"] = ge
    except Exception:
        pass

    # Analyst price targets
    try:
        apt = stock.analyst_price_targets
        if apt and apt.get("mean"):
            data["price_targets"] = apt
    except Exception:
        pass

    # Upgrades / downgrades (recent analyst actions)
    try:
        ud = stock.upgrades_downgrades
        if ud is not None and not ud.empty:
            data["upgrades_downgrades"] = ud.head(10)
    except Exception:
        pass

    # News
    try:
        news = stock.news
        if news:
            data["news"] = news[:10]
    except Exception:
        pass

    return data if data else None


def format_extended_financials_for_prompt(data, currency="", include_statements=True):
    """Format extended financial data into markdown for the LLM prompt.

    Args:
        data: Dict from get_extended_financials().
        currency: Currency code (e.g. "EUR", "CHF") for display.
        include_statements: If True, include income/balance/cashflow tables.
            Set False when SEC EDGAR already provides this data.
    """
    if not data:
        return ""

    lines = []

    # ---- Financial Statements ----
    if include_statements:
        inc = data.get("income_stmt")
        if inc is not None:
            lines.append("\n### Annual Income Statement (Yahoo Finance)")
            years = [str(c.year) for c in inc.columns[:5]]
            n = len(years)

            metrics = [
                ("Total Revenue",    ["Total Revenue", "Operating Revenue"]),
                ("Cost of Revenue",  ["Cost Of Revenue"]),
                ("Gross Profit",     ["Gross Profit"]),
                ("Operating Income", ["Operating Income", "EBIT"]),
                ("EBITDA",           ["EBITDA", "Normalized EBITDA"]),
                ("Net Income",       ["Net Income", "Net Income From Continuing Operation Net Minority Interest"]),
                ("R&D Expense",      ["Research And Development", "Research Development"]),
            ]

            header = f"  {'Metric':<22s} | " + " | ".join(f"{y:>12s}" for y in years)
            sep = f"  {'-'*22}-|-" + "-|-".join("-" * 12 for _ in years)
            lines.append(header)
            lines.append(sep)

            revenue_row = None
            for label, keywords in metrics:
                row = _extract_row(inc, keywords)
                if row is None:
                    continue
                vals = [_fmt_num(row.iloc[i], currency) if i < len(row) else "—" for i in range(n)]
                lines.append(f"  {label:<22s} | " + " | ".join(f"{v:>12s}" for v in vals))

                if label == "Total Revenue":
                    revenue_row = row
                    growths = _yoy_growth(row, n)
                    lines.append(f"  {'  YoY Growth':<22s} | " + " | ".join(f"{g:>12s}" for g in growths))

            # Margins (if we have revenue)
            if revenue_row is not None:
                for margin_label, margin_kw in [("Gross Margin", ["Gross Profit"]), ("Operating Margin", ["Operating Income", "EBIT"]), ("Net Margin", ["Net Income", "Net Income From Continuing Operation Net Minority Interest"])]:
                    margin_row = _extract_row(inc, margin_kw)
                    if margin_row is not None:
                        margins = []
                        for i in range(n):
                            try:
                                if i < len(margin_row) and i < len(revenue_row) and not pd.isna(margin_row.iloc[i]) and not pd.isna(revenue_row.iloc[i]) and revenue_row.iloc[i] != 0:
                                    margins.append(f"{margin_row.iloc[i] / revenue_row.iloc[i] * 100:.1f}%")
                                else:
                                    margins.append("—")
                            except (TypeError, ValueError):
                                margins.append("—")
                        lines.append(f"  {margin_label:<22s} | " + " | ".join(f"{m:>12s}" for m in margins))

        bs = data.get("balance_sheet")
        if bs is not None:
            lines.append("")
            years_bs = [str(c.year) for c in bs.columns[:5]]
            n_bs = len(years_bs)

            bs_metrics = [
                ("Total Assets",      ["Total Assets", "Assets"]),
                ("Total Liabilities",  ["Total Liabilities Net Minority Interest", "Total Liabilities"]),
                ("Cash & Equivalents", ["Cash And Cash Equivalents", "Cash Cash Equivalents And Short Term Investments"]),
                ("Total Debt",         ["Total Debt", "Net Debt"]),
                ("Equity",             ["Stockholders Equity", "Total Equity Gross Minority Interest"]),
            ]

            lines.append(f"  {'Balance Sheet':<22s} | " + " | ".join(f"{y:>12s}" for y in years_bs))
            lines.append(f"  {'-'*22}-|-" + "-|-".join("-" * 12 for _ in years_bs))

            for label, keywords in bs_metrics:
                row = _extract_row(bs, keywords)
                if row is None:
                    continue
                vals = [_fmt_num(row.iloc[i], currency) if i < len(row) else "—" for i in range(n_bs)]
                lines.append(f"  {label:<22s} | " + " | ".join(f"{v:>12s}" for v in vals))

        cf = data.get("cash_flow")
        if cf is not None:
            lines.append("")
            years_cf = [str(c.year) for c in cf.columns[:5]]
            n_cf = len(years_cf)

            cf_metrics = [
                ("Operating Cash Flow", ["Operating Cash Flow", "Cash Flow From Continuing Operating Activities"]),
                ("Capital Expenditure", ["Capital Expenditure"]),
                ("Free Cash Flow",      ["Free Cash Flow"]),
            ]

            lines.append(f"  {'Cash Flow':<22s} | " + " | ".join(f"{y:>12s}" for y in years_cf))
            lines.append(f"  {'-'*22}-|-" + "-|-".join("-" * 12 for _ in years_cf))

            for label, keywords in cf_metrics:
                row = _extract_row(cf, keywords)
                if row is None:
                    continue
                vals = [_fmt_num(row.iloc[i], currency) if i < len(row) else "—" for i in range(n_cf)]
                lines.append(f"  {label:<22s} | " + " | ".join(f"{v:>12s}" for v in vals))

    # ---- Analyst Revenue Estimates ----
    rev_est = data.get("revenue_estimate")
    if rev_est is not None:
        lines.append("\n### Analyst Revenue Estimates (Consensus)")
        for period in rev_est.columns:
            avg = rev_est.at["avg", period] if "avg" in rev_est.index else None
            low = rev_est.at["low", period] if "low" in rev_est.index else None
            high = rev_est.at["high", period] if "high" in rev_est.index else None
            growth = rev_est.at["growth", period] if "growth" in rev_est.index else None
            analysts = rev_est.at["numberOfAnalysts", period] if "numberOfAnalysts" in rev_est.index else None

            parts = []
            if avg and not pd.isna(avg):
                parts.append(f"avg {_fmt_num(avg, currency)}")
            if low and high and not pd.isna(low) and not pd.isna(high):
                parts.append(f"range {_fmt_num(low, currency)}–{_fmt_num(high, currency)}")
            if growth and not pd.isna(growth):
                parts.append(f"growth {growth:+.1%}")
            if analysts and not pd.isna(analysts):
                parts.append(f"{int(analysts)} analysts")

            label = {"0q": "Current Qtr", "+1q": "Next Qtr", "0y": "Current Year", "+1y": "Next Year"}.get(period, period)
            if parts:
                lines.append(f"  {label}: {', '.join(parts)}")

    # ---- Growth Estimates ----
    ge = data.get("growth_estimates")
    if ge is not None and "stockTrend" in ge.columns:
        valid = [(p, ge.at[p, "stockTrend"]) for p in ge.index if not pd.isna(ge.at[p, "stockTrend"])]
        if valid:
            lines.append("\n### Earnings Growth Estimates")
            for period, val in valid:
                label = {"0q": "Current Qtr", "+1q": "Next Qtr", "0y": "Current Year", "+1y": "Next Year", "LTG": "Long-Term"}.get(period, period)
                lines.append(f"  {label}: {val:+.1%}")

    # ---- Analyst Price Targets ----
    pt = data.get("price_targets")
    if pt:
        current = pt.get("current")
        mean = pt.get("mean")
        high = pt.get("high")
        low = pt.get("low")
        if current and mean:
            lines.append("\n### Analyst Price Targets")
            upside = (mean - current) / current * 100
            lines.append(f"  Current: {currency} {current:.2f} | Mean Target: {currency} {mean:.2f} ({upside:+.1f}%)")
            if high and low:
                lines.append(f"  Range: {currency} {low:.2f} — {currency} {high:.2f}")

    # ---- Upgrades / Downgrades ----
    ud = data.get("upgrades_downgrades")
    if ud is not None and not ud.empty:
        lines.append("\n### Recent Analyst Actions")
        for date_idx, row in ud.head(8).iterrows():
            firm = row.get("Firm", "?")
            to_grade = row.get("ToGrade", "?")
            action = row.get("Action", "?")
            date_str = date_idx.strftime("%Y-%m-%d") if hasattr(date_idx, "strftime") else str(date_idx)[:10]
            current_pt = row.get("currentPriceTarget")
            prior_pt = row.get("priorPriceTarget")

            pt_text = ""
            if current_pt and not pd.isna(current_pt):
                if prior_pt and not pd.isna(prior_pt) and current_pt != prior_pt:
                    pt_text = f" (PT: {currency}{prior_pt:.0f} → {currency}{current_pt:.0f})"
                else:
                    pt_text = f" (PT: {currency}{current_pt:.0f})"

            lines.append(f"  {date_str} | {firm}: {action} → {to_grade}{pt_text}")

    # ---- News ----
    news = data.get("news")
    if news:
        lines.append("\n### Recent News")
        for item in news:
            # yfinance 1.2+ nests under 'content'
            content = item.get("content", {})
            title = content.get("title", "") or item.get("title", "")
            publisher = content.get("provider", {}).get("displayName", "") or item.get("publisher", "")
            url = content.get("canonicalUrl", {}).get("url", "") or item.get("link", "")
            if not title:
                continue
            if url:
                lines.append(f"  - [{title}]({url}) — {publisher}")
            else:
                lines.append(f"  - {title} — {publisher}")

    return "\n".join(lines) if lines else ""
