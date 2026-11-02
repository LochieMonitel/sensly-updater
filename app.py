import streamlit as st
import requests
from datetime import datetime, timezone
import pytz

# ==========================================
# CONFIGURATION
# ==========================================
ORG_ID = "34"
PROJ_ID = "588"
BASE_URL = "https://senslysolutions.com/api/v1"

FACTOR_IDS = {
    "manual_dip": 3723, 
    "p1": 3724,         
    "b1": 3725,
    "dtw_offset": 3757,
    "delete_ec": 4039,         
    "delete_water": 3763,
    "ec_offset": 3758
}
MANUAL_DIP_INPUT_ID = "31764"
NOTES_FIELD_ID = 4146 

PERTH_TZ = pytz.timezone('Australia/Perth')

st.set_page_config(page_title="Sensly Calibration & Editing", page_icon="📈")



# ==========================================
# HELPER FUNCTIONS
# ==========================================
def parse_sensly_dt(dt_str):
    if not dt_str: return None
    try:
        if dt_str.endswith('Z'): dt_str = dt_str[:-1] + '+00:00'
        dt_str = dt_str.replace(" ", "T")
        dt_val = datetime.fromisoformat(dt_str)
        if dt_val.tzinfo is None:
            dt_val = PERTH_TZ.localize(dt_val)
        return dt_val
    except:
        return None

def get_active_factor(calibrations_list, factor_id, target_dt):
    active_value = 0.0
    latest_time = datetime.min.replace(tzinfo=timezone.utc)
    
    for c in calibrations_list:
        if c.get("factorId") != factor_id:
            continue
            
        dt_str = c.get("datetime")
        if dt_str:
            cal_dt = parse_sensly_dt(dt_str)
            if cal_dt and cal_dt <= target_dt and cal_dt > latest_time:
                latest_time = cal_dt
                active_value = float(c.get("value", 0.0))
        else:
            if latest_time == datetime.min.replace(tzinfo=timezone.utc):
                active_value = float(c.get("value", 0.0))
                
    return active_value

# ==========================================
# UI & LOGIC
# ==========================================
st.title("Sensly Calibration & Data Editor")
st.caption("BCI Test Project (588)")

with st.sidebar:
    # This forces the logo to span the full width of the sidebar
    st.image("monitel-logo-full-colour-rgb-900px-w-72ppi.png", use_container_width=True)
    
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

sensor_url = f"{BASE_URL}/org/{ORG_ID}/proj/{PROJ_ID}/sensors/{sensor_id}"
sensor_resp = requests.get(sensor_url, headers=HEADERS)
cals_url = f"{BASE_URL}/org/{ORG_ID}/proj/{PROJ_ID}/calibrations?sensorId={sensor_id}"
cals_resp = requests.get(cals_url, headers=HEADERS)

if sensor_resp.status_code != 200:
    st.error("Failed to fetch sensor details.")
    st.stop()
    
calibrations = sensor_resp.json().get("calibrations", []) + (cals_resp.json() if cals_resp.status_code == 200 else [])

mode = st.radio("Select Action:", ["Sensor Calibration", "Manual Data Edits"], horizontal=True)
st.divider()

if mode == "Sensor Calibration":
    st.subheader("Calibration")
    
    col1, col2 = st.columns(2)
    with col1:
        cal_date = st.date_input("Calibration Date", value=datetime.now(PERTH_TZ).date())
    with col2:
        cal_time = st.time_input("Calibration Time", value=datetime.now(PERTH_TZ).time())
        
    manual_dip = st.number_input("Enter Manual Dip Value (m):", value=0.00, format="%.2f")
    
    with st.expander("Hardware Replacement (Optional)"):
        st.markdown("**Sensor Change**")
        old_sensor_sn = st.text_input("Old Sensor SN:")
        new_sensor_sn = st.text_input("New Sensor SN:")
        sensor_reason = st.text_input("Reason for Sensor Change:")
        
        st.divider()
        st.markdown("**Logger Change**")
        old_logger_sn = st.text_input("Old YDOC Logger SN:")
        new_logger_sn = st.text_input("New YDOC Logger SN:")
        logger_reason = st.text_input("Reason for Logger Change:")

    user_notes = st.text_area("Additional Notes (Optional):", value="", placeholder="Enter any extra details here...")

    if st.button("Submit Calibration", type="primary"):
        with st.spinner("Calculating and updating Sensly..."):
            
            now_dt = PERTH_TZ.localize(datetime.combine(cal_date, cal_time))
            
            old_p1 = get_active_factor(calibrations, FACTOR_IDS["p1"], now_dt)
            old_b1 = get_active_factor(calibrations, FACTOR_IDS["b1"], now_dt)
            old_manual_dip = get_active_factor(calibrations, FACTOR_IDS["manual_dip"], now_dt)
            sg = get_active_factor(calibrations, 3738, now_dt)
            sg = sg if sg != 0.0 else 1.0  
            dtw_offset = get_active_factor(calibrations, FACTOR_IDS["dtw_offset"], now_dt)

            read_url = f"{BASE_URL}/org/{ORG_ID}/proj/{PROJ_ID}/readings/{sensor_id}?limit=500"
            read_resp = requests.get(read_url, headers=HEADERS)
            
            if read_resp.status_code != 200 or len(read_resp.json()) == 0:
                st.error("No original readings found for this sensor.")
                st.stop()
                
            readings = read_resp.json()
            closest_reading = None
            min_diff = float('inf')
            
            for r in readings:
                r_dt = parse_sensly_dt(r.get("datetime"))
                if r_dt:
                    diff = abs((r_dt - now_dt).total_seconds())
                    if diff < min_diff:
                        min_diff = diff
                        closest_reading = r
                        
            if not closest_reading:
                st.error("Could not parse reading dates to find the closest match.")
                st.stop()
                
            inputs_data = closest_reading.get("inputs", {})
            pr_val = float(inputs_data.get("31704", 0))
            bp_val = float(inputs_data.get("31697", 0))
            
            if pr_val == 0 or bp_val == 0:
                st.error(f"Missing 'pr' or 'bp' in the closest reading found ({closest_reading.get('datetime')})! Cannot calculate.")
                st.stop()
                
            old_dtw = old_manual_dip - ((pr_val - bp_val) - (old_p1 - old_b1))
            old_dc_dtw = old_manual_dip - ((old_manual_dip - old_dtw) / sg) + dtw_offset
            
            new_dtw = manual_dip - ((pr_val - bp_val) - (pr_val - bp_val))
            new_dc_dtw = manual_dip - ((manual_dip - new_dtw) / sg) + 0.0
            
            calculated_offset = new_dc_dtw - old_dc_dtw
            
            used_reading_dt = parse_sensly_dt(closest_reading.get("datetime"))
            used_reading_str = used_reading_dt.strftime("%d/%m/%Y %I:%M %p") if used_reading_dt else "Unknown"
            
            st.info(f"**Math Summary:**\n* **Reading Used:** {used_reading_str}\n* **Old WL:** {old_dc_dtw:.3f}m\n* **New WL:** {new_dc_dtw:.3f}m\n* **Offset Applied:** {calculated_offset:.3f}m\n* **Note:** DTW Offset has been reset to 0.0m.")
            
            current_time_iso = now_dt.isoformat()
            friendly_time = now_dt.strftime("%d/%m/%Y at %I:%M %p")
            
            cal_payload = [
                {"datetime": current_time_iso, "value": manual_dip, "factorId": FACTOR_IDS["manual_dip"], "sensorId": int(sensor_id)},
                {"datetime": current_time_iso, "value": pr_val, "factorId": FACTOR_IDS["p1"], "sensorId": int(sensor_id)},
                {"datetime": current_time_iso, "value": bp_val, "factorId": FACTOR_IDS["b1"], "sensorId": int(sensor_id)},
                {"datetime": current_time_iso, "value": 0.0, "factorId": FACTOR_IDS["dtw_offset"], "sensorId": int(sensor_id)}
            ]
            cal_url = f"{BASE_URL}/org/{ORG_ID}/proj/{PROJ_ID}/calibrations/many"
            cal_resp = requests.post(cal_url, headers=HEADERS, json=cal_payload)

            reading_url = f"{BASE_URL}/org/{ORG_ID}/proj/{PROJ_ID}/readings/{sensor_id}"
            reading_payload = [{"datetime": current_time_iso, "inputs": {MANUAL_DIP_INPUT_ID: float(manual_dip)}}]
            readings_resp = requests.post(reading_url, headers=HEADERS, json=reading_payload)

            fields_resp = requests.get(f"{BASE_URL}/org/{ORG_ID}/proj/{PROJ_ID}/sensor-fields", headers=HEADERS)
            field_status = 0
            
            if fields_resp.status_code == 200:
                target_field = next((f for f in fields_resp.json() if f.get("sensorId") == sensor_id and f.get("sensorModelFieldId") == NOTES_FIELD_ID), None)
                
                base_note = f"Calibrated on {friendly_time}. Dip reading: {manual_dip:.2f}m. Previous WL: {old_dc_dtw:.3f}m. Offset applied: {calculated_offset:.3f}m (DTW Offset reset to 0)."
                
                hw_changes = []
                if old_sensor_sn or new_sensor_sn:
                    hw_changes.append(f"- Sensor Swapped: [{old_sensor_sn or 'N/A'}] -> [{new_sensor_sn or 'N/A'}] (Reason: {sensor_reason or 'None'})")
                if old_logger_sn or new_logger_sn:
                    hw_changes.append(f"- Logger Swapped: [{old_logger_sn or 'N/A'}] -> [{new_logger_sn or 'N/A'}] (Reason: {logger_reason or 'None'})")
                
                if hw_changes:
                    base_note += "\n" + "\n".join(hw_changes)
                
                new_note = f"{base_note}\nNotes: {user_notes.strip()}" if user_notes.strip() else base_note
                
                if target_field:
                    field_instance_id = target_field.get("id")
                    existing_notes = target_field.get("content") or ""
                    combined_notes = f"{new_note}\n\n{existing_notes}" if existing_notes.strip() else new_note
                    
                    field_payload = {
                        "content": combined_notes, "contentId": field_instance_id,
                        "projectId": int(PROJ_ID), "sensorId": int(sensor_id), "sensorModelFieldId": NOTES_FIELD_ID 
                    }
                    update_resp = requests.put(f"{BASE_URL}/org/{ORG_ID}/proj/{PROJ_ID}/sensor-fields/{field_instance_id}", headers=HEADERS, json=field_payload)
                    field_status = update_resp.status_code
                else:
                    field_payload = {
                        "content": new_note, "contentId": None,
                        "projectId": int(PROJ_ID), "sensorId": int(sensor_id), "sensorModelFieldId": NOTES_FIELD_ID 
                    }
                    create_resp = requests.post(f"{BASE_URL}/org/{ORG_ID}/proj/{PROJ_ID}/sensor-fields", headers=HEADERS, json=field_payload)
                    field_status = create_resp.status_code
            else:
                field_status = fields_resp.status_code
            
            if cal_resp.status_code == 200 and readings_resp.status_code == 200 and field_status == 200:
                st.success("✅ Calibration successful! Audit trail updated.")
                st.balloons()
            else:
                st.error(f"Updates partially failed. Calibrations: {cal_resp.status_code}, Reading: {readings_resp.status_code}, Notes: {field_status}")


elif mode == "Manual Data Edits":
    st.subheader("Manual Data Edits")
    
    now_dt = datetime.now(PERTH_TZ)
    current_ec_offset = get_active_factor(calibrations, FACTOR_IDS["ec_offset"], now_dt)
    current_dtw_offset = get_active_factor(calibrations, FACTOR_IDS["dtw_offset"], now_dt)
    
    st.caption(f"Current Active EC Offset: {current_ec_offset} | Current Active DTW Offset: {current_dtw_offset}")

    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("**Delete Data**")
        del_ec = st.toggle("Delete Electrical Conductivity (EC)")
        del_dtw = st.toggle("Delete Depth to Water (DTW)")
        
        del_start_date = st.date_input("Start Date", value=None)
        del_start_time = st.time_input("Start Time", value=None)
        
        del_end_date = st.date_input("End Date (Optional)", value=None)
        del_end_time = st.time_input("End Time (Optional)", value=None)

    with col2:
        st.markdown("**Apply Offsets**")
        st.caption("Enter the visual offset needed based on the chart.")
        apply_ec_offset = st.toggle("Offset Electrical Conductivity")
        if apply_ec_offset:
            ec_target_offset = st.number_input("Visual EC Offset needed:", value=0.0)
            
        apply_dtw_offset = st.toggle("Offset Depth to Water")
        if apply_dtw_offset:
            dtw_target_offset = st.number_input("Visual DTW Offset needed:", value=0.0)
            
        offset_date = st.date_input("Offset Start Date", value=None)
        offset_time = st.time_input("Offset Start Time", value=None)
        
        offset_end_date = st.date_input("Offset End Date (Optional)", value=None)
        offset_end_time = st.time_input("Offset End Time (Optional)", value=None)

    if st.button("Apply Edits", type="primary"):
        with st.spinner("Applying edits..."):
            cal_payload = []
            
            # --- Delete Logic ---
            if del_ec or del_dtw:
                if not del_start_date or not del_start_time:
                    st.error("You must provide a Start Date and Time to delete data.")
                    st.stop()
                    
                start_dt = datetime.combine(del_start_date, del_start_time)
                start_iso = PERTH_TZ.localize(start_dt).isoformat()
                
                if del_ec:
                    cal_payload.append({"datetime": start_iso, "value": 1.0, "factorId": FACTOR_IDS["delete_ec"], "sensorId": int(sensor_id)})
                if del_dtw:
                    cal_payload.append({"datetime": start_iso, "value": 1.0, "factorId": FACTOR_IDS["delete_water"], "sensorId": int(sensor_id)})
                    
                if del_end_date and del_end_time:
                    end_dt = datetime.combine(del_end_date, del_end_time)
                    end_iso = PERTH_TZ.localize(end_dt).isoformat()
                    if del_ec:
                        cal_payload.append({"datetime": end_iso, "value": 0.0, "factorId": FACTOR_IDS["delete_ec"], "sensorId": int(sensor_id)})
                    if del_dtw:
                        cal_payload.append({"datetime": end_iso, "value": 0.0, "factorId": FACTOR_IDS["delete_water"], "sensorId": int(sensor_id)})

            # --- Offset Logic ---
            if apply_ec_offset or apply_dtw_offset:
                if not offset_date or not offset_time:
                    st.error("You must provide an Offset Start Date and Time.")
                    st.stop()
                    
                offset_dt = datetime.combine(offset_date, offset_time)
                offset_iso = PERTH_TZ.localize(offset_dt)
                
                active_ec_offset = get_active_factor(calibrations, FACTOR_IDS["ec_offset"], offset_iso)
                active_dtw_offset = get_active_factor(calibrations, FACTOR_IDS["dtw_offset"], offset_iso)
                
                if apply_ec_offset:
                    true_ec_offset = active_ec_offset + ec_target_offset
                    cal_payload.append({"datetime": offset_iso.isoformat(), "value": true_ec_offset, "factorId": FACTOR_IDS["ec_offset"], "sensorId": int(sensor_id)})
                    
                if apply_dtw_offset:
                    true_dtw_offset = active_dtw_offset + dtw_target_offset
                    cal_payload.append({"datetime": offset_iso.isoformat(), "value": true_dtw_offset, "factorId": FACTOR_IDS["dtw_offset"], "sensorId": int(sensor_id)})
                    
                if offset_end_date and offset_end_time:
                    offset_end_dt = datetime.combine(offset_end_date, offset_end_time)
                    offset_end_iso = PERTH_TZ.localize(offset_end_dt)
                    
                    active_ec_offset_end = get_active_factor(calibrations, FACTOR_IDS["ec_offset"], offset_end_iso)
                    active_dtw_offset_end = get_active_factor(calibrations, FACTOR_IDS["dtw_offset"], offset_end_iso)
                    
                    if apply_ec_offset:
                        cal_payload.append({"datetime": offset_end_iso.isoformat(), "value": active_ec_offset_end, "factorId": FACTOR_IDS["ec_offset"], "sensorId": int(sensor_id)})
                    if apply_dtw_offset:
                        cal_payload.append({"datetime": offset_end_iso.isoformat(), "value": active_dtw_offset_end, "factorId": FACTOR_IDS["dtw_offset"], "sensorId": int(sensor_id)})

            if not cal_payload:
                st.warning("No edits were selected to be applied.")
                st.stop()

            cal_url = f"{BASE_URL}/org/{ORG_ID}/proj/{PROJ_ID}/calibrations/many"
            cal_resp = requests.post(cal_url, headers=HEADERS, json=cal_payload)
            
            if cal_resp.status_code == 200:
                st.success("✅ Manual edits successfully applied.")
            else:
                st.error(f"❌ Failed to apply edits ({cal_resp.status_code}): {cal_resp.text}")
