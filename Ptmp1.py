import streamlit as st
import folium
from streamlit_folium import st_folium
import math
import itur
import astropy.units as u
import json
import os
import requests

# --- Constants & Data Tables ---
MCS_TABLE = [
    {"mcs": 0,  "mod": "BPSK",     "snr": 2,  "caps": {40: 16.25,  80: 34.03,  160: 68.06,   320: 136.11}},
    {"mcs": 1,  "mod": "QPSK",     "snr": 5,  "caps": {40: 32.50,  80: 68.06,  160: 136.11,  320: 272.22}},
    {"mcs": 2,  "mod": "QPSK",     "snr": 8,  "caps": {40: 48.75,  80: 102.08, 160: 204.17,  320: 408.33}},
    {"mcs": 3,  "mod": "16-QAM",   "snr": 11, "caps": {40: 65.00,  80: 136.11, 160: 272.22,  320: 544.44}},
    {"mcs": 4,  "mod": "16-QAM",   "snr": 14, "caps": {40: 97.50,  80: 204.17, 160: 408.33,  320: 816.67}},
    {"mcs": 5,  "mod": "64-QAM",   "snr": 16, "caps": {40: 130.00, 80: 272.22, 160: 544.44,  320: 1088.89}},
    {"mcs": 6,  "mod": "64-QAM",   "snr": 18, "caps": {40: 146.25, 80: 306.25, 160: 612.50,  320: 1225.00}},
    {"mcs": 7,  "mod": "64-QAM",   "snr": 21, "caps": {40: 162.50, 80: 340.28, 160: 680.56,  320: 1361.11}},
    {"mcs": 8,  "mod": "256-QAM",  "snr": 24, "caps": {40: 195.00, 80: 408.33, 160: 816.67,  320: 1633.33}},
    {"mcs": 9,  "mod": "256-QAM",  "snr": 27, "caps": {40: 216.67, 80: 453.70, 160: 907.41,  320: 1814.81}},
    {"mcs": 10, "mod": "1024-QAM", "snr": 30, "caps": {40: 243.75, 80: 510.42, 160: 1020.83, 320: 2041.67}},
    {"mcs": 11, "mod": "1024-QAM", "snr": 33, "caps": {40: 270.83, 80: 567.13, 160: 1134.26, 320: 2268.52}}
]

MCS_COLORS = {
    0: '#ff0000', 1: '#ff4500', 2: '#ff8c00', 3: '#ffa500', 
    4: '#ffd700', 5: '#ffff00', 6: '#adff2f', 7: '#7fff00', 
    8: '#00ff00', 9: '#00fa9a', 10: '#00ced1', 11: '#0000ff'
}

# --- Building Detection Function ---
def fetch_buildings_from_osm(south, west, north, east):
    """Queries OSM Overpass API for buildings in the visible area."""
    overpass_url = "http://overpass-api.de/api/interpreter"
    # Filter for ways (buildings) within the bounding box
    overpass_query = f"""
    [out:json][timeout:25];
    (
      way["building"]({south},{west},{north},{east});
      relation["building"]({south},{west},{north},{east});
    );
    out center;
    """
    try:
        response = requests.get(overpass_url, params={'data': overpass_query})
        data = response.json()
        return data.get('elements', [])
    except:
        return []

# --- Data Persistence ---
DATA_FILE = "ptmp_save.json"

def load_all_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            try:
                save_dict = json.load(f)
                return save_dict.get("aps", []), save_dict.get("cpes", [])
            except:
                return [], []
    return [], []

def save_all_data():
    save_dict = {"aps": st.session_state.aps, "cpes": st.session_state.cpes}
    with open(DATA_FILE, "w") as f:
        json.dump(save_dict, f)

# --- Link Budget Math ---
@st.cache_data
def calculate_all_mcs_radii(lat, lon, f_GHz, tx_power, tx_gain, rx_gain, noise_figure, channel_bw, availability):
    radii_results = {}
    bw_hz = channel_bw * 1e6
    noise_floor_dbm = -174 + (10 * math.log10(bw_hz)) + noise_figure
    f = f_GHz * u.GHz
    T = 15 * u.deg_C
    P = 1013 * u.hPa
    rho = 7.5 * u.g / u.m**3
    gamma_g_qty = itur.models.itu676.gamma_exact(f, P, rho, T)
    gamma_g = gamma_g_qty.value 
    p = 100.0 - availability 
    R_qty = itur.models.itu837.rainfall_rate(lat, lon, p)
    gamma_r_qty = itur.models.itu838.rain_specific_attenuation(R_qty, f, 0, 0)
    gamma_r = gamma_r_qty.value
    for mcs_index in range(12): 
        mcs_data = MCS_TABLE[mcs_index]
        rx_threshold = noise_floor_dbm + mcs_data["snr"]
        min_d_km, max_d_km, best_d_km = 0.01, 50.0, 0.01
        for _ in range(40): 
            mid_d = (min_d_km + max_d_km) / 2.0
            fspl = 20 * math.log10(mid_d) + 20 * math.log10(f_GHz) + 92.45
            total_loss = fspl + (gamma_g * mid_d) + (gamma_r * mid_d)
            rx_power = tx_power + tx_gain + rx_gain - total_loss
            if rx_power >= rx_threshold:
                min_d_km = mid_d
                best_d_km = mid_d
            else:
                max_d_km = mid_d
        radii_results[mcs_index] = {"radius_m": best_d_km * 1000.0, "capacity": mcs_data["caps"].get(channel_bw, 0)}
    return radii_results

def get_sector_polygon(lat, lon, radius_m, start_angle, end_angle):
    R = 6378137
    lat_rad, lon_rad = math.radians(lat), math.radians(lon)
    points = [(lat, lon)]
    for angle in range(int(start_angle), int(end_angle) + 1, 5):
        bearing = math.radians(angle)
        lat_out = math.asin(math.sin(lat_rad) * math.cos(radius_m / R) + math.cos(lat_rad) * math.sin(radius_m / R) * math.cos(bearing))
        lon_out = lon_rad + math.atan2(math.sin(bearing) * math.sin(radius_m / R) * math.cos(lat_rad), math.cos(radius_m / R) - math.sin(lat_rad) * math.sin(lat_out))
        points.append((math.degrees(lat_out), math.degrees(lon_out)))
    points.append((lat, lon))
    return points

# --- 1. Session State Init ---
if 'aps' not in st.session_state or 'cpes' not in st.session_state:
    st.session_state.aps, st.session_state.cpes = load_all_data()
if 'ap_counter' not in st.session_state:
    st.session_state.ap_counter = len(st.session_state.aps) + 1
if 'cpe_counter' not in st.session_state:
    st.session_state.cpe_counter = len(st.session_state.cpes) + 1
if 'map_bounds' not in st.session_state:
    st.session_state.map_bounds = None
if 'last_clicked' not in st.session_state:
    st.session_state.last_clicked = None

def add_ap(lat, lon):
    name = f"AP {st.session_state.ap_counter}"
    st.session_state.ap_counter += 1
    st.session_state.aps.append({
        "name": name, "lat": round(lat, 6), "lon": round(lon, 6), "height": 10.0,
        "tx_power": 23.0, "antenna_gain": 20.0, "channel_bw": 80, "num_sectors": 6, "beam_width": 60,
        "sectors": [{"id": i+1, "channel": (i % 2) + 1} for i in range(6)]
    })
    save_all_data()

# --- 2. Sidebar UI ---
st.set_page_config(page_title="PtMP Planner Pro", layout="wide")
st.title("📡 Point-to-Multipoint Planning App")

with st.sidebar:
    st.header("Global Settings")
    global_freq = st.selectbox("Frequency Band (GHz)", options=[5, 26, 60], index=1)
    availability_target = st.number_input("Availability Target (%)", value=99.9, format="%.3f")
    min_mcs_display = st.selectbox("Min MCS to Display", options=range(12), index=0)
    cpe_gain = st.number_input("Global CPE Gain (dBi)", value=15.0)
    cpe_nf = st.number_input("CPE Noise Fig (dB)", value=7.0)

    st.divider()
    st.header("CPE Discovery")
    # THE BUTTON
    if st.button("🏗️ Detect Buildings (Visible Map)"):
        if st.session_state.map_bounds:
            b = st.session_state.map_bounds
            buildings = fetch_buildings_from_osm(b['_southWest']['lat'], b['_southWest']['lng'], b['_northEast']['lat'], b['_northEast']['lng'])
            
            new_cpes = 0
            for bldg in buildings:
                tags = bldg.get('tags', {})
                center = bldg.get('center', {})
                if not center: continue
                
                # Height Guesstimate Logic
                h = tags.get('height')
                if h:
                    try: h = float(h.split()[0])
                    except: h = 8.0
                elif tags.get('building:levels'):
                    try: h = float(tags.get('building:levels')) * 3.5
                    except: h = 8.0
                else:
                    h = 8.0
                
                st.session_state.cpes.append({
                    "name": f"CPE {st.session_state.cpe_counter}",
                    "lat": center['lat'], "lon": center['lon'], "height": h
                })
                st.session_state.cpe_counter += 1
                new_cpes += 1
            st.success(f"Added {new_cpes} buildings as CPEs!")
            save_all_data()
            st.rerun()
        else:
            st.warning("Move the map slightly first to capture visibility area.")

    st.divider()
    # List CPEs in the sidebar
    with st.expander(f"🏠 Managed CPEs ({len(st.session_state.cpes)})"):
        for i, cpe in enumerate(st.session_state.cpes):
            col_cn, col_cd = st.columns([3, 1])
            st.session_state.cpes[i]["name"] = col_cn.text_input(f"Name", value=cpe["name"], key=f"cpe_n_{i}")
            st.session_state.cpes[i]["height"] = col_cn.number_input(f"Height (m)", value=float(cpe["height"]), key=f"cpe_h_{i}")
            if col_cd.button("🗑️", key=f"cpe_del_{i}"):
                st.session_state.cpes.pop(i)
                save_all_data()
                st.rerun()

    st.divider()
    # List APs in the sidebar
    with st.expander(f"📡 Managed APs ({len(st.session_state.aps)})"):
        for i, ap in enumerate(st.session_state.aps):
            st.session_state.aps[i]["name"] = st.text_input(f"AP Name", value=ap["name"], key=f"ap_n_{i}")
            if st.button(f"Delete {ap['name']}", key=f"ap_del_{i}"):
                st.session_state.aps.pop(i)
                save_all_data()
                st.rerun()

# --- 3. Map Generation ---
start_loc = [st.session_state.aps[0]["lat"], st.session_state.aps[0]["lon"]] if st.session_state.aps else [32.1750, 34.9069]
m = folium.Map(location=start_loc, zoom_start=15, control_scale=True)

# Draw APs and Heatmaps
for ap in st.session_state.aps:
    radii_data = calculate_all_mcs_radii(ap["lat"], ap["lon"], global_freq, ap["tx_power"], ap["antenna_gain"], cpe_gain, cpe_nf, ap["channel_bw"], availability_target)
    
    start_angle = 0
    for sector in sorted(ap["sectors"], key=lambda x: x["id"]):
        end_angle = start_angle + ap["beam_width"]
        for m_idx in range(min_mcs_display, 12):
            poly = get_sector_polygon(ap["lat"], ap["lon"], radii_data[m_idx]["radius_m"], start_angle, end_angle)
            folium.Polygon(locations=poly, stroke=False, fill=True, fill_color=MCS_COLORS[m_idx], fill_opacity=0.15).add_to(m)
        start_angle = end_angle
    folium.Marker([ap["lat"], ap["lon"]], tooltip=ap["name"], icon=folium.Icon(color="black", icon="tower-broadcast", prefix="fa")).add_to(m)

# Draw CPEs
for cpe in st.session_state.cpes:
    folium.CircleMarker(
        [cpe["lat"], cpe["lon"]], radius=4, color="blue", fill=True, 
        tooltip=f"{cpe['name']} (H: {cpe['height']}m)"
    ).add_to(m)

# Custom Legend
legend_html = f'<div style="position: absolute; bottom: 50px; left: 10px; width: 100px; background:white; z-index:9999; font-size:10px; padding:5px; border-radius:5px; border:1px solid grey;"><b>Capacity</b><br>'
for m_idx in range(11, min_mcs_display-1, -1):
    legend_html += f'<i style="background:{MCS_COLORS[m_idx]}; width:10px; height:10px; float:left; margin-right:5px;"></i>MCS {m_idx}<br>'
legend_html += '</div>'
m.get_root().html.add_child(folium.Element(legend_html))

map_data = st_folium(m, width=1000, height=600, key="ptmp_map", returned_objects=["last_clicked", "bounds"])

# --- 4. Logic ---
if map_data:
    if map_data.get("bounds"):
        st.session_state.map_bounds = map_data["bounds"]
    if map_data.get("last_clicked"):
        cl = map_data["last_clicked"]
        curr = (round(cl['lat'], 6), round(cl['lng'], 6))
        if st.session_state.last_clicked != curr:
            st.session_state.last_clicked = curr
            add_ap(curr[0], curr[1])
            st.rerun()
