import streamlit as st
import folium
from streamlit_folium import st_folium
import math
import itur
import astropy.units as u
import json
import os

# --- Data Persistence Functions ---
DATA_FILE = "ap_data.json"

def load_data():
    """Loads AP data from a local JSON file if it exists."""
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return []
    return []

def save_data():
    """Saves the current AP session state to a local JSON file."""
    with open(DATA_FILE, "w") as f:
        json.dump(st.session_state.aps, f)

# --- Link Budget & ITU-R Math ---
@st.cache_data
def calculate_coverage_radii(lat, lon, f_GHz, tx_power, tx_gain, rx_gain, threshold):
    availabilities = [99.9, 99.95, 99.99]
    radii_results = {}
    
    f = f_GHz * u.GHz
    T = 15 * u.deg_C
    P = 1013 * u.hPa
    rho = 7.5 * u.g / u.m**3
    
    # Fixed gaseous attenuation call
    gamma_g_qty = itur.models.itu676.gamma_exact(f, P, rho, T)
    gamma_g = gamma_g_qty.value 
    
    for avail in availabilities:
        p = 100.0 - avail
        R_qty = itur.models.itu837.rainfall_rate(lat, lon, p)
        
        # Fixed rain attenuation call (removed .deg)
        gamma_r_qty = itur.models.itu838.rain_specific_attenuation(R_qty, f, 0, 0)
        gamma_r = gamma_r_qty.value
        
        min_d_km = 0.01
        max_d_km = 50.0  
        best_d_km = min_d_km
        
        for _ in range(40): 
            mid_d = (min_d_km + max_d_km) / 2.0
            fspl = 20 * math.log10(mid_d) + 20 * math.log10(f_GHz) + 92.45
            total_loss = fspl + (gamma_g * mid_d) + (gamma_r * mid_d)
            rx_power = tx_power + tx_gain + rx_gain - total_loss
            
            if rx_power >= threshold:
                min_d_km = mid_d
                best_d_km = mid_d
            else:
                max_d_km = mid_d
                
        radii_results[avail] = best_d_km * 1000.0 
        
    return radii_results

# --- Helper Function: Calculate Sector Polygon ---
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
        lat_out = math.asin(math.sin(lat_rad) * math.cos(radius_m / R) +
                            math.cos(lat_rad) * math.sin(radius_m / R) * math.cos(bearing))
        lon_out = lon_rad + math.atan2(math.sin(bearing) * math.sin(radius_m / R) * math.cos(lat_rad),
                                       math.cos(radius_m / R) - math.sin(lat_rad) * math.sin(lat_out))
        points.append((math.degrees(lat_out), math.degrees(lon_out)))
        
    points.append((lat, lon))
    return points

# --- 1. Session State Initialization ---
if 'aps' not in st.session_state:
    st.session_state.aps = load_data() # Load saved data on startup
if 'ap_counter' not in st.session_state:
    # Set counter based on highest existing AP number to avoid naming collisions
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
        "num_sectors": 6,
        "beam_width": beam_width,
        "sectors": default_sectors
    })
    save_data() # Auto-save after adding

# --- 2. Main UI & Sidebar ---
st.set_page_config(page_title="PtMP Planner", layout="wide")
st.title("📡 Point-to-Multipoint Planning App")

with st.sidebar:
    st.header("Global Settings")
    global_freq = st.selectbox("Frequency Band (GHz)", options=[5, 26, 60], index=1)
    
    col_cpe1, col_cpe2 = st.columns(2)
    cpe_gain = col_cpe1.number_input("CPE Gain (dBi)", value=15.0, step=1.0)
    cpe_threshold = col_cpe2.number_input("CPE Threshold (dBm)", value=-70.0, step=1.0)
    
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
        with st.expander(ap["name"]):
            new_name = st.text_input("Name", value=ap["name"], key=f"name_{i}")
            
            col1, col2 = st.columns(2)
            new_lat = col1.number_input("Latitude", value=ap["lat"], format="%.6f", key=f"lat_{i}")
            new_lon = col2.number_input("Longitude", value=ap["lon"], format="%.6f", key=f"lon_{i}")
            new_h = col1.number_input("Height (m)", value=ap["height"], step=1.0, key=f"h_{i}")
            
            st.markdown("**RF Parameters**")
            col3, col4 = st.columns(2)
            new_tx = col3.number_input("Tx Power (dBm)", value=ap["tx_power"], step=1.0, key=f"tx_{i}")
            new_gain = col4.number_input("Ant. Gain (dBi)", value=ap["antenna_gain"], step=1.0, key=f"gain_{i}")
            new_num_sec = col3.number_input("Sectors", value=ap["num_sectors"], min_value=1, step=1, key=f"numsec_{i}")
            new_bw = col4.number_input("Beam Width (°)", value=ap["beam_width"], min_value=1, step=1, key=f"bw_{i}")
            
            # ENSURE SECTORS ARE SEQUENTIAL BEFORE MODIFYING
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

            # Check for changes
            if (new_name != ap["name"] or new_lat != ap["lat"] or new_lon != ap["lon"] or 
                new_h != ap["height"] or new_tx != ap["tx_power"] or new_gain != ap["antenna_gain"] or
                new_num_sec != ap["num_sectors"] or new_bw != ap["beam_width"] or updated_sectors != ap["sectors"]):
                
                st.session_state.aps[i].update({
                    "name": new_name, "lat": new_lat, "lon": new_lon,
                    "height": new_h, "tx_power": new_tx, "antenna_gain": new_gain,
                    "num_sectors": new_num_sec, "beam_width": new_bw, "sectors": updated_sectors
                })
                save_data() # Auto-save on edit
                st.rerun()
            
            # DELETE BUTTON
            st.divider()
            if st.button("🗑️ Delete AP", type="primary", key=f"del_{i}"):
                st.session_state.aps.pop(i)
                save_data() # Auto-save after delete
                st.rerun()

# --- 3. Map Generation ---
start_loc = [st.session_state.aps[0]["lat"], st.session_state.aps[0]["lon"]] if st.session_state.aps else [32.1750, 34.9069]
m = folium.Map(location=start_loc, zoom_start=12)

channel_colors = {
    1: '#FF3333', 2: '#3357FF', 3: '#33FF57', 4: '#F5FF33', 
    5: '#FF33F5', 6: '#33FFF5', 7: '#FFA533', 8: '#A533FF',
}

avail_colors = {99.9: '#2ECC71', 99.95: '#E67E22', 99.99: '#E74C3C'}

for ap in st.session_state.aps:
    radii = calculate_coverage_radii(
        ap["lat"], ap["lon"], global_freq, 
        ap["tx_power"], ap["antenna_gain"], 
        cpe_gain, cpe_threshold
    )
    
    for avail in [99.9, 99.95, 99.99]:
        radius_m = radii[avail]
        folium.Circle(
            location=[ap["lat"], ap["lon"]],
            radius=radius_m,
            color=avail_colors[avail],
            weight=2,
            fill=False,
            dash_array='5, 5',
            tooltip=f"{ap['name']} - {avail}% Avail ({radius_m/1000:.2f} km)"
        ).add_to(m)

    folium.Marker(
        [ap["lat"], ap["lon"]],
        popup=f"{ap['name']} ({global_freq}GHz)",
        tooltip=ap["name"],
        icon=folium.Icon(color="black", icon="wifi", prefix="fa")
    ).add_to(m)
    
    start_angle = 0 
    visual_radius_m = radii[99.9]
    
    # Ensure sectors are sorted for drawing too
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
