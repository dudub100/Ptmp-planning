import streamlit as st
import folium
from streamlit_folium import st_folium
import math
import itur
import astropy.units as u
import json
import os

# --- Step 2: Wi-Fi 7 MCS Data Table ---
# Transcribed from user provided table (Capacity in Mbps per spatial stream)
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
    {"mcs": 11, "mod": "1024-QAM", "snr": 33, "caps": {40: 270.83, 80: 567.13, 160: 1134.26, 320: 2268.52}},
    {"mcs": 12, "mod": "4096-QAM", "snr": 36, "caps": {40: 292.50, 80: 612.50, 160: 1225.00, 320: 2450.00}},
    {"mcs": 13, "mod": "4096-QAM", "snr": 39, "caps": {40: 325.00, 80: 680.56, 160: 1361.11, 320: 2722.22}}
]

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
def calculate_mcs_radii(lat, lon, f_GHz, tx_power, tx_gain, rx_gain, noise_figure, channel_bw):
    """Calculates max radius in meters for Edge (MCS 0), Mid (MCS 7), and Peak (MCS 13) at 99.9% availability."""
    target_mcs_levels = [0, 7, 13]
    radii_results = {}
    
    # 1. Calculate the Receiver Noise Floor
    # Thermal noise = -174 dBm/Hz. We add 10*log10(Bandwidth in Hz) + Noise Figure
    bw_hz = channel_bw * 1e6
    noise_floor_dbm = -174 + (10 * math.log10(bw_hz)) + noise_figure
    
    # 2. ITU Standard Atmospherics
    f = f_GHz * u.GHz
    T = 15 * u.deg_C
    P = 1013 * u.hPa
    rho = 7.5 * u.g / u.m**3
    
    gamma_g_qty = itur.models.itu676.gamma_exact(f, P, rho, T)
    gamma_g = gamma_g_qty.value 
    
    # 99.9% Availability -> 0.1% Exceedance
    p = 0.1 
    R_qty = itur.models.itu837.rainfall_rate(lat, lon, p)
    gamma_r_qty = itur.models.itu838.rain_specific_attenuation(R_qty, f, 0, 0)
    gamma_r = gamma_r_qty.value
    
    for mcs_index in target_mcs_levels:
        mcs_data = MCS_TABLE[mcs_index]
        required_snr = mcs_data["snr"]
        
        # Calculate dynamic receiver threshold for this specific MCS
        rx_threshold = noise_floor_dbm + required_snr
        
        # Binary search for distance
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
                
        # Save radius in meters and the expected capacity for the tooltip
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
    if st.session_state.aps:
        st.session_state.ap_counter = len(st.session_state.aps) + 1
    else:
        st.session_state.ap_counter = 1
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
        "lat": lat,
        "lon": lon,
        "height": 10.0,
        "tx_power": 23.0,
        "antenna_gain": 20.0,
        "channel_bw": 80,    # Default Channel BW
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
    
    col_cpe1, col_cpe2 = st.columns(2)
    cpe_gain = col_cpe1.number_input("CPE Gain (dBi)", value=15.0, step=1.0)
    # Replaced Threshold with Noise Figure
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
    
    for i, ap in enumerate(st.session_state.aps):
        # Default fallback for older saved data before channel_bw existed
        if "channel_bw" not in ap:
            ap["channel_bw"] = 80
            
        with st.expander(ap["name"]):
            new_name = st.text_input("Name", value=ap["name"], key=f"name_{i}")
            
            col1, col2 = st.columns(2)
            new_lat = col1.number_input("Latitude", value=ap["lat"], format="%.6f", key=f"lat_{i}")
            new_lon = col2.number_input("Longitude", value=ap["lon"], format="%.6f", key=f"lon_{i}")
            
            col_h, col_bw = st.columns(2)
            new_h = col_h.number_input("Height (m)", value=ap["height"], step=1.0, key=f"h_{i}")
            # New Channel BW selector
            new_chan_bw = col_bw.selectbox("Channel BW (MHz)", options=[40, 80, 160, 320], index=[40, 80, 160, 320].index(ap["channel_bw"]), key=f"cbw_{i}")
            
            st.markdown("**RF Parameters**")
            col3, col4 = st.columns(2)
            new_tx = col3.number_input("Tx Power (dBm)", value=ap["tx_power"], step=1.0, key=f"tx_{i}")
            new_gain = col4.number_input("Ant. Gain (dBi)", value=ap["antenna_gain"], step=1.0, key=f"gain_{i}")
            new_num_sec = col3.number_input("Sectors", value=ap["num_sectors"], min_value=1, step=1, key=f"numsec_{i}")
            new_bw = col4.number_input("Beam Width (°)", value=ap["beam_width"], min_value=1, step=1, key=f"bw_{i}")
            
            current_sectors = sorted(ap.get("sectors", []), key=lambda x: x["id"])
            if new_num_sec > len(current_sectors):
                num_channels_reuse = max(1, int(120 / new_bw))
                for s_idx in range(len(current_sectors), new_num_sec):
                    current_sectors.append({"id": s_idx + 1, "channel": (s_idx % num_channels_reuse) + 1})
            elif new_num_sec < len(current_sectors):
                current_sectors = current_sectors[:new_num_sec]
            
            st.markdown("**Sector Channels**")
            updated_sectors = []
            sec_cols = st.columns(3)
            for s_idx, sector in enumerate(current_sectors):
                with sec_cols[s_idx % 3]:
                    new_ch = st.number_input(f"Sec {s_idx+1} Ch", value=sector["channel"], step=1, key=f"ch_{i}_{s_idx}")
                    updated_sectors.append({"id": s_idx + 1, "channel": new_ch})

            if (new_name != ap["name"] or new_lat != ap["lat"] or new_lon != ap["lon"] or 
                new_h != ap["height"] or new_chan_bw != ap["channel_bw"] or new_tx != ap["tx_power"] or 
                new_gain != ap["antenna_gain"] or new_num_sec != ap["num_sectors"] or 
                new_bw != ap["beam_width"] or updated_sectors != ap["sectors"]):
                
                st.session_state.aps[i].update({
                    "name": new_name, "lat": new_lat, "lon": new_lon,
                    "height": new_h, "channel_bw": new_chan_bw, "tx_power": new_tx, "antenna_gain": new_gain,
                    "num_sectors": new_num_sec, "beam_width": new_bw, "sectors": updated_sectors
                })
                save_data() 
                st.rerun()
            
            st.divider()
            if st.button("🗑️ Delete AP", type="primary", key=f"del_{i}"):
                st.session_state.aps.pop(i)
                save_data()
                st.rerun()

# --- 3. Map Generation ---
start_loc = [st.session_state.aps[0]["lat"], st.session_state.aps[0]["lon"]] if st.session_state.aps else [32.1750, 34.9069]
m = folium.Map(location=start_loc, zoom_start=13)

channel_colors = {
    1: '#FF3333', 2: '#3357FF', 3: '#33FF57', 4: '#F5FF33', 
    5: '#FF33F5', 6: '#33FFF5', 7: '#FFA533', 8: '#A533FF',
}

# Colors for capacity tiers: Edge (Red), Mid (Orange), Peak (Green)
mcs_colors = {0: '#E74C3C', 7: '#E67E22', 13: '#2ECC71'}
mcs_labels = {0: 'Edge (MCS 0)', 7: 'Mid (MCS 7)', 13: 'Peak (MCS 13)'}

for ap in st.session_state.aps:
    # 1. Calculate dynamic radii based on MCS and SNR
    mcs_data = calculate_mcs_radii(
        ap["lat"], ap["lon"], global_freq, 
        ap["tx_power"], ap["antenna_gain"], 
        cpe_gain, cpe_nf, ap.get("channel_bw", 80)
    )
    
    # 2. Draw Coverage Circles
    for mcs_level in [0, 7, 13]:
        data = mcs_data[mcs_level]
        tooltip_text = f"{ap['name']} - {mcs_labels[mcs_level]}: {data['mod']} @ {data['capacity']} Mbps ({data['radius_m']/1000:.2f} km)"
        
        folium.Circle(
            location=[ap["lat"], ap["lon"]],
            radius=data['radius_m'],
            color=mcs_colors[mcs_level],
            weight=2,
            fill=False,
            dash_array='5, 5',
            tooltip=tooltip_text
        ).add_to(m)

    folium.Marker(
        [ap["lat"], ap["lon"]],
        popup=f"{ap['name']} ({global_freq}GHz)",
        tooltip=ap["name"],
        icon=folium.Icon(color="black", icon="wifi", prefix="fa")
    ).add_to(m)
    
    # Draw sectors using the MCS 0 (Edge) radius as the visual boundary
    start_angle = 0 
    visual_radius_m = mcs_data[0]['radius_m']
    sorted_sectors = sorted(ap.get("sectors", []), key=lambda x: x["id"])
    
    for idx, sector in enumerate(sorted_sectors):
        end_angle = start_angle + ap["beam_width"]
        polygon_points = get_sector_polygon(ap["lat"], ap["lon"], visual_radius_m, start_angle, end_angle)
        
        ch_num = sector["channel"]
        sec_color = channel_colors.get(ch_num, '#888888')
        
        folium.Polygon(
            locations=polygon_points,
            color=sec_color,
            weight=1,
            fill=True,
            fill_color=sec_color,
            fill_opacity=0.3,
            tooltip=f"{ap['name']} - Sector {sector['id']} (Ch: {ch_num})"
        ).add_to(m)
        
        start_angle = end_angle

map_data = st_folium(m, width=800, height=600)

# --- 4. Handle Map Clicks ---
if map_data and map_data.get("last_clicked"):
    clicked_lat = map_data["last_clicked"]["lat"]
    clicked_lon = map_data["last_clicked"]["lng"]
    
    current_click = (clicked_lat, clicked_lon)
    if st.session_state.last_clicked != current_click:
        st.session_state.last_clicked = current_click
        add_ap(clicked_lat, clicked_lon)
        st.rerun()
