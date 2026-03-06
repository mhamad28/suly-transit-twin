import streamlit as st
import pandas as pd
import math
import time
import base64
import json
from datetime import datetime, timezone

from supabase import create_client, Client
from streamlit_js_eval import get_geolocation
import folium
from streamlit_folium import st_folium
from geopy.geocoders import Nominatim


# --------------------------------------------------
# PAGE CONFIG
# --------------------------------------------------
st.set_page_config(page_title="Suly Transit System", layout="wide")


# --------------------------------------------------
# BACKGROUND
# --------------------------------------------------
def set_background(image_file: str) -> None:
    with open(image_file, "rb") as img:
        encoded = base64.b64encode(img.read()).decode()

    page_bg = f"""
    <style>
    .stApp {{
        background-image: linear-gradient(
            rgba(10, 15, 30, 0.55),
            rgba(10, 15, 30, 0.70)
        ), url("data:image/jpg;base64,{encoded}");
        background-size: cover;
        background-position: center;
        background-attachment: fixed;
    }}

    [data-testid="stHeader"] {{
        background: rgba(0, 0, 0, 0);
    }}

    [data-testid="stSidebar"] {{
        background: rgba(15, 20, 40, 0.55);
    }}

    .block-container {{
        background-color: rgba(0, 0, 0, 0.08);
        padding: 2rem;
        border-radius: 18px;
    }}

    .glass-card {{
        background: rgba(10, 20, 35, 0.45);
        border: 1px solid rgba(255,255,255,0.08);
        backdrop-filter: blur(8px);
        padding: 1rem 1.2rem;
        border-radius: 16px;
        margin-bottom: 1rem;
    }}
    </style>
    """
    st.markdown(page_bg, unsafe_allow_html=True)


set_background("assets/suli_bg.jpg")


# --------------------------------------------------
# SUPABASE
# --------------------------------------------------
URL = st.secrets["URL"]
KEY = st.secrets["KEY"]
supabase: Client = create_client(URL, KEY)


# --------------------------------------------------
# GEOCODER
# --------------------------------------------------
@st.cache_resource
def get_geocoder():
    return Nominatim(user_agent="suly_transit_system")


geocoder = get_geocoder()


# --------------------------------------------------
# ROUTE COLORS
# Names must match GeoJSON exactly
# --------------------------------------------------
ROUTE_COLORS = {
    "Bakrajo_Bazar": "#e41a1c",
    "Chwarchra_Bazar": "#377eb8",
    "FarmanBaran_Bazar": "#4daf4a",
    "HawaryShar_Bazar": "#984ea3",
    "Kazywa_Bazar": "#ff7f00",
    "Kshtukal_Bazar": "#a65628",
    "Qrgra_Bazar": "#f781bf",
    "Raparin_Bazar": "#999999",
    "Rzgary Bazar": "#66c2a5",
    "Shakraka_Bazar": "#fc8d62",
    "TwiMalik_Bazar": "#8da0cb",
    "Xabat_Bazar": "#ffd92f",
    "ZargatayTaza_Bazar": "#1b9e77",
}


# --------------------------------------------------
# HELPERS
# --------------------------------------------------
def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
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


def geocode_address(address: str):
    if not address.strip():
        return None

    address = address.strip()

    # Support raw coordinates: "lat, lon"
    if "," in address:
        parts = [p.strip() for p in address.split(",")]
        if len(parts) == 2:
            try:
                lat = float(parts[0])
                lon = float(parts[1])
                return {
                    "label": f"Selected coordinates ({lat:.5f}, {lon:.5f})",
                    "lat": lat,
                    "lon": lon,
                }
            except ValueError:
                pass

    try:
        query = f"{address}, Sulaymaniyah, Iraq"
        result = geocoder.geocode(query, timeout=10)
        if result:
            return {
                "label": result.address,
                "lat": result.latitude,
                "lon": result.longitude,
            }
    except Exception:
        return None

    return None


def load_routes_geojson(path="assets/bus_lines.geojson"):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def extract_route_points(routes_geojson):
    rows = []

    for feature in routes_geojson["features"]:
        route_name = feature["properties"].get("layer", "Unknown Route")
        geometry = feature.get("geometry", {})
        coords = geometry.get("coordinates", [])

        if geometry.get("type") == "LineString":
            for idx, coord in enumerate(coords):
                lon, lat = coord[0], coord[1]
                rows.append(
                    {
                        "route_name": route_name,
                        "point_order": idx,
                        "lat": lat,
                        "lon": lon,
                    }
                )

    return pd.DataFrame(rows)


def nearest_route(point_lat: float, point_lon: float, routes_geojson):
    route_points_df = extract_route_points(routes_geojson).copy()

    if route_points_df.empty:
        return None

    route_points_df["distance_km"] = route_points_df.apply(
        lambda row: haversine_km(point_lat, point_lon, row["lat"], row["lon"]),
        axis=1,
    )

    nearest = route_points_df.sort_values("distance_km").iloc[0]
    return nearest.to_dict()


def get_live_buses() -> pd.DataFrame:
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

    # Live table: keep only latest row for a bus
    supabase.table("live_bus_data").delete().eq("plate_number", plate_number).execute()
    supabase.table("live_bus_data").insert(live_data).execute()

    # History table: always append
    supabase.table("bus_location_history").insert(history_data).execute()


def build_passenger_map(
    routes_geojson,
    live_buses_df=None,
    origin_point=None,
    destination_point=None,
    highlight_route=None,
    show_all_lines=True,
):
    m = folium.Map(
        location=[35.56, 45.43],
        zoom_start=12,
        tiles="OpenStreetMap",
        control_scale=True,
    )

    for feature in routes_geojson["features"]:
        route_name = feature["properties"].get("layer", "Bus Route")
        color = ROUTE_COLORS.get(route_name, "#00bfff")

        # If full network is off, only show highlighted route
        if not show_all_lines and highlight_route and route_name != highlight_route:
            continue

        if highlight_route:
            if route_name == highlight_route:
                opacity = 0.95
                weight = 6
            else:
                opacity = 0.25 if show_all_lines else 0
                weight = 3
        else:
            opacity = 0.85
            weight = 5

        folium.GeoJson(
            feature,
            name=route_name,
            tooltip=route_name,
            style_function=lambda x, color=color, weight=weight, opacity=opacity: {
                "color": color,
                "weight": weight,
                "opacity": opacity,
            },
        ).add_to(m)

    if live_buses_df is not None and not live_buses_df.empty:
        for _, row in live_buses_df.iterrows():
            folium.Marker(
                location=[row["lat"], row["lon"]],
                popup=f"Bus: {row['plate_number']}",
                tooltip=f"Bus {row['plate_number']}",
                icon=folium.Icon(color="orange", icon="bus", prefix="fa"),
            ).add_to(m)

    if origin_point:
        folium.Marker(
            location=[origin_point["lat"], origin_point["lon"]],
            popup=origin_point.get("label", "Origin"),
            tooltip="Origin",
            icon=folium.Icon(color="green", icon="play"),
        ).add_to(m)

    if destination_point:
        folium.Marker(
            location=[destination_point["lat"], destination_point["lon"]],
            popup=destination_point.get("label", "Destination"),
            tooltip="Destination",
            icon=folium.Icon(color="red", icon="flag"),
        ).add_to(m)

    return m


# --------------------------------------------------
# SESSION STATE
# --------------------------------------------------
defaults = {
    "portal": None,
    "is_tracking": False,
    "driver_name": "",
    "plate_number": "",
    "line_id": "",
    "origin_point": None,
    "destination_point": None,
    "pick_mode": None,
}
for key, value in defaults.items():
    if key not in st.session_state:
        st.session_state[key] = value


# --------------------------------------------------
# HOME PAGE
# --------------------------------------------------
st.title("Suly Transit System")

if st.session_state.portal is None:
    st.subheader("Choose your portal")

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("### 👨‍✈️ Driver")
        st.write("Start shift and broadcast live bus location.")
        if st.button("Open Driver Portal", width="stretch"):
            st.session_state.portal = "driver"
            st.rerun()

    with col2:
        st.markdown("### 🚶 Passenger")
        st.write("Find the best line, see buses, and estimate arrival.")
        if st.button("Open Passenger Portal", width="stretch"):
            st.session_state.portal = "passenger"
            st.rerun()

else:
    back_col, _ = st.columns([1, 6])
    with back_col:
        if st.button("⬅ Back"):
            st.session_state.portal = None
            st.rerun()

    # --------------------------------------------------
    # DRIVER PORTAL
    # --------------------------------------------------
    if st.session_state.portal == "driver":
        st.header("Driver Tracking Portal")

        if not st.session_state.is_tracking:
            with st.form("driver_form"):
                driver_name = st.text_input("Driver Name")
                plate_number = st.text_input("Bus Plate Number")
                line_id = st.text_input("Bus Line Name / Route Name")

                submitted = st.form_submit_button("Start Tracking")

                if submitted:
                    if not driver_name or not plate_number or not line_id:
                        st.warning("Please fill in driver name, bus plate number, and line name.")
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

            if st.button("Stop Tracking"):
                st.session_state.is_tracking = False
                st.rerun()

            try:
                loc = get_geolocation()
                if loc and "coords" in loc:
                    lat = loc["coords"]["latitude"]
                    lon = loc["coords"]["longitude"]

                    save_driver_ping(
                        st.session_state.driver_name,
                        st.session_state.plate_number,
                        st.session_state.line_id,
                        lat,
                        lon,
                    )

                    st.info(f"📡 Last Ping: {time.strftime('%H:%M:%S')}")
                    st.write(f"Latitude: {lat}")
                    st.write(f"Longitude: {lon}")

                    driver_map_df = pd.DataFrame([{"lat": lat, "lon": lon}])
                    st.map(driver_map_df)
                else:
                    st.warning("Waiting for location permission or GPS data...")
            except Exception as e:
                st.error(f"Driver update failed: {e}")

            time.sleep(15)
            st.rerun()

    # --------------------------------------------------
    # PASSENGER PORTAL
    # --------------------------------------------------
    elif st.session_state.portal == "passenger":
        st.header("Passenger Portal")

        routes_geojson = load_routes_geojson("assets/bus_lines.geojson")
        live_df = get_live_buses()

        st.markdown('<div class="glass-card">', unsafe_allow_html=True)
        st.subheader("Trip Planner")

        input_mode = st.radio(
            "Choose input mode",
            ["Type address", "Choose from map"],
            horizontal=True,
        )

        col1, col2, col3 = st.columns([2, 2, 1])

        with col1:
            if input_mode == "Type address":
                origin_text = st.text_input(
                    "Origin",
                    placeholder="Example: Azadi Park or 35.576151, 45.337101",
                    key="origin_text_input",
                )
                if st.button("Set origin from address"):
                    point = geocode_address(origin_text)
                    if point:
                        st.session_state.origin_point = point
                        st.success("Origin set from typed address.")
                    else:
                        st.error("Could not find that origin address.")
            else:
                st.write("Pick origin by clicking on the map.")
                if st.button("Pick Origin From Map"):
                    st.session_state.pick_mode = "origin"

        with col2:
            if input_mode == "Type address":
                destination_text = st.text_input(
                    "Destination",
                    placeholder="Example: City Center or 35.560000, 45.430000",
                    key="destination_text_input",
                )
                if st.button("Set destination from address"):
                    point = geocode_address(destination_text)
                    if point:
                        st.session_state.destination_point = point
                        st.success("Destination set from typed address.")
                    else:
                        st.error("Could not find that destination address.")
            else:
                st.write("Pick destination by clicking on the map.")
                if st.button("Pick Destination From Map"):
                    st.session_state.pick_mode = "destination"

        with col3:
            st.write("")
            st.write("")
            if st.button("Use My Location"):
                loc = get_geolocation()
                if loc and "coords" in loc:
                    st.session_state.origin_point = {
                        "label": "My current location",
                        "lat": loc["coords"]["latitude"],
                        "lon": loc["coords"]["longitude"],
                    }
                    st.success("Current location set as origin.")
                else:
                    st.warning("Could not get your current location.")

        st.markdown("</div>", unsafe_allow_html=True)

        show_all_lines = st.checkbox("Show all bus lines", value=True)

        highlight_route = None
        if st.session_state.origin_point and st.session_state.destination_point:
            origin_route = nearest_route(
                st.session_state.origin_point["lat"],
                st.session_state.origin_point["lon"],
                routes_geojson,
            )
            destination_route = nearest_route(
                st.session_state.destination_point["lat"],
                st.session_state.destination_point["lon"],
                routes_geojson,
            )

            if origin_route and destination_route:
                if origin_route["route_name"] == destination_route["route_name"]:
                    highlight_route = origin_route["route_name"]

        passenger_map = build_passenger_map(
            routes_geojson=routes_geojson,
            live_buses_df=live_df if not live_df.empty else None,
            origin_point=st.session_state.origin_point,
            destination_point=st.session_state.destination_point,
            highlight_route=highlight_route,
            show_all_lines=show_all_lines,
        )

        map_data = st_folium(passenger_map, height=650, width="stretch")

        clicked = map_data.get("last_clicked") if map_data else None
        if clicked and st.session_state.pick_mode in ("origin", "destination"):
            clicked_point = {
                "label": f"Selected point ({clicked['lat']:.5f}, {clicked['lng']:.5f})",
                "lat": clicked["lat"],
                "lon": clicked["lng"],
            }

            if st.session_state.pick_mode == "origin":
                st.session_state.origin_point = clicked_point
                st.success("Origin selected from map.")
            elif st.session_state.pick_mode == "destination":
                st.session_state.destination_point = clicked_point
                st.success("Destination selected from map.")

            st.session_state.pick_mode = None
            st.rerun()

        if st.session_state.origin_point and st.session_state.destination_point:
            origin_route = nearest_route(
                st.session_state.origin_point["lat"],
                st.session_state.origin_point["lon"],
                routes_geojson,
            )
            destination_route = nearest_route(
                st.session_state.destination_point["lat"],
                st.session_state.destination_point["lon"],
                routes_geojson,
            )

            st.markdown('<div class="glass-card">', unsafe_allow_html=True)
            st.subheader("Trip Result")

            if origin_route:
                st.write(
                    f"Nearest origin route: **{origin_route['route_name']}** "
                    f"({origin_route['distance_km']:.2f} km away)"
                )

            if destination_route:
                st.write(
                    f"Nearest destination route: **{destination_route['route_name']}** "
                    f"({destination_route['distance_km']:.2f} km away)"
                )

            if origin_route and destination_route:
                if origin_route["route_name"] == destination_route["route_name"]:
                    route_name = origin_route["route_name"]
                    st.success(f"Recommended route: {route_name}")

                    if not live_df.empty:
                        line_buses = live_df[live_df["line_id"] == route_name].copy()

                        if not line_buses.empty:
                            line_buses["eta_minutes"] = line_buses.apply(
                                lambda row: haversine_km(
                                    row["lat"],
                                    row["lon"],
                                    st.session_state.origin_point["lat"],
                                    st.session_state.origin_point["lon"],
                                ) / 18 * 60,
                                axis=1,
                            )

                            best_bus = line_buses.sort_values("eta_minutes").iloc[0]
                            st.info(
                                f"Next bus: {best_bus['plate_number']} | "
                                f"ETA near your origin: {best_bus['eta_minutes']:.1f} min"
                            )

                            show_cols = [
                                c for c in ["plate_number", "driver_name", "last_ping", "eta_minutes"]
                                if c in line_buses.columns
                            ]
                            st.dataframe(
                                line_buses[show_cols].sort_values("eta_minutes"),
                                width="stretch",
                            )
                        else:
                            st.info("No live buses currently broadcasting on this route.")
                    else:
                        st.info("No live bus data available yet.")
                else:
                    st.warning(
                        "Origin and destination are closest to different routes. "
                        "Later we can add transfer logic."
                    )

            st.markdown("</div>", unsafe_allow_html=True)
