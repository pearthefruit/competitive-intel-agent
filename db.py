"""SQLite database setup and helpers for competitive-intel-agent."""

import sqlite3
import hashlib
from datetime import datetime, timezone


SCHEMA = """
CREATE TABLE IF NOT EXISTS companies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    url TEXT,
    ats_type TEXT,
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
    seniority_level TEXT,
    key_skills TEXT,
    strategic_signals TEXT,
    growth_signal TEXT,
    classified_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    model_used TEXT,
    FOREIGN KEY (job_id) REFERENCES jobs(id)
);
"""


def get_connection(db_path="intel.db"):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(db_path="intel.db"):
    conn = get_connection(db_path)
    conn.executescript(SCHEMA)
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


def get_unclassified_jobs(conn, company_id):
    return conn.execute(
        """SELECT j.* FROM jobs j
           WHERE j.company_id = ?
             AND j.id NOT IN (SELECT job_id FROM classifications)
           ORDER BY j.id""",
        (company_id,),
    ).fetchall()


def insert_classification(conn, job_id, classification, model_used):
    conn.execute(
        """INSERT OR REPLACE INTO classifications
           (job_id, department_category, seniority_level, key_skills, strategic_signals, growth_signal, model_used)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            job_id,
            classification.get("department_category"),
            classification.get("seniority_level"),
            classification.get("key_skills") if isinstance(classification.get("key_skills"), str) else str(classification.get("key_skills", "[]")),
            classification.get("strategic_signals") if isinstance(classification.get("strategic_signals"), str) else str(classification.get("strategic_signals", "[]")),
            classification.get("growth_signal"),
            model_used,
        ),
    )
    conn.commit()


def get_all_classified_jobs(conn, company_id):
    return conn.execute(
        """SELECT j.*, c.department_category, c.seniority_level, c.key_skills,
                  c.strategic_signals, c.growth_signal, c.model_used
           FROM jobs j
           JOIN classifications c ON j.id = c.job_id
           WHERE j.company_id = ?
           ORDER BY c.department_category, c.seniority_level""",
        (company_id,),
    ).fetchall()


def get_company_info(conn, company_id):
    return conn.execute("SELECT * FROM companies WHERE id = ?", (company_id,)).fetchone()
