import streamlit as st
import requests
from datetime import datetime

# ==========================================
# CONFIGURATION
# ==========================================
ORG_ID = "34"
PROJ_ID = "588"  # Hardcoded to BCI Test Project
BASE_URL = "https://senslysolutions.com/api/v1"

FACTOR_IDS = {
    "manual_dip": 3723, 
    "p1": 3724,         
    "b1": 3725           
}
MANUAL_DIP_INPUT_ID = "31764"

st.set_page_config(page_title="Sensly Calibration", page_icon="📈")

# ==========================================
# UI & LOGIC
# ==========================================
st.title("Sensly Calibration Updater")
st.caption("BCI Test Project (588)")

with st.sidebar:
    st.header("Settings")
    api_key = st.text_input("Enter Sensly API Key:", type="password")

if not api_key:
    st.warning("Please enter your API Key in the sidebar to begin.")
    st.stop()

HEADERS = {
    "Authorization": f"Bearer {api_key}",
    "Content-Type": "application/json",
    "Accept": "application/json"
}

# --- 1. Fetch & Select Sensor ---
@st.cache_data(ttl=60)
def get_sensors():
    resp = requests.get(f"{BASE_URL}/org/{ORG_ID}/proj/{PROJ_ID}/sensors", headers=HEADERS)
    return resp.json() if resp.status_code == 200 else []

sensors = get_sensors()
if not sensors:
    st.error("Could not load sensors. Check your API key.")
    st.stop()

sensor_options = {s.get("name"): s.get("id") for s in sensors}
selected_sensor_name = st.selectbox("Select Sensor", options=list(sensor_options.keys()))
sensor_id = sensor_options[selected_sensor_name]

# --- 2. Input Data ---
manual_dip = st.number_input("Enter Manual Dip Value (m):", value=0.00, format="%.2f")

if st.button("Submit Calibration", type="primary"):
    with st.spinner("Calculating and updating Sensly..."):
        
        # --- Step 0: Fetch old calibration factors ---
        sensor_url = f"{BASE_URL}/org/{ORG_ID}/proj/{PROJ_ID}/sensors/{sensor_id}"
        sensor_resp = requests.get(sensor_url, headers=HEADERS)
        
        if sensor_resp.status_code != 200:
            st.error("Failed to fetch sensor details for math calculations.")
            st.stop()
            
        calibrations = sensor_resp.json().get("calibrations", [])
        old_p1 = next((c.get("value") for c in calibrations if c.get("factorId") == 3724), 0.0)
        old_b1 = next((c.get("value") for c in calibrations if c.get("factorId") == 3725), 0.0)
        old_manual_dip = next((c.get("value") for c in calibrations if c.get("factorId") == 3723), 0.0)
        sg = next((c.get("value") for c in calibrations if c.get("factorId") == 3738), 1.0) 
        dtw_offset = next((c.get("value") for c in calibrations if c.get("factorId") == 3757), 0.0)

        # --- Step 1: Fetch latest PR and BP ---
        read_url = f"{BASE_URL}/org/{ORG_ID}/proj/{PROJ_ID}/readings/{sensor_id}?limit=1"
        read_resp = requests.get(read_url, headers=HEADERS)
        
        if read_resp.status_code != 200 or len(read_resp.json()) == 0:
            st.error("No original readings found for this sensor.")
            st.stop()
            
        latest = read_resp.json()[0]
        inputs_data = latest.get("inputs", {})
        pr_val = float(inputs_data.get("31704", 0))
        bp_val = float(inputs_data.get("31697", 0))
        
        if pr_val == 0 or bp_val == 0:
            st.error("Missing 'pr' or 'bp' in the latest reading! Cannot calculate.")
            st.stop()
            
        # --- Step 2: Calculate Offset ---
        old_dtw = old_manual_dip - ((pr_val - bp_val) - (old_p1 - old_b1))
        old_dc_dtw = old_manual_dip - ((old_manual_dip - old_dtw) / sg) + dtw_offset
        
        new_dtw = manual_dip - ((pr_val - bp_val) - (pr_val - bp_val))
        new_dc_dtw = manual_dip - ((manual_dip - new_dtw) / sg) + dtw_offset
        
        calculated_offset = new_dc_dtw - old_dc_dtw
        
        st.info(f"**Math Summary:**\n* **Old WL:** {old_dc_dtw:.3f}m\n* **New WL:** {new_dc_dtw:.3f}m\n* **Offset Applied:** {calculated_offset:.3f}m")
        
        current_time_iso = datetime.now().astimezone().isoformat()
        friendly_time = datetime.now().astimezone().strftime("%d/%m/%Y at %I:%M %p")
        
        # --- Step 3: Update Calibrations ---
        cal_url = f"{BASE_URL}/org/{ORG_ID}/proj/{PROJ_ID}/calibrations/many"
        cal_payload = [
            {"datetime": current_time_iso, "value": manual_dip, "factorId": FACTOR_IDS["manual_dip"], "sensorId": int(sensor_id)},
            {"datetime": current_time_iso, "value": pr_val, "factorId": FACTOR_IDS["p1"], "sensorId": int(sensor_id)},
            {"datetime": current_time_iso, "value": bp_val, "factorId": FACTOR_IDS["b1"], "sensorId": int(sensor_id)}
        ]
        cal_resp = requests.post(cal_url, headers=HEADERS, json=cal_payload)

        # --- Step 4: Create New Reading ---
        reading_url = f"{BASE_URL}/org/{ORG_ID}/proj/{PROJ_ID}/readings/{sensor_id}"
        reading_payload = [{"datetime": current_time_iso, "inputs": {MANUAL_DIP_INPUT_ID: float(manual_dip)}}]
        readings_resp = requests.post(reading_url, headers=HEADERS, json=reading_payload)

        # --- Step 5: Update Maintenance Notes ---
        fields_resp = requests.get(f"{BASE_URL}/org/{ORG_ID}/proj/{PROJ_ID}/sensor-fields", headers=HEADERS)
        field_status = 0
        
        if fields_resp.status_code == 200:
            target_field = next((f for f in fields_resp.json() if f.get("sensorId") == sensor_id and f.get("sensorModelFieldId") == 4146), None)
            
            if target_field:
                field_instance_id = target_field.get("id")
                existing_notes = target_field.get("content") or ""
                new_note = f"Calibrated on {friendly_time}. Dip reading: {manual_dip:.2f}m. Previous WL: {old_dc_dtw:.3f}m. Offset applied: {calculated_offset:.3f}m."
                
                combined_notes = f"{new_note}\n{existing_notes}" if existing_notes.strip() else new_note
                
                field_payload = {
                    "content": combined_notes, "contentId": field_instance_id,
                    "projectId": int(PROJ_ID), "sensorId": int(sensor_id), "sensorModelFieldId": 4146 
                }
                put_resp = requests.put(f"{BASE_URL}/org/{ORG_ID}/proj/{PROJ_ID}/sensor-fields/{field_instance_id}", headers=HEADERS, json=field_payload)
                field_status = put_resp.status_code
            else:
                st.warning("Maintenance Notes field not found on this sensor.")
                field_status = 200 
        
        # --- Final Validation ---
        if cal_resp.status_code == 200 and readings_resp.status_code == 200 and field_status == 200:
            st.success("✅ Calibration successful! Audit trail updated.")
            st.balloons()
        else:
            st.error(f"Updates partially failed. Calibrations: {cal_resp.status_code}, Reading: {readings_resp.status_code}, Notes: {field_status}")
