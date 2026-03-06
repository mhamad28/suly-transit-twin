import json
import math
import time
from datetime import datetime, timezone
from typing import List, Dict, Any

from supabase import create_client, Client

# --------------------------------------------------
# CONFIG
# --------------------------------------------------
SUPABASE_URL = "YOUR_SUPABASE_URL"
SUPABASE_KEY = "YOUR_SUPABASE_KEY"
GEOJSON_PATH = "assets/bus_lines.geojson"

AVERAGE_SPEED_KMH = 40.0
START_TERMINAL_DWELL_MIN = 40
END_TERMINAL_DWELL_MIN = 10
UPDATE_INTERVAL_SEC = 10

MIN_STOPS_PER_ONE_WAY = 4
MAX_STOPS_PER_ONE_WAY = 10
MAX_BUSES_ON_LONGEST_LINE = 10

SIM_DRIVER_NAME = "Sim Agent"

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# --------------------------------------------------
# GEO HELPERS
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


def route_length_km(coords: List[List[float]]) -> float:
    total = 0.0
    for i in range(len(coords) - 1):
        lon1, lat1 = coords[i]
        lon2, lat2 = coords[i + 1]
        total += haversine_km(lat1, lon1, lat2, lon2)
    return total


def cumulative_distances_km(coords: List[List[float]]) -> List[float]:
    cum = [0.0]
    total = 0.0
    for i in range(len(coords) - 1):
        lon1, lat1 = coords[i]
        lon2, lat2 = coords[i + 1]
        total += haversine_km(lat1, lon1, lat2, lon2)
        cum.append(total)
    return cum


# --------------------------------------------------
# LOAD ROUTES
# --------------------------------------------------
def load_routes(path: str) -> List[Dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as f:
        geojson = json.load(f)

    routes = []
    for feature in geojson["features"]:
        route_name = feature["properties"].get("layer", "Unknown Route")
        geometry = feature.get("geometry", {})
        coords = geometry.get("coordinates", [])

        if geometry.get("type") != "LineString" or len(coords) < 2:
            continue

        length_km = route_length_km(coords)
        cumdist = cumulative_distances_km(coords)

        routes.append(
            {
                "route_name": route_name,
                "coords": coords,
                "length_km": length_km,
                "cumdist": cumdist,
            }
        )

    return routes


# --------------------------------------------------
# FIXED STOP GENERATION
# --------------------------------------------------
def generate_fixed_stops(route: Dict[str, Any]) -> Dict[str, Any]:
    """
    Fixed stops based on route length.
    Number of stops scales between 4 and 10.
    Stop durations alternate 1 and 2 minutes in a fixed pattern.
    """
    coords = route["coords"]
    length_km = route["length_km"]
    cumdist = route["cumdist"]

    # Scale stop count by length, but keep between 4 and 10
    # Rough heuristic: 1 stop per ~2 km, bounded
    stop_count = max(
        MIN_STOPS_PER_ONE_WAY,
        min(MAX_STOPS_PER_ONE_WAY, round(length_km / 2.0))
    )

    # Spread stops evenly along the route, avoiding terminals
    total_len = cumdist[-1]
    if total_len <= 0:
        return {"stop_indices": [], "stop_durations_min": []}

    stop_indices = []
    for i in range(1, stop_count + 1):
        target_dist = (i / (stop_count + 1)) * total_len

        best_idx = min(
            range(len(cumdist)),
            key=lambda idx: abs(cumdist[idx] - target_dist)
        )

        if 0 < best_idx < len(coords) - 1:
            if best_idx not in stop_indices:
                stop_indices.append(best_idx)

    stop_indices = sorted(stop_indices)

    # Fixed pattern: mostly 1 minute, sometimes 2 minutes
    stop_durations_min = []
    for i in range(len(stop_indices)):
        stop_durations_min.append(2 if i % 4 == 2 else 1)

    return {
        "stop_indices": stop_indices,
        "stop_durations_min": stop_durations_min,
    }


# --------------------------------------------------
# BUS COUNT BY LINE LENGTH
# --------------------------------------------------
def assign_buses_by_length(routes: List[Dict[str, Any]]) -> None:
    longest = max(r["length_km"] for r in routes) if routes else 1.0

    for route in routes:
        ratio = route["length_km"] / longest if longest > 0 else 1.0
        buses = round(ratio * MAX_BUSES_ON_LONGEST_LINE)
        buses = max(1, min(MAX_BUSES_ON_LONGEST_LINE, buses))
        route["bus_count"] = buses


# --------------------------------------------------
# AGENT CREATION
# --------------------------------------------------
def create_bus_agents(routes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    buses = []

    for route in routes:
        route_name = route["route_name"]
        coords = route["coords"]
        bus_count = route["bus_count"]

        stop_info = generate_fixed_stops(route)
        stop_indices_out = stop_info["stop_indices"]
        stop_durations_out = stop_info["stop_durations_min"]

        # Return trip uses same stop pattern mirrored
        last_idx = len(coords) - 1
        stop_indices_in = sorted([last_idx - idx for idx in stop_indices_out], reverse=True)
        stop_durations_in = list(stop_durations_out)

        stagger_sec = 0
        if bus_count > 1:
            # stagger start terminal release over the 40-minute terminal wait
            stagger_sec = int((START_TERMINAL_DWELL_MIN * 60) / bus_count)

        for i in range(bus_count):
            bus = {
                "plate_number": f"SIM_{route_name[:3].upper()}_{i+1:02d}",
                "driver_name": SIM_DRIVER_NAME,
                "line_id": route_name,
                "route_name": route_name,
                "coords": coords,
                "current_index": 0,
                "direction": 1,  # 1 outbound, -1 inbound
                "state": "waiting_start",
                "state_until": time.time() + (i * stagger_sec),
                "speed_kmh": AVERAGE_SPEED_KMH,
                "stop_indices_out": stop_indices_out,
                "stop_durations_out": stop_durations_out,
                "stop_indices_in": stop_indices_in,
                "stop_durations_in": stop_durations_in,
                "active_stop_map": dict(zip(stop_indices_out, stop_durations_out)),
                "next_state_after_stop": None,
            }
            buses.append(bus)

    return buses


# --------------------------------------------------
# SUPABASE WRITE
# --------------------------------------------------
def write_bus_to_supabase(bus: Dict[str, Any]) -> None:
    idx = bus["current_index"]
    lon, lat = bus["coords"][idx]
    now_iso = datetime.now(timezone.utc).isoformat()

    live_data = {
        "plate_number": bus["plate_number"],
        "driver_name": bus["driver_name"],
        "line_id": bus["line_id"],
        "lat": lat,
        "lon": lon,
        "last_ping": now_iso,
    }

    history_data = {
        "plate_number": bus["plate_number"],
        "line_id": bus["line_id"],
        "lat": lat,
        "lon": lon,
        "recorded_at": now_iso,
    }

    supabase.table("live_bus_data").delete().eq("plate_number", bus["plate_number"]).execute()
    supabase.table("live_bus_data").insert(live_data).execute()
    supabase.table("bus_location_history").insert(history_data).execute()


# --------------------------------------------------
# BUS STATE MACHINE
# --------------------------------------------------
def set_outbound_mode(bus: Dict[str, Any]) -> None:
    bus["direction"] = 1
    bus["active_stop_map"] = dict(zip(bus["stop_indices_out"], bus["stop_durations_out"]))
    bus["state"] = "moving"


def set_inbound_mode(bus: Dict[str, Any]) -> None:
    bus["direction"] = -1
    bus["active_stop_map"] = dict(zip(bus["stop_indices_in"], bus["stop_durations_in"]))
    bus["state"] = "moving"


def maybe_stop_at_current_index(bus: Dict[str, Any]) -> bool:
    idx = bus["current_index"]
    if idx in bus["active_stop_map"]:
        stop_min = bus["active_stop_map"].pop(idx)
        bus["state"] = "stopping"
        bus["state_until"] = time.time() + (stop_min * 60)
        bus["next_state_after_stop"] = "moving"
        return True
    return False


def move_one_step(bus: Dict[str, Any]) -> None:
    idx = bus["current_index"]
    last_idx = len(bus["coords"]) - 1

    if bus["direction"] == 1:
        if idx < last_idx:
            bus["current_index"] += 1
        else:
            bus["state"] = "waiting_end"
            bus["state_until"] = time.time() + (END_TERMINAL_DWELL_MIN * 60)
            return
    else:
        if idx > 0:
            bus["current_index"] -= 1
        else:
            bus["state"] = "waiting_start"
            bus["state_until"] = time.time() + (START_TERMINAL_DWELL_MIN * 60)
            return

    maybe_stop_at_current_index(bus)


def update_bus(bus: Dict[str, Any]) -> None:
    now = time.time()

    if bus["state"] == "waiting_start":
        if now >= bus["state_until"]:
            bus["current_index"] = 0
            set_outbound_mode(bus)
        return

    if bus["state"] == "waiting_end":
        if now >= bus["state_until"]:
            bus["current_index"] = len(bus["coords"]) - 1
            set_inbound_mode(bus)
        return

    if bus["state"] == "stopping":
        if now >= bus["state_until"]:
            bus["state"] = bus["next_state_after_stop"]
            bus["next_state_after_stop"] = None
        return

    if bus["state"] == "moving":
        # One simple step per update interval.
        # Because route vertex spacing varies, this is an approximation for now.
        move_one_step(bus)
        return


# --------------------------------------------------
# MAIN
# --------------------------------------------------
def print_summary(routes: List[Dict[str, Any]]) -> None:
    print("\n=== ROUTE SUMMARY ===")
    for r in sorted(routes, key=lambda x: x["length_km"], reverse=True):
        print(
            f"{r['route_name']}: "
            f"{r['length_km']:.2f} km | "
            f"buses={r['bus_count']}"
        )
    print("=====================\n")


def main():
    routes = load_routes(GEOJSON_PATH)
    assign_buses_by_length(routes)
    print_summary(routes)

    buses = create_bus_agents(routes)
    print(f"Created {len(buses)} simulated buses.\n")

    while True:
        for bus in buses:
            update_bus(bus)
            write_bus_to_supabase(bus)

        print(f"[{datetime.now().strftime('%H:%M:%S')}] Updated {len(buses)} buses")
        time.sleep(UPDATE_INTERVAL_SEC)


if __name__ == "__main__":
    main()