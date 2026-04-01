import streamlit as st
import folium
from streamlit_folium import st_folium
import math

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
    st.session_state.aps = []
if 'ap_counter' not in st.session_state:
    st.session_state.ap_counter = 1
if 'last_clicked' not in st.session_state:
    st.session_state.last_clicked = None

def add_ap(lat, lon, name=None):
    if name is None:
        name = f"AP {st.session_state.ap_counter}"
        st.session_state.ap_counter += 1
    
    # 120-degree reuse logic: calculate how many channels fit in 120 degrees
    beam_width = 60
    num_channels_reuse = max(1, int(120 / beam_width)) 
    
    # Assign channels sequentially, then repeat (e.g., for 60deg: Ch1, Ch2, Ch1, Ch2...)
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

# --- 2. Main UI & Sidebar ---
st.set_page_config(page_title="PtMP Planner", layout="wide")
st.title("📡 Point-to-Multipoint Planning App")

with st.sidebar:
    st.header("Global Settings")
    global_freq = st.selectbox("Frequency Band (GHz)", options=[5, 26, 60], index=1)
    
    # NEW: Global CPE Parameters
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
            
            current_sectors = ap.get("sectors", [])
            if new_num_sec > len(current_sectors):
                # Apply reuse logic to newly appended sectors if the user increases sector count
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
                new_h != ap["height"] or new_tx != ap["tx_power"] or new_gain != ap["antenna_gain"] or
                new_num_sec != ap["num_sectors"] or new_bw != ap["beam_width"] or updated_sectors != ap["sectors"]):
                
                st.session_state.aps[i].update({
                    "name": new_name, "lat": new_lat, "lon": new_lon,
                    "height": new_h, "tx_power": new_tx, "antenna_gain": new_gain,
                    "num_sectors": new_num_sec, "beam_width": new_bw, "sectors": updated_sectors
                })
                st.rerun()

# --- 3. Map Generation ---
start_loc = [st.session_state.aps[0]["lat"], st.session_state.aps[0]["lon"]] if st.session_state.aps else [32.1750, 34.9069]
m = folium.Map(location=start_loc, zoom_start=13)

# Dictionary mapping Channel Numbers to specific hex colors
channel_colors = {
    1: '#FF3333', # Red
    2: '#3357FF', # Blue
    3: '#33FF57', # Green
    4: '#F5FF33', # Yellow
    5: '#FF33F5', # Pink
    6: '#33FFF5', # Cyan
    7: '#FFA533', # Orange
    8: '#A533FF', # Purple
}

for ap in st.session_state.aps:
    folium.Marker(
        [ap["lat"], ap["lon"]],
        popup=f"{ap['name']} ({global_freq}GHz)",
        tooltip=ap["name"],
        icon=folium.Icon(color="black", icon="wifi", prefix="fa")
    ).add_to(m)
    
    start_angle = 0 
    visual_radius_m = 800 
    
    for idx, sector in enumerate(ap["sectors"]):
        end_angle = start_angle + ap["beam_width"]
        polygon_points = get_sector_polygon(ap["lat"], ap["lon"], visual_radius_m, start_angle, end_angle)
        
        # Determine color based on the channel (default to gray if channel > 8)
        ch_num = sector["channel"]
        sec_color = channel_colors.get(ch_num, '#888888')
        
        folium.Polygon(
            locations=polygon_points,
            color=sec_color,
            fill=True,
            fill_color=sec_color,
            fill_opacity=0.4,
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
