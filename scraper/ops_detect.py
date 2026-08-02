"""Business process / operations maturity detection from a company website.

Answers a different question than tech_detect: not "what is this site built with"
but "does this business run on systems, or on the owner's phone?"

Two mechanisms:
  1. probe_paths()  — GET a fixed list of well-known routes (/pricing, /blog,
     /demo, /careers, ...). The site crawler's nav-priority BFS is the wrong tool
     here: it returns whichever three links happen to be in the header, so the
     absence of a pricing page in its output means nothing. Probing a known list
     turns absence into a real signal.
  2. detect_ops_signals() — scan HTML for the machinery of a funnel: email
     capture forms, booking embeds, checkout, gated content, customer portals,
     ATS links, and content recency.

Everything here is DOM-level and deterministic. A form is a form — there is no
version of this that a screenshot answers better.
"""

import hashlib
import re
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# Routes worth knowing the existence of, grouped by the capability they imply.
# Order within a group matters only for reporting — the first hit wins.
PROBE_PATHS = {
    "pricing":       ["/pricing", "/plans", "/rates", "/packages"],
    "blog":          ["/blog", "/news", "/insights", "/resources", "/articles"],
    "case_studies":  ["/case-studies", "/customers", "/portfolio", "/our-work", "/projects"],
    "booking":       ["/demo", "/book", "/book-online", "/schedule", "/request-a-quote",
                      "/get-a-quote", "/consultation", "/estimate"],
    "contact":       ["/contact", "/contact-us", "/get-in-touch"],
    "about":         ["/about", "/about-us", "/our-story"],
    "team":          ["/team", "/our-team", "/staff", "/leadership", "/people"],
    "careers":       ["/careers", "/jobs", "/join-us", "/work-with-us"],
    "shop":          ["/shop", "/store", "/products", "/collections/all", "/order"],
    "login":         ["/login", "/account", "/portal", "/client-portal", "/my-account", "/signin"],
    "faq":           ["/faq", "/faqs", "/help", "/support"],
    "testimonials":  ["/testimonials", "/reviews"],
}

# Email service providers — a form posting here is a real marketing list, not a
# contact form that dumps into someone's inbox.
_ESP_PATTERNS = [
    (r"klaviyo", "Klaviyo"),
    (r"list-manage\.com|mailchimp", "Mailchimp"),
    (r"constantcontact|ctctcdn", "Constant Contact"),
    (r"activecampaign|app-us1", "ActiveCampaign"),
    (r"hubspot|hsforms", "HubSpot"),
    (r"convertkit|ck\.page", "ConvertKit"),
    (r"sendinblue|brevo", "Brevo"),
    (r"omnisend", "Omnisend"),
    (r"mailerlite|emailoctopus", "MailerLite/EmailOctopus"),
    (r"attentivemobile|attn\.tv", "Attentive (SMS)"),
    (r"postscript", "Postscript (SMS)"),
    (r"substack", "Substack"),
    (r"beehiiv", "beehiiv"),
]

_BOOKING_PATTERNS = [
    (r"calendly\.com", "Calendly"),
    (r"acuityscheduling|squarespacescheduling", "Acuity"),
    (r"meetings\.hubspot\.com", "HubSpot Meetings"),
    (r"chilipiper", "Chili Piper"),
    (r"squareup\.com/appointments|square\.site/book", "Square Appointments"),
    (r"opentable\.com|resy\.com|sevenrooms", "Restaurant reservations"),
    (r"booksy\.com|vagaro\.com|schedulicity", "Booksy/Vagaro"),
    (r"mindbodyonline", "Mindbody"),
    (r"setmore|simplybook", "Setmore/SimplyBook"),
    (r"housecallpro\.com/book|getjobber\.com/book|servicetitan", "Field service booking"),
]

# Applicant tracking systems — a careers page that links to one of these means
# hiring is a process, not a Craigslist post.
_ATS_PATTERNS = [
    (r"greenhouse\.io", "Greenhouse"),
    (r"lever\.co", "Lever"),
    (r"ashbyhq\.com", "Ashby"),
    (r"workable\.com", "Workable"),
    (r"bamboohr\.com", "BambooHR"),
    (r"jazzhr\.com|applytojob\.com", "JazzHR"),
    (r"myworkdayjobs\.com", "Workday"),
    (r"recruiting\.paylocity|paycomonline|adp\.com/careers", "Paylocity/Paycom/ADP"),
    (r"indeed\.com/cmp|ziprecruiter\.com/jobs", "Indeed/ZipRecruiter (listing only)"),
]

_CHECKOUT_PATTERNS = [
    r"/cart", r"add-to-cart", r"addtocart", r"/checkout", r"data-product-id",
    r"snipcart", r"shopify-buy", r"woocommerce-cart",
]

# WAF / bot-challenge markers. A challenge page is served with a real body and
# often a 403, so it is easy to mistake for a thin site — which would turn a
# blocked probe into a confident "this business has no funnel" verdict. It must
# fail loudly instead.
_BLOCK_MARKERS = re.compile(
    r"cf-browser-verification|cf_chl_opt|__cf_chl|checking your browser|"
    r"attention required!\s*\|\s*cloudflare|access denied|request blocked|"
    r"ddos protection by|perimeterx|px-captcha|incapsula|imperva|akamai bot manager|"
    r"are you a robot|enable javascript and cookies to continue",
    re.IGNORECASE,
)

_DATE_ATTR_RE = re.compile(r"\b(20[12]\d)-(\d{2})-(\d{2})")
_DATE_TEXT_RE = re.compile(
    r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+(20[12]\d)\b",
    re.IGNORECASE,
)
_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


# ── Path probing ─────────────────────────────────────────────────────────────

def is_blocked(html, status_code=200):
    """True when a response is a bot challenge / WAF block rather than real content."""
    if not html:
        return False
    head = html[:4000]
    if _BLOCK_MARKERS.search(head):
        return True
    # A 403 or 503 carrying a short HTML body is a block page, not a thin page
    if status_code in (401, 403, 429, 503) and len(html) < 20000:
        return True
    return False


def _body_fingerprint(html):
    """Stable hash of a page's visible text, for catch-all detection."""
    soup = BeautifulSoup(html or "", "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    text = " ".join(soup.get_text(" ", strip=True).split())
    return hashlib.sha256(text.encode("utf-8", "ignore")).hexdigest()


def probe_paths(base_url, timeout=8, max_workers=4):
    """GET each candidate path and report which ones exist.

    Returns (found, meta):
      found — {capability: {"path", "url", "status", "title", "html"}} for hits only
      meta  — {"blocked", "catchall", "control_status", "probed", "reliable"}

    Two failure modes have to be distinguished from a genuinely thin site, because
    both otherwise produce a confident and completely wrong "no funnel" verdict:

      blocked  — the site WAF-challenges every request (Cloudflare et al). Nothing
                 was measured, so nothing can be concluded.
      catchall — the site returns 200 for every URL, including nonsense ones. A
                 control probe against a random path detects this; any page whose
                 body matches the control is discarded.
    """
    if not base_url.startswith("http"):
        base_url = f"https://{base_url}"
    root = f"{urlparse(base_url).scheme}://{urlparse(base_url).netloc}"

    candidates = [(cap, p) for cap, paths in PROBE_PATHS.items() for p in paths]
    found = {}
    meta = {"blocked": False, "catchall": False, "control_status": None,
            "probed": len(candidates), "reliable": True}

    client = httpx.Client(headers=REQUEST_HEADERS, timeout=timeout, follow_redirects=True)

    # --- Control probe: a path that cannot legitimately exist ---
    control_fp = None
    try:
        control_url = urljoin(root + "/", f"sv-probe-{uuid.uuid4().hex[:12]}")
        cresp = client.get(control_url)
        meta["control_status"] = cresp.status_code
        if is_blocked(cresp.text, cresp.status_code):
            meta["blocked"] = True
            meta["reliable"] = False
            client.close()
            return found, meta
        if cresp.status_code < 400 and "text/html" in cresp.headers.get("content-type", ""):
            # Site serves 200 for a URL that does not exist — everything below is
            # suspect, including the absences: a route we filtered out as a
            # control-page match might have been real.
            meta["catchall"] = True
            meta["reliable"] = False
            control_fp = _body_fingerprint(cresp.text)
    except Exception as e:
        print(f"[ops] Control probe failed for {root}: {e}")

    def _fetch(item):
        cap, path = item
        url = urljoin(root + "/", path.lstrip("/"))
        try:
            resp = client.get(url)
            if is_blocked(resp.text, resp.status_code):
                return ("__blocked__", None)
            if resp.status_code >= 400:
                return None
            if "text/html" not in resp.headers.get("content-type", ""):
                return None
            # Catch-all defence: identical body to the control page means this
            # route does not exist, whatever the status code says.
            if control_fp and _body_fingerprint(resp.text) == control_fp:
                return None
            soup = BeautifulSoup(resp.text, "html.parser")
            title_tag = soup.find("title")
            title = title_tag.get_text(strip=True) if title_tag else ""
            # Soft-404 filter — many SMB sites serve a 200 for everything
            if re.search(r"page not found|404|doesn'?t exist|no longer available", title, re.I):
                return None
            body_text = soup.get_text(" ", strip=True)[:400]
            if re.search(r"page (you requested |you are looking for )?(could not be|can'?t be|was not) found",
                         body_text, re.I):
                return None
            return cap, {"path": path, "url": str(resp.url), "status": resp.status_code,
                         "title": title, "html": resp.text}
        except Exception:
            return None

    blocked_count = 0
    try:
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            for result in pool.map(_fetch, candidates):
                if not result:
                    continue
                cap, data = result
                if cap == "__blocked__":
                    blocked_count += 1
                    continue
                # First hit per capability wins
                if cap not in found:
                    found[cap] = data
    finally:
        client.close()

    if blocked_count > len(candidates) * 0.5:
        meta["blocked"] = True
        meta["reliable"] = False
        return {}, meta

    return found, meta


# ── Signal extraction ────────────────────────────────────────────────────────

def _match_first(patterns, corpus):
    """Return the label of the first matching (pattern, label) pair, else None."""
    for pattern, label in patterns:
        if re.search(pattern, corpus, re.IGNORECASE):
            return label
    return None


def _extract_forms(soup):
    """Extract form shape: action target, method, and input field types."""
    forms = []
    for form in soup.find_all("form"):
        inputs = form.find_all(["input", "select", "textarea"])
        types = [(i.get("type") or i.name or "").lower() for i in inputs]
        # Ignore search boxes and hidden-only forms
        visible = [t for t in types if t not in ("hidden", "submit", "button", "search")]
        if not visible:
            continue
        forms.append({
            "action": form.get("action", ""),
            "method": (form.get("method") or "get").lower(),
            "field_count": len(visible),
            "has_email": any(t == "email" for t in types)
                         or any((i.get("name") or "").lower().find("email") >= 0 for i in inputs),
            "field_types": visible,
        })
    return forms


def _latest_content_date(html):
    """Best-effort newest publication date on a page. Returns (iso_date, days_ago) or (None, None)."""
    dates = []
    for y, m, d in _DATE_ATTR_RE.findall(html):
        try:
            dates.append(datetime(int(y), int(m), int(d), tzinfo=timezone.utc))
        except ValueError:
            continue
    for mon, y in _DATE_TEXT_RE.findall(html):
        mi = _MONTHS.get(mon[:3].lower())
        if mi:
            try:
                dates.append(datetime(int(y), mi, 1, tzinfo=timezone.utc))
            except ValueError:
                continue
    if not dates:
        return None, None
    now = datetime.now(timezone.utc)
    # Ignore future dates (copyright notices, event listings)
    past = [d for d in dates if d <= now]
    if not past:
        return None, None
    newest = max(past)
    return newest.strftime("%Y-%m-%d"), (now - newest).days


def detect_ops_signals(homepage_html, homepage_url, probed, probe_meta=None):
    """Build the ops maturity signal set from the homepage plus probed pages.

    Args:
        homepage_html: raw HTML of the homepage
        homepage_url: the homepage URL
        probed: found-pages dict from probe_paths()
        probe_meta: meta dict from probe_paths() — carries reliability flags

    Returns a dict of structured signals, ready for format_ops_for_prompt().
    """
    probe_meta = probe_meta or {"blocked": False, "catchall": False, "reliable": True}
    all_html = homepage_html or ""
    for data in probed.values():
        all_html += "\n" + (data.get("html") or "")

    soup = BeautifulSoup(homepage_html or "", "html.parser")
    forms = _extract_forms(soup)
    for data in probed.values():
        forms.extend(_extract_forms(BeautifulSoup(data.get("html") or "", "html.parser")))

    # --- Lead capture ---
    esp = _match_first(_ESP_PATTERNS, all_html)
    email_forms = [f for f in forms if f["has_email"]]
    newsletter_signup = bool(esp) or bool(
        re.search(r"subscribe|newsletter|join our (list|mailing)|sign up for", all_html, re.I)
        and email_forms
    )

    # --- Booking / demo funnel ---
    booking_tool = _match_first(_BOOKING_PATTERNS, all_html)
    booking_page = "booking" in probed

    # --- Gated content: a form asking for 3+ fields is qualifying a lead ---
    gated_forms = [f for f in forms if f["field_count"] >= 3 and f["has_email"]]
    gated_keywords = bool(re.search(r"whitepaper|e-?book|download the guide|free guide|"
                                    r"gated|webinar registration", all_html, re.I))

    # --- Content engine ---
    blog_date, blog_days_ago = (None, None)
    blog_post_count = 0
    if "blog" in probed:
        blog_html = probed["blog"]["html"]
        blog_date, blog_days_ago = _latest_content_date(blog_html)
        blog_soup = BeautifulSoup(blog_html, "html.parser")
        base_domain = urlparse(homepage_url).netloc
        post_links = set()
        for a in blog_soup.find_all("a", href=True):
            href = urljoin(homepage_url, a["href"])
            if urlparse(href).netloc != base_domain:
                continue
            if re.search(r"/(blog|news|insights|articles|post)/[\w-]{4,}", href):
                post_links.add(href.split("?")[0])
        blog_post_count = len(post_links)

    # --- Commerce / self-serve ---
    checkout = any(re.search(p, all_html, re.IGNORECASE) for p in _CHECKOUT_PATTERNS)

    # --- Hiring infrastructure ---
    ats = _match_first(_ATS_PATTERNS, all_html)

    # --- Site hygiene ---
    is_https = homepage_url.startswith("https://")
    has_viewport = bool(soup.find("meta", attrs={"name": "viewport"}))
    schema_types = set()
    for script in soup.find_all("script", type="application/ld+json"):
        raw = script.string or ""
        for t in re.findall(r'"@type"\s*:\s*"([^"]+)"', raw):
            schema_types.add(t)
    has_phone = bool(re.search(r"tel:\+?[\d\-\(\) ]{7,}", all_html))
    has_address = bool(re.search(r"\b\d{1,6}\s+[A-Z][\w\.]+\s+(St|Street|Ave|Avenue|Rd|Road|Blvd|"
                                 r"Boulevard|Dr|Drive|Ln|Lane|Way|Suite|Ste)\b", all_html))

    return {
        "probe_quality": {
            "blocked": probe_meta.get("blocked", False),
            "catchall": probe_meta.get("catchall", False),
            # When False, a missing page means "could not determine", never "absent"
            "absence_is_meaningful": probe_meta.get("reliable", True),
        },
        "pages_found": {cap: {"url": d["url"], "title": d["title"]} for cap, d in probed.items()},
        "pages_missing": [cap for cap in PROBE_PATHS if cap not in probed],
        "lead_capture": {
            "newsletter_signup": newsletter_signup,
            "esp": esp,
            "email_form_count": len(email_forms),
            "total_form_count": len(forms),
        },
        "sales_funnel": {
            "booking_tool": booking_tool,
            "booking_page": booking_page,
            "pricing_page": "pricing" in probed,
            "gated_content": bool(gated_forms) or gated_keywords,
            "gated_form_count": len(gated_forms),
            "case_studies": "case_studies" in probed,
            "testimonials": "testimonials" in probed,
        },
        "content_engine": {
            "blog_exists": "blog" in probed,
            "post_count_on_index": blog_post_count,
            "latest_post_date": blog_date,
            "days_since_last_post": blog_days_ago,
        },
        "self_serve": {
            "checkout": checkout,
            "shop_page": "shop" in probed,
            "customer_portal": "login" in probed,
            "faq_page": "faq" in probed,
        },
        "hiring": {
            "careers_page": "careers" in probed,
            "ats": ats,
            "team_page": "team" in probed,
        },
        "hygiene": {
            "https": is_https,
            "mobile_viewport": has_viewport,
            "schema_types": sorted(schema_types),
            "local_business_schema": any(
                t in schema_types for t in ("LocalBusiness", "Organization", "Restaurant", "Store")
            ),
            "phone_listed": has_phone,
            "address_listed": has_address,
        },
    }


# ── Prompt formatting ────────────────────────────────────────────────────────

def _yn(v):
    return "YES" if v else "no"


def format_ops_for_prompt(signals):
    """Render the signal dict into a compact block for the LLM prompt."""
    lc = signals["lead_capture"]
    sf = signals["sales_funnel"]
    ce = signals["content_engine"]
    ss = signals["self_serve"]
    hr = signals["hiring"]
    hy = signals["hygiene"]

    pq = signals.get("probe_quality", {})

    lines = []
    if pq.get("blocked"):
        lines += [
            "### ⚠ PROBE BLOCKED",
            "",
            "  The site returned bot-challenge/WAF responses. NOTHING below was actually measured.",
            "  Do not infer low maturity from these results — report insufficient data and stop.",
            "",
        ]
    elif pq.get("catchall"):
        lines += [
            "### ⚠ CATCH-ALL SITE",
            "",
            "  This site returns a page for URLs that do not exist, so a 'found' page may not be real",
            "  and a 'not found' page proves nothing. Treat all page-existence signals as UNRELIABLE",
            "  and weight the tooling/stack signals instead.",
            "",
        ]

    lines += ["### Pages Found", ""]
    for cap, d in sorted(signals["pages_found"].items()):
        lines.append(f"  - {cap}: {d['url']}" + (f" — \"{d['title'][:70]}\"" if d["title"] else ""))
    if not signals["pages_found"]:
        lines.append("  (none)")
    if signals["pages_missing"]:
        lines.append("")
        qualifier = ("Not found" if pq.get("absence_is_meaningful", True)
                     else "Not confirmed (probe unreliable — absence proves nothing)")
        lines.append(f"  {qualifier}: {', '.join(sorted(signals['pages_missing']))}")

    lines += [
        "",
        "### Lead Capture",
        f"  - Newsletter/email signup: {_yn(lc['newsletter_signup'])}",
        f"  - Email service provider: {lc['esp'] or 'none detected'}",
        f"  - Forms with an email field: {lc['email_form_count']} (of {lc['total_form_count']} total forms)",
        "",
        "### Sales Funnel",
        f"  - Booking/scheduling tool: {sf['booking_tool'] or 'none detected'}",
        f"  - Dedicated booking/demo/quote page: {_yn(sf['booking_page'])}",
        f"  - Public pricing page: {_yn(sf['pricing_page'])}",
        f"  - Gated content (3+ field forms): {_yn(sf['gated_content'])} ({sf['gated_form_count']} qualifying forms)",
        f"  - Case studies / portfolio: {_yn(sf['case_studies'])}",
        f"  - Testimonials page: {_yn(sf['testimonials'])}",
        "",
        "### Content Engine",
        f"  - Blog/resources section: {_yn(ce['blog_exists'])}",
    ]
    if ce["blog_exists"]:
        lines.append(f"  - Posts linked from index: {ce['post_count_on_index']}")
        if ce["days_since_last_post"] is not None:
            staleness = (
                "ACTIVE" if ce["days_since_last_post"] <= 90
                else "STALE" if ce["days_since_last_post"] <= 730
                else "ABANDONED"
            )
            lines.append(f"  - Most recent dated content: {ce['latest_post_date']} "
                         f"({ce['days_since_last_post']} days ago) — {staleness}")
        else:
            lines.append("  - Most recent dated content: no dates found on index (undated content)")

    lines += [
        "",
        "### Self-Serve & Customer Systems",
        f"  - Checkout / add-to-cart: {_yn(ss['checkout'])}",
        f"  - Shop/product listing page: {_yn(ss['shop_page'])}",
        f"  - Customer login/portal: {_yn(ss['customer_portal'])}",
        f"  - FAQ/help section: {_yn(ss['faq_page'])}",
        "",
        "### Hiring Infrastructure",
        f"  - Careers page: {_yn(hr['careers_page'])}",
        f"  - Applicant tracking system: {hr['ats'] or 'none detected'}",
        f"  - Team/leadership page: {_yn(hr['team_page'])}",
        "",
        "### Site Hygiene",
        f"  - HTTPS: {_yn(hy['https'])}",
        f"  - Mobile viewport meta: {_yn(hy['mobile_viewport'])}",
        f"  - Structured data (schema.org): {', '.join(hy['schema_types']) or 'none'}",
        f"  - LocalBusiness/Organization schema: {_yn(hy['local_business_schema'])}",
        f"  - Phone number listed: {_yn(hy['phone_listed'])}",
        f"  - Street address listed: {_yn(hy['address_listed'])}",
    ]

    return "\n".join(lines)
