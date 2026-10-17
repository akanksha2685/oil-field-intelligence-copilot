import json
import os
import re
import sqlite3

import pandas as pd
import streamlit as st

st.set_page_config(
    page_title="Asset Intelligence Copilot",
    page_icon="🛢️",
    layout="wide",
)

DB_PATH = "oil_field.db"
SPILL_KEYWORDS = ["spill", "leak", "puddle", "fluid", "valve", "release", "overflow"]


def get_wells_for_block(block_query):
    """Return the matching area's name and asset IDs from areas.json."""
    areas_path = (
        os.path.join("test-data", "dataset", "fleet", "areas.json")
        if os.path.exists(os.path.join("test-data", "dataset", "fleet", "areas.json"))
        else os.path.join("sample-data", "fleet", "areas.json")
    )

    if not os.path.exists(areas_path):
        return None, []

    try:
        with open(areas_path, "r", encoding="utf-8") as file:
            data = json.load(file)
    except (OSError, json.JSONDecodeError):
        return None, []

    query = block_query.lower()
    for area in data.get("areas", []):
        name = area.get("name", "")
        area_id = area.get("area_id", "")
        if query in name.lower() or query in area_id.lower():
            return name, area.get("asset_ids", [])

    return None, []


def get_connection():
    """Open a connection to the SQLite database."""
    if not os.path.exists(DB_PATH):
        st.error(
            f"Database '{DB_PATH}' was not found. Run the ingestion script first "
            "and make sure the database is in the app's working directory."
        )
        return None

    return sqlite3.connect(DB_PATH)


def get_latest_inspection(cursor, well_id):
    cursor.execute(
        """
        SELECT inspection_id, inspected_at, inspector_user_id,
               ambient_temp_c, wellhead_temp_c, notes
        FROM inspections
        WHERE asset_id = ?
        ORDER BY inspected_at DESC
        LIMIT 1
        """,
        (well_id,),
    )
    return cursor.fetchone()


def get_context_notes(cursor, well_id):
    cursor.execute(
        """
        SELECT note_id, author_user_id, text, valid_from
        FROM context_notes
        WHERE asset_id = ?
        ORDER BY valid_from DESC
        """,
        (well_id,),
    )
    return cursor.fetchall()


def get_temperature_delta(inspection):
    if not inspection:
        return None

    # Inspection columns: ..., ambient_temp_c, wellhead_temp_c, notes
    return round(inspection[4] - inspection[3], 1)


def show_well_status(well_id, well_type, recorded_status, inspection):
    delta = get_temperature_delta(inspection)
    if delta is None:
        st.warning(f"No inspection data is available for {well_id}.")
        return

    status_badge = "🟢 Producing" if delta >= 15 else "🔴 Inactive / Down"
    st.markdown("### 🤖 Copilot Response")
    st.markdown(
        f"**Operational analysis for {well_id}**\n\n"
        f"- **Type:** {well_type}\n"
        f"- **Recorded status:** {recorded_status}\n"
        f"- **Wellhead-to-ambient temperature difference:** {delta}°C"
    )

    with st.container(border=True):
        st.markdown(f"### 📊 Well Status Card: {well_id}")
        col1, col2, col3 = st.columns(3)
        col1.metric("Well Type", well_type)
        col2.metric("Temperature Difference", f"{delta}°C")
        col3.metric("Calculated State", status_badge)

    st.caption(
        f"Latest inspection: {inspection[1]} | "
        f"Inspector ID: {inspection[2] or 'Unknown'}"
    )


def show_conflict_analysis(well_id, recorded_status, inspection, notes):
    st.subheader(f"🔍 Record Reconciliation: {well_id}")
    delta = get_temperature_delta(inspection)

    if delta is None:
        st.warning("Cannot compare the recorded status because no inspection exists.")
        return

    calculated_status = "Producing" if delta >= 15 else "Inactive / Down"
    col1, col2 = st.columns(2)

    with col1:
        st.markdown("### 🗄️ Master Database Record")
        st.metric("Recorded Status", str(recorded_status).title())

    with col2:
        st.markdown("### 🌡️ Calculated Operational State")
        st.metric("Calculated Status", calculated_status, delta=f"{delta}°C")

    if str(recorded_status).lower() != calculated_status.lower():
        st.warning(
            f"**Potential discrepancy:** the database says `{recorded_status}`, "
            f"while the temperature rule suggests `{calculated_status}`. "
            f"The measured temperature difference is {delta}°C."
        )
    else:
        st.success("The recorded status matches the temperature-based rule.")

    if notes:
        st.markdown(f"**Latest context note:** {notes[0][2]}")
    elif inspection[5]:
        st.markdown(f"**Latest inspection note:** {inspection[5]}")
    else:
        st.info("No context or inspection notes are available.")


def show_spill_history(well_id, inspection, notes):
    st.subheader(f"🛢️ Spill History & Incident Log: {well_id}")
    spill_data = []

    for note in notes:
        note_text = str(note[2] or "")
        if any(keyword in note_text.lower() for keyword in SPILL_KEYWORDS):
            spill_data.append(
                {
                    "Date": note[3] or "Unknown",
                    "Source": "Context note",
                    "Incident Note": note_text,
                }
            )

    if inspection and inspection[5]:
        inspection_note = str(inspection[5])
        if any(keyword in inspection_note.lower() for keyword in SPILL_KEYWORDS):
            spill_data.append(
                {
                    "Date": inspection[1],
                    "Source": "Inspection",
                    "Incident Note": inspection_note,
                }
            )

    if spill_data:
        st.dataframe(pd.DataFrame(spill_data), use_container_width=True)
        st.markdown(f"Found {len(spill_data)} related record(s) for **{well_id}**.")
    else:
        st.info(
            f"No spill or leak keywords were found in the available records for "
            f"{well_id}. This does not prove that no incident occurred."
        )
        if inspection and inspection[5]:
            st.markdown("Latest inspection note:")
            st.write(inspection[5])


def show_temperature_trend(well_id):
    conn = get_connection()
    if conn is None:
        return

    try:
        df_history = pd.read_sql_query(
            """
            SELECT inspected_at, wellhead_temp_c, ambient_temp_c
            FROM inspections
            WHERE asset_id = ?
            ORDER BY inspected_at ASC
            """,
            conn,
            params=(well_id,),
        )
    finally:
        conn.close()

    st.subheader(f"📈 Temperature Trend: {well_id}")
    if df_history.empty:
        st.warning(f"No historical inspection data was found for {well_id}.")
        return

    df_history["inspected_at"] = pd.to_datetime(
        df_history["inspected_at"], errors="coerce"
    )
    df_history = df_history.dropna(subset=["inspected_at"])
    df_history = df_history.set_index("inspected_at")

    st.line_chart(df_history[["wellhead_temp_c", "ambient_temp_c"]])
    st.caption(
        "Temperature difference is calculated as wellhead temperature minus "
        "ambient temperature. The app's illustrative rule treats a difference "
        "of at least 15°C as a possible production indicator; verify this rule "
        "against the challenge documentation."
    )


def show_block_analysis(area_name, well_ids):
    st.subheader(f"📊 Operational Analysis: {area_name}")
    st.markdown(f"Checking the latest available inspection for {len(well_ids)} assets.")

    conn = get_connection()
    if conn is None:
        return

    non_producing_data = []

    try:
        cursor = conn.cursor()

        for well_id in well_ids:
            cursor.execute(
                "SELECT well_type, recorded_status FROM wells WHERE asset_id = ?",
                (well_id,),
            )
            well_data = cursor.fetchone()
            if not well_data:
                continue

            well_type, recorded_status = well_data
            inspection = get_latest_inspection(cursor, well_id)
            delta = get_temperature_delta(inspection)

            if delta is not None and delta < 15:
                cursor.execute(
                    """
                    SELECT text FROM context_notes
                    WHERE asset_id = ?
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    (well_id,),
                )
                context_note = cursor.fetchone()
                reason = (
                    context_note[0]
                    if context_note and context_note[0]
                    else (
                        inspection[5]
                        if inspection and inspection[5]
                        else "No recorded reason."
                    )
                )

                non_producing_data.append(
                    {
                        "Well": well_id,
                        "Type": well_type,
                        "Temperature Difference (°C)": delta,
                        "Recorded Status": recorded_status,
                        "Reason / Inspector Note": reason,
                    }
                )
    finally:
        conn.close()

    if non_producing_data:
        st.dataframe(
            pd.DataFrame(non_producing_data),
            use_container_width=True,
        )
    else:
        st.success(
            "No wells below the illustrative temperature threshold were found "
            "among the assets with inspection data."
        )

    st.caption("Sources: SQLite well, inspection, and context-note records.")


# Page heading and sidebar
st.title("🛢️ Asset Intelligence Copilot")
st.markdown(
    "*FlytBase Oil-Well Operations Copilot — Hacktoberfest 2026 | "
    "AG-UI & Gemma Architecture*"
)

st.sidebar.header("Agent-User Interaction (AG-UI)")
st.sidebar.selectbox(
    "Active User Profile",
    [
        "Michael Turner (Production Supervisor)",
        "Tyler Hughes (Field Operator)",
        "Jessica Reed (Field Inspector)",
        "Laura Simmons (HSE Officer)",
    ],
)
st.sidebar.markdown("---")
st.sidebar.markdown("**AI Engine:** Gemma integration pending verification")
st.sidebar.markdown("**Context Memory:** SQLite database")

tab1, tab2, tab3, tab4 = st.tabs(
    [
        "💬 1. Copilot Chat & Status",
        "📊 2. Fleet Table",
        "📈 3. Trend Chart",
        "🗺️ 4. Spill & Asset Map",
    ]
)

# TAB 1: Copilot Chat and status
with tab1:
    st.subheader("Interactive Agent Query")
    query_input = st.text_input(
        "Ask about a well or block "
        "(e.g., 'Show the trend for WELL-0001' or "
        "'Which wells in Northeast Block 8 are not producing?'):",
        key="copilot_query",
    )

    if st.button("Ask Copilot") and query_input.strip():
        query_lower = query_input.lower()

        block_match = re.search(
            r"(northeast|southwest)\s+block\s+\d+",
            query_lower,
        )
        if "downtime" in query_input.lower() or ("down" in query_input.lower() and "days" in query_input.lower()):
         st.markdown(f"Calculating weekly inspection downtime records for records...")
        
         conn = sqlite3.connect(DB_PATH)
         cursor = conn.cursor()
         cursor.execute("""
            SELECT inspected_at, ambient_temp_c, wellhead_temp_c, notes 
            FROM inspections WHERE asset_id = ? ORDER BY inspected_at ASC
         """, (well_id,))
         all_insp = cursor.fetchall()
         conn.close()
        
         downtime_records = []
         total_down_days = 0
        
         for ins in all_insp:
            ins_date = ins[0]
            ambient = ins[1]
            wellhead = ins[2]
            note = ins[3]
            
            if ambient is not None and wellhead is not None:
                delta = round(wellhead - ambient, 1)
                if delta < 15.0:
                    total_down_days += 7
                    downtime_records.append({
                        "Inspection Date": ins_date,
                        "Wellhead Temp (°C)": wellhead,
                        "Ambient Temp (°C)": ambient,
                        "Delta (°C)": f"{delta}°C",
                        "Inspector Note": note if note else "No note recorded"
                    })
                    
         st.metric("Total Calculated Downtime Inspections", f"{len(downtime_records)} inspections", f"{total_down_days} cumulative days (7 days per inspection)")
        
        if downtime_records:
            df_dt = pd.DataFrame(downtime_records)
            st.markdown("### 📋 Breakdown of Inspections Indicating Inactive State")
            st.dataframe(df_dt, use_container_width=True)
            st.markdown("**Rule Applied:** Each weekly inspection finding the well not producing oil counts as 7 days of downtime[cite: 12].")
        else:
            st.success(f"No downtime found for **{well_id}**.")

        if block_match:
            block_query = block_match.group(0).title()
            area_name, block_wells = get_wells_for_block(block_query)

            if area_name and block_wells:
                show_block_analysis(area_name, block_wells)
            else:
                st.warning(
                    f"Could not find '{block_query}' in sample-data/fleet/areas.json."
                )
        else:
            well_match = re.search(r"WELL-\d{4}", query_input.upper())

            if not well_match:
                st.info("Please include a valid well ID (e.g. WELL-0001) or block name.")
            else:
                well_id = well_match.group(0)
                conn = get_connection()

                if conn is not None:
                    try:
                        cursor = conn.cursor()
                        cursor.execute(
                            """
                            SELECT well_type, recorded_status
                            FROM wells
                            WHERE asset_id = ?
                            """,
                            (well_id,),
                        )
                        well_data = cursor.fetchone()

                        if not well_data:
                            st.warning(f"Well {well_id} was not found in the database.")
                        else:
                            well_type, recorded_status = well_data
                            inspection = get_latest_inspection(cursor, well_id)
                            notes = get_context_notes(cursor, well_id)

                            if any(word in query_lower for word in ["trend", "chart", "temperature history"]):
                                show_temperature_trend(well_id)
                            elif any(word in query_lower for word in ["spill", "leak", "puddle", "overflow"]):
                                show_spill_history(well_id, inspection, notes)
                            
                            elif any(word in query_lower for word in ["conflict", "discrepancy", "different", "difference"]):
                                show_conflict_analysis(
                                    well_id,
                                    recorded_status,
                                    inspection,
                                    notes,
                                )
                            elif any(
                                word in query_lower
                                for word in ["rule", "breach", "compliance", "fine"]
                            ):
                                st.subheader(
                                    f"⚖️ Regulatory Compliance & Breach Analysis: {well_id}"
                                )

                                conn = sqlite3.connect(DB_PATH)
                                try:
                                    cursor = conn.cursor()
                                    cursor.execute(
                                        """
                                        SELECT event_id, date, agency, event_type,
                                               protocol_id, hours_to_report,
                                               detail, fine_usd, status
                                        FROM regulator_events
                                        WHERE asset_id = ?
                                        """,
                                        (well_id,),
                                    )
                                    reg_events = cursor.fetchall()
                                finally:
                                    conn.close()

                                if reg_events:
                                    reg_data = [
                                        {
                                            "Event ID": ev[0],
                                            "Date": ev[1],
                                            "Agency": ev[2],
                                            "Type": ev[3],
                                            "Protocol": ev[4],
                                            "Hours to Report": ev[5],
                                            "Detail": ev[6],
                                            "Fine (USD)": f"${ev[7]:,.2f}" if ev[7] else "$0",
                                            "Status": ev[8],
                                        }
                                        for ev in reg_events
                                    ]

                                    st.dataframe(
                                        pd.DataFrame(reg_data),
                                        use_container_width=True,
                                    )
                                else:
                                    st.info(
                                        f"No regulatory events found for {well_id}."
                                    )

                                if notes:
                                    st.markdown("**Associated Context / Inspector Notes:**")
                                    for n in notes:
                                        st.info(f"[{n[3]}] {n[2]}")
                                elif "downtime" in query_input.lower() or "down" in query_input.lower() and "days" in query_input.lower():
                                                    st.subheader(f"⏳ Cumulative Downtime Analysis: {well_id}")
                                                    st.markdown(f"Calculating weekly inspection downtime records for **{well_id}**...")
                                                    
                                                    conn = sqlite3.connect(DB_PATH)
                                                    cursor = conn.cursor()
                                                    cursor.execute("""
                                                        SELECT inspected_at, ambient_temp_c, wellhead_temp_c, notes 
                                                        FROM inspections WHERE asset_id = ? ORDER BY inspected_at ASC
                                                    """, (well_id,))
                                                    all_insp = cursor.fetchall()
                                                    conn.close()
                                                    
                                                    downtime_records = []
                                                    total_down_days = 0
                           
                            
                        
                                for ins in all_insp:
                                    ins_date = ins[0]
                                    ambient = ins[1]
                                    wellhead = ins[2]
                                    note = ins[3]
                                    
                                    if ambient is not None and wellhead is not None:
                                        delta = round(wellhead - ambient, 1)
                                        if delta < 15.0:
                                            total_down_days += 7
                                            downtime_records.append({
                                                "Inspection Date": ins_date,
                                                "Wellhead Temp (°C)": wellhead,
                                                "Ambient Temp (°C)": ambient,
                                                "Delta (°C)": f"{delta}°C",
                                                "Inspector Note": note if note else "No note recorded"
                                            })
                                else:
                                                            show_well_status(
                                                                well_id,
                                                                well_type,
                                                                recorded_status,
                                                                inspection,
                                                            )                
                            st.metric("Total Calculated Downtime Inspections", f"{len(downtime_records)} inspections", f"{total_down_days} cumulative days (7 days per inspection)")
                            
                            if downtime_records:
                                df_dt = pd.DataFrame(downtime_records)
                                st.markdown("### 📋 Breakdown of Inspections Indicating Inactive State")
                                st.dataframe(df_dt, use_container_width=True)
                                st.markdown("**Rule Applied:** Each weekly inspection finding the well not producing oil counts as 7 days of downtime[cite: 12].")
                            else:
                                st.success(f"No downtime found for **{well_id}**.")                 

                    finally:
                        conn.close()

# TAB 2: Fleet table
with tab2:
    st.subheader("📋 Fleet Status & Operational Table")
    conn = get_connection()

    if conn is not None:
        try:
            df_wells = pd.read_sql_query(
                """
                SELECT asset_id, well_type, recorded_status
                FROM wells
                LIMIT 50
                """,
                conn,
            )
            st.dataframe(df_wells, use_container_width=True)
        finally:
            conn.close()

# TAB 3: Trend chart
with tab3:
    st.subheader("📈 Wellhead vs. Ambient Temperature Trend")
    chart_well = st.text_input(
        "Enter Well ID for Trend Analysis:",
        value="WELL-0001",
        key="trend_well_id",
    )

    if st.button("Show Trend"):
        if re.fullmatch(r"WELL-\d{4}", chart_well.strip().upper()):
            show_temperature_trend(chart_well.strip().upper())
        else:
            st.warning("Enter a well ID in the format WELL-0001.")

# TAB 4: Spill and asset map
with tab4:
    st.subheader("🗺️ Geographic Asset & Spill Map")
    st.info(
        "The original map used randomly generated coordinates. Those are not "
        "verified asset locations, so they have been removed. Add the real "
        "latitude and longitude fields from the dataset to display a reliable map."
    )
