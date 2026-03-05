import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
from supabase import create_client, Client
from streamlit_js_eval import get_geolocation
import time

# Values from your screenshots
URL = "https://wvbrpclzdvcvkbgehxfu.supabase.co"
KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Ind2YnJwY2x6ZHZjdmtiZ2VoeGZ1Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzI0OTEyNDAsImV4cCI6MjA4ODA2NzI0MH0.DnMn4u5drKcETVTv4tFKz-7uv5AEisU36q1hEm0rE2k" # Paste the full long key from your screen here

supabase: Client = create_client(URL, KEY)

st.set_page_config(page_title="Suly Bus Digital Twin", layout="wide")

# --- 2. LOAD ROUTE DATA ---
@st.cache_data
def load_route():
    # Ensure 'l v l.csv' is in the same folder as this script
    return pd.read_csv('l v l.csv')

df_route = load_route()

# --- 3. INTERFACE NAVIGATION ---
st.title("🚌 Sulaymaniyah Transit Digital Twin")
role = st.sidebar.radio("Select Portal:", ["🚶 Pedestrian View", "👨‍✈️ Driver Broadcast"])

# --- 4. DRIVER PORTAL (Data Ingestion) ---
if role == "👨‍✈️ Driver Broadcast":
    st.header("Driver Tracking Mode")
    st.info("Keep this tab open to broadcast your live location.")
    
    with st.form("driver_info"):
        name = st.text_input("Driver Name")
        plate = st.text_input("Bus Plate Number")
        start = st.form_submit_button("Start Shift")

    if start:
        st.success(f"Broadcasting for {plate}...")
        # Browser-based GPS capture
        loc = get_geolocation()
        if loc:
            lat, lon = loc['coords']['latitude'], loc['coords']['longitude']
            # Push to Supabase
            data = {"plate_number": plate, "driver_name": name, "lat": lat, "lon": lon}
            supabase.table("live_bus_data").upsert(data, on_conflict="plate_number").execute()
            st.write(f"Updated: {lat}, {lon}")

# --- 5. PEDESTRIAN PORTAL (Real-Time Map) ---
else:
    st.header("Real-Time Bus Tracker")
    
    # Fetch live buses from Cloud
    response = supabase.table("live_bus_data").select("*").execute()
    live_buses = response.data

    # Initialize Folium Map
    m = folium.Map(location=[35.5852, 45.4390], zoom_start=14)
    
    # Draw the static 319-point route
    folium.PolyLine(df_route[['Y', 'X']].values, color="blue", weight=5, opacity=0.7).add_to(m)

    # Plot live buses
    if live_buses:
        for bus in live_buses:
            folium.Marker(
                [bus['lat'], bus['lon']],
                popup=f"Bus: {bus['plate_number']}",
                icon=folium.Icon(color='red', icon='bus', prefix='fa')
            ).add_to(m)
            st.write(f"✅ Bus {bus['plate_number']} is currently active.")
    else:
        st.warning("No buses are currently broadcasting.")

    st_folium(m, width=1200, height=600)

# Auto-refresh the page every 10 seconds for real-time feel
time.sleep(10)
st.rerun()
