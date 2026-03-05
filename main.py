import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
from supabase import create_client, Client
from streamlit_js_eval import get_geolocation
import time

# --- 1. CLOUD CONNECTION ---
# These pull from the "Secrets" you added to Streamlit Cloud
URL = st.secrets["URL"]
KEY = st.secrets["KEY"]
supabase: Client = create_client(URL, KEY)

st.set_page_config(page_title="Suly Bus Digital Twin", layout="wide")

# --- 2. LOAD ROUTE DATA ---
@st.cache_data
def load_route():
    # Ensure 'l v l.csv' is in your GitHub folder
    return pd.read_csv('l v l.csv')

df_route = load_route()

# --- 3. INTERFACE NAVIGATION ---
st.sidebar.title("Suly Transit System")
role = st.sidebar.radio("Select Portal:", ["🚶 Pedestrian View", "👨‍✈️ Driver Broadcast"])

# --- 4. DRIVER PORTAL (Data Ingestion) ---
if role == "👨‍✈️ Driver Broadcast":
    st.header("Driver Tracking Mode")
    
    # SECURITY: Access code protects your research data
    access_code = st.text_input("Enter Driver Access Code", type="password")
    
    # We define the form and the START button here FIRST
    with st.form("driver_info"):
        name = st.text_input("Driver Name")
        plate = st.text_input("Bus Plate Number")
        start = st.form_submit_button("Start Shift")

    # NOW we check if the button was clicked and if the code is correct
    if start:
        if access_code == "Suly2026": 
            st.success(f"Access Granted! Broadcasting for {plate}...")
            
            # This container keeps the screen stable
            dashboard = st.empty()
            
            while True:
                loc = get_geolocation()
                if loc:
                    lat = loc['coords']['latitude']
                    lon = loc['coords']['longitude']
                    
                    # A. UPDATE LIVE MAP (Overwrites current location)
                    live_data = {"plate_number": plate, "driver_name": name, "lat": lat, "lon": lon}
                    supabase.table("live_bus_data").upsert(live_data, on_conflict="plate_number").execute()
                    
                    # B. SAVE TO HISTORY (Adds new row for Thesis/Spark analysis)
                    history_data = {"plate_number": plate, "lat": lat, "lon": lon}
                    supabase.table("bus_location_history").insert(history_data).execute()
                    
                    with dashboard.container():
                        st.info("📡 GPS Signal Active")
                        st.write(f"📍 Latitude: {lat:.5f} | Longitude: {lon:.5f}")
                        st.write(f"🕒 Last Update: {time.strftime('%H:%M:%S')}")
                
                # Ping every 15 seconds
                time.sleep(15) 
                st.rerun() 
        else:
            st.error("Incorrect Access Code. Security blocked data upload.")

# --- 5. PEDESTRIAN PORTAL (Real-Time Map) ---
else:
    st.header("Real-Time Bus Tracker")
    
    # Fetch live buses from Supabase
    response = supabase.table("live_bus_data").select("*").execute()
    live_buses = response.data

    # Center map on Sulaymaniyah
    m = folium.Map(location=[35.5852, 45.4390], zoom_start=14)
    
    # Draw the static 319-point Raparin Baridaka route line
    folium.PolyLine(df_route[['Y', 'X']].values, color="blue", weight=5, opacity=0.7).add_to(m)

    # Plot markers for all active buses
    if live_buses:
        for bus in live_buses:
            folium.Marker(
                [bus['lat'], bus['lon']],
                popup=f"Bus: {bus['plate_number']} (Driver: {bus['driver_name']})",
                icon=folium.Icon(color='red', icon='bus', prefix='fa')
            ).add_to(m)
            st.success(f"✅ Bus {bus['plate_number']} is currently on route.")
    else:
        st.warning("No buses are currently broadcasting.")

    st_folium(m, width=1200, height=600)

# Auto-refresh Pedestrian view every 20 seconds
if role == "🚶 Pedestrian View":
    time.sleep(20)
    st.rerun()
