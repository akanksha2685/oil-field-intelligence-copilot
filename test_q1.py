import sqlite3
import os

DB_PATH = "oil_field.db"

def get_well_manual_threshold(well_type):
    # Read the corresponding well manual
    manual_path = os.path.join("sample-data", "fleet", "well-types", f"{well_type}.md")
    if os.path.exists(manual_path):
        with open(manual_path, "r") as f:
            content = f.read()
            return content # We can parse this or let the LLM read it
    return "Manual not found."

def answer_q1():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # 1. Get well metadata
    cursor.execute("SELECT well_type, recorded_status FROM wells WHERE asset_id = 'WELL-0001'")
    well = cursor.fetchone()
    well_type, recorded_status = well[0], well[1]
    
    # 2. Get latest inspection for WELL-0001
    cursor.execute("""
        SELECT inspection_id, inspected_at, inspector_user_id, ambient_temp_c, wellhead_temp_c, notes 
        FROM inspections 
        WHERE asset_id = 'WELL-0001' 
        ORDER BY inspected_at DESC LIMIT 1
    """)
    insp = cursor.fetchone()
    
    # 3. Get recent context notes for WELL-0001
    cursor.execute("""
        SELECT note_id, author_user_id, text, valid_from, valid_to 
        FROM context_notes 
        WHERE asset_id = 'WELL-0001'
    """)
    notes = cursor.fetchall()
    
    conn.close()
    
    print(f"--- Well Data for WELL-0001 ---")
    print(f"Well Type: {well_type} | Recorded Status: {recorded_status}")
    print(f"\nLatest Inspection ({insp[0]}):")
    print(f" - Inspected At: {insp[1]}")
    print(f" - Inspector ID: {insp[2]}")
    print(f" - Ambient Temp: {insp[3]}°C | Wellhead Temp: {insp[4]}°C")
    print(f" - Temp Difference: {round(insp[4] - inspire_diff(insp[3], insp[4]), 1)}°C") # wait, let's just print simple diff
    temp_diff = insp[4] - insp[3]
    print(f" - Calculated Delta: {temp_diff:.1f}°C")
    print(f" - Inspector Notes: {insp[5]}")
    
    print(f"\nContext & Human Notes:")
    for n in notes:
        print(f" - [{n[0]}] by {n[1]}: {n[2]} (Valid: {n[3]} to {n[4]})")
        
    print(f"\nManual Excerpt ({well_type}):")
    manual_text = get_well_manual_threshold(well_type)
    print(manual_text[:300] + "...\n[Truncated for display]")

def inspire_diff(ambient, wellhead):
    return ambient

if __name__ == "__main__":
    answer_q1()
    