import os
import sys
import json
import sqlite3

DB_PATH = "oil_field.db"
# Default to test-data/dataset if present, otherwise sample-data
DATA_DIR = sys.argv[1] if len(sys.argv) > 1 else ("test-data/dataset" if os.path.exists("test-data/dataset") else "sample-data")

def init_db():
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Create tables
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS wells (
        asset_id TEXT PRIMARY KEY,
        name TEXT,
        well_type TEXT,
        area_id TEXT,
        team_id TEXT,
        lat REAL,
        lon REAL,
        installed_on TEXT,
        recorded_status TEXT,
        in_charge_user_id TEXT,
        status TEXT,
        decommissioned_on TEXT,
        type_history TEXT,
        team_history TEXT,
        equipment TEXT
    )
    """)
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS inspections (
        inspection_id TEXT PRIMARY KEY,
        asset_id TEXT,
        inspected_at TEXT,
        inspector_user_id TEXT,
        method TEXT,
        ambient_temp_c REAL,
        wellhead_temp_c REAL,
        spill_detected INTEGER,
        spill_area_pct REAL,
        spill_est_volume_bbl REAL,
        notes TEXT,
        recorded_at TEXT
    )
    """)
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS maintenance (
        maintenance_id TEXT PRIMARY KEY,
        asset_id TEXT,
        started_at TEXT,
        completed_at TEXT,
        maintenance_type TEXT,
        equipment_kind TEXT,
        issue TEXT,
        action_taken TEXT,
        downtime_hours REAL,
        cost_total REAL,
        triggered_by_inspection_id TEXT,
        report_file TEXT,
        recorded_at TEXT,
        cost_revision TEXT
    )
    """)
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS regulator_events (
        event_id TEXT PRIMARY KEY,
        asset_id TEXT,
        date TEXT,
        agency TEXT,
        event_type TEXT,
        protocol_id TEXT,
        related_inspection_id TEXT,
        hours_to_report REAL,
        detail TEXT,
        fine_usd REAL,
        status TEXT
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS context_notes (
        note_id TEXT PRIMARY KEY,
        asset_id TEXT,
        created_at TEXT,
        author_user_id TEXT,
        note_type TEXT,
        inspection_id TEXT,
        text TEXT,
        valid_from TEXT,
        valid_to TEXT,
        field TEXT,
        original_value TEXT,
        corrected_value TEXT
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS areas (
        area_id TEXT PRIMARY KEY,
        name TEXT,
        team_id TEXT,
        center_lat REAL,
        center_lon REAL,
        asset_ids TEXT
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS teams (
        team_id TEXT PRIMARY KEY,
        name TEXT,
        lead_user_id TEXT
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        user_id TEXT PRIMARY KEY,
        name TEXT,
        role TEXT,
        team_id TEXT
    )
    """)
    
    conn.commit()
    conn.close()

def load_fleet_data(conn):
    fleet_dir = os.path.join(DATA_DIR, "fleet")
    if not os.path.exists(fleet_dir):
        return

    # Load areas.json
    areas_file = os.path.join(fleet_dir, "areas.json")
    if os.path.exists(areas_file):
        with open(areas_file, "r", encoding="utf-8") as f:
            areas_data = json.load(f)
            for area in areas_data.get("areas", []):
                center = area.get("center", {})
                conn.execute("""
                INSERT OR REPLACE INTO areas VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    area.get("area_id"),
                    area.get("name"),
                    area.get("team_id"),
                    center.get("lat"),
                    center.get("lon"),
                    json.dumps(area.get("asset_ids", []))
                ))
            for team in areas_data.get("teams", []):
                conn.execute("""
                INSERT OR REPLACE INTO teams VALUES (?, ?, ?)
                """, (
                    team.get("team_id"),
                    team.get("name"),
                    team.get("lead_user_id")
                ))

    # Load users.json
    users_file = os.path.join(fleet_dir, "users.json")
    if os.path.exists(users_file):
        with open(users_file, "r", encoding="utf-8") as f:
            raw_users = json.load(f)
            user_list = raw_users.get("users", []) if isinstance(raw_users, dict) else raw_users
            for u in user_list:
                conn.execute("""
                INSERT OR REPLACE INTO users VALUES (?, ?, ?, ?)
                """, (
                    u.get("user_id"),
                    u.get("name"),
                    u.get("role"),
                    u.get("team_id")
                ))

def load_data():
    conn = sqlite3.connect(DB_PATH)
    assets_dir = os.path.join(DATA_DIR, "assets")
    
    print(f"Loading data from: {DATA_DIR}")
    if not os.path.exists(assets_dir):
        print(f"Error: {assets_dir} not found! Check data directory path.")
        return

    # Ingest fleet data
    load_fleet_data(conn)

    well_folders = [f for f in os.listdir(assets_dir) if f.startswith("WELL-")]
    well_folders.sort()
    print(f"Found {len(well_folders)} wells to process...")

    for well_id in well_folders:
        well_path = os.path.join(assets_dir, well_id)
        
        # 1. Load metadata.json
        meta_file = os.path.join(well_path, "metadata.json")
        if os.path.exists(meta_file):
            with open(meta_file, "r", encoding="utf-8") as f:
                meta = json.load(f)
                loc = meta.get("location", {})
                conn.execute("""
                INSERT OR REPLACE INTO wells VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    meta.get("asset_id"),
                    meta.get("name"),
                    meta.get("well_type"),
                    meta.get("area_id"),
                    meta.get("team_id"),
                    loc.get("lat"),
                    loc.get("lon"),
                    meta.get("installed_on"),
                    meta.get("recorded_status"),
                    meta.get("in_charge_user_id"),
                    meta.get("status"),
                    meta.get("decommissioned_on"),
                    json.dumps(meta.get("type_history")) if meta.get("type_history") else None,
                    json.dumps(meta.get("team_history")) if meta.get("team_history") else None,
                    json.dumps(meta.get("equipment")) if meta.get("equipment") else None
                ))
        
        # 2. Load inspections.jsonl
        insp_file = os.path.join(well_path, "inspections.jsonl")
        if os.path.exists(insp_file):
            with open(insp_file, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        row = json.loads(line)
                        conn.execute("""
                        INSERT OR REPLACE INTO inspections VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (
                            row.get("inspection_id"),
                            well_id,
                            row.get("inspected_at"),
                            row.get("inspector_user_id"),
                            row.get("method"),
                            row.get("ambient_temp_c"),
                            row.get("wellhead_temp_c"),
                            1 if row.get("spill_detected") else 0,
                            row.get("spill_area_pct"),
                            row.get("spill_est_volume_bbl"),
                            row.get("notes"),
                            row.get("recorded_at")
                        ))

        # 3. Load maintenance.jsonl
        maint_file = os.path.join(well_path, "maintenance.jsonl")
        if os.path.exists(maint_file):
            with open(maint_file, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        row = json.loads(line)
                        cost = row.get("cost_usd", {})
                        total_cost = cost.get("total", 0.0) if isinstance(cost, dict) else 0.0
                        cost_rev = row.get("cost_revision")
                        conn.execute("""
                        INSERT OR REPLACE INTO maintenance VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (
                            row.get("maintenance_id"),
                            well_id,
                            row.get("started_at"),
                            row.get("completed_at"),
                            row.get("maintenance_type"),
                            row.get("equipment_kind"),
                            row.get("issue"),
                            row.get("action_taken"),
                            row.get("downtime_hours"),
                            total_cost,
                            row.get("triggered_by_inspection_id"),
                            row.get("report_file"),
                            row.get("recorded_at"),
                            json.dumps(cost_rev) if cost_rev else None
                        ))

        # 4. Load regulatory-events.jsonl
        reg_file = os.path.join(well_path, "regulatory-events.jsonl")
        if os.path.exists(reg_file):
            with open(reg_file, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        row = json.loads(line)
                        conn.execute("""
                        INSERT OR REPLACE INTO regulator_events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (
                            row.get("event_id"),
                            well_id,
                            row.get("date"),
                            row.get("agency"),
                            row.get("event_type"),
                            row.get("protocol_id"),
                            row.get("related_inspection_id"),
                            row.get("hours_to_report"),
                            row.get("detail"),
                            row.get("fine_usd"),
                            row.get("status")
                        ))

        # 5. Load context.jsonl (human notes, operator notes & corrections)
        ctx_file = os.path.join(well_path, "context.jsonl")
        if os.path.exists(ctx_file):
            with open(ctx_file, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        row = json.loads(line)
                        conn.execute("""
                        INSERT OR REPLACE INTO context_notes VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (
                            row.get("note_id"),
                            well_id,
                            row.get("created_at"),
                            row.get("author_user_id"),
                            row.get("note_type"),
                            row.get("inspection_id"),
                            row.get("text"),
                            row.get("valid_from"),
                            row.get("valid_to"),
                            row.get("field"),
                            str(row.get("original_value")) if row.get("original_value") is not None else None,
                            str(row.get("corrected_value")) if row.get("corrected_value") is not None else None
                        ))

    # Create indexes for optimal query performance
    cursor = conn.cursor()
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_inspections_asset ON inspections(asset_id, inspected_at DESC)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_maintenance_asset ON maintenance(asset_id, started_at DESC)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_context_notes_asset ON context_notes(asset_id, valid_from DESC)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_regulator_events_asset ON regulator_events(asset_id, date DESC)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_wells_area ON wells(area_id)")

    conn.commit()
    conn.close()
    print("Data ingestion complete! SQLite database 'oil_field.db' created successfully.")

if __name__ == "__main__":
    init_db()
    load_data()
