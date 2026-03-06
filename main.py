import streamlit as st
import pandas as pd
import math
import time
from datetime import datetime, timezone
from supabase import create_client, Client
from streamlit_js_eval import get_geolocation
import base64

def set_background(image_file):
    with open(image_file, "rb") as img:
        encoded = base64.b64encode(img.read()).decode()

    page_bg = f"""
    <style>
    .stApp {{
        background-image: linear-gradient(
            rgba(10, 15, 30, 0.85),
            rgba(10, 15, 30, 0.95)
        ), url("data:image/jpg;base64,{encoded}");
        background-size: cover;
        background-position: center;
        background-attachment: fixed;
    }}

    [data-testid="stHeader"] {{
        background: rgba(0,0,0,0);
    }}

    [data-testid="stSidebar"] {{
        background: rgba(15,20,40,0.9);
    }}
    </style>
    """

    st.markdown(page_bg, unsafe_allow_html=True)
    st.set_page_config(page_title="Suly Transit System", layout="wide")

set_background("assets/suli_bg.jpg")

# ----------------------------
# CONFIG
# ----------------------------
st.set_page_config(page_title="Suly Transit System", layout="wide")

URL = st.secrets["URL"]
KEY = st.secrets["KEY"]
supabase: Client = create_client(URL, KEY)

# ----------------------------
# SIMPLE ROUTE/STOPS DATA
# Replace later with Supabase tables
# ----------------------------
LINES = {
    "L1": {
        "name": "Line 1",
        "stops": [
            {"stop_name": "Bakhtiary", "lat": 35.5610, "lon": 45.4300},
            {"stop_name": "Salim Street", "lat": 35.5640, "lon": 45.4350},
            {"stop_name": "Sarchnar", "lat": 35.5680, "lon": 45.4400},
            {"stop_name": "City Center", "lat": 35.5615, "lon": 45.4440},
        ]
    },
    "L2": {
        "name": "Line 2",
        "stops": [
            {"stop_name": "Tasluja", "lat": 35.5330, "lon": 45.3940},
            {"stop_name": "Azadi Park", "lat": 35.5480, "lon": 45.4200},
            {"stop_name": "Saray", "lat": 35.5570, "lon": 45.4330},
            {"stop_name": "City Center", "lat": 35.5615, "lon": 45.4440},
        ]
    },
}

# ----------------------------
# HELPERS
# ----------------------------
def haversine_km(lat1, lon1, lat2, lon2):
    r = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)

    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return r * c


def flatten_stops():
    rows = []
    for line_id, line_data in LINES.items():
        for idx, stop in enumerate(line_data["stops"]):
            rows.append({
                "line_id": line_id,
                "line_name": line_data["name"],
                "stop_name": stop["stop_name"],
                "lat": stop["lat"],
                "lon": stop["lon"],
                "stop_order": idx
            })
    return pd.DataFrame(rows)


def find_nearest_stop(user_lat, user_lon):
    stops_df = flatten_stops().drop_duplicates(subset=["stop_name"])
    stops_df["distance_km"] = stops_df.apply(
        lambda row: haversine_km(user_lat, user_lon, row["lat"], row["lon"]),
        axis=1
    )
    return stops_df.sort_values("distance_km").iloc[0].to_dict()


def find_direct_line(origin_stop, destination_stop):
    for line_id, line_data in LINES.items():
        stop_names = [s["stop_name"] for s in line_data["stops"]]
        if origin_stop in stop_names and destination_stop in stop_names:
            if stop_names.index(origin_stop) < stop_names.index(destination_stop):
                return line_id
    return None


def get_stop_coords(line_id, stop_name):
    for stop in LINES[line_id]["stops"]:
        if stop["stop_name"] == stop_name:
            return stop["lat"], stop["lon"]
    return None, None


def estimate_eta_minutes(bus_lat, bus_lon, stop_lat, stop_lon, speed_kmh=18):
    distance_km = haversine_km(bus_lat, bus_lon, stop_lat, stop_lon)
    speed_kmh = max(speed_kmh, 12)
    return (distance_km / speed_kmh) * 60


def estimate_route_ride_minutes(line_id, origin_stop, destination_stop, avg_speed_kmh=20):
    stops = LINES[line_id]["stops"]

    origin_index = next(i for i, s in enumerate(stops) if s["stop_name"] == origin_stop)
    destination_index = next(i for i, s in enumerate(stops) if s["stop_name"] == destination_stop)

    total_km = 0
    for i in range(origin_index, destination_index):
        s1 = stops[i]
        s2 = stops[i + 1]
        total_km += haversine_km(s1["lat"], s1["lon"], s2["lat"], s2["lon"])

    return (total_km / avg_speed_kmh) * 60


def get_live_buses():
    result = supabase.table("live_bus_data").select("*").execute()
    if result.data:
        return pd.DataFrame(result.data)
    return pd.DataFrame(columns=["plate_number", "driver_name", "line_id", "lat", "lon", "last_ping"])


def save_driver_ping(driver_name, plate_number, line_id, lat, lon):
    now_iso = datetime.now(timezone.utc).isoformat()

    live_data = {
        "plate_number": plate_number,
        "driver_name": driver_name,
        "line_id": line_id,
        "lat": lat,
        "lon": lon,
        "last_ping": now_iso,
    }

    history_data = {
        "plate_number": plate_number,
        "line_id": line_id,
        "lat": lat,
        "lon": lon,
        "recorded_at": now_iso,
    }

    supabase.table("live_bus_data").upsert(live_data, on_conflict="plate_number").execute()
    supabase.table("bus_location_history").insert(history_data).execute()

# ----------------------------
# SESSION STATE
# ----------------------------
if "portal" not in st.session_state:
    st.session_state.portal = None

if "is_tracking" not in st.session_state:
    st.session_state.is_tracking = False

if "driver_name" not in st.session_state:
    st.session_state.driver_name = ""

if "plate_number" not in st.session_state:
    st.session_state.plate_number = ""

if "line_id" not in st.session_state:
    st.session_state.line_id = ""

# ----------------------------
# HOME PAGE
# ----------------------------
st.title("Suly Transit System")

if st.session_state.portal is None:
    st.subheader("Choose your portal")
    col1, col2 = st.columns(2)

    with col1:
        st.markdown("### 👨‍✈️ Driver")
        st.write("Start shift and broadcast live bus location.")
        if st.button("Open Driver Portal", use_container_width=True):
            st.session_state.portal = "driver"
            st.rerun()

    with col2:
        st.markdown("### 🚶 Passenger")
        st.write("Find the best line, see buses, and estimate arrival.")
        if st.button("Open Passenger Portal", use_container_width=True):
            st.session_state.portal = "passenger"
            st.rerun()

else:
    top1, top2 = st.columns([1, 5])
    with top1:
        if st.button("⬅ Back"):
            st.session_state.portal = None
            st.rerun()

    # ----------------------------
    # DRIVER PORTAL
    # ----------------------------
    if st.session_state.portal == "driver":
        st.header("Driver Tracking Portal")

        if not st.session_state.is_tracking:
            with st.form("driver_form"):
                driver_name = st.text_input("Driver Name")
                plate_number = st.text_input("Bus Plate Number")
                line_id = st.selectbox("Choose Bus Line", list(LINES.keys()), format_func=lambda x: f"{x} - {LINES[x]['name']}")

                submitted = st.form_submit_button("Start Tracking")
                if submitted:
                    if not driver_name or not plate_number:
                        st.warning("Please fill in driver name and bus plate number.")
                    else:
                        st.session_state.driver_name = driver_name
                        st.session_state.plate_number = plate_number
                        st.session_state.line_id = line_id
                        st.session_state.is_tracking = True
                        st.rerun()

        else:
            st.success(
                f"Tracking active | Driver: {st.session_state.driver_name} | "
                f"Bus: {st.session_state.plate_number} | Line: {st.session_state.line_id}"
            )

            col_a, col_b = st.columns([1, 3])
            with col_a:
                if st.button("Stop Tracking"):
                    st.session_state.is_tracking = False
                    st.rerun()

            status_box = st.empty()

            loc = get_geolocation()
            if loc and "coords" in loc:
                lat = loc["coords"]["latitude"]
                lon = loc["coords"]["longitude"]

                save_driver_ping(
                    st.session_state.driver_name,
                    st.session_state.plate_number,
                    st.session_state.line_id,
                    lat,
                    lon
                )

                with status_box.container():
                    st.info(f"📡 Last Ping: {time.strftime('%H:%M:%S')}")
                    st.write(f"Latitude: {lat}")
                    st.write(f"Longitude: {lon}")

                    driver_map_df = pd.DataFrame([{"lat": lat, "lon": lon}])
                    st.map(driver_map_df, size=12)

            else:
                st.warning("Waiting for location permission or GPS data...")

            time.sleep(15)
            st.rerun()

    # ----------------------------
    # PASSENGER PORTAL
    # ----------------------------
    elif st.session_state.portal == "passenger":
        st.header("Passenger Portal")

        stops_df = flatten_stops()
        unique_stops = sorted(stops_df["stop_name"].unique().tolist())

        col1, col2 = st.columns(2)
        with col1:
            origin_stop = st.selectbox("Your boarding stop", unique_stops)
        with col2:
            destination_stop = st.selectbox("Your destination stop", unique_stops)

        if origin_stop == destination_stop:
            st.warning("Choose different origin and destination stops.")
        else:
            line_id = find_direct_line(origin_stop, destination_stop)

            if not line_id:
                st.error("No direct line found yet in this MVP.")
            else:
                st.success(f"Recommended line: {line_id} - {LINES[line_id]['name']}")

                board_lat, board_lon = get_stop_coords(line_id, origin_stop)
                dest_lat, dest_lon = get_stop_coords(line_id, destination_stop)

                ride_minutes = estimate_route_ride_minutes(line_id, origin_stop, destination_stop)

                live_df = get_live_buses()
                line_buses = live_df[live_df["line_id"] == line_id].copy() if not live_df.empty else pd.DataFrame()

                eta_text = "No live buses currently found on this line."
                best_eta = None
                next_bus_plate = None

                if not line_buses.empty:
                    line_buses["eta_minutes"] = line_buses.apply(
                        lambda row: estimate_eta_minutes(
                            row["lat"], row["lon"], board_lat, board_lon, speed_kmh=18
                        ),
                        axis=1,
                    )
                    best_bus = line_buses.sort_values("eta_minutes").iloc[0]
                    best_eta = float(best_bus["eta_minutes"])
                    next_bus_plate = best_bus["plate_number"]
                    eta_text = f"Next bus: {next_bus_plate} | ETA to {origin_stop}: {best_eta:.1f} min"

                st.info(eta_text)
                st.write(f"Estimated ride time from {origin_stop} to {destination_stop}: {ride_minutes:.1f} min")

                total_display_rows = []

                # stop markers
                route_stops = pd.DataFrame(LINES[line_id]["stops"])
                total_display_rows.extend(route_stops.to_dict(orient="records"))

                # live buses
                if not line_buses.empty:
                    bus_points = line_buses[["lat", "lon"]].rename(columns={"lat": "lat", "lon": "lon"})
                    total_display_rows.extend(bus_points.to_dict(orient="records"))

                if total_display_rows:
                    map_df = pd.DataFrame(total_display_rows)
                    st.map(map_df, size=10)

                st.subheader("Live buses on recommended line")
                if not line_buses.empty:
                    show_cols = [c for c in ["plate_number", "driver_name", "last_ping", "eta_minutes"] if c in line_buses.columns]
                    st.dataframe(line_buses[show_cols].sort_values("eta_minutes"), use_container_width=True)
                else:
                    st.write("No buses are currently broadcasting on this line.")
