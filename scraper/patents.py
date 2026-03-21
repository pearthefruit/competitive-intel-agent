"""PatentsView API client — search US patent data by company."""

import os
import json
from urllib.parse import quote

import httpx

# New PatentSearch API (legacy API was retired Feb 2025)
# Requires free API key from https://patentsview.org/apis/keyrequest
PATENTSVIEW_URL = "https://search.patentsview.org/api/v1/patent/"


def search_patents(company_name, max_results=25):
    """Search PatentsView for patents assigned to a company.

    Requires PATENTSVIEW_API_KEY env var (free registration).
    Returns (list of patent dicts, total_count).
    """
    api_key = os.environ.get("PATENTSVIEW_API_KEY", "").strip()
    if not api_key:
        print("[patents] No PATENTSVIEW_API_KEY set — get a free key at https://patentsview.org/apis/keyrequest")
        return [], 0

    print(f"[patents] Searching PatentsView for '{company_name}'...")

    # Build query params for the new GET-based API
    q = json.dumps({"assignee_organization": company_name})
    f = json.dumps([
        "patent_id", "patent_title", "patent_date", "patent_abstract",
        "patent_num_us_patents_cited", "patent_num_claims",
        "assignees.assignee_organization",
        "cpcs.cpc_group_id", "cpcs.cpc_group_title",
    ])
    s = json.dumps([{"patent_date": "desc"}])

    params = {
        "q": q,
        "f": f,
        "s": s,
        "per_page": str(max_results),
    }

    http = httpx.Client(timeout=30)
    try:
        resp = http.get(
            PATENTSVIEW_URL,
            params=params,
            headers={"X-Api-Key": api_key},
        )

        if resp.status_code != 200:
            print(f"[patents] PatentsView API returned {resp.status_code}: {resp.text[:200]}")
            return [], 0

        data = resp.json()
        total = data.get("total_patent_count", 0)
        patents = data.get("patents", [])

        print(f"[patents] Found {total} total patents, retrieved {len(patents)}")

        results = []
        for p in patents:
            # Extract CPC categories
            cpcs = p.get("cpcs", []) or []
            cpc_categories = []
            seen_groups = set()
            for cpc in cpcs:
                group_id = cpc.get("cpc_group_id", "")
                group_title = cpc.get("cpc_group_title", "")
                if group_id and group_id not in seen_groups:
                    seen_groups.add(group_id)
                    cpc_categories.append({
                        "id": group_id,
                        "title": group_title,
                    })

            results.append({
                "title": p.get("patent_title", ""),
                "date": p.get("patent_date", ""),
                "number": p.get("patent_id", ""),
                "abstract": (p.get("patent_abstract", "") or "")[:300],
                "citations": p.get("patent_num_us_patents_cited", 0) or 0,
                "claims": p.get("patent_num_claims", 0) or 0,
                "cpc_categories": cpc_categories[:3],
            })

        return results, total

    except Exception as e:
        print(f"[patents] Error: {e}")
        return [], 0
    finally:
        http.close()


def format_patents_for_prompt(patents, total_count):
    """Format patent data into a string for the LLM prompt."""
    lines = [f"Total patents found: {total_count}"]
    lines.append(f"Showing {len(patents)} most recent:\n")

    for i, p in enumerate(patents, 1):
        lines.append(f"### Patent {i}: {p['title']}")
        lines.append(f"  Number: US{p['number']} | Date: {p['date']}")
        lines.append(f"  Citations: {p['citations']} | Claims: {p['claims']}")

        if p["cpc_categories"]:
            cats = ", ".join(c["title"] or c["id"] for c in p["cpc_categories"])
            lines.append(f"  CPC Categories: {cats}")

        if p["abstract"]:
            lines.append(f"  Abstract: {p['abstract']}")
        lines.append("")

    # Aggregate CPC categories
    cpc_counts = {}
    for p in patents:
        for c in p["cpc_categories"]:
            title = c["title"] or c["id"]
            cpc_counts[title] = cpc_counts.get(title, 0) + 1

    if cpc_counts:
        lines.append("\n### Technology Category Distribution")
        for cat, count in sorted(cpc_counts.items(), key=lambda x: -x[1])[:15]:
            lines.append(f"  {cat}: {count} patents")

    return "\n".join(lines)
