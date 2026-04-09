"""SQLite database setup and helpers for competitive-intel-agent."""

import json
import sqlite3
import hashlib
from datetime import datetime, timezone

# Default lens slug — used as fallback when no lens_id specified for briefing
DT_LENS_SLUG = "digital-transformation"

_VALID_DOMAINS = {"economics", "finance", "geopolitics", "tech_ai", "labor", "regulatory"}
_DOMAIN_ALIASES = {
    "software_development": "tech_ai", "technology": "tech_ai", "artificial_intelligence": "tech_ai",
    "tech": "tech_ai", "ai": "tech_ai", "software": "tech_ai", "automation": "tech_ai",
    "hiring": "labor", "employment": "labor", "workforce": "labor", "jobs": "labor",
    "financial": "finance", "markets": "finance", "banking": "finance",
    "political": "geopolitics", "trade": "geopolitics", "policy": "geopolitics",
    "regulation": "regulatory", "compliance": "regulatory", "legal": "regulatory",
    "economic": "economics", "macro": "economics",
}


def sanitize_domain(raw):
    """Normalize a domain string (possibly pipe-separated) to valid domain(s).
    Preserves multiple domains as pipe-separated string."""
    if not raw:
        return "economics"
    parts = [p.strip().lower() for p in raw.split("|")]
    valid = []
    for p in parts:
        if p in _VALID_DOMAINS:
            if p not in valid:
                valid.append(p)
        elif p in _DOMAIN_ALIASES:
            mapped = _DOMAIN_ALIASES[p]
            if mapped not in valid:
                valid.append(mapped)
    return "|".join(valid) if valid else "economics"


def merge_domains(existing_domain, new_domain):
    """Combine two domain strings into a pipe-separated multi-domain string."""
    parts = set()
    for raw in (existing_domain, new_domain):
        if raw:
            for p in raw.split("|"):
                p = p.strip().lower()
                if p in _VALID_DOMAINS:
                    parts.add(p)
                elif p in _DOMAIN_ALIASES:
                    parts.add(_DOMAIN_ALIASES[p])
    return "|".join(sorted(parts)) if parts else "economics"


SCHEMA = """
CREATE TABLE IF NOT EXISTS companies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    url TEXT,
    ats_type TEXT,
    seniority_framework TEXT,
    last_scraped TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL,
    title TEXT,
    department TEXT,
    location TEXT,
    url TEXT UNIQUE,
    description TEXT,
    description_hash TEXT,
    salary TEXT,
    date_posted TEXT,
    scrape_status TEXT DEFAULT 'scraped',
    scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (company_id) REFERENCES companies(id)
);

CREATE TABLE IF NOT EXISTS classifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL UNIQUE,
    department_category TEXT,
    department_subcategory TEXT,
    seniority_level TEXT,
    key_skills TEXT,
    strategic_signals TEXT,
    strategic_tags TEXT,
    growth_signal TEXT,
    classified_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    model_used TEXT,
    FOREIGN KEY (job_id) REFERENCES jobs(id)
);

-- Company dossiers: persistent knowledge that accumulates across scans
CREATE TABLE IF NOT EXISTS dossiers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_name TEXT NOT NULL UNIQUE COLLATE NOCASE,
    sector TEXT,
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Each analysis run gets stored here with extracted key facts
CREATE TABLE IF NOT EXISTS dossier_analyses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dossier_id INTEGER NOT NULL,
    analysis_type TEXT NOT NULL,
    report_file TEXT,
    key_facts_json TEXT,
    model_used TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (dossier_id) REFERENCES dossiers(id)
);

-- Timeline events: strategic moves, news, changes detected between scans
CREATE TABLE IF NOT EXISTS dossier_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dossier_id INTEGER NOT NULL,
    event_date TEXT,
    event_type TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT,
    source_url TEXT,
    data_json TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (dossier_id) REFERENCES dossiers(id)
);

-- Hiring snapshots: periodic captures of hiring stats for temporal trend analysis
CREATE TABLE IF NOT EXISTS hiring_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL REFERENCES companies(id),
    snapshot_date TEXT NOT NULL,
    total_roles INTEGER,
    dept_counts TEXT,
    subcategory_counts TEXT,
    seniority_counts TEXT,
    strategic_tag_counts TEXT,
    ai_ml_role_count INTEGER,
    growth_signal_ratio TEXT,
    top_skills TEXT,
    top_locations TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(company_id, snapshot_date)
);

CREATE TABLE IF NOT EXISTS llm_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    key_hint TEXT,
    status TEXT NOT NULL,
    error TEXT,
    caller TEXT,
    input_tokens INTEGER,
    output_tokens INTEGER,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS icp_profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT,
    is_default INTEGER DEFAULT 0,
    is_active INTEGER DEFAULT 0,
    survey_answers_json TEXT,
    config_json TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS campaigns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    niche TEXT NOT NULL,
    name TEXT,
    top_n INTEGER,
    status TEXT DEFAULT 'running',
    insight_json TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS campaign_prospects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id INTEGER NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    dossier_id INTEGER NOT NULL REFERENCES dossiers(id),
    validation_status TEXT,
    validation_reason TEXT,
    prospect_status TEXT DEFAULT 'new',
    brief_json TEXT,
    discovered_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(campaign_id, dossier_id)
);

CREATE TABLE IF NOT EXISTS lenses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    slug TEXT NOT NULL UNIQUE,
    description TEXT,
    config_json TEXT NOT NULL,
    is_preset INTEGER DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS lens_scores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dossier_id INTEGER NOT NULL REFERENCES dossiers(id),
    lens_id INTEGER NOT NULL REFERENCES lenses(id),
    overall_score INTEGER,
    overall_label TEXT,
    score_json TEXT NOT NULL,
    analyses_used TEXT,
    scored_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(dossier_id, lens_id)
);

-- Signals: raw items collected from data sources for macro monitoring
CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    domain TEXT NOT NULL,
    title TEXT NOT NULL,
    url TEXT,
    body TEXT,
    published_at TEXT,
    source_name TEXT,
    content_hash TEXT UNIQUE,
    raw_json TEXT,
    collected_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Narratives: top-level hypotheses that own threads
CREATE TABLE IF NOT EXISTS narratives (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    thesis TEXT NOT NULL,
    reasoning TEXT,
    sub_claims_json TEXT,
    search_queries_json TEXT,
    confidence_score INTEGER,
    status TEXT DEFAULT 'active',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Hypothesis bank: lightweight investigation leads from brainstorm
CREATE TABLE IF NOT EXISTS hypotheses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    reasoning TEXT,
    confidence TEXT DEFAULT 'medium',
    investigate_query TEXT,
    source_thread_ids TEXT,
    source_entities_json TEXT,
    status TEXT DEFAULT 'captured',
    narrative_id INTEGER REFERENCES narratives(id),
    brainstorm_id INTEGER REFERENCES brainstorms(id),
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Signal clusters: LLM-synthesized groupings of related signals
CREATE TABLE IF NOT EXISTS signal_clusters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    domain TEXT NOT NULL,
    title TEXT NOT NULL,
    synthesis TEXT,
    opportunity_score INTEGER,
    opportunity_type TEXT,
    estimated_scope TEXT,
    status TEXT DEFAULT 'active',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Junction table linking signals to clusters
CREATE TABLE IF NOT EXISTS signal_cluster_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cluster_id INTEGER NOT NULL REFERENCES signal_clusters(id) ON DELETE CASCADE,
    signal_id INTEGER NOT NULL REFERENCES signals(id),
    UNIQUE(cluster_id, signal_id)
);

-- Scan history: last few execution results (not full pipeline, just outcomes)
CREATE TABLE IF NOT EXISTS scan_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    total_collected INTEGER,
    new_inserted INTEGER,
    domains_json TEXT,
    threads_created INTEGER DEFAULT 0,
    threads_assigned INTEGER DEFAULT 0,
    articles_enriched INTEGER DEFAULT 0,
    entities_extracted INTEGER DEFAULT 0,
    duration_seconds REAL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Brainstorm sessions: persisted hypothesis generation from connected threads
CREATE TABLE IF NOT EXISTS brainstorms (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    thread_ids TEXT NOT NULL,
    connection_summary TEXT,
    hypotheses_json TEXT,
    second_order_json TEXT,
    questions_json TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Manual thread links created by the user
CREATE TABLE IF NOT EXISTS thread_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    thread_a_id INTEGER NOT NULL REFERENCES signal_clusters(id),
    thread_b_id INTEGER NOT NULL REFERENCES signal_clusters(id),
    label TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(thread_a_id, thread_b_id)
);

-- Board positions: pinned node locations for investigation board
CREATE TABLE IF NOT EXISTS board_positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    node_type TEXT NOT NULL DEFAULT 'thread',
    node_id INTEGER NOT NULL,
    x REAL NOT NULL,
    y REAL NOT NULL,
    pinned INTEGER DEFAULT 1,
    UNIQUE(node_type, node_id)
);

-- Board notes: sticky notes on the investigation board
CREATE TABLE IF NOT EXISTS board_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    text TEXT NOT NULL,
    x REAL NOT NULL,
    y REAL NOT NULL,
    color TEXT DEFAULT '#eab308',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Extracted entities from signals for entity linking
CREATE TABLE IF NOT EXISTS signal_entities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_id INTEGER REFERENCES signals(id),
    cluster_id INTEGER REFERENCES signal_clusters(id),
    entity_type TEXT NOT NULL,
    entity_value TEXT NOT NULL,
    normalized_value TEXT,
    dossier_id INTEGER REFERENCES dossiers(id),
    campaign_id INTEGER REFERENCES campaigns(id),
    metadata_json TEXT
);

-- Named paths through the causal graph (saved chain views)
CREATE TABLE IF NOT EXISTS causal_paths (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    thread_ids_json TEXT NOT NULL,
    status TEXT DEFAULT 'active',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Directed causal links between threads (temporal/causal view)
CREATE TABLE IF NOT EXISTS causal_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cause_thread_id INTEGER NOT NULL REFERENCES signal_clusters(id),
    effect_thread_id INTEGER NOT NULL REFERENCES signal_clusters(id),
    label TEXT,
    hypothesis_id INTEGER REFERENCES hypotheses(id),
    confidence TEXT DEFAULT 'medium',
    status TEXT DEFAULT 'captured',
    reasoning TEXT,
    brainstorm_id INTEGER REFERENCES brainstorms(id),
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(cause_thread_id, effect_thread_id)
);
"""


def get_connection(db_path="intel.db"):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=10000")
    return conn


def _migrate_db(conn):
    """Add columns that may not exist in older databases."""
    migrations = [
        ("classifications", "department_subcategory", "TEXT"),
        ("classifications", "strategic_tags", "TEXT"),
        ("companies", "seniority_framework", "TEXT"),
        ("dossiers", "briefing_json", "TEXT"),
        ("dossiers", "briefing_generated_at", "TIMESTAMP"),
        ("dossiers", "briefing_model", "TEXT"),
        ("llm_usage", "input_tokens", "INTEGER"),
        ("llm_usage", "output_tokens", "INTEGER"),
        ("dossiers", "ua_fit_json", "TEXT"),
        ("dossiers", "ua_fit_generated_at", "TEXT"),
        ("dossiers", "icp_profile_id", "INTEGER"),
        ("dossiers", "website_url", "TEXT"),
        ("campaign_prospects", "discovery_json", "TEXT"),
        ("dossiers", "briefing_lens_id", "INTEGER"),
        ("campaigns", "parent_campaign_id", "INTEGER"),
        ("campaigns", "seed_company", "TEXT"),
        ("campaigns", "execution_log_json", "TEXT"),
        ("dossiers", "financial_snapshot_json", "TEXT"),
        ("dossiers", "financial_snapshot_at", "TEXT"),
        ("campaigns", "niche_eval_json", "TEXT"),
        ("campaigns", "scoring_lens_id", "INTEGER"),
        ("jobs", "source_board", "TEXT"),
        ("campaigns", "signal_cluster_id", "INTEGER"),
        ("signal_clusters", "last_signal_at", "TEXT"),
        ("signals", "signal_status", "TEXT DEFAULT 'signal'"),
        ("signals", "source_type", "TEXT DEFAULT 'news'"),
        ("signal_clusters", "narrative_id", "INTEGER REFERENCES narratives(id)"),
        ("signal_cluster_items", "evidence_stance", "TEXT DEFAULT 'neutral'"),
    ]
    for table, column, col_type in migrations:
        try:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
        except sqlite3.OperationalError:
            pass  # Column already exists
    conn.commit()


def init_db(db_path="intel.db"):
    conn = get_connection(db_path)
    conn.executescript(SCHEMA)
    _migrate_db(conn)
    ensure_default_icp_profile(conn)
    ensure_preset_lenses(conn)
    conn.commit()
    conn.close()


def log_llm_call(provider, model, key_hint, status, error=None, caller=None,
                  input_tokens=None, output_tokens=None, db_path="intel.db"):
    """Log an LLM API call for usage tracking."""
    try:
        conn = get_connection(db_path)
        conn.execute(
            "INSERT INTO llm_usage (provider, model, key_hint, status, error, caller, input_tokens, output_tokens) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (provider, model, key_hint, status, error, caller, input_tokens, output_tokens),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[log_llm_call] LOGGING FAILED: {e}")


def get_llm_usage_stats(db_path="intel.db"):
    """Get LLM usage statistics for today and all time."""
    try:
        conn = get_connection(db_path)
        today = datetime.now().strftime("%Y-%m-%d")

        # Today's calls by provider/model (convert UTC timestamps to local time)
        today_rows = conn.execute(
            """SELECT provider, model, key_hint, status, COUNT(*) as cnt,
                      COALESCE(SUM(input_tokens), 0) as input_tokens,
                      COALESCE(SUM(output_tokens), 0) as output_tokens
               FROM llm_usage WHERE DATE(created_at, 'localtime') = ?
               GROUP BY provider, model, key_hint, status
               ORDER BY cnt DESC""",
            (today,)
        ).fetchall()

        # Today's totals
        today_total = conn.execute(
            """SELECT COUNT(*) as total,
                      SUM(CASE WHEN status='success' THEN 1 ELSE 0 END) as success,
                      COALESCE(SUM(input_tokens), 0) as input_tokens,
                      COALESCE(SUM(output_tokens), 0) as output_tokens
               FROM llm_usage WHERE DATE(created_at, 'localtime') = ?""",
            (today,)
        ).fetchone()

        # All time totals
        all_total = conn.execute(
            """SELECT COUNT(*) as total,
                      SUM(CASE WHEN status='success' THEN 1 ELSE 0 END) as success,
                      COALESCE(SUM(input_tokens), 0) as input_tokens,
                      COALESCE(SUM(output_tokens), 0) as output_tokens
               FROM llm_usage"""
        ).fetchone()

        # Recent errors
        recent_errors = conn.execute(
            """SELECT provider, model, key_hint, error, created_at
               FROM llm_usage WHERE status != 'success' AND DATE(created_at, 'localtime') = ?
               ORDER BY created_at DESC LIMIT 10""",
            (today,)
        ).fetchall()

        # Hourly breakdown today (show local hours)
        hourly = conn.execute(
            """SELECT strftime('%H', created_at, 'localtime') as hour, COUNT(*) as cnt,
                      SUM(CASE WHEN status='success' THEN 1 ELSE 0 END) as success
               FROM llm_usage WHERE DATE(created_at, 'localtime') = ?
               GROUP BY hour ORDER BY hour""",
            (today,)
        ).fetchall()

        conn.close()

        return {
            "date": today,
            "today": {
                "total": today_total["total"] if today_total else 0,
                "success": today_total["success"] if today_total else 0,
                "input_tokens": today_total["input_tokens"] if today_total else 0,
                "output_tokens": today_total["output_tokens"] if today_total else 0,
                "by_provider": [dict(r) for r in today_rows],
                "hourly": [dict(r) for r in hourly],
            },
            "all_time": {
                "total": all_total["total"] if all_total else 0,
                "success": all_total["success"] if all_total else 0,
                "input_tokens": all_total["input_tokens"] if all_total else 0,
                "output_tokens": all_total["output_tokens"] if all_total else 0,
            },
            "recent_errors": [dict(r) for r in recent_errors],
        }
    except Exception as e:
        return {"error": str(e)}


def hash_description(text):
    if not text:
        return None
    return hashlib.sha256(text.encode()).hexdigest()


def upsert_company(conn, name, url=None, ats_type=None):
    """Insert or update a company. Returns the company id."""
    row = conn.execute(
        "SELECT id FROM companies WHERE name = ? COLLATE NOCASE",
        (name,),
    ).fetchone()
    if row:
        company_id = row["id"]
        conn.execute(
            "UPDATE companies SET last_scraped = ?, url = COALESCE(?, url), ats_type = COALESCE(?, ats_type) WHERE id = ?",
            (datetime.now(timezone.utc).isoformat(), url, ats_type, company_id),
        )
    else:
        cur = conn.execute(
            "INSERT INTO companies (name, url, ats_type, last_scraped) VALUES (?, ?, ?, ?)",
            (name, url, ats_type, datetime.now(timezone.utc).isoformat()),
        )
        company_id = cur.lastrowid
    conn.commit()
    return company_id


def insert_job(conn, company_id, job_dict, source_board=None):
    """Insert a job, skipping duplicates by URL. Returns True if inserted."""
    desc_hash = hash_description(job_dict.get("description", ""))
    try:
        conn.execute(
            """INSERT OR IGNORE INTO jobs
               (company_id, title, department, location, url, description, description_hash, salary, date_posted, source_board)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                company_id,
                job_dict.get("title"),
                job_dict.get("department"),
                job_dict.get("location"),
                job_dict.get("url"),
                job_dict.get("description"),
                desc_hash,
                job_dict.get("salary"),
                job_dict.get("date_posted"),
                source_board,
            ),
        )
        conn.commit()
        return conn.total_changes > 0
    except sqlite3.IntegrityError:
        return False


def get_company_id(conn, name):
    row = conn.execute(
        "SELECT id FROM companies WHERE name = ? COLLATE NOCASE", (name,)
    ).fetchone()
    return row["id"] if row else None


def get_company_seniority_framework(conn, company_id):
    """Get the stored seniority framework for a company, or None."""
    row = conn.execute(
        "SELECT seniority_framework FROM companies WHERE id = ?", (company_id,)
    ).fetchone()
    return row["seniority_framework"] if row and row["seniority_framework"] else None


def set_company_seniority_framework(conn, company_id, framework):
    """Store the seniority framework for a company."""
    conn.execute(
        "UPDATE companies SET seniority_framework = ? WHERE id = ?",
        (framework, company_id),
    )
    conn.commit()


def get_unclassified_jobs(conn, company_id):
    rows = conn.execute(
        """SELECT j.* FROM jobs j
           WHERE j.company_id = ?
             AND j.id NOT IN (SELECT job_id FROM classifications)
           ORDER BY j.id""",
        (company_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def _to_json_str(value, default="[]"):
    """Convert a value to a JSON string for storage."""
    if isinstance(value, str):
        return value
    return str(value) if value is not None else default


def insert_classification(conn, job_id, classification, model_used):
    conn.execute(
        """INSERT OR REPLACE INTO classifications
           (job_id, department_category, department_subcategory, seniority_level,
            key_skills, strategic_signals, strategic_tags, growth_signal, model_used)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            job_id,
            classification.get("department_category"),
            classification.get("department_subcategory", "General"),
            classification.get("seniority_level"),
            _to_json_str(classification.get("key_skills")),
            classification.get("strategic_signals", ""),  # now a sentence, not JSON array
            _to_json_str(classification.get("strategic_tags")),
            classification.get("growth_signal"),
            model_used,
        ),
    )
    conn.commit()


def clear_classifications(conn, company_id):
    """Delete all classifications for a company so jobs can be re-classified."""
    conn.execute(
        "DELETE FROM classifications WHERE job_id IN (SELECT id FROM jobs WHERE company_id = ?)",
        (company_id,),
    )
    conn.commit()


def clear_company_jobs(conn, company_id):
    """Delete all jobs AND classifications for a company, forcing a fresh scrape."""
    conn.execute(
        "DELETE FROM classifications WHERE job_id IN (SELECT id FROM jobs WHERE company_id = ?)",
        (company_id,),
    )
    count = conn.execute("SELECT COUNT(*) FROM jobs WHERE company_id = ?", (company_id,)).fetchone()[0]
    conn.execute("DELETE FROM jobs WHERE company_id = ?", (company_id,))
    conn.commit()
    return count


def get_all_classified_jobs(conn, company_id):
    rows = conn.execute(
        """SELECT j.*, c.department_category, c.department_subcategory,
                  c.seniority_level, c.key_skills,
                  c.strategic_signals, c.strategic_tags,
                  c.growth_signal, c.model_used
           FROM jobs j
           JOIN classifications c ON j.id = c.job_id
           WHERE j.company_id = ?
           ORDER BY c.department_category, c.seniority_level""",
        (company_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_company_info(conn, company_id):
    row = conn.execute("SELECT * FROM companies WHERE id = ?", (company_id,)).fetchone()
    return dict(row) if row else None


# --- Dossier helpers ---

def _find_similar_dossier(conn, name, threshold=0.85):
    """Find an existing dossier with a similar name (fuzzy match).

    Catches typos and spelling variants like 'loveable' → 'Lovable'.
    Returns (dossier_id, canonical_name) or (None, None).
    """
    from difflib import SequenceMatcher
    rows = conn.execute("SELECT id, company_name FROM dossiers").fetchall()
    name_lower = name.lower().strip()
    best_id, best_name, best_ratio = None, None, 0.0
    for row in rows:
        existing = row["company_name"].lower().strip()
        ratio = SequenceMatcher(None, name_lower, existing).ratio()
        if ratio >= threshold and ratio > best_ratio:
            best_id, best_name, best_ratio = row["id"], row["company_name"], ratio
    if best_id:
        return best_id, best_name
    return None, None


def merge_dossiers(conn, keep_name, merge_name):
    """Merge two dossiers — moves all data from merge_name into keep_name, deletes merge_name.

    Returns (kept_id, merged_count) or raises ValueError if either dossier not found.
    """
    keep = conn.execute("SELECT id FROM dossiers WHERE company_name = ? COLLATE NOCASE", (keep_name,)).fetchone()
    merge = conn.execute("SELECT id FROM dossiers WHERE company_name = ? COLLATE NOCASE", (merge_name,)).fetchone()
    if not keep:
        raise ValueError(f"Dossier '{keep_name}' not found")
    if not merge:
        raise ValueError(f"Dossier '{merge_name}' not found")
    if keep["id"] == merge["id"]:
        raise ValueError("Cannot merge a dossier with itself")

    keep_id, merge_id = keep["id"], merge["id"]
    merged = 0

    # Move analyses
    cur = conn.execute("UPDATE dossier_analyses SET dossier_id = ? WHERE dossier_id = ?", (keep_id, merge_id))
    merged += cur.rowcount
    # Move events
    cur = conn.execute("UPDATE dossier_events SET dossier_id = ? WHERE dossier_id = ?", (keep_id, merge_id))
    merged += cur.rowcount
    # Move lens scores (skip duplicates — same lens_id)
    conn.execute("""UPDATE OR IGNORE lens_scores SET dossier_id = ? WHERE dossier_id = ?""", (keep_id, merge_id))
    conn.execute("DELETE FROM lens_scores WHERE dossier_id = ?", (merge_id,))
    # Move campaign prospect links
    conn.execute("UPDATE OR IGNORE campaign_prospects SET dossier_id = ? WHERE dossier_id = ?", (keep_id, merge_id))
    conn.execute("DELETE FROM campaign_prospects WHERE dossier_id = ?", (merge_id,))
    # Delete the merged dossier
    conn.execute("DELETE FROM dossiers WHERE id = ?", (merge_id,))
    conn.commit()
    print(f"[dossier] Merged '{merge_name}' (id={merge_id}) into '{keep_name}' (id={keep_id}), moved {merged} records")
    return keep_id, merged


def get_or_create_dossier(conn, company_name, sector=None, description=None):
    """Get existing dossier or create a new one. Returns dossier id.

    Uses COLLATE NOCASE for exact match, then fuzzy matching (≥85% similarity)
    to catch typos and spelling variants.
    """
    # Exact match (case-insensitive)
    row = conn.execute(
        "SELECT id FROM dossiers WHERE company_name = ? COLLATE NOCASE",
        (company_name,),
    ).fetchone()
    if row:
        dossier_id = row["id"]
        updates = ["updated_at = ?"]
        params = [datetime.now(timezone.utc).isoformat()]
        if sector:
            updates.append("sector = ?")
            params.append(sector)
        if description:
            updates.append("description = ?")
            params.append(description)
        params.append(dossier_id)
        conn.execute(f"UPDATE dossiers SET {', '.join(updates)} WHERE id = ?", params)
        conn.commit()
        return dossier_id

    # Fuzzy match — catch typos/spelling variants (e.g., "loveable" → "Lovable")
    fuzzy_id, fuzzy_name = _find_similar_dossier(conn, company_name)
    if fuzzy_id:
        print(f"[dossier] Fuzzy matched '{company_name}' → existing '{fuzzy_name}'")
        updates = ["updated_at = ?"]
        params = [datetime.now(timezone.utc).isoformat()]
        if sector:
            updates.append("sector = ?")
            params.append(sector)
        if description:
            updates.append("description = ?")
            params.append(description)
        params.append(fuzzy_id)
        conn.execute(f"UPDATE dossiers SET {', '.join(updates)} WHERE id = ?", params)
        conn.commit()
        return fuzzy_id

    cur = conn.execute(
        "INSERT INTO dossiers (company_name, sector, description) VALUES (?, ?, ?)",
        (company_name, sector, description),
    )
    conn.commit()
    return cur.lastrowid


def add_dossier_analysis(conn, dossier_id, analysis_type, report_file=None,
                         key_facts_json=None, model_used=None):
    """Record a completed analysis run for a dossier."""
    now = datetime.now(timezone.utc).isoformat()
    cur = conn.execute(
        """INSERT INTO dossier_analyses (dossier_id, analysis_type, report_file, key_facts_json, model_used, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (dossier_id, analysis_type, report_file, key_facts_json, model_used, now),
    )
    conn.execute(
        "UPDATE dossiers SET updated_at = ? WHERE id = ?",
        (datetime.now(timezone.utc).isoformat(), dossier_id),
    )
    conn.commit()
    return cur.lastrowid


def add_dossier_event(conn, dossier_id, event_type, title, description=None,
                      event_date=None, source_url=None, data_json=None):
    """Add a timeline event to a dossier."""
    cur = conn.execute(
        """INSERT INTO dossier_events (dossier_id, event_date, event_type, title, description, source_url, data_json)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (dossier_id, event_date, event_type, title, description, source_url, data_json),
    )
    conn.commit()
    return cur.lastrowid


def get_dossier_by_company(conn, company_name):
    """Get dossier with all analyses and events for a company."""
    row = conn.execute(
        "SELECT * FROM dossiers WHERE company_name = ? COLLATE NOCASE",
        (company_name,),
    ).fetchone()
    if not row:
        return None

    dossier = dict(row)
    dossier_id = dossier["id"]

    analyses = conn.execute(
        """SELECT id, analysis_type, report_file, key_facts_json, model_used, created_at
           FROM dossier_analyses WHERE dossier_id = ? ORDER BY created_at DESC""",
        (dossier_id,),
    ).fetchall()
    dossier["analyses"] = [dict(a) for a in analyses]

    events = conn.execute(
        """SELECT id, event_date, event_type, title, description, source_url, data_json, created_at
           FROM dossier_events WHERE dossier_id = ? ORDER BY event_date DESC, created_at DESC""",
        (dossier_id,),
    ).fetchall()
    dossier["events"] = [dict(e) for e in events]

    return dossier


def get_all_dossiers(conn, hide_empty=False):
    """Get all dossiers with summary stats.

    Args:
        hide_empty: If True, exclude dossiers with 0 analyses (e.g. Discover stubs).
    """
    query = """SELECT d.*,
                  (SELECT COUNT(*) FROM dossier_analyses WHERE dossier_id = d.id) as analysis_count,
                  (SELECT COUNT(*) FROM dossier_events WHERE dossier_id = d.id) as event_count,
                  (SELECT MAX(created_at) FROM dossier_analyses WHERE dossier_id = d.id) as last_analysis_at
           FROM dossiers d"""
    if hide_empty:
        query += " WHERE (SELECT COUNT(*) FROM dossier_analyses WHERE dossier_id = d.id) > 0"
    query += " ORDER BY d.updated_at DESC"
    rows = conn.execute(query).fetchall()
    return [dict(r) for r in rows]


def get_dossier_staleness(conn, dossier_id):
    """Get the last analysis date per type for staleness tracking."""
    rows = conn.execute(
        """SELECT analysis_type, MAX(created_at) as last_run
           FROM dossier_analyses WHERE dossier_id = ?
           GROUP BY analysis_type""",
        (dossier_id,),
    ).fetchall()
    return {r["analysis_type"]: r["last_run"] for r in rows}


def get_latest_key_facts(conn, dossier_id):
    """Get the most recent key_facts_json per analysis type."""
    rows = conn.execute(
        """SELECT analysis_type, key_facts_json, created_at
           FROM dossier_analyses
           WHERE dossier_id = ? AND key_facts_json IS NOT NULL
           ORDER BY created_at DESC""",
        (dossier_id,),
    ).fetchall()
    # Return the latest per type
    seen = set()
    facts = {}
    for r in rows:
        if r["analysis_type"] not in seen:
            seen.add(r["analysis_type"])
            facts[r["analysis_type"]] = {
                "data": json.loads(r["key_facts_json"]) if r["key_facts_json"] else {},
                "as_of": r["created_at"],
            }
    return facts


def get_previous_key_facts(conn, dossier_id, analysis_type):
    """Get the key_facts_json from the most recent prior analysis of this type.

    Returns parsed dict or None if no prior analysis exists.
    """
    row = conn.execute(
        """SELECT key_facts_json FROM dossier_analyses
           WHERE dossier_id = ? AND analysis_type = ? AND key_facts_json IS NOT NULL
           ORDER BY created_at DESC LIMIT 1""",
        (dossier_id, analysis_type),
    ).fetchone()
    if row and row["key_facts_json"]:
        try:
            return json.loads(row["key_facts_json"])
        except (json.JSONDecodeError, TypeError):
            return None
    return None


def compute_hiring_stats(conn, company_id):
    """Compute aggregate hiring stats from classified jobs for a company.

    Returns dict with dept_counts, subcategory_counts, seniority_counts,
    strategic_tag_counts, ai_ml_role_count, total_roles, growth_signal_ratio,
    top_skills, top_locations — or None if no data.
    """
    from collections import Counter

    rows = conn.execute(
        """SELECT c.department_category, c.department_subcategory, c.seniority_level,
                  c.strategic_tags, c.growth_signal, c.key_skills, j.location
           FROM classifications c
           JOIN jobs j ON c.job_id = j.id
           WHERE j.company_id = ?""",
        (company_id,),
    ).fetchall()

    if not rows:
        return None

    dept_counts = Counter()
    subcat_counts = Counter()
    seniority_counts = Counter()
    strategic_tag_counts = Counter()
    growth_counts = Counter()
    skill_counts = Counter()
    location_counts = Counter()
    ai_ml_count = 0

    for r in rows:
        dept = r["department_category"] or "Other"
        dept_counts[dept] += 1

        subcat = r["department_subcategory"] or "General"
        subcat_counts[subcat] += 1

        seniority_counts[r["seniority_level"] or "Unknown"] += 1
        growth_counts[r["growth_signal"] or "unclear"] += 1

        loc = r["location"]
        if loc:
            location_counts[loc] += 1

        # Parse strategic tags
        tags_raw = r["strategic_tags"]
        if tags_raw:
            try:
                tags = json.loads(tags_raw)
                for tag in tags:
                    strategic_tag_counts[tag] += 1
                    if "AI" in tag or "ML" in tag:
                        ai_ml_count += 1
            except (json.JSONDecodeError, TypeError):
                pass

        # Parse key skills
        skills_raw = r["key_skills"]
        if skills_raw:
            try:
                skills = json.loads(skills_raw) if isinstance(skills_raw, str) else skills_raw
                if isinstance(skills, list):
                    for skill in skills:
                        skill_counts[str(skill)] += 1
            except (json.JSONDecodeError, TypeError):
                pass

        # Count AI/ML department roles
        if "AI" in subcat or "ML" in subcat or "Machine Learning" in subcat:
            ai_ml_count += 1

    total = len(rows)
    new_roles = growth_counts.get("likely new role", 0)
    growth_ratio = f"{round(new_roles * 100 / total)}% new roles" if total else "unknown"

    return {
        "total_roles": total,
        "dept_counts": dict(dept_counts),
        "subcategory_counts": dict(subcat_counts.most_common(20)),
        "seniority_counts": dict(seniority_counts),
        "strategic_tag_counts": dict(strategic_tag_counts),
        "ai_ml_role_count": ai_ml_count,
        "growth_signal_ratio": growth_ratio,
        "top_skills": [s for s, _ in skill_counts.most_common(20)],
        "top_locations": dict(location_counts.most_common(15)),
    }


def save_hiring_snapshot(conn, company_id, stats):
    """Save a hiring stats snapshot for today. Uses INSERT OR REPLACE for idempotency."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    conn.execute(
        """INSERT OR REPLACE INTO hiring_snapshots
           (company_id, snapshot_date, total_roles, dept_counts, subcategory_counts,
            seniority_counts, strategic_tag_counts, ai_ml_role_count,
            growth_signal_ratio, top_skills, top_locations)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            company_id, today, stats["total_roles"],
            json.dumps(stats["dept_counts"]),
            json.dumps(stats["subcategory_counts"]),
            json.dumps(stats["seniority_counts"]),
            json.dumps(stats["strategic_tag_counts"]),
            stats["ai_ml_role_count"],
            stats["growth_signal_ratio"],
            json.dumps(stats["top_skills"]),
            json.dumps(stats["top_locations"]),
        ),
    )
    conn.commit()


def get_hiring_snapshots(conn, company_id, limit=10):
    """Get recent hiring snapshots for a company, most recent first."""
    rows = conn.execute(
        """SELECT * FROM hiring_snapshots
           WHERE company_id = ?
           ORDER BY snapshot_date DESC LIMIT ?""",
        (company_id, limit),
    ).fetchall()
    results = []
    for r in rows:
        d = dict(r)
        for field in ("dept_counts", "subcategory_counts", "seniority_counts",
                      "strategic_tag_counts", "top_skills", "top_locations"):
            if d.get(field):
                try:
                    d[field] = json.loads(d[field])
                except (json.JSONDecodeError, TypeError):
                    pass
        results.append(d)
    return results


def get_recent_changes(conn, dossier_id, limit=15):
    """Get change_detected events, most recent first."""
    rows = conn.execute(
        """SELECT event_date, event_type, title, description, data_json, created_at
           FROM dossier_events
           WHERE dossier_id = ? AND event_type = 'change_detected'
           ORDER BY created_at DESC LIMIT ?""",
        (dossier_id, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def get_ua_targets(conn, icp_profile_id=None):
    """Get dossiers with UA fit scores, optionally filtered by ICP profile.

    When icp_profile_id is provided, only return prospects scored under that profile.
    """
    if icp_profile_id is not None:
        rows = conn.execute(
            """SELECT d.id, d.company_name, d.sector, d.description,
                      d.ua_fit_json, d.ua_fit_generated_at, d.icp_profile_id,
                      (SELECT COUNT(*) FROM dossier_analyses WHERE dossier_id = d.id) as analysis_count
               FROM dossiers d
               WHERE d.ua_fit_json IS NOT NULL
                 AND (d.icp_profile_id = ? OR d.icp_profile_id IS NULL)
               ORDER BY json_extract(d.ua_fit_json, '$.overall_score') DESC""",
            (icp_profile_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            """SELECT d.id, d.company_name, d.sector, d.description,
                      d.ua_fit_json, d.ua_fit_generated_at, d.icp_profile_id,
                      (SELECT COUNT(*) FROM dossier_analyses WHERE dossier_id = d.id) as analysis_count
               FROM dossiers d
               WHERE d.ua_fit_json IS NOT NULL
               ORDER BY json_extract(d.ua_fit_json, '$.overall_score') DESC"""
        ).fetchall()
    results = []
    for r in rows:
        d = dict(r)
        if d.get("ua_fit_json"):
            try:
                d["ua_fit"] = json.loads(d["ua_fit_json"])
            except (json.JSONDecodeError, TypeError):
                d["ua_fit"] = None
        results.append(d)
    return results


# --- Campaign helpers ---

def create_campaign(conn, niche, top_n, name=None, parent_campaign_id=None, seed_company=None):
    """Create a new campaign. Returns campaign id."""
    now = datetime.now(timezone.utc).isoformat()
    cur = conn.execute(
        """INSERT INTO campaigns (niche, name, top_n, status, parent_campaign_id, seed_company, created_at, updated_at)
           VALUES (?, ?, ?, 'running', ?, ?, ?, ?)""",
        (niche, name or niche, top_n, parent_campaign_id, seed_company, now, now),
    )
    conn.commit()
    return cur.lastrowid


def update_campaign_status(conn, campaign_id, status):
    """Update campaign status (running|complete|error)."""
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "UPDATE campaigns SET status = ?, updated_at = ? WHERE id = ?",
        (status, now, campaign_id),
    )
    conn.commit()


def save_financial_snapshot(conn, dossier_id, snapshot_dict):
    """Save lightweight financial scan data to a dossier."""
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "UPDATE dossiers SET financial_snapshot_json = ?, financial_snapshot_at = ?, updated_at = ? WHERE id = ?",
        (json.dumps(snapshot_dict), now, now, dossier_id),
    )
    conn.commit()


def get_financial_snapshot(conn, dossier_id):
    """Get existing financial snapshot from a dossier, or None."""
    row = conn.execute(
        "SELECT financial_snapshot_json FROM dossiers WHERE id = ?", (dossier_id,)
    ).fetchone()
    if row and row["financial_snapshot_json"]:
        try:
            return json.loads(row["financial_snapshot_json"])
        except (json.JSONDecodeError, TypeError):
            return None
    return None


def save_niche_evaluation(conn, campaign_id, niche_eval_dict):
    """Save aggregated niche evaluation to a campaign."""
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "UPDATE campaigns SET niche_eval_json = ?, updated_at = ? WHERE id = ?",
        (json.dumps(niche_eval_dict), now, campaign_id),
    )
    conn.commit()


def get_niche_evaluation(conn, campaign_id):
    """Get existing niche evaluation from a campaign, or None."""
    row = conn.execute(
        "SELECT niche_eval_json FROM campaigns WHERE id = ?", (campaign_id,)
    ).fetchone()
    if row and row["niche_eval_json"]:
        try:
            return json.loads(row["niche_eval_json"])
        except (json.JSONDecodeError, TypeError):
            return None
    return None


def save_campaign_execution_log(conn, campaign_id, execution_log):
    """Save the execution log (search queries, results) as JSON on the campaign."""
    conn.execute(
        "UPDATE campaigns SET execution_log_json = ? WHERE id = ?",
        (json.dumps(execution_log), campaign_id),
    )
    conn.commit()


def add_campaign_prospect(conn, campaign_id, dossier_id, validation_status=None,
                          validation_reason=None, discovery_json=None):
    """Add a prospect to a campaign. Upserts on (campaign_id, dossier_id)."""
    conn.execute(
        """INSERT INTO campaign_prospects (campaign_id, dossier_id, validation_status,
              validation_reason, discovery_json)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(campaign_id, dossier_id) DO UPDATE SET
             validation_status = excluded.validation_status,
             validation_reason = excluded.validation_reason,
             discovery_json = COALESCE(excluded.discovery_json, campaign_prospects.discovery_json)""",
        (campaign_id, dossier_id, validation_status, validation_reason, discovery_json),
    )
    conn.commit()


def update_prospect_status(conn, campaign_id, dossier_id, prospect_status):
    """Update a prospect's workflow status (new|reviewing|brief_ready|contacted)."""
    conn.execute(
        "UPDATE campaign_prospects SET prospect_status = ? WHERE campaign_id = ? AND dossier_id = ?",
        (prospect_status, campaign_id, dossier_id),
    )
    conn.commit()


def get_all_campaigns(conn):
    """Get all campaigns with prospect counts and avg scores."""
    rows = conn.execute(
        """SELECT c.*,
                  (SELECT COUNT(*) FROM campaign_prospects WHERE campaign_id = c.id) as prospect_count,
                  (SELECT ROUND(AVG(json_extract(d.ua_fit_json, '$.overall_score')), 1)
                   FROM campaign_prospects cp
                   JOIN dossiers d ON cp.dossier_id = d.id
                   WHERE cp.campaign_id = c.id AND d.ua_fit_json IS NOT NULL) as avg_score
           FROM campaigns c ORDER BY c.created_at DESC"""
    ).fetchall()
    return [dict(r) for r in rows]


def set_campaign_lens(conn, campaign_id, lens_id):
    """Set the scoring lens for a campaign."""
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "UPDATE campaigns SET scoring_lens_id = ?, updated_at = ? WHERE id = ?",
        (lens_id, now, campaign_id),
    )
    conn.commit()


def get_campaign_detail(conn, campaign_id):
    """Get a single campaign with its prospects joined to dossier scores."""
    campaign = conn.execute("SELECT * FROM campaigns WHERE id = ?", (campaign_id,)).fetchone()
    if not campaign:
        return None
    campaign = dict(campaign)
    scoring_lens_id = campaign.get("scoring_lens_id")
    rows = conn.execute(
        """SELECT cp.*, d.company_name, d.sector, d.description as company_description,
                  d.website_url, d.ua_fit_json, d.ua_fit_generated_at
           FROM campaign_prospects cp
           JOIN dossiers d ON cp.dossier_id = d.id
           WHERE cp.campaign_id = ?
           ORDER BY CASE WHEN d.ua_fit_json IS NOT NULL
                    THEN json_extract(d.ua_fit_json, '$.overall_score') ELSE 0 END DESC""",
        (campaign_id,),
    ).fetchall()

    # Pre-fetch lens scores for all prospects in this campaign
    lens_scores_map = {}
    if scoring_lens_id:
        ls_rows = conn.execute(
            """SELECT ls.dossier_id, ls.score_json
               FROM lens_scores ls
               JOIN campaign_prospects cp ON ls.dossier_id = cp.dossier_id
               WHERE cp.campaign_id = ? AND ls.lens_id = ?""",
            (campaign_id, scoring_lens_id),
        ).fetchall()
        for ls_row in ls_rows:
            try:
                lens_scores_map[ls_row["dossier_id"]] = json.loads(ls_row["score_json"])
            except (json.JSONDecodeError, TypeError):
                pass
    else:
        # No specific lens — check for any lens scores on these dossiers
        ls_rows = conn.execute(
            """SELECT ls.dossier_id, ls.score_json
               FROM lens_scores ls
               JOIN campaign_prospects cp ON ls.dossier_id = cp.dossier_id
               WHERE cp.campaign_id = ?
               ORDER BY ls.scored_at DESC""",
            (campaign_id,),
        ).fetchall()
        for ls_row in ls_rows:
            did = ls_row["dossier_id"]
            if did not in lens_scores_map:  # keep latest per dossier
                try:
                    lens_scores_map[did] = json.loads(ls_row["score_json"])
                except (json.JSONDecodeError, TypeError):
                    pass

    prospects = []
    for r in rows:
        p = dict(r)
        if p.get("ua_fit_json"):
            try:
                p["ua_fit"] = json.loads(p["ua_fit_json"])
            except (json.JSONDecodeError, TypeError):
                p["ua_fit"] = None
        else:
            p["ua_fit"] = None
        # Attach lens score if available
        p["lens_score"] = lens_scores_map.get(p["dossier_id"])
        if p.get("brief_json"):
            try:
                p["brief"] = json.loads(p["brief_json"])
            except (json.JSONDecodeError, TypeError):
                p["brief"] = None
        else:
            p["brief"] = None
        if p.get("discovery_json"):
            try:
                p["discovery"] = json.loads(p["discovery_json"])
            except (json.JSONDecodeError, TypeError):
                p["discovery"] = None
        else:
            p["discovery"] = None
        prospects.append(p)
    # Sort by best available score (lens_score preferred over ua_fit)
    def _best_score(p):
        ls = p.get("lens_score")
        if ls and ls.get("overall_score") is not None:
            return ls["overall_score"]
        ua = p.get("ua_fit")
        if ua and ua.get("overall_score") is not None:
            return ua["overall_score"]
        return -1
    prospects.sort(key=_best_score, reverse=True)
    campaign["prospects"] = prospects
    if campaign.get("insight_json"):
        try:
            campaign["insight"] = json.loads(campaign["insight_json"])
        except (json.JSONDecodeError, TypeError):
            campaign["insight"] = None
    else:
        campaign["insight"] = None
    if campaign.get("execution_log_json"):
        try:
            campaign["execution_log"] = json.loads(campaign["execution_log_json"])
        except (json.JSONDecodeError, TypeError):
            campaign["execution_log"] = None
    else:
        campaign["execution_log"] = None
    if campaign.get("niche_eval_json"):
        try:
            campaign["niche_eval"] = json.loads(campaign["niche_eval_json"])
        except (json.JSONDecodeError, TypeError):
            campaign["niche_eval"] = None
    else:
        campaign["niche_eval"] = None
    return campaign


def rename_campaign(conn, campaign_id, name):
    """Rename a campaign."""
    now = datetime.now(timezone.utc).isoformat()
    conn.execute("UPDATE campaigns SET name = ?, updated_at = ? WHERE id = ?", (name, now, campaign_id))
    conn.commit()


def delete_campaign(conn, campaign_id):
    """Delete a campaign, all child campaigns, and their prospect links (not the dossiers)."""
    tree = get_campaign_tree(conn, campaign_id)
    # Delete leaf-first to respect any FK constraints
    for node in reversed(tree):
        conn.execute("DELETE FROM campaign_prospects WHERE campaign_id = ?", (node["id"],))
        conn.execute("DELETE FROM campaigns WHERE id = ?", (node["id"],))
    conn.commit()


def get_root_campaigns(conn):
    """Get top-level (non-child) campaigns only, for sidebar rendering."""
    rows = conn.execute(
        """SELECT c.*,
                  (SELECT COUNT(*) FROM campaign_prospects WHERE campaign_id = c.id) as prospect_count
           FROM campaigns c
           WHERE c.parent_campaign_id IS NULL
           ORDER BY c.created_at DESC"""
    ).fetchall()
    return [dict(r) for r in rows]


def get_campaign_tree(conn, root_id):
    """Return all campaigns in the tree rooted at root_id, ordered by created_at."""
    rows = conn.execute(
        """WITH RECURSIVE tree(id) AS (
             SELECT id FROM campaigns WHERE id = ?
             UNION ALL
             SELECT c.id FROM campaigns c JOIN tree ON c.parent_campaign_id = tree.id
           )
           SELECT c.*,
                  (SELECT COUNT(*) FROM campaign_prospects WHERE campaign_id = c.id) as prospect_count
           FROM campaigns c JOIN tree USING(id)
           ORDER BY c.created_at""",
        (root_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_campaign_depth(conn, campaign_id):
    """Return the depth of this campaign in its tree (root = 0)."""
    row = conn.execute(
        "SELECT parent_campaign_id FROM campaigns WHERE id = ?", (campaign_id,)
    ).fetchone()
    if not row or row["parent_campaign_id"] is None:
        return 0
    return 1 + get_campaign_depth(conn, row["parent_campaign_id"])


# --- ICP Profile helpers ---

def create_icp_profile(conn, name, description, config_json, survey_answers_json=None, is_default=0):
    """Create a new ICP profile. Returns profile id."""
    now = datetime.now(timezone.utc).isoformat()
    cur = conn.execute(
        """INSERT INTO icp_profiles (name, description, is_default, config_json, survey_answers_json, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (name, description, is_default, config_json, survey_answers_json, now, now),
    )
    conn.commit()
    return cur.lastrowid


def update_icp_profile(conn, profile_id, name=None, description=None, config_json=None):
    """Update an existing ICP profile."""
    updates = ["updated_at = ?"]
    params = [datetime.now(timezone.utc).isoformat()]
    if name is not None:
        updates.append("name = ?")
        params.append(name)
    if description is not None:
        updates.append("description = ?")
        params.append(description)
    if config_json is not None:
        updates.append("config_json = ?")
        params.append(config_json)
    params.append(profile_id)
    conn.execute(f"UPDATE icp_profiles SET {', '.join(updates)} WHERE id = ?", params)
    conn.commit()


def delete_icp_profile(conn, profile_id):
    """Delete a non-default ICP profile."""
    conn.execute("DELETE FROM icp_profiles WHERE id = ? AND is_default = 0", (profile_id,))
    conn.commit()


def set_active_icp_profile(conn, profile_id):
    """Set one profile as active, deactivating all others."""
    conn.execute("UPDATE icp_profiles SET is_active = 0")
    conn.execute("UPDATE icp_profiles SET is_active = 1 WHERE id = ?", (profile_id,))
    conn.commit()


def get_active_icp_profile(conn):
    """Get the currently active ICP profile with parsed config. Returns dict or None."""
    row = conn.execute(
        "SELECT * FROM icp_profiles WHERE is_active = 1"
    ).fetchone()
    if not row:
        return None
    d = dict(row)
    if d.get("config_json"):
        try:
            d["config"] = json.loads(d["config_json"])
        except (json.JSONDecodeError, TypeError):
            d["config"] = None
    if d.get("survey_answers_json"):
        try:
            d["survey_answers"] = json.loads(d["survey_answers_json"])
        except (json.JSONDecodeError, TypeError):
            d["survey_answers"] = None
    return d


def get_icp_profile(conn, profile_id):
    """Get a single ICP profile by ID with parsed config."""
    row = conn.execute(
        "SELECT * FROM icp_profiles WHERE id = ?", (profile_id,)
    ).fetchone()
    if not row:
        return None
    d = dict(row)
    if d.get("config_json"):
        try:
            d["config"] = json.loads(d["config_json"])
        except (json.JSONDecodeError, TypeError):
            d["config"] = None
    if d.get("survey_answers_json"):
        try:
            d["survey_answers"] = json.loads(d["survey_answers_json"])
        except (json.JSONDecodeError, TypeError):
            d["survey_answers"] = None
    return d


def get_all_icp_profiles(conn):
    """Get all ICP profiles, active one first."""
    rows = conn.execute(
        "SELECT * FROM icp_profiles ORDER BY is_active DESC, is_default DESC, created_at DESC"
    ).fetchall()
    results = []
    for r in rows:
        d = dict(r)
        if d.get("config_json"):
            try:
                d["config"] = json.loads(d["config_json"])
            except (json.JSONDecodeError, TypeError):
                d["config"] = None
        results.append(d)
    return results


_DEFAULT_ICP_CONFIG = {
    "icp_definition": (
        "The ideal prospect is an SMB or midmarket brand ($1M\u2013$500M revenue) that is heavy on "
        "social/performance marketing (Meta, TikTok, Google Ads, Instagram) but has little or no "
        "TV/CTV/streaming advertising history. They are hitting a ceiling on social ad channels \u2014 "
        "rising CPMs, diminishing returns, audience saturation. They have strong creative capabilities "
        "\u2014 video content, UGC, influencer partnerships \u2014 meaning they could easily adapt existing "
        "assets to 15\u201330 second TV spots. They are in a growth phase \u2014 recent funding, expanding "
        "markets, hiring marketing talent. They are actively seeking new customer acquisition channels "
        "beyond their current social media mix."
    ),
    "dimensions": [
        {
            "key": "channel_saturation",
            "label": "Channel Saturation",
            "weight": 0.25,
            "description": "How heavily the company relies on social/performance channels vs TV/CTV",
            "rubric": {
                "80_100": "Clear evidence of heavy Meta/TikTok/Instagram ad spend (pixel detected, ad library presence, 'paid social' in job listings). No evidence of TV/CTV advertising. Classic 'social-native brand.'",
                "60_79": "Some social ad indicators but less definitive. Or evidence of light CTV testing.",
                "40_59": "Mixed signals. May have some social presence but unclear spending level. Or already doing some TV.",
                "20_39": "Limited social ad signals. Primarily organic/SEO-driven, or already has substantial TV presence.",
                "0_19": "Company is already a major TV advertiser, or shows no marketing activity at all.",
            },
            "signal_queries": {
                "primary": "{company} advertising marketing strategy",
                "secondary": None,
                "news": False,
                "reddit": None,
            },
            "signal_category_name": "Ad Channel & Tech Stack",
            "use_tech_detection": True,
        },
        {
            "key": "growth_posture",
            "label": "Growth Posture",
            "weight": 0.20,
            "description": "Whether the company is in a growth phase",
            "rubric": {
                "80_100": "Recent funding round (Series A-C), aggressive hiring (especially marketing/growth), market expansion, revenue growth mentions.",
                "60_79": "Some growth indicators \u2014 profitable and expanding, or new products/markets.",
                "40_59": "Stable business with moderate growth. Not shrinking, but no aggressive expansion.",
                "20_39": "Flat or declining. Cost-cutting, layoffs, market contraction.",
                "0_19": "Struggling, pivoting away from growth, or lifestyle business.",
            },
            "signal_queries": {
                "primary": "{company} funding round series investment 2024 2025 2026",
                "secondary": "{company} growth expansion launch",
                "news": True,
                "reddit": None,
            },
            "signal_category_name": "Growth Signals",
        },
        {
            "key": "creative_readiness",
            "label": "Creative Readiness",
            "weight": 0.20,
            "description": "Quality of existing creative assets and video capability",
            "rubric": {
                "80_100": "Video-first brand. Strong Instagram/TikTok with professional or UGC video. Influencer partnerships. Visual product category.",
                "60_79": "Good visual brand but maybe more photo-oriented. Could transition to video easily.",
                "40_59": "Basic social presence but limited creative output. Would need development for video ads.",
                "20_39": "Minimal brand presence. Text-heavy, B2B-oriented, hard to showcase in 15\u201330 seconds.",
                "0_19": "No creative presence, or product fundamentally unsuited for video advertising.",
            },
            "signal_queries": {
                "primary": "{company} Instagram TikTok social media presence",
                "secondary": "{company} video content ads commercial",
                "news": False,
                "reddit": None,
            },
            "signal_category_name": "Brand & Creative",
        },
        {
            "key": "size_budget_fit",
            "label": "Size & Budget Fit",
            "weight": 0.20,
            "description": "Whether the company's size and budget align with the product",
            "rubric": {
                "80_100": "Sweet spot \u2014 $5M\u2013$200M revenue, has marketing team, can afford $10K\u2013$100K/month, not so large TV is core.",
                "60_79": "Likely in range but less clear. Could be smaller side or larger side.",
                "40_59": "Ambiguous. Could be too small (pre-revenue) or too large (public with TV budgets).",
                "20_39": "Appears too small (bootstrap, solo founder) or too large (Fortune 500).",
                "0_19": "Clearly outside target range \u2014 micro-business or mega-brand.",
            },
            "signal_queries": {
                "primary": "{company} revenue employees company size",
                "secondary": None,
                "news": False,
                "reddit": None,
            },
            "signal_category_name": "Size Indicators",
        },
        {
            "key": "intent_signals",
            "label": "Intent Signals",
            "weight": 0.15,
            "description": "Whether the company shows intent to explore new ad channels",
            "rubric": {
                "80_100": "Explicit mentions of exploring new channels, 'beyond social', rising CPM complaints, CTV interest, 'brand awareness' goals.",
                "60_79": "Implicit intent \u2014 expanding marketing team, new markets, industry known for CTV adoption.",
                "40_59": "No specific intent signals but profile suggests receptiveness.",
                "20_39": "No intent signals. Company seems content with current channels.",
                "0_19": "Focused on incompatible channels (B2B enterprise sales, no advertising model).",
            },
            "signal_queries": {
                "primary": "{company} TV commercial streaming CTV advertising",
                "secondary": "{company} new advertising channels brand awareness",
                "news": False,
                "reddit": "{company} advertising CPM social media ads",
            },
            "signal_category_name": "Intent & Pain Signals",
        },
    ],
    "labels": [
        {"min_score": 80, "label": "CTV Vanguard"},
        {"min_score": 60, "label": "CTV Contender"},
        {"min_score": 40, "label": "CTV Explorer"},
        {"min_score": 20, "label": "CTV Laggard"},
        {"min_score": 0, "label": "CTV Dark Spot"},
    ],
    "discovery_filters": {
        "include_description": "Focus on companies with real marketing operations, website, social presence, SMB-to-midmarket range.",
        "exclude_description": "Exclude mega-brands already advertising on TV at scale (Nike, Coca-Cola, P&G). Exclude micro-businesses with no marketing presence.",
        "search_queries_template": [
            "top {niche} 2026",
            "fastest growing {niche}",
            "best {niche} companies brands",
            "{niche} emerging brands to watch",
        ],
    },
    "scoring_output_schema": {
        "recommended_angle_guidance": "Reference the company's actual channel mix and suggest how premium streaming TV addresses their ceiling.",
        "risk_focus": "budget concerns, existing vendor lock-in, lack of video assets, already doing TV",
    },
}


def ensure_default_icp_profile(conn):
    """Create the default ICP profile from hardcoded values if it doesn't exist."""
    existing = conn.execute("SELECT id FROM icp_profiles WHERE is_default = 1").fetchone()
    if existing:
        return existing["id"]

    now = datetime.now(timezone.utc).isoformat()
    cur = conn.execute(
        """INSERT INTO icp_profiles (name, description, is_default, is_active, config_json, created_at, updated_at)
           VALUES (?, ?, 1, 1, ?, ?, ?)""",
        (
            "Universal Ads \u2014 Premium Video",
            "SMBs heavy on social, ready for streaming TV",
            json.dumps(_DEFAULT_ICP_CONFIG),
            now,
            now,
        ),
    )
    conn.commit()
    return cur.lastrowid


# =========================================================================
# Lens system — configurable evaluation frameworks
# =========================================================================

_PRESET_LENSES = [
    {
        "name": "CTV Ad Sales",
        "slug": "ctv-ad-sales",
        "description": "Evaluate prospect fit for premium video / streaming TV advertising (Comcast Universal Ads use case)",
        "config": {
            "dimensions": [
                {
                    "key": "financial_capacity",
                    "label": "Financial Capacity",
                    "weight": 0.25,
                    "sources": ["financial"],
                    "rubric": (
                        "80-100: Clear evidence of $10M+ revenue or recent Series B+ funding. Has budget headroom for new channels.\n"
                        "60-79: Revenue/funding suggests moderate capacity. Could allocate $10K-50K/month without strain.\n"
                        "40-59: Financial signals ambiguous or limited. Early-stage, unclear revenue, or tight margins.\n"
                        "20-39: Resource-constrained. Minimal funding, small team, or financial difficulty evident.\n"
                        "0-19: Clearly cannot afford new ad channels. Pre-revenue or in distress."
                    ),
                },
                {
                    "key": "advertising_maturity",
                    "label": "Paid Media Footprint",
                    "weight": 0.20,
                    "sources": ["techstack"],
                    "rubric": (
                        "80-100: 2+ ad pixels detected (Facebook, TikTok, Google Ads). Marketing automation present. Heavy digital buyer but NOT yet on TV/CTV.\n"
                        "60-79: 1 ad pixel detected OR strong social presence indicating paid activity.\n"
                        "40-59: Basic analytics (GA4) only — tracking but not necessarily buying ads.\n"
                        "20-39: Almost no ad infrastructure. Likely organic/word-of-mouth only.\n"
                        "0-19: No advertising tools detected, OR already a major TV advertiser at scale."
                    ),
                },
                {
                    "key": "growth_trajectory",
                    "label": "Growth Trajectory",
                    "weight": 0.20,
                    "sources": ["financial", "brand_ad"],
                    "rubric": (
                        "80-100: Strong growth (>20% YoY revenue, or recent funding round), expansion announcements, active hiring.\n"
                        "60-79: Moderate growth signals. Stable and expanding, not explosive.\n"
                        "40-59: Flat or unclear trajectory. No meaningful growth or decline signals.\n"
                        "20-39: Concerning signals — layoffs, revenue decline, market contraction.\n"
                        "0-19: Company clearly shrinking, in distress, or going through strategic wind-down."
                    ),
                },
                {
                    "key": "creative_readiness",
                    "label": "Video Asset Readiness",
                    "weight": 0.20,
                    "sources": ["brand_ad"],
                    "rubric": (
                        "80-100: Strong social/video presence (YouTube, TikTok, Reels). Existing brand campaigns. Product visually demonstrable.\n"
                        "60-79: Good brand presence, photo-heavy or text-heavy. Could transition to video.\n"
                        "40-59: Basic digital presence, limited content output.\n"
                        "20-39: Minimal brand presence. Highly technical B2B or invisible online.\n"
                        "0-19: No creative presence, or product fundamentally unsuited for video."
                    ),
                },
                {
                    "key": "channel_expansion_intent",
                    "label": "Channel Expansion Intent",
                    "weight": 0.15,
                    "sources": ["brand_ad", "financial"],
                    "rubric": (
                        "80-100: Explicit mentions of CTV, streaming, or 'beyond social'. Hiring brand/media roles.\n"
                        "60-79: Implicit intent — entering new markets, increasing budgets, peers are diversifying.\n"
                        "40-59: No specific intent signals. Profile suggests receptivity but no evidence.\n"
                        "20-39: Content with existing channels. No diversification signals.\n"
                        "0-19: Actively cutting marketing spend or focused away from broadcast."
                    ),
                },
            ],
            "labels": [
                {"min_score": 80, "label": "CTV Vanguard"},
                {"min_score": 60, "label": "CTV Contender"},
                {"min_score": 40, "label": "CTV Explorer"},
                {"min_score": 20, "label": "CTV Laggard"},
                {"min_score": 0, "label": "CTV Dark Spot"},
            ],
            "score_label": "CTV Propensity Score",
            "scoring_context": "You are a GTM intelligence analyst scoring a company's suitability as a prospect for a premium video / streaming TV advertising platform (similar to Comcast Universal Ads).",
            "angle_guidance": "Focus on their current paid media spend, growth trajectory, and the gap between their digital and TV presence.",
            "risk_focus": "budget concerns, existing vendor lock-in, lack of video assets, already doing TV at scale",
        },
    },
    {
        "name": "Digital Transformation",
        "slug": "digital-transformation",
        "description": "Evaluate digital maturity and transformation consulting opportunity for technology advisory firms",
        "config": {
            "dimensions": [
                {
                    "key": "tech_modernity",
                    "label": "Tech Modernity",
                    "weight": 0.30,
                    "sources": ["techstack", "hiring"],
                    "rubric": (
                        "Primary signals: hiring data (what technologies they hire for), sector/product (what they build), engineering ratio.\n"
                        "Secondary signals: website tech stack (what's on their public site — this is a weak signal for internal capability).\n\n"
                        "CRITICAL DISTINCTION — 'uses SaaS tools' vs 'is a SaaS company':\n"
                        "A non-tech company (food, retail, manufacturing) whose public website uses SaaS tools like Algolia, Cloudflare, or Shopify is NOT a SaaS/software company. "
                        "Using off-the-shelf SaaS products on a marketing website is a PURCHASING decision, not an engineering capability. "
                        "Only score website SaaS usage positively if the company's CORE BUSINESS is technology/software.\n\n"
                        "80-100: Company IS a technology/software/AI company (core product is technology), OR hiring data shows modern stack "
                        "(React/Go/Rust/K8s/cloud-native/microservices roles dominate), high engineering ratio (>50%). "
                        "If a company literally BUILDS software, LLMs, cloud infrastructure, or AI products, floor at 80.\n"
                        "60-79: Tech-adjacent company with significant engineering investment (30-50% engineering roles), modern tools in hiring reqs.\n"
                        "40-59: Non-tech company with modest engineering team (<30% roles). Legacy technologies (COBOL, mainframe, .NET Framework, on-prem).\n"
                        "20-39: Minimal tech hiring. No engineering culture signals. Basic or outsourced IT.\n"
                        "0-19: No tech data available or fully pre-digital.\n"
                        "If no tech stack data AND no hiring data: score 50 and note 'insufficient data' in rationale."
                    ),
                },
                {
                    "key": "data_analytics",
                    "label": "Data & Analytics",
                    "weight": 0.25,
                    "sources": ["techstack", "hiring"],
                    "rubric": (
                        "Primary signals: hiring data (Data Engineers, Data Scientists, ML Ops, Analytics Engineers), data-related strategic tags, company product.\n"
                        "Secondary signals: analytics tools detected on website (Segment, Amplitude — useful for non-tech companies, irrelevant for data/AI companies).\n\n"
                        "80-100: Company's core product IS data or AI, OR actively hiring multiple data roles. 'Data Infrastructure' strategic tag present.\n"
                        "60-79: Some data hiring but not a strategic focus. OR advanced analytics tooling (Segment/Amplitude + A/B testing).\n"
                        "40-59: No data-specific hiring. Basic website analytics only (GA alone). No experimentation signals.\n"
                        "20-39: No data signals at all — no data roles, no analytics tools."
                    ),
                },
                {
                    "key": "ai_readiness",
                    "label": "AI Readiness",
                    "weight": 0.25,
                    "sources": ["hiring", "patents", "techstack"],
                    "rubric": (
                        "95-100: Company's core product IS AI/ML (e.g., OpenAI, Anthropic, Google DeepMind, Nvidia AI). AI is the business.\n"
                        "80-94: Active AI hiring (AI/ML roles >10% of engineering), AI-related patents, AI tools/platforms, 'AI/ML Investment' strategic tag.\n"
                        "60-79: Some AI hiring (5-10% of engineering) or AI patents exist, but no visible unified AI platform strategy.\n"
                        "40-59: Minimal AI signals (1-3 AI roles, or 'AI' mentioned in strategy but not a focus).\n"
                        "20-39: No AI signals — no AI hiring, no AI patents, no AI tools.\n"
                        "Patent bonus: +5-10 if AI/ML patent areas exist in the IP portfolio."
                    ),
                },
                {
                    "key": "org_readiness",
                    "label": "Organizational Readiness",
                    "weight": 0.20,
                    "sources": ["sentiment", "hiring"],
                    "rubric": (
                        "80-100: Growing hiring trend, high engineering ratio (>50%), strong strategic investment tags "
                        "(Cloud/Infrastructure, AI/ML Investment, Platform Migration, Automation). Positive employee sentiment.\n"
                        "60-79: Stable hiring, moderate engineering ratio (30-50%), some strategic investment tags.\n"
                        "40-59: Mixed signals. Flat or slightly declining hiring. Low engineering ratio (<30%). Few strategic tags.\n"
                        "20-39: Shrinking hiring, negative sentiment, no strategic investment signals.\n"
                        "NUANCE: Negative sentiment from rapid growth (burnout, equity complaints during hypergrowth) is NOT the same as "
                        "organizational resistance to change. Distinguish growing pains from structural dysfunction."
                    ),
                },
            ],
            "labels": [
                {"min_score": 80, "label": "Digital Vanguard"},
                {"min_score": 60, "label": "Digital Contender"},
                {"min_score": 40, "label": "Digitally Exposed"},
                {"min_score": 20, "label": "Digital Laggard"},
                {"min_score": 0, "label": "Digital Liability"},
            ],
            "score_label": "Digital Maturity Score",
            "scoring_context": (
                "You are a senior management consultant at a top-tier firm (McKinsey, Deloitte, EY Studio+). "
                "You are preparing a target qualification intelligence briefing to help a consulting partner assess "
                "whether to pursue this company for digital transformation and AI consulting engagements."
            ),
            "angle_guidance": (
                "Identify non-core pain points: org design for hypergrowth, sales ops, M&A integration, regulatory compliance. "
                "NEVER suggest services the company is expert in. If it's an AI company, don't suggest AI Strategy. "
                "If it's a cloud company, don't suggest Cloud Migration. Focus on the messy human/org problems that tech excellence doesn't solve."
            ),
            "risk_focus": (
                "change resistance, budget constraints, leadership gaps, legacy system dependencies, "
                "engagement risks for the consulting firm (long procurement cycles, recent leadership change)"
            ),
            "engagement_service_list": [
                "Cloud Migration & Architecture",
                "AI/ML Strategy & Implementation (only for companies ADOPTING AI, not building it)",
                "Data & Analytics Modernization (only for companies that DON'T have data as their core product)",
                "Digital Customer Experience",
                "IT Operating Model Transformation",
                "Cybersecurity & Compliance",
                "Legacy Application Modernization",
                "Change Management & Org Design",
                "Intelligent Automation / RPA",
                "Supply Chain Digitization",
                "AI Governance & Responsible AI (ONLY for companies ADOPTING AI, never for AI-native companies)",
                "Technology Due Diligence (M&A)",
                "Engineering Effectiveness & Developer Platform",
                "Talent Strategy & Organizational Design",
                "Enterprise Architecture & Technical Debt",
            ],
        },
    },
    {
        "name": "Workforce Management",
        "slug": "workforce-management",
        "description": "Evaluate workforce management maturity for HR/people consulting engagements (Deloitte, Mercer, etc.)",
        "config": {
            "dimensions": [
                {
                    "key": "talent_acquisition",
                    "label": "Talent Acquisition Maturity",
                    "weight": 0.25,
                    "sources": ["hiring"],
                    "rubric": (
                        "80-100: Sophisticated hiring machine — diverse pipelines, employer branding, competitive comp. High volume, strategic hiring.\n"
                        "60-79: Functional TA operation. Hiring actively but some process gaps.\n"
                        "40-59: Basic hiring. Mostly reactive, limited employer brand.\n"
                        "20-39: Struggling to attract talent. High time-to-fill, limited reach.\n"
                        "0-19: Minimal hiring activity or severe talent acquisition dysfunction."
                    ),
                },
                {
                    "key": "employee_experience",
                    "label": "Employee Experience",
                    "weight": 0.25,
                    "sources": ["sentiment"],
                    "rubric": (
                        "80-100: Highly rated employer (4.0+ Glassdoor). Strong culture signals. Low voluntary turnover indicators.\n"
                        "60-79: Generally positive sentiment with some concerns. Glassdoor 3.5-4.0.\n"
                        "40-59: Mixed signals. Notable complaints about management, culture, or work-life balance.\n"
                        "20-39: Poor sentiment. Sub-3.0 Glassdoor, high turnover signals, toxic culture indicators.\n"
                        "0-19: Severe employee experience crisis. Public controversies, mass departures."
                    ),
                },
                {
                    "key": "workforce_analytics",
                    "label": "Workforce Analytics",
                    "weight": 0.20,
                    "sources": ["techstack", "hiring"],
                    "rubric": (
                        "80-100: HR tech stack includes people analytics, HRIS, workforce planning tools. People analytics roles.\n"
                        "60-79: Basic HRIS in place. Some HR tech but no advanced analytics.\n"
                        "40-59: Minimal HR tech footprint. Likely spreadsheet-based workforce planning.\n"
                        "20-39: No evidence of HR technology or people analytics capability.\n"
                        "0-19: Workforce management appears entirely manual or outsourced."
                    ),
                },
                {
                    "key": "org_design",
                    "label": "Organizational Design",
                    "weight": 0.15,
                    "sources": ["hiring", "sentiment"],
                    "rubric": (
                        "80-100: Well-structured org. Clear departments, balanced seniority, leadership pipeline.\n"
                        "60-79: Generally functional but some imbalances (top-heavy, missing middle management).\n"
                        "40-59: Org structure concerns — rapid growth without matching management, department silos.\n"
                        "20-39: Significant structural issues — seniority skew, leadership gaps, high churn in key roles.\n"
                        "0-19: Organizational chaos. No clear structure, constant reorgs, mass departures."
                    ),
                },
                {
                    "key": "change_readiness",
                    "label": "Change Readiness",
                    "weight": 0.15,
                    "sources": ["sentiment", "financial"],
                    "rubric": (
                        "80-100: Strong financial position + positive sentiment = can invest in and sustain transformation.\n"
                        "60-79: Financial capacity exists but cultural readiness uncertain.\n"
                        "40-59: Either financial or cultural barriers present. Engagement possible but challenging.\n"
                        "20-39: Both financial strain and cultural resistance. High-risk engagement.\n"
                        "0-19: Company not in a position to absorb consulting engagement costs or change."
                    ),
                },
            ],
            "labels": [
                {"min_score": 80, "label": "Workforce Leader"},
                {"min_score": 60, "label": "Workforce Builder"},
                {"min_score": 40, "label": "Workforce Challenger"},
                {"min_score": 20, "label": "Workforce Laggard"},
                {"min_score": 0, "label": "Workforce Crisis"},
            ],
            "score_label": "Workforce Maturity Score",
            "scoring_context": "You are a workforce management consultant evaluating a company's people operations maturity for a consulting engagement.",
            "angle_guidance": "Identify the biggest gaps between their current workforce management and industry best practices.",
            "risk_focus": "leadership buy-in, budget for HR transformation, change fatigue, competing priorities",
        },
    },
]


def ensure_preset_lenses(conn):
    """Seed preset lenses if they don't exist, and update if config has changed."""
    for preset in _PRESET_LENSES:
        config_str = json.dumps(preset["config"], sort_keys=True)
        config_hash = hashlib.md5(config_str.encode()).hexdigest()
        existing = conn.execute("SELECT id, config_json FROM lenses WHERE slug = ?", (preset["slug"],)).fetchone()
        if existing:
            # Check if config changed — update if so
            existing_hash = hashlib.md5(
                json.dumps(json.loads(existing["config_json"]), sort_keys=True).encode()
            ).hexdigest()
            if existing_hash != config_hash:
                now = datetime.now(timezone.utc).isoformat()
                conn.execute(
                    "UPDATE lenses SET config_json = ?, description = ?, updated_at = ? WHERE id = ?",
                    (json.dumps(preset["config"]), preset["description"], now, existing["id"]),
                )
                print(f"[db] Updated preset lens '{preset['slug']}' — config changed")
            continue
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT INTO lenses (name, slug, description, config_json, is_preset, created_at, updated_at) VALUES (?, ?, ?, ?, 1, ?, ?)",
            (preset["name"], preset["slug"], preset["description"], json.dumps(preset["config"]), now, now),
        )
    conn.commit()


# ---- Lens CRUD helpers ----

def create_lens(conn, name, slug, description, config_json):
    """Create a user-defined lens. Returns lens id."""
    now = datetime.now(timezone.utc).isoformat()
    cur = conn.execute(
        "INSERT INTO lenses (name, slug, description, config_json, is_preset, created_at, updated_at) VALUES (?, ?, ?, ?, 0, ?, ?)",
        (name, slug, description, json.dumps(config_json) if isinstance(config_json, dict) else config_json, now, now),
    )
    conn.commit()
    return cur.lastrowid


def update_lens(conn, lens_id, name=None, description=None, config_json=None):
    """Update a lens. Only non-None fields are changed."""
    updates, params = [], []
    if name is not None:
        updates.append("name = ?"); params.append(name)
    if description is not None:
        updates.append("description = ?"); params.append(description)
    if config_json is not None:
        updates.append("config_json = ?")
        params.append(json.dumps(config_json) if isinstance(config_json, dict) else config_json)
    if not updates:
        return
    updates.append("updated_at = ?"); params.append(datetime.now(timezone.utc).isoformat())
    params.append(lens_id)
    conn.execute(f"UPDATE lenses SET {', '.join(updates)} WHERE id = ?", params)
    conn.commit()


def delete_lens(conn, lens_id):
    """Delete a non-preset lens. Returns True if deleted."""
    row = conn.execute("SELECT is_preset FROM lenses WHERE id = ?", (lens_id,)).fetchone()
    if not row or row["is_preset"]:
        return False
    conn.execute("DELETE FROM lens_scores WHERE lens_id = ?", (lens_id,))
    conn.execute("DELETE FROM lenses WHERE id = ?", (lens_id,))
    conn.commit()
    return True


def get_lens(conn, lens_id):
    """Get a single lens by id."""
    row = conn.execute("SELECT * FROM lenses WHERE id = ?", (lens_id,)).fetchone()
    if not row:
        return None
    d = dict(row)
    d["config"] = json.loads(d["config_json"]) if d.get("config_json") else {}
    return d


def get_lens_by_slug(conn, slug):
    """Get a single lens by slug."""
    row = conn.execute("SELECT * FROM lenses WHERE slug = ?", (slug,)).fetchone()
    if not row:
        return None
    d = dict(row)
    d["config"] = json.loads(d["config_json"]) if d.get("config_json") else {}
    return d


def get_all_lenses(conn):
    """Get all lenses, ordered presets first then by name."""
    rows = conn.execute("SELECT * FROM lenses ORDER BY is_preset DESC, name").fetchall()
    result = []
    for row in rows:
        d = dict(row)
        d["config"] = json.loads(d["config_json"]) if d.get("config_json") else {}
        result.append(d)
    return result


# ---- Lens Score helpers ----

def save_lens_score(conn, dossier_id, lens_id, overall_score, overall_label, score_json, analyses_used=None):
    """Upsert a lens score for a dossier. Returns the score id."""
    now = datetime.now(timezone.utc).isoformat()
    score_text = json.dumps(score_json) if isinstance(score_json, dict) else score_json
    analyses_text = json.dumps(analyses_used) if isinstance(analyses_used, dict) else analyses_used
    existing = conn.execute(
        "SELECT id FROM lens_scores WHERE dossier_id = ? AND lens_id = ?",
        (dossier_id, lens_id),
    ).fetchone()
    if existing:
        conn.execute(
            "UPDATE lens_scores SET overall_score = ?, overall_label = ?, score_json = ?, analyses_used = ?, scored_at = ? WHERE id = ?",
            (overall_score, overall_label, score_text, analyses_text, now, existing["id"]),
        )
        conn.commit()
        return existing["id"]
    else:
        cur = conn.execute(
            "INSERT INTO lens_scores (dossier_id, lens_id, overall_score, overall_label, score_json, analyses_used, scored_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (dossier_id, lens_id, overall_score, overall_label, score_text, analyses_text, now),
        )
        conn.commit()
        return cur.lastrowid


def get_lens_scores_for_dossier(conn, dossier_id):
    """Get all lens scores for a dossier, joined with lens name/slug."""
    rows = conn.execute(
        """SELECT ls.*, l.name as lens_name, l.slug as lens_slug, l.config_json as lens_config_json
           FROM lens_scores ls JOIN lenses l ON ls.lens_id = l.id
           WHERE ls.dossier_id = ? ORDER BY ls.scored_at DESC""",
        (dossier_id,),
    ).fetchall()
    result = []
    for row in rows:
        d = dict(row)
        d["score_data"] = json.loads(d["score_json"]) if d.get("score_json") else {}
        d["lens_config"] = json.loads(d["lens_config_json"]) if d.get("lens_config_json") else {}
        result.append(d)
    return result


def get_lens_score(conn, dossier_id, lens_id):
    """Get a single lens score."""
    row = conn.execute(
        "SELECT * FROM lens_scores WHERE dossier_id = ? AND lens_id = ?",
        (dossier_id, lens_id),
    ).fetchone()
    if not row:
        return None
    d = dict(row)
    d["score_data"] = json.loads(d["score_json"]) if d.get("score_json") else {}
    return d


def get_all_scores_for_lens(conn, lens_id):
    """Get all companies scored through a specific lens, ranked by score."""
    rows = conn.execute(
        """SELECT ls.*, d.company_name
           FROM lens_scores ls JOIN dossiers d ON ls.dossier_id = d.id
           WHERE ls.lens_id = ? ORDER BY ls.overall_score DESC""",
        (lens_id,),
    ).fetchall()
    result = []
    for row in rows:
        d = dict(row)
        d["score_data"] = json.loads(d["score_json"]) if d.get("score_json") else {}
        result.append(d)
    return result


# ── Signal helpers ─────────────────────────────────────────────────────

def insert_signal(conn, signal_dict):
    """Insert a signal, ignoring duplicates by content_hash. Returns signal id or None."""
    try:
        cur = conn.execute(
            """INSERT OR IGNORE INTO signals
               (source, domain, title, url, body, published_at, source_name, content_hash, raw_json, source_type)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                signal_dict["source"],
                signal_dict["domain"],
                signal_dict["title"],
                signal_dict.get("url", ""),
                signal_dict.get("body", ""),
                signal_dict.get("published_at", ""),
                signal_dict.get("source_name", ""),
                signal_dict["content_hash"],
                signal_dict.get("raw_json"),
                signal_dict.get("source_type", "news"),
            ),
        )
        return cur.lastrowid if cur.rowcount > 0 else None
    except Exception as e:
        print(f"[db] insert_signal error: {e}")
        return None


def insert_signals_batch(conn, signals):
    """Insert a batch of signals, returning count of new inserts."""
    new_count = 0
    for sig in signals:
        sid = insert_signal(conn, sig)
        if sid:
            new_count += 1
    conn.commit()
    return new_count


def get_signals(conn, domain=None, days_back=7, limit=200):
    """Fetch signals with optional domain filter and recency window."""
    if domain:
        rows = conn.execute(
            """SELECT * FROM signals
               WHERE domain = ? AND collected_at >= datetime('now', ?)
               ORDER BY collected_at DESC LIMIT ?""",
            (domain, f"-{days_back} days", limit),
        ).fetchall()
    else:
        rows = conn.execute(
            """SELECT * FROM signals
               WHERE collected_at >= datetime('now', ?)
               ORDER BY collected_at DESC LIMIT ?""",
            (f"-{days_back} days", limit),
        ).fetchall()
    return [dict(r) for r in rows]


def get_unassigned_signals(conn, days_back=1, limit=300):
    """Fetch signals not yet assigned to any thread, within recency window."""
    rows = conn.execute(
        """SELECT s.* FROM signals s
           LEFT JOIN signal_cluster_items sci ON sci.signal_id = s.id
           WHERE sci.id IS NULL AND s.collected_at >= datetime('now', ?)
           ORDER BY s.collected_at DESC LIMIT ?""",
        (f"-{days_back} days", limit),
    ).fetchall()
    return [dict(r) for r in rows]


def get_signal_counts_by_domain(conn, days_back=7):
    """Get signal counts per domain for the last N days."""
    rows = conn.execute(
        """SELECT domain, COUNT(*) as cnt FROM signals
           WHERE collected_at >= datetime('now', ?)
           GROUP BY domain ORDER BY cnt DESC""",
        (f"-{days_back} days",),
    ).fetchall()
    return {r["domain"]: r["cnt"] for r in rows}


def get_signal_freshness(conn):
    """Get most recent collected_at per domain."""
    rows = conn.execute(
        """SELECT domain, MAX(collected_at) as last_scan FROM signals
           GROUP BY domain"""
    ).fetchall()
    return {r["domain"]: r["last_scan"] for r in rows}


def insert_signal_cluster(conn, cluster_dict):
    """Insert a signal cluster. Returns cluster id."""
    cur = conn.execute(
        """INSERT INTO signal_clusters
           (domain, title, synthesis, opportunity_score, opportunity_type, estimated_scope)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (
            cluster_dict["domain"],
            cluster_dict["title"],
            cluster_dict.get("synthesis"),
            cluster_dict.get("opportunity_score"),
            cluster_dict.get("opportunity_type"),
            cluster_dict.get("estimated_scope"),
        ),
    )
    conn.commit()
    return cur.lastrowid


def link_signal_to_cluster(conn, cluster_id, signal_id):
    """Link a signal to a cluster (junction table)."""
    try:
        conn.execute(
            "INSERT OR IGNORE INTO signal_cluster_items (cluster_id, signal_id) VALUES (?, ?)",
            (cluster_id, signal_id),
        )
    except Exception:
        pass


def get_signal_clusters(conn, domain=None, status="active", limit=50, min_signals=0, exclude_domain=None):
    """Fetch signal clusters (threads) with signal counts, sorted by most recently active."""
    where = []
    params = []
    if status and status != "all":
        where.append("sc.status = ?")
        params.append(status)
    if domain:
        where.append("sc.domain = ?")
        params.append(domain)
    if exclude_domain:
        where.append("sc.domain != ?")
        params.append(exclude_domain)
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    having_sql = f"HAVING COUNT(sci.signal_id) >= {int(min_signals)}" if min_signals > 0 else ""
    rows = conn.execute(
        f"""SELECT sc.*, COUNT(sci.signal_id) as signal_count
            FROM signal_clusters sc
            LEFT JOIN signal_cluster_items sci ON sci.cluster_id = sc.id
            {where_sql}
            GROUP BY sc.id {having_sql}
            ORDER BY COALESCE(sc.last_signal_at, sc.created_at) DESC LIMIT ?""",
        (*params, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def get_cluster_detail(conn, cluster_id):
    """Fetch a single cluster with its signals and entities."""
    cluster = conn.execute(
        "SELECT * FROM signal_clusters WHERE id = ?", (cluster_id,)
    ).fetchone()
    if not cluster:
        return None

    d = dict(cluster)

    # Attached signals
    signals = conn.execute(
        """SELECT s.* FROM signals s
           JOIN signal_cluster_items sci ON sci.signal_id = s.id
           WHERE sci.cluster_id = ? ORDER BY s.published_at DESC""",
        (cluster_id,),
    ).fetchall()
    d["signals"] = [dict(s) for s in signals]

    # Attached entities
    entities = conn.execute(
        "SELECT * FROM signal_entities WHERE cluster_id = ?", (cluster_id,)
    ).fetchall()
    d["entities"] = [dict(e) for e in entities]

    return d


def insert_signal_entity(conn, entity_dict):
    """Insert a signal entity. Returns entity id."""
    cur = conn.execute(
        """INSERT INTO signal_entities
           (signal_id, cluster_id, entity_type, entity_value, normalized_value, dossier_id, campaign_id, metadata_json)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            entity_dict.get("signal_id"),
            entity_dict.get("cluster_id"),
            entity_dict["entity_type"],
            entity_dict["entity_value"],
            entity_dict.get("normalized_value"),
            entity_dict.get("dossier_id"),
            entity_dict.get("campaign_id"),
            entity_dict.get("metadata_json"),
        ),
    )
    return cur.lastrowid


def set_signal_status(conn, signal_id, status):
    """Set a signal's status ('signal' or 'noise')."""
    conn.execute("UPDATE signals SET signal_status = ? WHERE id = ?", (status, signal_id))
    conn.commit()


def get_pattern_signal_noise_counts(conn, pattern_id):
    """Get signal vs noise counts for a pattern."""
    row = conn.execute(
        """SELECT
             COUNT(*) as total,
             SUM(CASE WHEN COALESCE(s.signal_status, 'signal') = 'signal' THEN 1 ELSE 0 END) as signal_count,
             SUM(CASE WHEN s.signal_status = 'noise' THEN 1 ELSE 0 END) as noise_count
           FROM signal_cluster_items sci
           JOIN signals s ON s.id = sci.signal_id
           WHERE sci.cluster_id = ?""",
        (pattern_id,),
    ).fetchone()
    return {"total": row["total"], "signal_count": row["signal_count"], "noise_count": row["noise_count"]}


def save_scan_history(conn, scan_data):
    """Save a scan result. Keeps only the last 3 entries."""
    conn.execute(
        """INSERT INTO scan_history
           (total_collected, new_inserted, domains_json, threads_created, threads_assigned,
            articles_enriched, entities_extracted, duration_seconds)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            scan_data.get("total_collected", 0),
            scan_data.get("new_inserted", 0),
            json.dumps(scan_data.get("domains", {})),
            scan_data.get("threads_created", 0),
            scan_data.get("threads_assigned", 0),
            scan_data.get("articles_enriched", 0),
            scan_data.get("entities_extracted", 0),
            scan_data.get("duration_seconds"),
        ),
    )
    # Prune to last 3
    conn.execute(
        "DELETE FROM scan_history WHERE id NOT IN (SELECT id FROM scan_history ORDER BY created_at DESC LIMIT 3)"
    )
    conn.commit()


def get_scan_history(conn):
    """Fetch the last 3 scan results."""
    rows = conn.execute(
        "SELECT * FROM scan_history ORDER BY created_at DESC LIMIT 3"
    ).fetchall()
    results = []
    for r in rows:
        d = dict(r)
        d["domains"] = json.loads(d["domains_json"]) if d.get("domains_json") else {}
        results.append(d)
    return results


def update_cluster_status(conn, cluster_id, status):
    """Update a cluster's status (active/dismissed/converted)."""
    conn.execute(
        "UPDATE signal_clusters SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (status, cluster_id),
    )
    conn.commit()


# ── Brainstorm helpers ─────────────────────────────────────────────────

def save_brainstorm(conn, thread_ids, result):
    """Persist a brainstorm session. Returns brainstorm id."""
    cur = conn.execute(
        """INSERT INTO brainstorms (thread_ids, connection_summary, hypotheses_json, second_order_json, questions_json)
           VALUES (?, ?, ?, ?, ?)""",
        (
            json.dumps(thread_ids),
            result.get("connection_summary", ""),
            json.dumps(result.get("hypotheses", [])),
            json.dumps(result.get("second_order_effects", [])),
            json.dumps(result.get("questions_to_investigate", [])),
        ),
    )
    conn.commit()
    return cur.lastrowid


def get_brainstorms(conn, limit=20):
    """Fetch recent brainstorm sessions."""
    rows = conn.execute(
        "SELECT * FROM brainstorms ORDER BY created_at DESC LIMIT ?", (limit,)
    ).fetchall()
    results = []
    for r in rows:
        d = dict(r)
        d["thread_ids"] = json.loads(d["thread_ids"]) if d.get("thread_ids") else []
        d["hypotheses"] = json.loads(d["hypotheses_json"]) if d.get("hypotheses_json") else []
        d["second_order_effects"] = json.loads(d["second_order_json"]) if d.get("second_order_json") else []
        d["questions_to_investigate"] = json.loads(d["questions_json"]) if d.get("questions_json") else []
        results.append(d)
    return results


def get_brainstorm(conn, brainstorm_id):
    """Fetch a single brainstorm session."""
    row = conn.execute("SELECT * FROM brainstorms WHERE id = ?", (brainstorm_id,)).fetchone()
    if not row:
        return None
    d = dict(row)
    d["thread_ids"] = json.loads(d["thread_ids"]) if d.get("thread_ids") else []
    d["hypotheses"] = json.loads(d["hypotheses_json"]) if d.get("hypotheses_json") else []
    d["second_order_effects"] = json.loads(d["second_order_json"]) if d.get("second_order_json") else []
    d["questions_to_investigate"] = json.loads(d["questions_json"]) if d.get("questions_json") else []
    return d


# ── Thread link helpers ────────────────────────────────────────────────

def add_thread_link(conn, thread_a_id, thread_b_id, label=None):
    """Create a manual link between two threads. Returns link id or None if exists."""
    # Normalize order
    a, b = min(thread_a_id, thread_b_id), max(thread_a_id, thread_b_id)
    try:
        cur = conn.execute(
            "INSERT OR IGNORE INTO thread_links (thread_a_id, thread_b_id, label) VALUES (?, ?, ?)",
            (a, b, label),
        )
        conn.commit()
        return cur.lastrowid if cur.rowcount > 0 else None
    except Exception:
        return None


def get_thread_links(conn):
    """Fetch all manual thread links."""
    rows = conn.execute(
        "SELECT * FROM thread_links ORDER BY created_at DESC"
    ).fetchall()
    return [dict(r) for r in rows]


def delete_thread_link(conn, link_id):
    """Delete a manual thread link."""
    conn.execute("DELETE FROM thread_links WHERE id = ?", (link_id,))
    conn.commit()


# ===================== NARRATIVES =====================

def insert_narrative(conn, data):
    """Create a new narrative. Returns the new narrative ID."""
    cur = conn.execute(
        """INSERT INTO narratives (title, thesis, reasoning, sub_claims_json, search_queries_json, confidence_score)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (data["title"], data["thesis"], data.get("reasoning", ""),
         json.dumps(data.get("sub_claims", [])), json.dumps(data.get("search_queries", [])),
         data.get("confidence_score")),
    )
    conn.commit()
    return cur.lastrowid


def get_narratives(conn, status="all", limit=50):
    """Fetch narratives with thread counts."""
    where = "WHERE n.status = ?" if status != "all" else ""
    params = [status, limit] if status != "all" else [limit]
    rows = conn.execute(
        f"""SELECT n.*, COUNT(sc.id) as thread_count,
                   SUM(CASE WHEN sci_cnt.cnt > 0 THEN sci_cnt.cnt ELSE 0 END) as signal_count
            FROM narratives n
            LEFT JOIN signal_clusters sc ON sc.narrative_id = n.id
            LEFT JOIN (SELECT cluster_id, COUNT(*) as cnt FROM signal_cluster_items GROUP BY cluster_id) sci_cnt
                ON sci_cnt.cluster_id = sc.id
            {where}
            GROUP BY n.id ORDER BY n.updated_at DESC LIMIT ?""",
        params,
    ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d["sub_claims"] = json.loads(d["sub_claims_json"]) if d.get("sub_claims_json") else []
        d["search_queries"] = json.loads(d["search_queries_json"]) if d.get("search_queries_json") else []
        result.append(d)
    return result


def get_narrative(conn, narrative_id):
    """Fetch a single narrative with its threads and evidence summary."""
    row = conn.execute("SELECT * FROM narratives WHERE id = ?", (narrative_id,)).fetchone()
    if not row:
        return None
    d = dict(row)
    d["sub_claims"] = json.loads(d["sub_claims_json"]) if d.get("sub_claims_json") else []
    d["search_queries"] = json.loads(d["search_queries_json"]) if d.get("search_queries_json") else []
    # Get threads belonging to this narrative
    threads = conn.execute(
        """SELECT sc.*, COUNT(sci.signal_id) as signal_count
           FROM signal_clusters sc
           LEFT JOIN signal_cluster_items sci ON sci.cluster_id = sc.id
           WHERE sc.narrative_id = ?
           GROUP BY sc.id ORDER BY sc.last_signal_at DESC""",
        (narrative_id,),
    ).fetchall()
    d["threads"] = [dict(t) for t in threads]
    # Evidence stance counts across all threads
    stances = conn.execute(
        """SELECT sci.evidence_stance, COUNT(*) as cnt
           FROM signal_cluster_items sci
           JOIN signal_clusters sc ON sc.id = sci.cluster_id
           WHERE sc.narrative_id = ?
           GROUP BY sci.evidence_stance""",
        (narrative_id,),
    ).fetchall()
    d["evidence"] = {s["evidence_stance"]: s["cnt"] for s in stances}
    return d


def update_narrative(conn, narrative_id, data):
    """Update a narrative's fields."""
    fields = []
    params = []
    for key in ("title", "thesis", "reasoning", "confidence_score", "status"):
        if key in data:
            fields.append(f"{key} = ?")
            params.append(data[key])
    if "sub_claims" in data:
        fields.append("sub_claims_json = ?")
        params.append(json.dumps(data["sub_claims"]))
    if "search_queries" in data:
        fields.append("search_queries_json = ?")
        params.append(json.dumps(data["search_queries"]))
    if not fields:
        return
    fields.append("updated_at = CURRENT_TIMESTAMP")
    params.append(narrative_id)
    conn.execute(f"UPDATE narratives SET {', '.join(fields)} WHERE id = ?", params)
    conn.commit()


def delete_narrative(conn, narrative_id):
    """Delete a narrative and unlink its threads."""
    conn.execute("UPDATE signal_clusters SET narrative_id = NULL WHERE narrative_id = ?", (narrative_id,))
    conn.execute("DELETE FROM narratives WHERE id = ?", (narrative_id,))
    conn.commit()


def link_thread_to_narrative(conn, thread_id, narrative_id):
    """Assign a thread to a narrative."""
    conn.execute(
        "UPDATE signal_clusters SET narrative_id = ? WHERE id = ?",
        (narrative_id, thread_id),
    )
    conn.commit()


def unlink_thread_from_narrative(conn, thread_id):
    """Remove a thread from its narrative."""
    conn.execute("UPDATE signal_clusters SET narrative_id = NULL WHERE id = ?", (thread_id,))
    conn.commit()


# ===================== HYPOTHESIS BANK =====================

def insert_hypothesis(conn, data):
    """Save a hypothesis to the bank."""
    cur = conn.execute(
        """INSERT INTO hypotheses (title, reasoning, confidence, investigate_query,
           source_thread_ids, source_entities_json, status, brainstorm_id)
           VALUES (?, ?, ?, ?, ?, ?, 'captured', ?)""",
        (data["title"], data.get("reasoning", ""), data.get("confidence", "medium"),
         data.get("investigate_query", ""), json.dumps(data.get("source_thread_ids", [])),
         json.dumps(data.get("source_entities", [])), data.get("brainstorm_id")),
    )
    conn.commit()
    return cur.lastrowid


def get_hypotheses(conn, status=None, limit=50):
    """Fetch hypotheses, optionally filtered by status."""
    if status and status != "all":
        rows = conn.execute(
            "SELECT * FROM hypotheses WHERE status = ? ORDER BY created_at DESC LIMIT ?",
            (status, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM hypotheses ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d["source_thread_ids"] = json.loads(d["source_thread_ids"]) if d.get("source_thread_ids") else []
        d["source_entities"] = json.loads(d["source_entities_json"]) if d.get("source_entities_json") else []
        result.append(d)
    return result


def get_hypothesis_concept_graph(conn):
    """Build a concept overlap graph from all captured hypotheses.
    Extracts [[concepts]] from title/reasoning + entities from source_entities_json.
    Returns {concepts: [{name, hypothesis_ids}], hypotheses: [{id, title, concepts}]}."""
    import re
    hypotheses = get_hypotheses(conn, status="captured", limit=100)
    concept_map = {}  # concept_name -> set of hyp IDs
    hyp_concepts = {}  # hyp_id -> list of concept names

    for h in hypotheses:
        concepts = set()
        # Extract [[concept]] from title and reasoning
        text = (h.get("title", "") or "") + " " + (h.get("reasoning", "") or "")
        for match in re.findall(r'\[\[([^\]]+)\]\]', text):
            concepts.add(match.lower().strip())
        # Also include entity names from source_entities
        for e in (h.get("source_entities") or []):
            name = e.get("name") or e.get("entity_value") or (e if isinstance(e, str) else "")
            if name and len(str(name)) >= 3:
                concepts.add(str(name).lower().strip())

        hyp_concepts[h["id"]] = list(concepts)
        for c in concepts:
            if c not in concept_map:
                concept_map[c] = set()
            concept_map[c].add(h["id"])

    # Filter to concepts appearing in 2+ hypotheses (the overlaps)
    shared_concepts = {c: ids for c, ids in concept_map.items() if len(ids) >= 2}

    return {
        "concepts": [{"name": c, "hypothesis_ids": sorted(ids)} for c, ids in sorted(shared_concepts.items(), key=lambda x: -len(x[1]))],
        "hypotheses": [{"id": h["id"], "title": h.get("title", ""), "confidence": h.get("confidence", "medium"),
                        "concepts": [c for c in hyp_concepts.get(h["id"], []) if c in shared_concepts]}
                       for h in hypotheses if any(c in shared_concepts for c in hyp_concepts.get(h["id"], []))],
    }


# ── Causal link helpers ────────────────────────────────────────────────

def add_causal_link(conn, cause_thread_id, effect_thread_id, label=None,
                    hypothesis_id=None, confidence='medium', status='captured',
                    reasoning=None, brainstorm_id=None):
    """Create a directed causal link between two threads. Returns link id or None if exists."""
    try:
        cur = conn.execute(
            """INSERT OR IGNORE INTO causal_links
               (cause_thread_id, effect_thread_id, label, hypothesis_id,
                confidence, status, reasoning, brainstorm_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (cause_thread_id, effect_thread_id, label, hypothesis_id,
             confidence, status, reasoning, brainstorm_id),
        )
        conn.commit()
        return cur.lastrowid if cur.rowcount > 0 else None
    except Exception:
        return None


def get_causal_links(conn, thread_id=None, status=None):
    """Fetch causal links, optionally filtered by thread involvement or status."""
    query = "SELECT * FROM causal_links"
    conditions, params = [], []
    if thread_id:
        conditions.append("(cause_thread_id = ? OR effect_thread_id = ?)")
        params.extend([thread_id, thread_id])
    if status:
        conditions.append("status = ?")
        params.append(status)
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY created_at DESC"
    return [dict(r) for r in conn.execute(query, params).fetchall()]


def update_causal_link(conn, link_id, **kwargs):
    """Update causal link fields (label, status, confidence, reasoning)."""
    allowed = {'label', 'status', 'confidence', 'reasoning', 'hypothesis_id'}
    updates = {k: v for k, v in kwargs.items() if k in allowed}
    if not updates:
        return
    updates['updated_at'] = datetime.now(timezone.utc).isoformat()
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    conn.execute(f"UPDATE causal_links SET {set_clause} WHERE id = ?",
                 (*updates.values(), link_id))
    conn.commit()


def delete_causal_link(conn, link_id):
    """Delete a causal link."""
    conn.execute("DELETE FROM causal_links WHERE id = ?", (link_id,))
    conn.commit()


def get_causal_suggestions(conn, limit=20):
    """Discover potential causal links using three heuristics:
    1. Temporal lead/lag between threads
    2. Entity overlap (shared entities suggest connection)
    3. Brainstorm second-order effects (LLM-generated causal predictions)
    Excludes pairs that already have a causal_link."""

    # Fetch active threads with signal counts (exclude narrative threads)
    threads = conn.execute(
        """SELECT sc.id, sc.title, sc.domain, sc.created_at, sc.last_signal_at,
                  COUNT(sci.id) as signal_count
           FROM signal_clusters sc
           LEFT JOIN signal_cluster_items sci ON sci.cluster_id = sc.id
           WHERE sc.status = 'active' AND sc.domain != 'narrative'
           GROUP BY sc.id HAVING signal_count >= 2
           ORDER BY sc.last_signal_at DESC LIMIT 60"""
    ).fetchall()
    threads = [dict(t) for t in threads]
    if len(threads) < 2:
        return []

    thread_map = {t["id"]: t for t in threads}
    thread_ids = [t["id"] for t in threads]

    # Existing causal links — exclude these pairs
    existing = set()
    for row in conn.execute("SELECT cause_thread_id, effect_thread_id FROM causal_links").fetchall():
        existing.add((row[0], row[1]))
        existing.add((row[1], row[0]))  # both directions

    # ── Heuristic 1: Temporal lead/lag ──
    # Batch query: median signal date per thread
    placeholders = ",".join("?" * len(thread_ids))
    temporal = {}
    rows = conn.execute(
        f"""SELECT sci.cluster_id as tid,
                   MIN(s.published_at) as first_sig,
                   MAX(s.published_at) as last_sig,
                   AVG(julianday(s.published_at)) as median_jd
            FROM signal_cluster_items sci
            JOIN signals s ON s.id = sci.signal_id
            WHERE sci.cluster_id IN ({placeholders})
              AND s.published_at IS NOT NULL AND s.published_at != ''
            GROUP BY sci.cluster_id""",
        thread_ids
    ).fetchall()
    for r in rows:
        temporal[r["tid"]] = {
            "first": r["first_sig"][:10] if r["first_sig"] else None,
            "last": r["last_sig"][:10] if r["last_sig"] else None,
            "median_jd": r["median_jd"],
        }

    # ── Heuristic 2: Entity overlap ──
    # Batch query: all entities for all threads at once
    entity_rows = conn.execute(
        f"""SELECT DISTINCT
                COALESCE(se.cluster_id, sci.cluster_id) as tid,
                LOWER(COALESCE(se.normalized_value, se.entity_value)) as name
            FROM signal_entities se
            LEFT JOIN signal_cluster_items sci ON sci.signal_id = se.signal_id
            WHERE COALESCE(se.cluster_id, sci.cluster_id) IN ({placeholders})""",
        thread_ids
    ).fetchall()
    thread_entities = {}
    for r in entity_rows:
        tid = r["tid"]
        if tid not in thread_entities:
            thread_entities[tid] = set()
        if r["name"] and len(r["name"]) >= 3:
            thread_entities[tid].add(r["name"])

    # ── Heuristic 3: Brainstorm second-order effects ──
    brainstorms = conn.execute("SELECT * FROM brainstorms ORDER BY created_at DESC LIMIT 30").fetchall()
    # Build a lookup: lowercase thread title → thread id
    title_to_id = {}
    for t in threads:
        for word in t["title"].lower().split():
            clean = word.strip(".,;:!?\"'()-")
            if len(clean) > 4:
                if clean not in title_to_id:
                    title_to_id[clean] = set()
                title_to_id[clean].add(t["id"])

    brainstorm_links = []  # (cause_tid, effect_tid, effect_text)
    for bs in brainstorms:
        bs_thread_ids = json.loads(bs["thread_ids"]) if bs["thread_ids"] else []
        effects = json.loads(bs["second_order_json"]) if bs.get("second_order_json") else []
        for eff in effects:
            effect_text = (eff.get("effect") or "").lower()
            if not effect_text:
                continue
            # Find which threads the effect text matches (by keyword)
            matched_tids = set()
            for word in effect_text.split():
                clean = word.strip(".,;:!?\"'()-")
                if clean in title_to_id:
                    matched_tids.update(title_to_id[clean])
            # Effect points from brainstorm source threads → matched effect threads
            for cause_tid in bs_thread_ids:
                for effect_tid in matched_tids:
                    if cause_tid != effect_tid and cause_tid in thread_map:
                        brainstorm_links.append((cause_tid, effect_tid, eff.get("effect", "")))

    # ── Score all pairs ──
    scored = {}
    for i, tid_a in enumerate(thread_ids):
        for tid_b in thread_ids[i+1:]:
            if (tid_a, tid_b) in existing:
                continue

            reasons = []
            score = 0

            # Temporal: does A lead B or B lead A?
            ta = temporal.get(tid_a)
            tb = temporal.get(tid_b)
            cause, effect = tid_a, tid_b
            if ta and tb and ta["median_jd"] and tb["median_jd"]:
                lag_days = tb["median_jd"] - ta["median_jd"]
                if abs(lag_days) >= 2:
                    if lag_days < 0:
                        cause, effect = tid_b, tid_a
                        lag_days = -lag_days
                    temporal_score = min(int(lag_days), 10)  # cap at 10
                    score += temporal_score
                    reasons.append({"type": "temporal", "detail": f"Leads by {int(lag_days)} days"})

            # Entity overlap
            ents_a = thread_entities.get(tid_a, set())
            ents_b = thread_entities.get(tid_b, set())
            shared = ents_a & ents_b
            if len(shared) >= 2:
                entity_score = len(shared) * 3
                score += entity_score
                reasons.append({"type": "entity", "detail": f"Shared: {', '.join(list(shared)[:4])}"})

            # Brainstorm second-order
            for (c, e, txt) in brainstorm_links:
                if (c == cause and e == effect) or (c == effect and e == cause):
                    score += 5
                    reasons.append({"type": "brainstorm", "detail": f"Second-order: '{txt[:60]}'"})
                    break  # one brainstorm match per pair is enough

            if score >= 5 and reasons:
                key = (cause, effect)
                if key not in scored or scored[key]["score"] < score:
                    scored[key] = {
                        "cause_thread_id": cause,
                        "cause_title": thread_map.get(cause, {}).get("title", ""),
                        "effect_thread_id": effect,
                        "effect_title": thread_map.get(effect, {}).get("title", ""),
                        "score": score,
                        "reasons": reasons,
                    }

    results = sorted(scored.values(), key=lambda x: -x["score"])
    return results[:limit]


def get_causal_graph(conn):
    """Build full causal graph for cascade view rendering."""
    links = [dict(r) for r in conn.execute(
        "SELECT * FROM causal_links ORDER BY created_at"
    ).fetchall()]
    thread_ids = set()
    for l in links:
        thread_ids.add(l["cause_thread_id"])
        thread_ids.add(l["effect_thread_id"])
    threads = {}
    for tid in thread_ids:
        row = conn.execute(
            """SELECT sc.id, sc.title, sc.domain, sc.created_at, sc.last_signal_at,
                      COUNT(sci.id) as signal_count
               FROM signal_clusters sc
               LEFT JOIN signal_cluster_items sci ON sci.cluster_id = sc.id
               WHERE sc.id = ? GROUP BY sc.id""",
            (tid,)
        ).fetchone()
        if row:
            threads[tid] = dict(row)
    # Timeline data: first/last signal dates per thread
    timeline = {}
    for tid in thread_ids:
        row = conn.execute(
            """SELECT MIN(s.published_at) as first_signal, MAX(s.published_at) as last_signal
               FROM signal_cluster_items sci
               JOIN signals s ON s.id = sci.signal_id
               WHERE sci.cluster_id = ? AND s.published_at IS NOT NULL AND s.published_at != ''""",
            (tid,)
        ).fetchone()
        if row and row["first_signal"]:
            timeline[tid] = {"first": row["first_signal"], "last": row["last_signal"]}
    # Positions
    positions = {}
    for row in conn.execute("SELECT node_id, x, y, pinned FROM board_positions WHERE node_type = 'causal'").fetchall():
        positions[row["node_id"]] = dict(row)
    return {"links": links, "threads": threads, "timeline": timeline, "positions": positions}


# ── Causal path helpers ────────────────────────────────────────────────

def create_causal_path(conn, name, thread_ids):
    """Create a named path through the causal graph. Returns path id."""
    cur = conn.execute(
        "INSERT INTO causal_paths (name, thread_ids_json) VALUES (?, ?)",
        (name, json.dumps(thread_ids)),
    )
    conn.commit()
    return cur.lastrowid


def get_causal_paths(conn):
    """Fetch all causal paths."""
    rows = conn.execute("SELECT * FROM causal_paths WHERE status = 'active' ORDER BY updated_at DESC").fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d["thread_ids"] = json.loads(d["thread_ids_json"]) if d.get("thread_ids_json") else []
        result.append(d)
    return result


def update_causal_path(conn, path_id, name=None, thread_ids=None):
    """Update a causal path's name or thread sequence."""
    updates = ["updated_at = CURRENT_TIMESTAMP"]
    params = []
    if name is not None:
        updates.append("name = ?")
        params.append(name)
    if thread_ids is not None:
        updates.append("thread_ids_json = ?")
        params.append(json.dumps(thread_ids))
    params.append(path_id)
    conn.execute(f"UPDATE causal_paths SET {', '.join(updates)} WHERE id = ?", params)
    conn.commit()


def delete_causal_path(conn, path_id):
    """Delete a causal path."""
    conn.execute("DELETE FROM causal_paths WHERE id = ?", (path_id,))
    conn.commit()


def update_hypothesis_status(conn, hypothesis_id, status, narrative_id=None):
    """Update hypothesis status (captured, promoted, dismissed)."""
    if narrative_id:
        conn.execute(
            "UPDATE hypotheses SET status = ?, narrative_id = ? WHERE id = ?",
            (status, narrative_id, hypothesis_id),
        )
    else:
        conn.execute("UPDATE hypotheses SET status = ? WHERE id = ?", (status, hypothesis_id))
    conn.commit()


def delete_hypothesis(conn, hypothesis_id):
    """Delete a hypothesis."""
    conn.execute("DELETE FROM hypotheses WHERE id = ?", (hypothesis_id,))
    conn.commit()


def find_related_hypotheses(conn, thread_ids, limit=10):
    """Find hypotheses related to given threads via entity overlap + keyword matching."""
    if not thread_ids:
        return []

    # Get entities from the given threads
    placeholders = ",".join("?" * len(thread_ids))
    entities = conn.execute(
        f"""SELECT DISTINCT COALESCE(normalized_value, entity_value) as name
            FROM signal_entities
            WHERE cluster_id IN ({placeholders}) OR signal_id IN
              (SELECT signal_id FROM signal_cluster_items WHERE cluster_id IN ({placeholders}))""",
        (*thread_ids, *thread_ids),
    ).fetchall()
    entity_names = {e["name"].lower() for e in entities}

    # Get thread titles for keyword matching
    threads = conn.execute(
        f"SELECT title FROM signal_clusters WHERE id IN ({placeholders})", thread_ids
    ).fetchall()
    # Extract significant words (>3 chars, not stopwords)
    stopwords = {"the", "and", "for", "are", "but", "not", "you", "all", "can", "had", "her",
                  "was", "one", "our", "out", "has", "have", "been", "will", "with", "this",
                  "that", "from", "they", "were", "what", "when", "make", "like", "than",
                  "each", "which", "their", "more", "about", "into", "could", "other"}
    keywords = set()
    for t in threads:
        for word in t["title"].lower().split():
            clean = word.strip(".,;:!?\"'()-")
            if len(clean) > 3 and clean not in stopwords:
                keywords.add(clean)

    # Get all captured hypotheses
    all_hyps = conn.execute(
        "SELECT * FROM hypotheses WHERE status != 'dismissed' ORDER BY created_at DESC LIMIT ?",
        (limit * 3,),
    ).fetchall()

    scored = []
    for h in all_hyps:
        d = dict(h)
        d["source_thread_ids"] = json.loads(d["source_thread_ids"]) if d.get("source_thread_ids") else []
        d["source_entities"] = json.loads(d["source_entities_json"]) if d.get("source_entities_json") else []

        # Skip if this hypothesis was generated from the exact same threads
        if set(d["source_thread_ids"]) == set(thread_ids):
            continue

        score = 0
        match_type = []

        # Entity overlap (strong signal)
        hyp_entities = {e.lower() for e in d["source_entities"]}
        entity_overlap = entity_names & hyp_entities
        if entity_overlap:
            score += len(entity_overlap) * 3
            match_type.append(f"entities: {', '.join(list(entity_overlap)[:3])}")

        # Keyword overlap in title/reasoning (weak signal)
        hyp_text = (d["title"] + " " + (d.get("reasoning") or "")).lower()
        kw_matches = {kw for kw in keywords if kw in hyp_text}
        if kw_matches:
            score += len(kw_matches)
            match_type.append(f"keywords: {', '.join(list(kw_matches)[:3])}")

        if score > 0:
            d["relevance_score"] = score
            d["match_reason"] = "; ".join(match_type)
            scored.append(d)

    scored.sort(key=lambda x: x["relevance_score"], reverse=True)
    return scored[:limit]


# ===================== BOARD =====================

def get_board_state(conn):
    """Get all board positions and notes."""
    positions = conn.execute("SELECT * FROM board_positions").fetchall()
    notes = conn.execute("SELECT * FROM board_notes").fetchall()
    return {
        "positions": {f"{r['node_type']}:{r['node_id']}": dict(r) for r in positions},
        "notes": [dict(n) for n in notes],
    }


def save_board_position(conn, node_type, node_id, x, y, pinned=True):
    """Save or update a node's board position."""
    conn.execute(
        """INSERT INTO board_positions (node_type, node_id, x, y, pinned)
           VALUES (?, ?, ?, ?, ?) ON CONFLICT(node_type, node_id)
           DO UPDATE SET x = ?, y = ?, pinned = ?""",
        (node_type, node_id, x, y, int(pinned), x, y, int(pinned)),
    )
    conn.commit()


def save_board_positions_batch(conn, positions):
    """Save multiple board positions at once."""
    for p in positions:
        conn.execute(
            """INSERT INTO board_positions (node_type, node_id, x, y, pinned)
               VALUES (?, ?, ?, ?, ?) ON CONFLICT(node_type, node_id)
               DO UPDATE SET x = ?, y = ?, pinned = ?""",
            (p["node_type"], p["node_id"], p["x"], p["y"], int(p.get("pinned", True)),
             p["x"], p["y"], int(p.get("pinned", True))),
        )
    conn.commit()


def delete_board_position(conn, node_type, node_id):
    """Remove a node from the board."""
    conn.execute("DELETE FROM board_positions WHERE node_type = ? AND node_id = ?", (node_type, node_id))
    conn.commit()


def insert_board_note(conn, text, x, y, color="#eab308"):
    """Create a sticky note on the board."""
    cur = conn.execute(
        "INSERT INTO board_notes (text, x, y, color) VALUES (?, ?, ?, ?)",
        (text, x, y, color),
    )
    conn.commit()
    return cur.lastrowid


def update_board_note(conn, note_id, text=None, x=None, y=None, color=None):
    """Update a board note."""
    fields, params = [], []
    if text is not None: fields.append("text = ?"); params.append(text)
    if x is not None: fields.append("x = ?"); params.append(x)
    if y is not None: fields.append("y = ?"); params.append(y)
    if color is not None: fields.append("color = ?"); params.append(color)
    if not fields: return
    params.append(note_id)
    conn.execute(f"UPDATE board_notes SET {', '.join(fields)} WHERE id = ?", params)
    conn.commit()


def delete_board_note(conn, note_id):
    """Delete a board note."""
    conn.execute("DELETE FROM board_notes WHERE id = ?", (note_id,))
    conn.commit()
