"""SQLite database setup and helpers for competitive-intel-agent."""

import json
import sqlite3
import hashlib
from datetime import datetime, timezone


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
"""


def get_connection(db_path="intel.db"):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
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
    conn.commit()
    conn.close()


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


def insert_job(conn, company_id, job_dict):
    """Insert a job, skipping duplicates by URL. Returns True if inserted."""
    desc_hash = hash_description(job_dict.get("description", ""))
    try:
        conn.execute(
            """INSERT OR IGNORE INTO jobs
               (company_id, title, department, location, url, description, description_hash, salary, date_posted)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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

def get_or_create_dossier(conn, company_name, sector=None, description=None):
    """Get existing dossier or create a new one. Returns dossier id."""
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
    cur = conn.execute(
        "INSERT INTO dossiers (company_name, sector, description) VALUES (?, ?, ?)",
        (company_name, sector, description),
    )
    conn.commit()
    return cur.lastrowid


def add_dossier_analysis(conn, dossier_id, analysis_type, report_file=None,
                         key_facts_json=None, model_used=None):
    """Record a completed analysis run for a dossier."""
    cur = conn.execute(
        """INSERT INTO dossier_analyses (dossier_id, analysis_type, report_file, key_facts_json, model_used)
           VALUES (?, ?, ?, ?, ?)""",
        (dossier_id, analysis_type, report_file, key_facts_json, model_used),
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


def get_all_dossiers(conn):
    """Get all dossiers with summary stats."""
    rows = conn.execute(
        """SELECT d.*,
                  (SELECT COUNT(*) FROM dossier_analyses WHERE dossier_id = d.id) as analysis_count,
                  (SELECT COUNT(*) FROM dossier_events WHERE dossier_id = d.id) as event_count,
                  (SELECT MAX(created_at) FROM dossier_analyses WHERE dossier_id = d.id) as last_analysis_at
           FROM dossiers d ORDER BY d.updated_at DESC"""
    ).fetchall()
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
