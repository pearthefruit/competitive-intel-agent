import sqlite3
import os

base_dir = r"C:\Users\peary\OneDrive - The City University of New York\Web Scraping\competitive-intel-agent"
db_path = os.path.join(base_dir, "intel.db")
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row

old_company = "Www Huel Com"
new_company = "Huel"
old_file = os.path.join(base_dir, "reports", "www_huel_com_techstack_2026-03-24.md")
new_file = os.path.join(base_dir, "reports", "huel_techstack_2026-03-24.md")

if os.path.exists(old_file):
    os.rename(old_file, new_file)
    print(f"Renamed {os.path.basename(old_file)} to {os.path.basename(new_file)}")
else:
    print(f"File {os.path.basename(old_file)} not found. Moving on to database update regardless.")

old_dossier = conn.execute("SELECT id FROM dossiers WHERE company_name COLLATE NOCASE = ?", (old_company,)).fetchone()
new_dossier = conn.execute("SELECT id FROM dossiers WHERE company_name COLLATE NOCASE = ?", (new_company,)).fetchone()

if old_dossier and new_dossier:
    conn.execute('UPDATE dossier_analyses SET dossier_id = ?, report_file = ? WHERE dossier_id = ? AND analysis_type = "techstack"', 
                 (new_dossier['id'], new_file, old_dossier['id']))
    conn.commit()
    print("Migrated database records.")
    
    count = conn.execute("SELECT count(*) FROM dossier_analyses WHERE dossier_id = ?", (old_dossier['id'],)).fetchone()[0]
    if count == 0:
        conn.execute("DELETE FROM dossiers WHERE id = ?", (old_dossier['id'],))
        conn.commit()
        print("Cleaned up empty Www Huel Com dossier.")
elif not old_dossier:
    print(f"Could not find old dossier for {old_company}")
elif not new_dossier:
    print(f"Could not find new dossier for {new_company}")

conn.close()
