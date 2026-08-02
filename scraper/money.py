"""Shared money formatting for every financial data source.

All financial sources land in the same LLM prompt, so they must speak the same
units. When they don't, the model has to infer scale from context and it gets it
wrong: a ProPublica 990 reports in raw dollars, so `$501,098` sat in a report
template that otherwise talks in $M and $B, and came out the far side as
"$501.1M" — a nonprofit's half-million dollars rendered as half a billion.

The fix is conversion at format time, not an instruction in the prompt. Scale is
a known property of the data, so deciding it in code makes the error impossible
rather than merely unlikely. Under this formatter that same figure reads
"$501.1K", which cannot be misread as millions.

Format matches what scraper/sec_edgar.py has always emitted for XBRL values, so
SEC and non-SEC financials are indistinguishable in scale to the reader.
"""


def format_money(value, none_label: str = "N/A") -> str:
    """Format a dollar amount with an explicit magnitude suffix.

    >>> format_money(501_098)
    '$501.1K'
    >>> format_money(1_112_185)
    '$1.1M'
    >>> format_money(2_500_000_000)
    '$2.50B'
    >>> format_money(-45_000)
    '-$45.0K'
    >>> format_money(None)
    'N/A'
    """
    if value is None:
        return none_label
    try:
        v = float(value)
    except (TypeError, ValueError):
        return str(value)

    # Sign handled separately so negatives read '-$1.2M', not '$-1.2M'.
    # Net assets and operating results legitimately go negative on 990s.
    sign = "-" if v < 0 else ""
    a = abs(v)

    if a >= 1_000_000_000:
        return f"{sign}${a / 1_000_000_000:.2f}B"
    if a >= 1_000_000:
        return f"{sign}${a / 1_000_000:.1f}M"
    if a >= 1_000:
        return f"{sign}${a / 1_000:.1f}K"
    return f"{sign}${a:,.0f}"
