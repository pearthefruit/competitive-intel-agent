"""Stock market data via yfinance — price, market cap, valuation metrics."""

import yfinance as yf

# Well-known foreign-listed companies and their Yahoo Finance tickers
# This avoids guessing for the most commonly analyzed companies
KNOWN_TICKERS = {
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
    "nestle": "NSRGY",
    "novartis": "NVS",
    "roche": "RHHBY",
    "shell": "SHEL",
    "bp": "BP",
    "hsbc": "HSBC",
    "unilever": "UL",
    "astrazeneca": "AZN",
    "siemens": "SIEGY",
    "sap": "SAP",
    "lvmh": "LVMHF",
    "asml": "ASML",
    "novo nordisk": "NVO",
    "baidu": "BIDU",
    "jd.com": "JD",
    "pinduoduo": "PDD",
    "pdd holdings": "PDD",
    "infosys": "INFY",
    "wipro": "WIT",
    "reliance": "RELIANCE.NS",
    "tata": "TCS.NS",
    "tata consultancy": "TCS.NS",
    "softbank": "9984.T",
    "nintendo": "NTDOY",
    "honda": "HMC",
    "mitsubishi": "8058.T",
    "volkswagen": "VWAGY",
    "bmw": "BMWYY",
    "mercedes": "MBGYY",
    "mercedes-benz": "MBGYY",
    "byd": "BYDDY",
    "xiaomi": "XIACF",
    "shopify": "SHOP",
    "spotify": "SPOT",
}


def lookup_ticker(company_name):
    """Try to find a Yahoo Finance ticker for a company name.

    Checks known tickers map first, then tries the name as a ticker directly.
    Returns ticker string or None.
    """
    name_lower = company_name.strip().lower()

    # Check known tickers
    if name_lower in KNOWN_TICKERS:
        return KNOWN_TICKERS[name_lower]

    # Check partial matches (e.g., "Samsung" matches "samsung electronics")
    for key, ticker in KNOWN_TICKERS.items():
        if name_lower in key or key in name_lower:
            return ticker

    # Try the company name as a ticker directly (works for many US stocks)
    test_ticker = company_name.strip().upper().replace(" ", "")
    if len(test_ticker) <= 5:
        try:
            stock = yf.Ticker(test_ticker)
            info = stock.info
            if info and (info.get("currentPrice") or info.get("regularMarketPrice")):
                return test_ticker
        except Exception:
            pass

    return None


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
