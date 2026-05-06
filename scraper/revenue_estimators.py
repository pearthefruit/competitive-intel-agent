"""Type-specific revenue estimators for private companies.

Each estimator scrapes public signals (review counts, pricing pages, app stores, etc.)
and applies a multiplier model to produce a revenue range estimate.

Entry point: estimate_revenue(company_name, website_url, description, niche_context)
  → classifies business type → routes to the right estimator

Return shape (all estimators):
{
    "revenue":             int | None,   # point estimate in USD (midpoint of range)
    "estimate_low":        int | None,   # lower bound in USD
    "estimate_high":       int | None,   # upper bound in USD
    "is_estimated":        bool,         # always True from this module
    "confidence":          str,          # "medium" | "low"
    "estimate_basis":      str,          # human-readable signal summary
    "estimated_employees": int | None,
    "sector":              str | None,
    "industry":            str | None,
    "sources":             list[str],    # e.g. ["google_maps", "ddg_search"]
}
Returns None if no usable signals found.
"""

import re
import json
import httpx
from bs4 import BeautifulSoup

from scraper.web_search import search_web


# ---------------------------------------------------------------------------
# Business type classifier
# ---------------------------------------------------------------------------

def classify_business_type(name, description, niche_context):
    """Classify company into a revenue estimation category.

    Returns one of: 'restaurant' | 'ecommerce' | 'saas' | 'services' |
                    'consumer_app' | 'other'

    Uses keyword matching on name + description + niche — no LLM call.
    """
    text = " ".join(filter(None, [name, description, niche_context])).lower()

    restaurant_kw = ["restaurant", "cafe", "bistro", "bar ", "grill", "diner",
                     "eatery", "food ", "pizza", "sushi", "bakery", "brewery",
                     "winery", "wine bar", "steakhouse", "taqueria", "kitchen",
                     "brasserie", "tavern", "pub ", "food hall", "catering"]
    if any(k in text for k in restaurant_kw):
        return "restaurant"

    app_kw = ["app ", "mobile app", "ios ", "android ", "app store",
              "play store", "saas app", "consumer app", "subscription app",
              "fitness app", "meditation app", "dating app", "game ", "gaming"]
    if any(k in text for k in app_kw):
        return "consumer_app"

    ecommerce_kw = ["ecommerce", "e-commerce", "shopify", "amazon seller",
                    "online store", "direct-to-consumer", "dtc", "d2c",
                    "cpg", "consumer goods", "retailer", "brand ", "skincare",
                    "beverage", "supplement", "apparel", "clothing", "shoes",
                    "beauty", "cosmetic", "food brand", "packaged food",
                    "household goods", "pet products"]
    if any(k in text for k in ecommerce_kw):
        return "ecommerce"

    saas_kw = ["saas", "software", "platform ", "api ", "cloud ", "crm",
               "erp", "hris", "devtools", "developer tool", "b2b software",
               "enterprise software", "data platform", "analytics platform",
               "workflow", "automation", "marketplace", "fintech", "insurtech",
               "proptech", "legaltech", "edtech", "healthtech"]
    if any(k in text for k in saas_kw):
        return "saas"

    services_kw = ["consulting", "agency", "staffing", "services", "firm",
                   "advisory", "outsourcing", "managed services", "bpo",
                   "law firm", "accounting", "audit", "marketing agency",
                   "pr firm", "recruiting", "headhunting", "research firm"]
    if any(k in text for k in services_kw):
        return "services"

    return "other"


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def estimate_revenue(company_name, website_url=None, description=None, niche_context=None):
    """Classify and route to the right estimator. Returns estimate dict or None."""
    btype = classify_business_type(company_name, description or "", niche_context or "")

    if btype == "restaurant":
        return _estimate_restaurant(company_name, website_url)
    elif btype == "ecommerce":
        return _estimate_ecommerce(company_name, website_url)
    elif btype == "saas":
        return _estimate_saas_services(company_name, website_url, description, is_saas=True)
    elif btype == "services":
        return _estimate_saas_services(company_name, website_url, description, is_saas=False)
    elif btype == "consumer_app":
        return _estimate_consumer_app(company_name)
    else:
        return None  # fall through to Tier 4 web search + niche-anchored LLM


# ---------------------------------------------------------------------------
# Phase 1 — Restaurant estimator (Google Maps)
# ---------------------------------------------------------------------------

def _estimate_restaurant(company_name, website_url=None):
    """Estimate restaurant revenue from Google Maps review signals.

    Model:
      visits_per_year ≈ review_count × purchase_to_review_ratio[price_tier]
      estimated_revenue = visits_per_year × avg_check[price_tier]
      range: ±40%

    Price tier proxies: $ → avg_check $15, $$ → $35, $$$ → $65, $$$$ → $120
    Purchase-to-review ratios:  $ → 120, $$ → 80, $$$ → 50, $$$$ → 30
    """
    PRICE_TIERS = {
        "$":       {"avg_check": 15,  "ratio": 120, "employees": 10},
        "$$":      {"avg_check": 35,  "ratio": 80,  "employees": 25},
        "$$$":     {"avg_check": 65,  "ratio": 50,  "employees": 40},
        "$$$$":    {"avg_check": 120, "ratio": 30,  "employees": 60},
        "unknown": {"avg_check": 35,  "ratio": 80,  "employees": 25},
    }

    def _parse_signals(text):
        """Extract review_count, rating, and price_tier from a text snippet."""
        review_count = None
        rating = None
        price_tier = None

        # Review count patterns (order: most-specific first)
        review_patterns = [
            r"([\d,]+)\s+(?:google\s+)?reviews",          # "1,234 reviews"
            r"([\d,]+)\s+(?:yelp\s+)?reviews",
            r"([\d,]+)\s+(?:tripadvisor\s+)?reviews",
            r"based\s+on\s+([\d,]+)\s+reviews",            # "based on 500 reviews"
            r"\(\s*([\d,]+)\s*\)",                          # "(876)" — Google Maps inline count
            r"([\d,]+)\s+ratings",
            r"([\d,]+)\s+user\s+reviews",
        ]
        for pat in review_patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                raw = m.group(1).replace(",", "")
                if raw.isdigit() and int(raw) > 0:
                    review_count = int(raw)
                    break

        # Rating patterns
        rating_patterns = [
            r"rated\s+([\d.]+)\s*(?:out\s+of\s*5)?",        # "Rated 4.1"
            r"([\d.]+)\s+stars?",                            # "4.5 stars"
            r"([\d.]+)\s*/\s*5",                             # "4.2/5"
            r"\b([1-5]\.[0-9])\b",                           # bare "4.2"
        ]
        for pat in rating_patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                try:
                    v = float(m.group(1))
                    if 1.0 <= v <= 5.0:
                        rating = v
                        break
                except ValueError:
                    pass

        # Price tier — look for dollar signs in common contexts
        tier_match = re.search(r"price[:\s·•\-]+(\${1,4})", text, re.IGNORECASE)
        if not tier_match:
            # Standalone $$$$ down to $ (greedy: match longest first)
            tier_match = re.search(r"(\${1,4})(?:\s|·|•|,|$)", text)
        if tier_match:
            raw_tier = tier_match.group(1)
            if raw_tier in PRICE_TIERS:
                price_tier = raw_tier

        return review_count, rating, price_tier

    try:
        print(f"[restaurant_est] Starting estimate for: {company_name}")

        all_snippets = []

        # Query 1: Google Maps snippet (DDG returns map cards with review counts)
        q1 = f'"{company_name}" restaurant google maps reviews'
        results1 = search_web(q1, max_results=3)
        print(f"[restaurant_est] Maps query returned {len(results1)} results")
        all_snippets.extend(results1)

        # Query 2: Yelp / TripAdvisor / review aggregators
        q2 = f'"{company_name}" restaurant reviews rating'
        results2 = search_web(q2, max_results=5)
        print(f"[restaurant_est] Reviews query returned {len(results2)} results")
        all_snippets.extend(results2)

        if not all_snippets:
            print("[restaurant_est] No search results returned — giving up")
            return None

        # Accumulate best signals across all snippets
        best_review_count = None
        best_rating = None
        best_price_tier = None
        best_source_title = None

        for result in all_snippets:
            title = result.get("title", "")
            body = result.get("body", "")
            combined = f"{title} {body}"

            rc, rt, pt = _parse_signals(combined)

            # Prefer highest review count (more data = more reliable)
            if rc is not None:
                if best_review_count is None or rc > best_review_count:
                    best_review_count = rc
                    best_source_title = title
                    print(f"[restaurant_est] Found review_count={rc} in: {title[:60]}")

            if rt is not None and best_rating is None:
                best_rating = rt
                print(f"[restaurant_est] Found rating={rt}")

            if pt is not None and best_price_tier is None:
                best_price_tier = pt
                print(f"[restaurant_est] Found price_tier={pt}")

        if best_review_count is None:
            print("[restaurant_est] No review count found in any result — returning None")
            return None

        tier_key = best_price_tier if best_price_tier in PRICE_TIERS else "unknown"
        tier = PRICE_TIERS[tier_key]

        visits_per_year = best_review_count * tier["ratio"]
        revenue = visits_per_year * tier["avg_check"]
        estimate_low = int(revenue * 0.6)
        estimate_high = int(revenue * 1.4)
        revenue = int(revenue)

        tier_display = tier_key if tier_key != "unknown" else "unknown price tier"
        basis = (
            f"Google Maps/Yelp search: {best_review_count:,} reviews, "
            f"{tier_display}, "
            f"~{tier['ratio']} visits/review, "
            f"avg check ${tier['avg_check']}"
        )
        if best_rating is not None:
            basis += f", rating {best_rating}"

        print(
            f"[restaurant_est] Result: revenue=${revenue:,} "
            f"(low=${estimate_low:,}, high=${estimate_high:,}) | {basis}"
        )

        return {
            "revenue":             revenue,
            "estimate_low":        estimate_low,
            "estimate_high":       estimate_high,
            "is_estimated":        True,
            "confidence":          "low",
            "estimate_basis":      basis,
            "estimated_employees": tier["employees"],
            "sector":              "Consumer Discretionary",
            "industry":            "Restaurants",
            "sources":             ["google_maps_search"],
        }

    except Exception as e:
        print(f"[restaurant_est] Error estimating {company_name}: {e}")
        return None


# ---------------------------------------------------------------------------
# Phase 2 — B2B SaaS / Services estimator
# ---------------------------------------------------------------------------

def _estimate_saas_services(company_name, website_url=None, description=None, is_saas=True):
    """Estimate revenue for SaaS or services companies.

    SaaS model:
      - Scrape pricing page → identify ARPU tier
      - Scrape homepage/about → count customer logos
      - ARR ≈ logo_count × 3 × ARPU

    Services model:
      - Find employee count from web search / LinkedIn snippet
      - revenue ≈ employee_count × revenue_per_employee[industry]
    """
    prefix = "[saas_est]" if is_saas else "[services_est]"
    try:
        if is_saas:
            return _estimate_saas(company_name, website_url, description, prefix)
        else:
            return _estimate_services(company_name, website_url, description, prefix)
    except Exception as e:
        print(f"{prefix} Unhandled error for {company_name}: {e}")
        return None


def _estimate_saas(company_name, website_url, description, prefix):
    sources = []

    # ------------------------------------------------------------------
    # Step 1 — Find pricing page, extract tier price + pricing model
    # ------------------------------------------------------------------
    lowest_price_monthly = None
    pricing_model = "unknown"

    try:
        results = search_web(f'"{company_name}" pricing', max_results=3)
        sources.append("ddg_search")
        print(f"{prefix} Pricing search returned {len(results)} results")

        # Prefer a result whose URL contains "pricing"
        pricing_result = None
        for r in results:
            if "pricing" in (r.get("href") or "").lower():
                pricing_result = r
                break
        if pricing_result is None and results:
            pricing_result = results[0]

        if pricing_result:
            pricing_url = pricing_result.get("href")
            text_blob = " ".join(filter(None, [
                pricing_result.get("title", ""),
                pricing_result.get("body", ""),
            ])).lower()

            # Try fetching the actual pricing page for richer text
            if pricing_url:
                try:
                    resp = httpx.get(
                        pricing_url, timeout=10, follow_redirects=True,
                        headers={"User-Agent": "Mozilla/5.0"},
                    )
                    if resp.status_code == 200:
                        soup = BeautifulSoup(resp.text, "html.parser")
                        text_blob = soup.get_text(separator=" ").lower()
                        sources.append("pricing_page")
                        print(f"{prefix} Fetched pricing page: {pricing_url}")
                except Exception as fe:
                    print(f"{prefix} Could not fetch pricing page ({pricing_url}): {fe}")

            # Classify pricing model
            if any(k in text_blob for k in ["per user", "per seat", "/user", "/seat", "per member"]):
                pricing_model = "per_seat"
            elif any(k in text_blob for k in ["api call", "api calls", "requests", "credits", "usage"]):
                pricing_model = "usage"
            elif any(k in text_blob for k in ["flat rate", "one price", "unlimited users", "flat fee"]):
                pricing_model = "flat"

            # Extract lowest visible price
            # Each tuple: (pattern, is_annual)
            price_patterns = [
                (r'\$(\d[\d,]*)/mo(?:nth)?',           False),
                (r'\$(\d[\d,]*)\s+per\s+mo(?:nth)?',   False),
                (r'starting\s+at\s+\$(\d[\d,]*)',       False),
                (r'\$(\d[\d,]*)/year(?:ly)?',            True),
                (r'\$(\d[\d,]*)\s+per\s+year',           True),
            ]
            candidates = []
            for pat, is_annual in price_patterns:
                for m in re.finditer(pat, text_blob):
                    val = int(m.group(1).replace(",", ""))
                    if is_annual:
                        val = round(val / 12)
                    candidates.append(val)

            if candidates:
                lowest_price_monthly = min(candidates)
                print(f"{prefix} Pricing model={pricing_model}, lowest monthly=${lowest_price_monthly}")
            else:
                print(f"{prefix} No price extracted from pricing page text")
    except Exception as e:
        print(f"{prefix} Pricing search error: {e}")

    # ------------------------------------------------------------------
    # Step 2 — Count customer logos
    # ------------------------------------------------------------------
    logo_count = 0

    try:
        logo_results = search_web(
            f'"{company_name}" customers OR clients trusted by', max_results=3
        )
        if "ddg_search" not in sources:
            sources.append("ddg_search")

        # Determine homepage URL
        home_url = website_url
        if not home_url and logo_results:
            m = re.match(r'(https?://[^/]+)', logo_results[0].get("href", ""))
            if m:
                home_url = m.group(1)

        if home_url:
            try:
                resp = httpx.get(
                    home_url, timeout=10, follow_redirects=True,
                    headers={"User-Agent": "Mozilla/5.0"},
                )
                if resp.status_code == 200:
                    soup = BeautifulSoup(resp.text, "html.parser")
                    sources.append("homepage")

                    # Targeted logo-wall detection — avoid matching body/top-level divs
                    # that inflate counts by pulling in every image on the page.
                    attr_kw = ["logo", "customer", "client", "trust", "partner",
                                "brand", "social-proof"]
                    text_kw = ["trusted by", "used by", "our customers", "our clients",
                                "join", "companies trust"]

                    counted_imgs = set()
                    for container in soup.find_all(["section", "div", "ul"]):
                        # Check class/id attributes for logo-wall signals
                        attrs_str = " ".join(
                            " ".join(container.get(a, []) if isinstance(container.get(a), list)
                                     else [container.get(a, "")])
                            for a in ("class", "id")
                        ).lower()
                        attr_match = any(k in attrs_str for k in attr_kw)

                        # Check direct text (first ~200 chars) for customer phrasing
                        direct_text = container.get_text(separator=" ", strip=True)[:200].lower()
                        text_match = any(k in direct_text for k in text_kw)

                        if not (attr_match or text_match):
                            continue

                        # Count images one level deep only (direct children + their direct children)
                        for img in container.find_all("img", recursive=False):
                            src = img.get("src") or img.get("data-src") or ""
                            if src:
                                counted_imgs.add(src)
                        for child in container.find_all(["li", "div"], recursive=False):
                            for img in child.find_all("img", recursive=False):
                                src = img.get("src") or img.get("data-src") or ""
                                if src:
                                    counted_imgs.add(src)

                    logo_count = min(len(counted_imgs), 100)
                    print(f"{prefix} Found {logo_count} logo images on homepage")
            except Exception as fe:
                print(f"{prefix} Could not fetch homepage ({home_url}): {fe}")

        # Fallback: parse customer count from search snippet text
        if logo_count == 0:
            for r in logo_results:
                body = (r.get("body") or "").lower()
                m = re.search(
                    r'(\d[\d,]+)\+?\s+(?:customers|clients|companies|organizations)',
                    body,
                )
                if m:
                    parsed_count = int(m.group(1).replace(",", ""))
                    logo_count = min(parsed_count, 500)
                    print(f"{prefix} Customer count from snippet: {logo_count}")
                    break
    except Exception as e:
        print(f"{prefix} Customer logo search error: {e}")

    # ------------------------------------------------------------------
    # Step 3 — Revenue estimate
    # ------------------------------------------------------------------
    if lowest_price_monthly is None and logo_count == 0:
        print(f"{prefix} No usable signals found, returning None")
        return None

    if pricing_model == "per_seat":
        arpu = (lowest_price_monthly * 12 * 15) if lowest_price_monthly else 24_000
    elif pricing_model == "flat":
        arpu = int(lowest_price_monthly * 12 * 1.5) if lowest_price_monthly else 24_000
    else:  # usage / unknown
        arpu = 24_000  # $2k/mo fallback

    customer_count = max(logo_count * 3, 10)
    arr = int(customer_count * arpu)
    estimate_low = int(arr * 0.4)
    estimate_high = int(arr * 1.6)

    price_str = f"${lowest_price_monthly}/mo" if lowest_price_monthly else "unknown price"
    basis = (
        f"Pricing: {price_str} {pricing_model}, "
        f"~{logo_count} logo customers → ~{customer_count} estimated → "
        f"~${arr:,} ARR"
    )
    print(f"{prefix} {basis}")

    return {
        "revenue":             arr,
        "estimate_low":        estimate_low,
        "estimate_high":       estimate_high,
        "is_estimated":        True,
        "confidence":          "low",
        "estimate_basis":      basis,
        "estimated_employees": None,
        "sector":              "Technology",
        "industry":            "SaaS",
        "sources":             sources,
    }


def _estimate_services(company_name, website_url, description, prefix):
    REVENUE_PER_EMPLOYEE = {
        "staffing":              65_000,
        "it_consulting":        180_000,
        "management_consulting": 250_000,
        "marketing_agency":     120_000,
        "law_firm":             400_000,
        "accounting":           200_000,
        "research":             160_000,
        "default":              130_000,
    }

    sources = []

    # ------------------------------------------------------------------
    # Step 1 — Find employee count
    # ------------------------------------------------------------------
    employee_count = None

    try:
        results = search_web(
            f'"{company_name}" employees staff headcount team size', max_results=5
        )
        sources.append("ddg_search")
        print(f"{prefix} Employee search returned {len(results)} results")

        for r in results:
            text = " ".join(filter(None, [
                r.get("title", ""), r.get("body", "")
            ])).lower()

            # LinkedIn-style range: "51-200 employees"
            m = re.search(r'(\d+)\s*[-–]\s*(\d+)\s+employees', text)
            if m:
                employee_count = (int(m.group(1)) + int(m.group(2))) // 2
                print(f"{prefix} LinkedIn range: {m.group(0)} → midpoint {employee_count}")
                break

            # Explicit count patterns
            explicit_patterns = [
                r'(\d[\d,]+)\+?\s+employees',
                r'team\s+of\s+(\d[\d,]+)',
                r'(\d[\d,]+)\+?\s+professionals',
                r'(\d[\d,]+)\+?\s+staff',
                r'(\d[\d,]+)\+?\s+people',
                r'over\s+(\d[\d,]+)\s+employees',
            ]
            for pat in explicit_patterns:
                m = re.search(pat, text)
                if m:
                    employee_count = int(m.group(1).replace(",", ""))
                    print(f"{prefix} Employee count from snippet: {employee_count}")
                    break
            if employee_count is not None:
                break
    except Exception as e:
        print(f"{prefix} Employee search error: {e}")

    if employee_count is None:
        print(f"{prefix} No employee count found, returning None")
        return None

    # ------------------------------------------------------------------
    # Step 2 — Classify industry
    # ------------------------------------------------------------------
    text = " ".join(filter(None, [company_name, description or ""])).lower()

    if any(k in text for k in ["staffing", "recruitment", "temp agency", "workforce solutions"]):
        industry_key = "staffing"
    elif any(k in text for k in ["it consulting", "technology consulting", "systems integrator",
                                  "managed service", "msp", "digital transformation"]):
        industry_key = "it_consulting"
    elif any(k in text for k in ["management consulting", "strategy consulting",
                                  "advisory", "mckinsey", "bain", "bcg"]):
        industry_key = "management_consulting"
    elif any(k in text for k in ["marketing agency", "advertising", "pr firm", "creative agency",
                                  "digital marketing", "media agency"]):
        industry_key = "marketing_agency"
    elif any(k in text for k in ["law firm", "legal", "attorney", "lawyer", "counsel"]):
        industry_key = "law_firm"
    elif any(k in text for k in ["accounting", "audit", "cpa", "tax", "bookkeeping"]):
        industry_key = "accounting"
    elif any(k in text for k in ["research", "think tank", "analyst", "market research"]):
        industry_key = "research"
    else:
        industry_key = "default"

    revenue_per_employee = REVENUE_PER_EMPLOYEE[industry_key]
    print(
        f"{prefix} Industry={industry_key}, "
        f"rev/employee=${revenue_per_employee:,}, headcount={employee_count}"
    )

    # ------------------------------------------------------------------
    # Step 3 — Revenue estimate
    # ------------------------------------------------------------------
    estimated_revenue = int(employee_count * revenue_per_employee)
    estimate_low = int(estimated_revenue * 0.5)
    estimate_high = int(estimated_revenue * 1.5)

    basis = (
        f"{employee_count} employees × ${revenue_per_employee:,}/employee "
        f"({industry_key}) → ~${estimated_revenue:,}"
    )
    print(f"{prefix} {basis}")

    return {
        "revenue":             estimated_revenue,
        "estimate_low":        estimate_low,
        "estimate_high":       estimate_high,
        "is_estimated":        True,
        "confidence":          "low",
        "estimate_basis":      basis,
        "estimated_employees": employee_count,
        "sector":              "Services",
        "industry":            industry_key,
        "sources":             sources,
    }


# ---------------------------------------------------------------------------
# Phase 3 — E-Commerce / CPG estimator
# ---------------------------------------------------------------------------

_ECOMMERCE_CATEGORY_PROFILES = {
    "cpg_food":    {"ratio": 75, "avg_price": 18,  "industry": "Consumer Packaged Goods – Food & Beverage"},
    "cpg_beauty":  {"ratio": 50, "avg_price": 35,  "industry": "Consumer Packaged Goods – Beauty & Personal Care"},
    "supplements": {"ratio": 60, "avg_price": 45,  "industry": "Health & Wellness – Supplements"},
    "electronics": {"ratio": 50, "avg_price": 120, "industry": "Consumer Electronics"},
    "apparel":     {"ratio": 40, "avg_price": 60,  "industry": "Apparel & Accessories"},
    "pet":         {"ratio": 65, "avg_price": 30,  "industry": "Pet Products"},
    "default":     {"ratio": 60, "avg_price": 35,  "industry": "E-Commerce / Consumer Goods"},
}

_ECOMMERCE_PLATFORM_MULTIPLIER = {1: 1.0, 2: 1.8, 3: 1.8, 4: 2.5}

_RETAIL_DOMAINS = [
    "amazon.com", "walmart.com", "target.com", "costco.com", "kroger.com",
    "whole-foods.com", "wholefoodsmarket.com", "cvs.com", "walgreens.com",
    "sephora.com", "ulta.com", "nordstrom.com", "macys.com",
]


def _classify_ecommerce_category(company_name, snippets_text):
    """Return a _ECOMMERCE_CATEGORY_PROFILES key based on keyword signals."""
    text = (company_name + " " + snippets_text).lower()
    if any(k in text for k in ["food", "snack", "beverage", "drink", "grocery", "organic", "sauce",
                                "coffee", "tea", "chocolate", "candy", "cereal", "pasta", "protein bar"]):
        return "cpg_food"
    if any(k in text for k in ["supplement", "vitamin", "probiotic", "collagen", "omega", "nootropic",
                                "pre-workout", "whey", "creatine", "multivitamin"]):
        return "supplements"
    if any(k in text for k in ["beauty", "skincare", "cosmetic", "makeup", "serum", "moisturizer",
                                "lipstick", "foundation", "cleanser", "lotion", "shampoo", "conditioner"]):
        return "cpg_beauty"
    if any(k in text for k in ["electronic", "headphone", "speaker", "gadget", "cable", "charger",
                                "laptop", "phone", "camera", "smartwatch", "earbuds"]):
        return "electronics"
    if any(k in text for k in ["apparel", "clothing", "clothes", "shirt", "pants", "dress", "shoes",
                                "sneakers", "jacket", "hoodie", "fashion", "wear"]):
        return "apparel"
    if any(k in text for k in ["pet", "dog", "cat", "puppy", "kitten", "animal", "paw", "treat",
                                "kibble", "leash", "collar"]):
        return "pet"
    return "default"


def _extract_ecommerce_review_counts(snippets):
    """Extract review counts from search result snippets (up to 3 SKUs).

    Handles: "1,234 ratings", "2,456 customer reviews", "(876)",
             "4.5 out of 5 stars 1,234 ratings"
    Returns list of ints, at most 3.
    """
    patterns = [
        r"([\d,]+)\s+ratings",
        r"([\d,]+)\s+customer\s+reviews?",
        r"([\d,]+)\s+reviews?",
        r"\(\s*([\d,]+)\s*\)",
    ]
    counts = []
    for snippet in snippets:
        for pat in patterns:
            for m in re.finditer(pat, snippet, re.IGNORECASE):
                raw = m.group(1).replace(",", "")
                try:
                    val = int(raw)
                    if val >= 5:
                        counts.append(val)
                except ValueError:
                    pass
        if len(counts) >= 3:
            break
    return counts[:3]


def _extract_ecommerce_price(snippets):
    """Extract the first plausible USD product price from snippets. Returns float or None."""
    price_pat = re.compile(r"\$\s*([\d]+(?:\.[\d]{1,2})?)")
    for snippet in snippets:
        m = price_pat.search(snippet)
        if m:
            val = float(m.group(1))
            if 1.0 <= val <= 2000.0:
                return val
    return None


def _extract_retail_platform_domains(results):
    """Return set of distinct retail platform domains found in result hrefs."""
    found = set()
    for r in results:
        href = (r.get("href") or "").lower()
        for domain in _RETAIL_DOMAINS:
            if domain in href:
                found.add(domain)
    return found


def _estimate_ecommerce(company_name, website_url=None):
    """Estimate revenue for e-commerce / CPG brands via Amazon review signals.

    Model:
      annual_units_est ≈ total_reviews × ratio (ratio calibrated for annual output)
      estimated_revenue = annual_units_est × avg_price × platform_multiplier
      platform_multiplier: 1 platform → 1.0x, 2-3 → 1.8x, 4+ → 2.5x
      range: ±50%
    """
    try:
        sources_used = []
        all_snippets = []
        amazon_results = []

        # Step 1 — Amazon review count
        print(f"[ecommerce_est] Searching Amazon reviews for: {company_name}")
        amazon_results = search_web(
            f'"{company_name}" site:amazon.com reviews', max_results=5
        )

        if amazon_results:
            sources_used.append("amazon_search")
            for r in amazon_results:
                all_snippets.append(
                    " ".join(filter(None, [r.get("title", ""), r.get("body", "")]))
                )

        review_counts = _extract_ecommerce_review_counts(all_snippets)

        if not review_counts:
            print(f"[ecommerce_est] No Amazon reviews found, trying fallback search")
            fallback_results = search_web(
                f'"{company_name}" reviews ratings buy online', max_results=5
            )
            if fallback_results:
                sources_used.append("ddg_search")
                fallback_snippets = [
                    " ".join(filter(None, [r.get("title", ""), r.get("body", "")]))
                    for r in fallback_results
                ]
                all_snippets.extend(fallback_snippets)
                review_counts = _extract_ecommerce_review_counts(fallback_snippets)

        if not review_counts:
            print(f"[ecommerce_est] No review counts found for {company_name}, returning None")
            return None

        total_reviews = sum(review_counts)
        sku_count = len(review_counts)
        print(f"[ecommerce_est] Found {sku_count} SKU(s), total reviews: {total_reviews:,}")

        # Step 2 — Platform presence
        print(f"[ecommerce_est] Checking platform presence for: {company_name}")
        buy_results = search_web(f'"{company_name}" buy', max_results=5)
        platform_domains = set()

        if buy_results:
            if "ddg_search" not in sources_used:
                sources_used.append("ddg_search")
            platform_domains = _extract_retail_platform_domains(buy_results)

        if amazon_results:
            platform_domains |= _extract_retail_platform_domains(amazon_results)

        if "amazon_search" in sources_used and not platform_domains:
            platform_domains.add("amazon.com")

        platform_count = max(1, len(platform_domains))
        print(f"[ecommerce_est] Platforms found ({platform_count}): {platform_domains}")

        # Step 3 — Category classification
        combined_text = " ".join(all_snippets)
        category_key = _classify_ecommerce_category(company_name, combined_text)
        profile = _ECOMMERCE_CATEGORY_PROFILES[category_key]
        print(f"[ecommerce_est] Category: {category_key}")

        extracted_price = _extract_ecommerce_price(all_snippets)
        avg_price = extracted_price if extracted_price else profile["avg_price"]
        price_source = "extracted" if extracted_price else "profile default"
        print(f"[ecommerce_est] Avg price: ${avg_price} ({price_source})")

        # Step 4 — Apply model
        platform_mult = _ECOMMERCE_PLATFORM_MULTIPLIER.get(min(platform_count, 4), 2.5)

        annual_units_est = total_reviews * profile["ratio"]
        annual_revenue = annual_units_est * avg_price * platform_mult

        annual_revenue_int = int(round(annual_revenue))
        estimate_low = int(round(annual_revenue * 0.5))
        estimate_high = int(round(annual_revenue * 1.5))

        skus_str = "SKU" if sku_count == 1 else "SKUs"
        platforms_str = "platform" if platform_count == 1 else "platforms"
        price_label = ("$" + f"{avg_price:.2f}").rstrip("0").rstrip(".")
        basis = (
            f"Amazon: {total_reviews:,} reviews ({sku_count} {skus_str}) "
            f"× {profile['ratio']} units/review "
            f"× {price_label} avg "
            f"× {platform_mult}x ({platform_count} {platforms_str})"
        )

        print(
            f"[ecommerce_est] Annual estimate: ${annual_revenue_int:,} "
            f"(low=${estimate_low:,}, high=${estimate_high:,}) | {basis}"
        )

        return {
            "revenue":             annual_revenue_int,
            "estimate_low":        estimate_low,
            "estimate_high":       estimate_high,
            "is_estimated":        True,
            "confidence":          "low",
            "estimate_basis":      basis,
            "estimated_employees": None,
            "sector":              "Consumer Staples",
            "industry":            profile["industry"],
            "sources":             sources_used,
        }

    except Exception as exc:
        print(f"[ecommerce_est] ERROR for {company_name}: {exc}")
        return None

# ---------------------------------------------------------------------------
# Phase 4 — Consumer App estimator
# ---------------------------------------------------------------------------

def _parse_rating_count(text):
    """Parse a rating/review count from a text snippet.

    Handles formats:
      "12.3K Ratings", "1.2M reviews", "8,500 Ratings",
      "4.7 (8,500)", "4.1★ 5K+", "12,345 reviews"
    Returns an int or None.
    """
    text = text.replace(",", "")

    # "4.7 • 12.3K Ratings" — rating dot count pattern, grab the K/M suffix number
    m = re.search(r"[\d.]+\s*[•·★]\s*([\d.]+[KkMm]?)\+?\s*(?:ratings?|reviews?)", text, re.IGNORECASE)
    if m:
        return _parse_k_suffix(m.group(1))

    # "12.3K Ratings" / "8500 Ratings" / "1.2M reviews"
    m = re.search(r"([\d.]+[KkMm]?)\+?\s*(?:ratings?|reviews?)", text, re.IGNORECASE)
    if m:
        return _parse_k_suffix(m.group(1))

    # "4.1★ 5K+" — star rating followed by download/rating count
    m = re.search(r"[\d.]+[★*]\s*([\d.]+[KkMm]?)\+?", text)
    if m:
        return _parse_k_suffix(m.group(1))

    # Parenthesised count: "4.7 (8500)"
    m = re.search(r"\(\s*([\d.]+[KkMm]?)\s*\)", text)
    if m:
        return _parse_k_suffix(m.group(1))

    return None


def _parse_k_suffix(s):
    """Convert '12.3K' → 12300, '1.2M' → 1200000, '8500' → 8500. Returns int or None."""
    s = s.strip()
    if not s:
        return None
    suffix = s[-1].upper()
    if suffix == "K":
        try:
            return int(float(s[:-1]) * 1_000)
        except ValueError:
            return None
    if suffix == "M":
        try:
            return int(float(s[:-1]) * 1_000_000)
        except ValueError:
            return None
    try:
        val = int(float(s))
        return val if val > 0 else None
    except ValueError:
        return None


def _parse_app_price(text):
    """Extract a numeric price from a snippet. Returns float or None.

    Matches '$2.99', '$4.99', etc.  Returns 0.0 for 'Free'.
    """
    if re.search(r"\bfree\b", text, re.IGNORECASE):
        return 0.0
    m = re.search(r"\$([\d]+(?:\.[\d]{1,2})?)", text)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            return None
    return None


def _parse_subscription_price(text):
    """Extract annual subscription price from snippet text.

    Looks for '/month' or '/year' patterns and normalises to annual USD.
    Returns float or None.
    """
    # "/month" pricing: "$X.XX/month" or "$X/mo"
    m = re.search(r"\$([\d]+(?:\.[\d]{1,2})?)\s*/\s*(?:month|mo\b)", text, re.IGNORECASE)
    if m:
        try:
            return float(m.group(1)) * 12
        except ValueError:
            pass

    # "/year" pricing: "$X.XX/year" or "$X/yr"
    m = re.search(r"\$([\d]+(?:\.[\d]{1,2})?)\s*/\s*(?:year|yr\b|annually)", text, re.IGNORECASE)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            pass

    return None


def _estimate_consumer_app(company_name):
    """Estimate revenue for consumer apps via App Store / Play Store signals.

    Model (free apps with IAP):
      downloads_est = total_ratings × 50
      paying_users  = downloads_est × 0.03
      revenue_est   = paying_users × avg_iap_spend_per_year ($20)

    Model (paid apps):
      revenue_est = total_ratings × 40 × price

    Model (subscription apps):
      downloads_est = total_ratings × 50
      subscribers   = downloads_est × 0.05
      revenue_est   = subscribers × subscription_price_annual (default $30/yr)

    Range: ±60%
    """
    SUBSCRIPTION_KEYWORDS = ["subscription", "premium", "pro", "/month", "/year"]

    try:
        print(f"[app_est] Starting estimate for: {company_name}")

        ios_results = search_web(
            f'"{company_name}" app site:apps.apple.com', max_results=3
        )
        print(f"[app_est] iOS App Store query returned {len(ios_results)} results")

        android_results = search_web(
            f'"{company_name}" app site:play.google.com', max_results=3
        )
        print(f"[app_est] Google Play query returned {len(android_results)} results")

        all_results = ios_results + android_results
        if not all_results:
            print("[app_est] No results from either store — returning None")
            return None

        total_ratings = 0
        app_price = None
        has_iap = False
        is_subscription = False
        subscription_price_annual = None
        sources_used = []

        if ios_results:
            sources_used.append("app_store_search")
        if android_results:
            sources_used.append("play_store_search")

        for result in all_results:
            title = result.get("title", "")
            body = result.get("body", "")
            combined = f"{title} {body}"

            # Rating count
            rc = _parse_rating_count(combined)
            if rc is not None:
                print(f"[app_est] Found rating_count={rc:,} in: {title[:60]}")
                total_ratings += rc

            # Subscription detection
            combined_lower = combined.lower()
            if any(kw in combined_lower for kw in SUBSCRIPTION_KEYWORDS):
                is_subscription = True
                sp = _parse_subscription_price(combined)
                if sp is not None and subscription_price_annual is None:
                    subscription_price_annual = sp
                    print(f"[app_est] Found subscription_price_annual=${sp:.2f}")

            # IAP detection
            if "in-app purchase" in combined_lower or "offers in-app" in combined_lower:
                has_iap = True
                print("[app_est] Detected in-app purchases")

            # Price extraction (only override if not yet set)
            if app_price is None:
                p = _parse_app_price(combined)
                if p is not None:
                    app_price = p
                    print(f"[app_est] Found app_price=${p}")

        if total_ratings == 0:
            print("[app_est] No rating counts found in any result — returning None")
            return None

        print(f"[app_est] Total combined ratings: {total_ratings:,}")

        # ---- Revenue model selection ----

        if is_subscription:
            sub_price = subscription_price_annual if subscription_price_annual else 30.0
            downloads_est = total_ratings * 50
            subscribers = downloads_est * 0.05
            revenue_est = subscribers * sub_price
            model_label = "subscription"
            basis = (
                f"App Store + Play Store: {total_ratings:,} ratings, subscription app "
                f"→ ~{int(downloads_est):,} downloads × 5% → ~{int(subscribers):,} "
                f"subscribers × ${sub_price:.0f}/yr"
            )

        elif app_price is not None and app_price > 0:
            revenue_est = total_ratings * 40 * app_price
            model_label = "paid"
            basis = (
                f"App Store + Play Store: {total_ratings:,} ratings, paid app "
                f"(${app_price:.2f}) → {total_ratings:,} × 40 × ${app_price:.2f}"
            )

        else:
            # Free (with or without IAP) — default model
            downloads_est = total_ratings * 50
            paying_users = downloads_est * 0.03
            avg_iap_spend = 20.0
            revenue_est = paying_users * avg_iap_spend
            model_label = "free+IAP"
            basis = (
                f"App Store + Play Store: {total_ratings:,} ratings, free+IAP "
                f"→ ~{int(downloads_est):,} downloads × 3% → ~{int(paying_users):,} "
                f"paying × ${avg_iap_spend:.0f}/yr"
            )

        revenue = int(revenue_est)
        estimate_low = int(revenue_est * 0.4)
        estimate_high = int(revenue_est * 1.6)

        print(
            f"[app_est] Model: {model_label} | revenue=${revenue:,} "
            f"(low=${estimate_low:,}, high=${estimate_high:,}) | {basis}"
        )

        return {
            "revenue":             revenue,
            "estimate_low":        estimate_low,
            "estimate_high":       estimate_high,
            "is_estimated":        True,
            "confidence":          "low",
            "estimate_basis":      basis,
            "estimated_employees": None,
            "sector":              "Technology",
            "industry":            "Mobile Applications",
            "sources":             sources_used,
        }

    except Exception as e:
        print(f"[app_est] Error estimating {company_name}: {e}")
        return None
