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

# --- 4. DRIVER PORTAL (Tracking & Saving) ---
if role == "👨‍✈️ Driver Broadcast":
    st.header("Driver Tracking Mode")
    st.info("Click 'Start Shift' to begin broadcasting and saving data to history.")
    
    with st.form("driver_info"):
        name = st.text_input("Driver Name")
        plate = st.text_input("Bus Plate Number")
        start = st.form_submit_button("Start Shift")

    if start:
        st.success(f"Tracking started for {plate}. Keep this tab open.")
        
        # Dashboard keeps the screen from flickering wildly
        dashboard = st.empty()
        
        while True:
            loc = get_geolocation()
            if loc:
                lat = loc['coords']['latitude']
                lon = loc['coords']['longitude']
                
                # A. UPDATE LIVE MAP (Overwrites current location for pedestrians)
                live_data = {"plate_number": plate, "driver_name": name, "lat": lat, "lon": lon}
                supabase.table("live_bus_data").upsert(live_data, on_conflict="plate_number").execute()
                
                # B. SAVE TO HISTORY (NEW: Creates a permanent record for your thesis)
                history_data = {"plate_number": plate, "lat": lat, "lon": lon}
                supabase.table("bus_location_history").insert(history_data).execute()
                
                with dashboard.container():
                    st.info("📡 GPS Active - Every 15s point saved to History")
                    st.write(f"📍 Current: {lat:.5f}, {lon:.5f}")
                    st.write(f"🕒 Last Ping: {time.strftime('%H:%M:%S')}")
            
            # Wait 15 seconds then refresh the GPS
            time.sleep(15) 
            st.rerun() 

# --- 5. PEDESTRIAN PORTAL (Real-Time View) ---
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

if role == "🚶 Pedestrian View":
    time.sleep(20)
    st.rerun()
