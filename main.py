import streamlit as st
import pandas as pd
from supabase import create_client, Client
from streamlit_js_eval import get_geolocation
import time

# --- CLOUD CONNECTION ---
URL = st.secrets["URL"]
KEY = st.secrets["KEY"]
supabase: Client = create_client(URL, KEY)

st.set_page_config(page_title="Suly Bus Digital Twin", layout="wide")

# --- DRIVER PORTAL ---
st.sidebar.title("Suly Transit System")
role = st.sidebar.radio("Select Portal:", ["🚶 Pedestrian View", "👨‍✈️ Driver Broadcast"])

if role == "👨‍✈️ Driver Broadcast":
    st.header("Driver Tracking Mode")

    if 'is_tracking' not in st.session_state:
        st.session_state.is_tracking = False

    if not st.session_state.is_tracking:
        with st.form("driver_info"):
            st.session_state.d_name = st.text_input("Driver Name")
            st.session_state.d_plate = st.text_input("Bus Plate Number")
            if st.form_submit_button("Start Shift"):
                st.session_state.is_tracking = True
                st.rerun()
    else:
        st.success(f"🚀 Tracking Active for {st.session_state.d_plate}")
        if st.button("Stop Shift"):
            st.session_state.is_tracking = False
            st.rerun()
        
        status = st.empty()
        while st.session_state.is_tracking:
            loc = get_geolocation()
            if loc:
                lat, lon = loc['coords']['latitude'], loc['coords']['longitude']
                
                # A. Update Live Table (Has driver_name column)
                live_data = {"plate_number": st.session_state.d_plate, "driver_name": st.session_state.d_name, "lat": lat, "lon": lon}
                supabase.table("live_bus_data").upsert(live_data, on_conflict="plate_number").execute()
                
                # B. Save to History Table (Matches your schema: id and plate_number only)
                # Note: 'id' is automatic, so we only send plate, lat, and lon if you added those columns
                history_data = {"plate_number": st.session_state.d_plate, "lat": lat, "lon": lon}
                supabase.table("bus_location_history").insert(history_data).execute()
                
                with status.container():
                    st.info(f"📡 Last Ping: {time.strftime('%H:%M:%S')}")
                    st.write(f"Logged: {lat}, {lon}")
            
            time.sleep(15) 
            st.rerun()
