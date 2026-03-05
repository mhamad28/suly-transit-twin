import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
from supabase import create_client, Client
from streamlit_js_eval import get_geolocation
import time

# --- 1. CLOUD CONNECTION ---
URL = st.secrets["URL"]
KEY = st.secrets["KEY"]
supabase: Client = create_client(URL, KEY)

st.set_page_config(page_title="Suly Bus Digital Twin", layout="wide")

# --- 2. LOAD ROUTE DATA ---
@st.cache_data
def load_route():
    return pd.read_csv('l v l.csv')
df_route = load_route()

# --- 3. INTERFACE NAVIGATION ---
st.sidebar.title("Suly Transit System")
role = st.sidebar.radio("Select Portal:", ["🚶 Pedestrian View", "👨‍✈️ Driver Broadcast"])

# --- 4. DRIVER PORTAL (With Memory/Session State) ---
if role == "👨‍✈️ Driver Broadcast":
    st.header("Driver Tracking Mode")

    # Initialize "Memory" if it doesn't exist
    if 'tracking_active' not in st.session_state:
        st.session_state.tracking_active = False

    # If NOT tracking, show the login form
    if not st.session_state.tracking_active:
        with st.form("driver_info"):
            st.session_state.name = st.text_input("Driver Name")
            st.session_state.plate = st.text_input("Bus Plate Number")
            submit = st.form_submit_button("Start Shift")
            if submit:
                st.session_state.tracking_active = True
                st.rerun()

    # If tracking IS active, run the loop forever
    else:
        st.success(f"🚀 Tracking Active for {st.session_state.plate}")
        if st.button("Stop Shift"):
            st.session_state.tracking_active = False
            st.rerun()
        
        # This keeps the GPS data visible in one place
        dashboard = st.empty()
        
        while st.session_state.tracking_active:
            loc = get_geolocation()
            if loc:
                lat = loc['coords']['latitude']
                lon = loc['coords']['longitude']
                
                # A. Update Live Map
                live_data = {"plate_number": st.session_state.plate, "driver_name": st.session_state.name, "lat": lat, "lon": lon}
                supabase.table("live_bus_data").upsert(live_data, on_conflict="plate_number").execute()
                
                # B. Save to History (Research Data)
                history_data = {"plate_number": st.session_state.plate, "lat": lat, "lon": lon}
                supabase.table("bus_location_history").insert(history_data).execute()
                
                with dashboard.container():
                    st.info("📡 GPS Signal Strong - Point Saved to History")
                    st.write(f"📍 Location: {lat:.5f}, {lon:.5f}")
                    st.write(f"🕒 Last Ping: {time.strftime('%H:%M:%S')}")
            
            time.sleep(15) # Wait 15 seconds
            st.rerun() # Refresh and keep going

# --- 5. PEDESTRIAN PORTAL ---
else:
    st.header("Real-Time Bus Tracker")
    response = supabase.table("live_bus_data").select("*").execute()
    live_buses = response.data

    m = folium.Map(location=[35.5852, 45.4390], zoom_start=14)
    folium.PolyLine(df_route[['Y', 'X']].values, color="blue", weight=5, opacity=0.7).add_to(m)

    if live_buses:
        for bus in live_buses:
            folium.Marker(
                [bus['lat'], bus['lon']],
                popup=f"Bus: {bus['plate_number']}",
                icon=folium.Icon(color='red', icon='bus', prefix='fa')
            ).add_to(m)
    
    st_folium(m, width=1200, height=600)
    time.sleep(20)
    st.rerun()
