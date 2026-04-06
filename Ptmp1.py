import streamlit as st
import folium
from streamlit_folium import st_folium
import math
import itur
import astropy.units as u
import json
import os

# --- Step 2: Wi-Fi 7 MCS Data Table ---
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

# --- Data Persistence ---
DATA_FILE = "ap_data.json"

def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return []
    return []

def save_data():
    with open(DATA_FILE, "w") as f:
        json.dump(st.session_state.aps, f)

# --- Link Budget & ITU-R Math ---
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
        
        min_d_km = 0.01
        max_d_km = 50.0  
        best_d_km = min_d_km
        
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
                
        radii_results[mcs_index] = {
            "radius_m": best_d_km * 1000.0,
            "capacity": mcs_data["caps"].get(channel_bw, 0),
            "mod": mcs_data["mod"]
        }
        
    return radii_results

def get_sector_polygon(lat, lon, radius_m, start_angle, end_angle):
    R = 6378137
    lat_rad = math.radians(lat)
    lon_rad = math.radians(lon)
    points = [(lat, lon)]
    step = 5
    angles = list(range(int(start_angle), int(end_angle), step))
    if angles[-1] != end_angle:
        angles.append(end_angle)
    for angle in angles:
        bearing = math.radians(angle)
        lat_out = math.asin(math.sin(lat_rad) * math.cos(radius_m / R) + math.cos(lat_rad) * math.sin(radius_m / R) * math.cos(bearing))
        lon_out = lon_rad + math.atan2(math.sin(bearing) * math.sin(radius_m / R) * math.cos(lat_rad), math.cos(radius_m / R) - math.sin(lat_rad) * math.sin(lat_out))
        points.append((math.degrees(lat_out), math.degrees(lon_out)))
    points.append((lat, lon))
    return points

# --- 1. Session State Initialization ---
if 'aps' not in st.session_state:
    st.session_state.aps = load_data() 
if 'ap_counter' not in st.session_state:
    st.session_state.ap_counter = len(st.session_state.aps) + 1 if st.session_state.aps else 1
if 'last_clicked' not in st.session_state:
    st.session_state.last_clicked = None

def add_ap(lat, lon, name=None):
    if name is None:
        name = f"AP {st.session_state.ap_counter}"
        st.session_state.ap_counter += 1
    
    beam_width = 60
    num_channels_reuse = max(1, int(120 / beam_width)) 
    default_sectors = [{"id": i+1, "channel": (i % num_channels_reuse) + 1} for i in range(6)]
        
    st.session_state.aps.append({
        "name": name,
        "lat": round(float(lat), 6),
        "lon": round(float(lon), 6),
        "height": 10.0,
        "tx_power": 23.0,
        "antenna_gain": 20.0,
        "channel_bw": 80,    
        "num_sectors": 6,
        "beam_width": beam_width,
        "sectors": default_sectors
    })
    save_data()

# --- 2. Main UI & Sidebar ---
st.set_page_config(page_title="PtMP Planner", layout="wide")
st.title("📡 Point-to-Multipoint Planning App")

with st.sidebar:
    st.header("Global Settings")
    global_freq = st.selectbox("Frequency Band (GHz)", options=[5, 26, 60], index=1)
    availability_target = st.number_input("Availability Target (%)", value=99.9, min_value=90.0, max_value=99.999, step=0.01, format="%.3f")
    
    col_cpe1, col_cpe2 = st.columns(2)
    cpe_gain = col_cpe1.number_input("CPE Gain (dBi)", value=15.0, step=1.0)
    cpe_nf = col_cpe2.number_input("CPE Noise Fig (dB)", value=7.0, step=0.5) 
    
    st.divider()
    st.header("AP Management")
    with st.expander("➕ Add AP Manually"):
        man_lat = st.number_input("Latitude", value=32.1750, format="%.6f")
        man_lon = st.number_input("Longitude", value=34.9069, format="%.6f")
        if st.button("Add to Map"):
            add_ap(man_lat, man_lon)
            st.rerun()
            
    st.divider()
    st.subheader("Existing APs")
    
    # Direct session state mutation - No manual st.rerun() needed! Streamlit handles it natively.
    for i, ap in enumerate(st.session_state.aps):
        if "channel_bw" not in ap:
            ap["channel_bw"] = 80
            
        with st.expander(ap["name"]):
            st.session_state.aps[i]["name"] = st.text_input("Name", value=ap["name"], key=f"name_{i}")
            
            col1, col2 = st.columns(2)
            st.session_state.aps[i]["lat"] = col1.number_input("Latitude", value=float(ap["lat"]), format="%.6f", key=f"lat_{i}")
            st.session_state.aps[i]["lon"] = col2.number_input("Longitude", value=float(ap["lon"]), format="%.6f", key=f"lon_{i}")
            
            col_h, col_bw = st.columns(2)
            st.session_state.aps[i]["height"] = col_h.number_input("Height (m)", value=float(ap["height"]), step=1.0, key=f"h_{i}")
            st.session_state.aps[i]["channel_bw"] = col_bw.selectbox("Channel BW (MHz)", options=[40, 80, 160, 320], index=[40, 80, 160, 320].index(ap["channel_bw"]), key=f"cbw_{i}")
            
            st.markdown("**RF Parameters**")
            col3, col4 = st.columns(2)
            st.session_state.aps[i]["tx_power"] = col3.number_input("Tx Power (dBm)", value=float(ap["tx_power"]), step=1.0, key=f"tx_{i}")
            st.session_state.aps[i]["antenna_gain"] = col4.number_input("Ant. Gain (dBi)", value=float(ap["antenna_gain"]), step=1.0, key=f"gain_{i}")
            st.session_state.aps[i]["num_sectors"] = col3.number_input("Sectors", value=int(ap["num_sectors"]), min_value=1, step=1, key=f"numsec_{i}")
            st.session_state.aps[i]["beam_width"] = col4.number_input("Beam Width (°)", value=int(ap["beam_width"]), min_value=1, step=1, key=f"bw_{i}")
            
            current_sectors = sorted(ap.get("sectors", []), key=lambda x: x["id"])
            if st.session_state.aps[i]["num_sectors"] > len(current_sectors):
                num_channels_reuse = max(1, int(120 / st.session_state.aps[i]["beam_width"]))
                for s_idx in range(len(current_sectors), st.session_state.aps[i]["num_sectors"]):
                    current_sectors.append({"id": s_idx + 1, "channel": (s_idx % num_channels_reuse) + 1})
            elif st.session_state.aps[i]["num_sectors"] < len(current_sectors):
                current_sectors = current_sectors[:st.session_state.aps[i]["num_sectors"]]
            
            st.markdown("**Sector Channels**")
            updated_sectors = []
            sec_cols = st.columns(3)
            for s_idx, sector in enumerate(current_sectors):
                with sec_cols[s_idx % 3]:
                    new_ch = st.number_input(f"Sec {s_idx+1} Ch", value=int(sector["channel"]), step=1, key=f"ch_{i}_{s_idx}")
                    updated_sectors.append({"id": s_idx + 1, "channel": new_ch})
            
            st.session_state.aps[i]["sectors"] = updated_sectors
            
            st.divider()
            if st.button("🗑️ Delete AP", type="primary", key=f"del_{i}"):
                st.session_state.aps.pop(i)
                save_data()
                st.rerun()

    save_data() # Saves quietly without causing an infinite rerun loop

# --- 3. Map Generation ---
start_loc = [st.session_state.aps[0]["lat"], st.session_state.aps[0]["lon"]] if st.session_state.aps else [32.1750, 34.9069]
m = folium.Map(location=start_loc, zoom_start=13, control_scale=True)

for ap in st.session_state.aps:
    mcs_data = calculate_all_mcs_radii(
        ap["lat"], ap["lon"], global_freq, 
        ap["tx_power"], ap["antenna_gain"], 
        cpe_gain, cpe_nf, ap.get("channel_bw", 80), availability_target
    )
    
    for mcs_level in range(12):
        data = mcs_data[mcs_level]
        folium.Circle(
            location=[ap["lat"], ap["lon"]],
            radius=data['radius_m'],
            color=MCS_COLORS[mcs_level],
            weight=1,
            fill=False,
            dash_array='3, 4',
        ).add_to(m)

    start_angle = 0 
    sorted_sectors = sorted(ap.get("sectors", []), key=lambda x: x["id"])
    
    for idx, sector in enumerate(sorted_sectors):
        end_angle = start_angle + ap["beam_width"]
        
        for mcs_level in range(12):
            data = mcs_data[mcs_level]
            polygon_points = get_sector_polygon(ap["lat"], ap["lon"], data['radius_m'], start_angle, end_angle)
            
            folium.Polygon(
                locations=polygon_points,
                stroke=False, 
                fill=True,
                fill_color=MCS_COLORS[mcs_level],
                fill_opacity=0.15,
                tooltip=f"{ap['name']} Sec {sector['id']} - MCS {mcs_level} ({data['capacity']} Mbps)"
            ).add_to(m)
            
        largest_polygon = get_sector_polygon(ap["lat"], ap["lon"], mcs_data[0]['radius_m'], start_angle, end_angle)
        folium.PolyLine(
            locations=largest_polygon,
            color='black',
            weight=1,
            opacity=0.4
        ).add_to(m)
        
        start_angle = end_angle

    folium.Marker(
        [ap["lat"], ap["lon"]],
        popup=f"{ap['name']} ({global_freq}GHz)",
        tooltip=ap["name"],
        icon=folium.Icon(color="black", icon="wifi", prefix="fa")
    ).add_to(m)

legend_html = """
<div style="position: absolute; bottom: 50px; left: 10px; width: 120px; background-color: rgba(255, 255, 255, 0.85); border: 1px solid grey; z-index: 9999; font-size: 10px; padding: 6px; border-radius: 4px;">
<div style="font-weight: bold; margin-bottom: 4px; text-align: center;">Capacity</div>
"""
for m_idx in range(11, -1, -1):
    color = MCS_COLORS[m_idx]
    mod = MCS_TABLE[m_idx]['mod']
    legend_html += f"""<div style="margin-bottom: 2px; line-height: 12px;"><i style="background:{color}; width: 10px; height: 10px; float: left; margin-right: 5px; border: 1px solid #777; border-radius: 2px;"></i>MCS {m_idx} ({mod})</div>"""
legend_html += "</div>"
m.get_root().html.add_child(folium.Element(legend_html))

# --- IMPORTANT: returned_objects strictly limits what the map tells Streamlit, breaking the loop ---
map_data = st_folium(m, width=800, height=600, key="ptmp_map", returned_objects=["last_clicked"])

# --- 4. Handle Map Clicks ---
if map_data and map_data.get("last_clicked"):
    clicked_lat = round(map_data["last_clicked"]["lat"], 6)
    clicked_lon = round(map_data["last_clicked"]["lng"], 6)
    
    current_click = (clicked_lat, clicked_lon)
    if st.session_state.last_clicked != current_click:
        st.session_state.last_clicked = current_click
        add_ap(clicked_lat, clicked_lon)
        st.rerun()
