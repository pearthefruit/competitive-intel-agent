"""Patent search — USPTO ODP (primary) + Google Patents (secondary)."""

import os
import json
import html
import re
import time

import httpx

# --- USPTO Open Data Portal API (primary, requires free API key) ---

USPTO_ODP_URL = "https://api.uspto.gov/api/v1/patent/applications/search"

# Fields we want from the response
_USPTO_FIELDS = [
    "applicationMetaData.applicationNumberText",
    "applicationMetaData.inventionTitle",
    "applicationMetaData.filingDate",
    "applicationMetaData.applicationStatusDescriptionText",
    "applicationMetaData.firstApplicantName",
    "applicationMetaData.firstInventorName",
    "applicationMetaData.applicationTypeCategory",
    "applicationMetaData.patentNumber",
    "applicationMetaData.uspcSymbolText",
    "applicationMetaData.class",
]


def search_uspto(applicant_query, max_results=25, granted_only=True):
    """Search USPTO ODP by applicant name. Supports wildcards (e.g. 'Microsoft*').

    Returns (list of patent dicts, total_count).
    """
    api_key = os.environ.get("USPTO_API_KEY", "").strip()
    if not api_key:
        # Fall back to old env var name
        api_key = os.environ.get("PATENTSVIEW_API_KEY", "").strip()
    if not api_key:
        return [], 0

    body = {
        "q": f"applicationMetaData.firstApplicantName:{applicant_query}",
        "sort": [{"field": "applicationMetaData.filingDate", "order": "desc"}],
        "pagination": {"offset": 0, "limit": max_results},
        "fields": _USPTO_FIELDS,
    }

    if granted_only:
        body["filters"] = [{
            "name": "applicationMetaData.applicationStatusDescriptionText",
            "value": ["Patented Case"],
        }]

    http = httpx.Client(timeout=30)
    try:
        resp = http.post(
            USPTO_ODP_URL,
            json=body,
            headers={
                "X-API-Key": api_key,
                "Content-Type": "application/json",
            },
        )

        if resp.status_code != 200:
            print(f"[patents] USPTO ODP returned {resp.status_code}")
            return [], 0

        data = resp.json()
        total = data.get("count", 0)
        raw = data.get("patentFileWrapperDataBag", [])

        results = []
        for item in raw:
            meta = item.get("applicationMetaData", {})
            patent_num = meta.get("patentNumber", "")
            results.append({
                "title": meta.get("inventionTitle", ""),
                "date": meta.get("filingDate", ""),
                "number": patent_num or meta.get("applicationNumberText", ""),
                "assignee": meta.get("firstApplicantName", ""),
                "inventor": meta.get("firstInventorName", ""),
                "filing_date": meta.get("filingDate", ""),
                "status": meta.get("applicationStatusDescriptionText", ""),
                "type": meta.get("applicationTypeCategory", ""),
                "uspc_class": meta.get("uspcSymbolText", ""),
                "url": f"https://patents.google.com/patent/US{patent_num}" if patent_num else "",
            })

        print(f"[patents] Found {total} patents via USPTO ODP, retrieved {len(results)}")
        return results, total

    except Exception as e:
        print(f"[patents] USPTO ODP error: {e}")
        return [], 0
    finally:
        http.close()


# --- Google Patents (no API key needed, secondary) ---

_GP_URL = "https://patents.google.com/xhr/query"
_GP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
}


def _clean_html_entities(text):
    """Decode HTML entities and strip leftover tags."""
    text = html.unescape(text)
    text = re.sub(r"<[^>]+>", "", text)
    return text.strip()


def search_google_patents(company_name, max_results=25):
    """Search Google Patents by assignee. No API key needed.

    Returns (list of patent dicts, total_count).
    """
    query = company_name.replace(" ", "+")

    http = httpx.Client(timeout=20, follow_redirects=True)
    try:
        params = {
            "url": f"assignee={query}&num={max_results}&type=PATENT&sort=new",
        }

        resp = http.get(_GP_URL, params=params, headers=_GP_HEADERS)
        if resp.status_code == 503:
            print("[patents] Google Patents rate limited, retrying in 3s...")
            time.sleep(3)
            resp = http.get(_GP_URL, params=params, headers=_GP_HEADERS)

        if resp.status_code != 200:
            print(f"[patents] Google Patents returned {resp.status_code}")
            return [], 0

        data = resp.json()
        results_data = data.get("results", {})
        total = results_data.get("total_num_results", 0)

        if not total:
            if "corporation" not in company_name.lower() and " " not in company_name:
                alt_query = f"{query}+Corporation"
                params["url"] = f"assignee={alt_query}&num={max_results}&type=PATENT&sort=new"
                resp = http.get(_GP_URL, params=params, headers=_GP_HEADERS)
                if resp.status_code == 200:
                    data = resp.json()
                    results_data = data.get("results", {})
                    total = results_data.get("total_num_results", 0)

        if not total:
            return [], 0

        clusters = results_data.get("cluster", [])
        if not clusters:
            return [], total

        patents = []
        for item in clusters[0].get("result", []):
            p = item.get("patent", {})
            pub_number = p.get("publication_number", "")

            family = p.get("family_metadata", {}).get("aggregated", {})
            country_status = family.get("country_status", [])
            active_countries = [
                cs["country_code"] for cs in country_status
                if cs.get("best_patent_stage", {}).get("state") == "ACTIVE"
            ]

            patents.append({
                "title": _clean_html_entities(p.get("title", "")),
                "date": p.get("publication_date", ""),
                "number": pub_number,
                "abstract": _clean_html_entities(p.get("snippet", ""))[:300],
                "assignee": p.get("assignee", ""),
                "inventor": p.get("inventor", ""),
                "priority_date": p.get("priority_date", ""),
                "filing_date": p.get("filing_date", ""),
                "active_countries": active_countries,
                "url": f"https://patents.google.com/patent/{pub_number}/en",
            })

        print(f"[patents] Found {total} total patents via Google Patents, retrieved {len(patents)}")
        return patents, total

    except Exception as e:
        print(f"[patents] Google Patents error: {e}")
        return [], 0
    finally:
        http.close()


# --- Relevance filter ---

def _normalize_for_match(name):
    """Normalize a name for fuzzy assignee matching."""
    if not name:
        return ""
    n = name.lower().strip()
    # Strip common suffixes
    for suffix in [" inc.", " inc", " llc", " ltd.", " ltd", " co.", " co",
                   " corp.", " corp", " corporation", " gmbh", " ag",
                   " s.a.", " plc", " limited", " technologies", " technology"]:
        if n.endswith(suffix):
            n = n[:-len(suffix)].strip()
    # Remove punctuation and extra spaces
    n = re.sub(r"[^a-z0-9 ]", "", n)
    n = re.sub(r"\s+", " ", n).strip()
    return n


def _is_relevant_assignee(assignee, company_name):
    """Check if a patent assignee is plausibly related to the target company."""
    if not assignee:
        return True  # No assignee data — keep it, let LLM decide
    norm_assignee = _normalize_for_match(assignee)
    norm_company = _normalize_for_match(company_name)
    if not norm_company:
        return True

    # Exact or substring match (either direction)
    if norm_company in norm_assignee or norm_assignee in norm_company:
        return True

    # Word overlap: all significant words of the company must appear in the assignee
    company_words = set(norm_company.split())
    # Drop very common short words that cause false matches
    stop_words = {"the", "and", "of", "for", "a", "an", "in", "on", "at", "to", "by"}
    company_words -= stop_words
    if not company_words:
        return True

    assignee_words = set(norm_assignee.split())
    # All company name words must be in the assignee (in any order)
    if company_words.issubset(assignee_words):
        return True

    return False


def filter_relevant_patents(patents, company_name):
    """Filter patent list to only those with assignees plausibly matching the company.

    Returns (filtered_patents, removed_count).
    """
    relevant = []
    removed = 0
    for p in patents:
        if _is_relevant_assignee(p.get("assignee", ""), company_name):
            relevant.append(p)
        else:
            removed += 1
    if removed:
        print(f"[patents] Filtered {removed} irrelevant patents (assignee mismatch)")
    return relevant, removed


# --- Public API: try USPTO ODP first, then Google Patents ---

def search_patents(company_name, max_results=25):
    """Search for patents by company. Tries USPTO ODP (wildcard), then Google Patents.

    Returns (list of patent dicts, total_count, source_name).
    """
    # Primary: USPTO ODP with wildcard on company name
    query = f"{company_name}*"
    patents, total = search_uspto(query, max_results)
    if patents:
        patents, removed = filter_relevant_patents(patents, company_name)
        if patents:
            return patents, total - removed, "USPTO ODP"

    # Secondary: Google Patents (no key needed)
    print("[patents] Trying Google Patents as fallback...")
    patents, total = search_google_patents(company_name, max_results)
    if patents:
        patents, removed = filter_relevant_patents(patents, company_name)
        if patents:
            return patents, total - removed, "Google Patents"

    return [], 0, None


def search_patents_with_name(name_query, max_results=25):
    """Search USPTO with a specific applicant name query (for agentic retries).

    Returns (list of patent dicts, total_count).
    """
    clean_name = name_query.rstrip("*").strip()
    patents, total = search_uspto(name_query, max_results)
    if patents:
        patents, removed = filter_relevant_patents(patents, clean_name)
        if patents:
            return patents, total - removed
    # Try Google Patents with the raw name
    patents, total = search_google_patents(clean_name, max_results)
    if patents:
        patents, removed = filter_relevant_patents(patents, clean_name)
        if patents:
            return patents, total - removed
    return [], 0


def format_patents_for_prompt(patents, total_count):
    """Format patent data into a string for the LLM prompt."""
    lines = [f"Total patents found: {total_count}"]
    lines.append(f"Showing {len(patents)} most recent:\n")

    for i, p in enumerate(patents, 1):
        url = p.get("url", f"https://patents.google.com/patent/{p['number']}")
        lines.append(f"### Patent {i}: {p['title']}")
        lines.append(f"  Number: {p['number']} | Filed: {p['date']}")
        lines.append(f"  URL: {url}")

        if p.get("assignee"):
            lines.append(f"  Assignee: {p['assignee']}")
        if p.get("inventor"):
            lines.append(f"  Inventor: {p['inventor']}")
        if p.get("priority_date"):
            lines.append(f"  Priority Date: {p['priority_date']}")
        if p.get("filing_date") and p.get("filing_date") != p.get("date"):
            lines.append(f"  Filing Date: {p['filing_date']}")
        if p.get("active_countries"):
            lines.append(f"  Active in: {', '.join(p['active_countries'])}")
        if p.get("status"):
            lines.append(f"  Status: {p['status']}")
        if p.get("uspc_class"):
            lines.append(f"  USPC Class: {p['uspc_class']}")

        # PatentsView/Google Patents fields
        if p.get("citations"):
            lines.append(f"  Citations: {p['citations']} | Claims: {p.get('claims', 0)}")
        if p.get("cpc_categories"):
            cats = ", ".join(c["title"] or c["id"] for c in p["cpc_categories"])
            lines.append(f"  CPC Categories: {cats}")

        if p.get("abstract"):
            lines.append(f"  Abstract: {p['abstract']}")
        lines.append("")

    # Aggregate USPC classes if present (USPTO ODP data)
    class_counts = {}
    for p in patents:
        cls = p.get("uspc_class", "")
        if cls:
            class_counts[cls] = class_counts.get(cls, 0) + 1

    if class_counts:
        lines.append("\n### Technology Class Distribution (USPC)")
        for cls, count in sorted(class_counts.items(), key=lambda x: -x[1])[:15]:
            lines.append(f"  {cls}: {count} patents")

    # Aggregate CPC categories if present (Google Patents data)
    cpc_counts = {}
    for p in patents:
        for c in p.get("cpc_categories", []):
            title = c["title"] or c["id"]
            cpc_counts[title] = cpc_counts.get(title, 0) + 1

    if cpc_counts:
        lines.append("\n### Technology Category Distribution (CPC)")
        for cat, count in sorted(cpc_counts.items(), key=lambda x: -x[1])[:15]:
            lines.append(f"  {cat}: {count} patents")

    return "\n".join(lines)
