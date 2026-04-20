import streamlit as st
import folium
from folium.plugins import Draw
from streamlit_folium import st_folium
import math
import itur
import astropy.units as u
import json
import os
import requests

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
CPE_FILE = "cpe_data.json"

def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            try: return json.load(f)
            except json.JSONDecodeError: return []
    return []

def save_data():
    with open(DATA_FILE, "w") as f:
        json.dump(st.session_state.aps, f)

def load_cpes():
    if os.path.exists(CPE_FILE):
        with open(CPE_FILE, "r") as f:
            try: return json.load(f)
            except json.JSONDecodeError: return []
    return []

def save_cpes():
    with open(CPE_FILE, "w") as f:
        json.dump(st.session_state.cpes, f)

# --- Helper & KML Generation ---
def get_distance(lat1, lon1, lat2, lon2):
    """Calculates geographical distance between two points."""
    R = 6378137 
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
    return R * (2 * math.atan2(math.sqrt(a), math.sqrt(1-a)))

def generate_kml():
    """Generates a strict, OGC-compliant 3D KML string."""
    kml = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<kml xmlns="http://www.opengis.net/kml/2.2">',
        '  <Document>',
        '    <name>PtMP Network Plan</name>',
        '    <description>Exported from PtMP Planner Pro</description>',
        
        # --- Define Styles properly at the Document level ---
        '    <Style id="ap_style">',
        '      <IconStyle><color>ff0000ff</color><scale>1.2</scale></IconStyle>',
        '      <LineStyle><color>ff0000ff</color><width>2</width></LineStyle>',
        '    </Style>',
        '    <Style id="cpe_style">',
        '      <IconStyle><color>ffff0000</color><scale>1.0</scale></IconStyle>',
        '      <LineStyle><color>ffff0000</color><width>2</width></LineStyle>',
        '    </Style>',
        '    <Style id="link_style">',
        '      <LineStyle><color>7f00ffff</color><width>2</width></LineStyle>',
        '    </Style>'
    ]

    # Add Access Points (APs)
    for ap in st.session_state.aps:
        kml.extend([
            '    <Placemark>',
            f'      <name>{ap["name"]}</name>',
            f'      <description>Tx Power: {ap["tx_power"]} dBm\nAntenna Gain: {ap["antenna_gain"]} dBi</description>',
            '      <styleUrl>#ap_style</styleUrl>',
            '      <Point>',
            '        <extrude>1</extrude>',
            '        <altitudeMode>relativeToGround</altitudeMode>',
            f'        <coordinates>{ap["lon"]},{ap["lat"]},{ap["height"]}</coordinates>',
            '      </Point>',
            '    </Placemark>'
        ])

    # Add Customer Premises Equipment (CPEs)
    for cpe in st.session_state.cpes:
        kml.extend([
            '    <Placemark>',
            f'      <name>{cpe["name"]}</name>',
            '      <styleUrl>#cpe_style</styleUrl>',
            '      <Point>',
            '        <extrude>1</extrude>',
            '        <altitudeMode>relativeToGround</altitudeMode>',
            f'        <coordinates>{cpe["lon"]},{cpe["lat"]},{cpe["height"]}</coordinates>',
            '      </Point>',
            '    </Placemark>'
        ])

    # Draw 3D Links from each CPE to the closest AP
    if st.session_state.aps and st.session_state.cpes:
        for cpe in st.session_state.cpes:
            closest_ap = min(st.session_state.aps, key=lambda ap: get_distance(cpe['lat'], cpe['lon'], ap['lat'], ap['lon']))
            
            kml.extend([
                '    <Placemark>',
                f'      <name>Link: {closest_ap["name"]} to {cpe["name"]}</name>',
                '      <styleUrl>#link_style</styleUrl>',
                '      <LineString>',
                '        <extrude>0</extrude>',
                '        <altitudeMode>relativeToGround</altitudeMode>',
                f'        <coordinates>{closest_ap["lon"]},{closest_ap["lat"]},{closest_ap["height"]} {cpe["lon"]},{cpe["lat"]},{cpe["height"]}</coordinates>',
                '      </LineString>',
                '    </Placemark>'
            ])

    kml.extend([
        '  </Document>',
        '</kml>'
    ])
    
    return "\n".join(kml)

# --- Building Detection Function ---
def fetch_buildings_from_osm_poly(poly_str):
    overpass_url = "http://overpass-api.de/api/interpreter"
    overpass_query = f"""
    [out:json][timeout:25];
    (
      way["building"](poly:"{poly_str}");
      relation["building"](poly:"{poly_str}");
    );
    out center;
    """
    try:
        headers = {'User-Agent': 'PtMP-Planner/1.1'}
        response = requests.get(overpass_url, params={'data': overpass_query}, headers=headers)
        if response.status_code == 200:
            return response.json().get('elements', []), None
        else:
            return [], f"HTTP Error {response.status_code}"
    except Exception as e:
        return [], str(e)

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
                
        radii_results[mcs_index] = {"radius_m": best_d_km * 1000.0, "capacity": mcs_data["caps"].get(channel_bw, 0), "mod": mcs_data["mod"]}
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

# --- 1. Session State Initialization ---
if 'aps' not in st.session_state: st.session_state.aps = load_data() 
if 'ap_counter' not in st.session_state: st.session_state.ap_counter = len(st.session_state.aps) + 1 if st.session_state.aps else 1

if 'cpes' not in st.session_state: st.session_state.cpes = load_cpes()
if 'cpe_counter' not in st.session_state: st.session_state.cpe_counter = len(st.session_state.cpes) + 1 if st.session_state.cpes else 1

if 'all_drawings' not in st.session_state: st.session_state.all_drawings = []
if 'map_center' not in st.session_state: st.session_state.map_center = None
if 'map_zoom' not in st.session_state: st.session_state.map_zoom = 13
if 'map_key' not in st.session_state: st.session_state.map_key = 0

def add_ap(lat, lon):
    name = f"AP {st.session_state.ap_counter}"
    st.session_state.ap_counter += 1
    st.session_state.aps.append({
        "name": name, "lat": round(float(lat), 6), "lon": round(float(lon), 6), "height": 10.0,
        "tx_power": 23.0, "antenna_gain": 20.0, "channel_bw": 80, "num_sectors": 6, "beam_width": 60,
        "sectors": [{"id": i+1, "channel": (i % 2) + 1} for i in range(6)]
    })
    save_data()

def add_cpe(lat, lon, height=8.0):
    st.session_state.cpes.append({
        "name": f"CPE {st.session_state.cpe_counter}", 
        "lat": round(float(lat), 6), 
        "lon": round(float(lon), 6), 
        "height": height
    })
    st.session_state.cpe_counter += 1
    save_cpes()

# --- 2. Main UI & Sidebar ---
st.set_page_config(page_title="PtMP Planner Pro", layout="wide")
st.title("📡 Point-to-Multipoint Planning App")

with st.sidebar:
    st.download_button(
        label="🌍 Download 3D KML File",
        data=generate_kml(),
        file_name="ptmp_network_plan.kml",
        mime="application/vnd.google-earth.kml+xml",
        use_container_width=True
    )
    
    st.header("Global Settings")
    global_freq = st.selectbox("Frequency Band (GHz)", options=[5, 26, 60], index=1)
    availability_target = st.number_input("Availability Target (%)", value=99.9, min_value=90.0, max_value=99.999, step=0.01, format="%.3f")
    
    min_mcs_display = st.selectbox(
        "Minimum Displayed MCS", 
        options=list(range(12)), 
        index=0, 
        format_func=lambda x: f"MCS {x} ({MCS_TABLE[x]['mod']})"
    )
    
    col_cpe1, col_cpe2 = st.columns(2)
    cpe_gain = col_cpe1.number_input("Global CPE Gain (dBi)", value=15.0, step=1.0)
    cpe_nf = col_cpe2.number_input("CPE Noise Fig (dB)", value=7.0, step=0.5) 
    
    st.divider()

    st.header("CPE Discovery & Management")
    st.markdown("1. Use the **Polygon/Square Tool** to draw an area.\n2. Click the button below.")
    max_cpes = st.number_input("Max Buildings to Detect", value=64, min_value=1, step=10)
    
    if st.button("🏗️ Detect Buildings in Drawn Area", type="primary", use_container_width=True):
        polygons = [d for d in st.session_state.all_drawings if d["geometry"]["type"] in ["Polygon", "Rectangle"]]
        
        if not polygons:
            st.warning("Please draw a polygon or rectangle on the map first.")
        else:
            with st.spinner("Detecting buildings precisely inside your drawn shape..."):
                last_shape = polygons[-1]
                coords = last_shape["geometry"]["coordinates"][0]
                
                poly_str = " ".join([f"{pt[1]} {pt[0]}" for pt in coords])
                lats, lons = [pt[1] for pt in coords], [pt[0] for pt in coords]
                
                buildings, error = fetch_buildings_from_osm_poly(poly_str)
                
                if error:
                    st.error(f"Detection failed. Reason: {error}")
                elif not buildings:
                    st.warning("0 buildings found in this exact shape.")
                else:
                    added_count = 0
                    for bldg in buildings:
                        if added_count >= max_cpes: break
                        tags, center = bldg.get('tags', {}), bldg.get('center', {})
                        if not center: continue
                        
                        h = tags.get('height')
                        if h:
                            try: h = float(h.split()[0])
                            except: h = 8.0
                        elif tags.get('building:levels'):
                            try: h = float(tags.get('building:levels')) * 3.5
                            except: h = 8.0
                        else: h = 8.0
                            
                        add_cpe(center['lat'], center['lon'], h)
                        added_count += 1
                        
                    st.session_state.map_center = [(min(lats) + max(lats)) / 2, (min(lons) + max(lons)) / 2]
                    st.session_state.map_zoom = 16
                    st.session_state.all_drawings = []
                    st.session_state.map_key += 1 
                    
                    st.success(f"Successfully detected {added_count} buildings inside the polygon!")
                    st.rerun()

    with st.expander("➕ Add CPE Manually"):
        m_cpe_lat = st.number_input("CPE Latitude", value=32.1750, format="%.6f", key="m_cpe_lat")
        m_cpe_lon = st.number_input("CPE Longitude", value=34.9069, format="%.6f", key="m_cpe_lon")
        m_cpe_h = st.number_input("CPE Height (m)", value=8.0, step=1.0, key="m_cpe_h")
        if st.button("Add CPE to Map"):
            add_cpe(m_cpe_lat, m_cpe_lon, m_cpe_h)
            st.session_state.map_center = [m_cpe_lat, m_cpe_lon]
            st.session_state.map_key += 1
            st.rerun()

    with st.expander(f"🏠 Managed CPEs ({len(st.session_state.cpes)})", expanded=True):
        if st.session_state.cpes:
            if st.button("🗑️ Clear All Buildings", type="primary", use_container_width=True):
                st.session_state.cpes, st.session_state.cpe_counter = [], 1
                save_cpes()
                st.session_state.map_key += 1
                st.rerun()
                
            for i, cpe in enumerate(st.session_state.cpes):
                col_n, col_h, col_del = st.columns([4, 3, 2])
                new_n = col_n.text_input("Name", value=cpe["name"], key=f"c_n_{i}", label_visibility="collapsed")
                new_h = col_h.number_input("H (m)", value=float(cpe["height"]), key=f"c_h_{i}", label_visibility="collapsed")
                
                if new_n != cpe["name"] or new_h != cpe["height"]:
                    st.session_state.cpes[i]["name"] = new_n
                    st.session_state.cpes[i]["height"] = new_h
                    save_cpes()
                
                if col_del.button("🗑️", key=f"c_del_{i}"):
                    st.session_state.cpes.pop(i)
                    save_cpes()
                    st.rerun()
        else:
            st.info("No CPEs added yet.")
                
    st.divider()

    st.header("AP Management")
    st.markdown("To drop an AP on the map, click the **Marker tool** (📍) on the map toolbar, then click where you want it.")
            
    st.subheader("Existing APs")
    for i, ap in enumerate(st.session_state.aps):
        if "channel_bw" not in ap: ap["channel_bw"] = 80
        with st.expander(ap["name"]):
            st.session_state.aps[i]["name"] = st.text_input("Name", value=ap["name"], key=f"name_{i}")
            col1, col2 = st.columns(2)
            st.session_state.aps[i]["lat"] = col1.number_input("Latitude", value=float(ap["lat"]), format="%.6f", key=f"lat_{i}")
            st.session_state.aps[i]["lon"] = col2.number_input("Longitude", value=float(ap["lon"]), format="%.6f", key=f"lon_{i}")
            col_h, col_bw = st.columns(2)
            st.session_state.aps[i]["height"] = col_h.number_input("Height (m)", value=float(ap["height"]), step=1.0, key=f"h_{i}")
            st.session_state.aps[i]["channel_bw"] = col_bw.selectbox("Channel BW (MHz)", options=[40, 80, 160, 320], index=[40, 80, 160, 320].index(ap["channel_bw"]), key=f"cbw_{i}")
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
            
            updated_sectors = []
            sec_cols = st.columns(3)
            for s_idx, sector in enumerate(current_sectors):
                with sec_cols[s_idx % 3]:
                    new_ch = st.number_input(f"Sec {s_idx+1} Ch", value=int(sector["channel"]), step=1, key=f"ch_{i}_{s_idx}")
                    updated_sectors.append({"id": s_idx + 1, "channel": new_ch})
            st.session_state.aps[i]["sectors"] = updated_sectors
            
            if st.button("🗑️ Delete AP", type="primary", key=f"del_{i}"):
                st.session_state.aps.pop(i)
                save_data()
                st.rerun()
    save_data()

# --- 3. Clean Map Generation ---
if st.session_state.map_center:
    start_loc, zoom = st.session_state.map_center, st.session_state.map_zoom
elif st.session_state.aps:
    start_loc, zoom = [st.session_state.aps[0]["lat"], st.session_state.aps[0]["lon"]], 13
else:
    start_loc, zoom = [32.1750, 34.9069], 13

m = folium.Map(location=start_loc, zoom_start=zoom, control_scale=True)

Draw(
    export=False,
    draw_options={'polyline': False, 'polygon': True, 'rectangle': True, 'circle': False, 'marker': True, 'circlemarker': False}
).add_to(m)

for ap in st.session_state.aps:
    mcs_data = calculate_all_mcs_radii(ap["lat"], ap["lon"], global_freq, ap["tx_power"], ap["antenna_gain"], cpe_gain, cpe_nf, ap.get("channel_bw", 80), availability_target)
    for mcs_level in range(12):
        if mcs_level < min_mcs_display: continue
        folium.Circle(location=[ap["lat"], ap["lon"]], radius=mcs_data[mcs_level]['radius_m'], color=MCS_COLORS[mcs_level], weight=1, fill=False, dash_array='3, 4').add_to(m)

    start_angle = 0 
    for idx, sector in enumerate(sorted(ap.get("sectors", []), key=lambda x: x["id"])):
        end_angle = start_angle + ap["beam_width"]
        for mcs_level in range(12):
            if mcs_level < min_mcs_display: continue 
            polygon_points = get_sector_polygon(ap["lat"], ap["lon"], mcs_data[mcs_level]['radius_m'], start_angle, end_angle)
            folium.Polygon(locations=polygon_points, stroke=False, fill=True, fill_color=MCS_COLORS[mcs_level], fill_opacity=0.15, tooltip=f"{ap['name']} Sec {sector['id']} - MCS {mcs_level} ({mcs_data[mcs_level]['capacity']} Mbps)").add_to(m)
            
        largest_polygon = get_sector_polygon(ap["lat"], ap["lon"], mcs_data[min_mcs_display]['radius_m'], start_angle, end_angle)
        folium.PolyLine(locations=largest_polygon, color='black', weight=1, opacity=0.4).add_to(m)
        start_angle = end_angle

    folium.Marker([ap["lat"], ap["lon"]], popup=f"{ap['name']} ({global_freq}GHz)", tooltip=ap["name"], icon=folium.Icon(color="black", icon="wifi", prefix="fa")).add_to(m)

for cpe in st.session_state.cpes:
    folium.CircleMarker(location=[cpe["lat"], cpe["lon"]], radius=4, color="#0000FF", fill=True, fill_opacity=0.8, tooltip=f"{cpe['name']} (H: {cpe['height']}m)").add_to(m)

legend_html = """
<div style="position: absolute; bottom: 50px; left: 10px; width: 140px; background-color: rgba(255, 255, 255, 0.95); border: 1px solid grey; z-index: 9999; font-size: 11px; padding: 6px; border-radius: 4px; color: black !important; font-family: Arial, sans-serif;">
<div style="font-weight: bold; margin-bottom: 4px; text-align: center;">Capacity</div>
"""
for m_idx in range(11, min_mcs_display - 1, -1):
    legend_html += f"""<div style="margin-bottom: 2px; line-height: 14px; white-space: nowrap;"><i style="background:{MCS_COLORS[m_idx]}; width: 10px; height: 10px; float: left; margin-right: 5px; border: 1px solid #777; border-radius: 2px;"></i>MCS {m_idx} ({MCS_TABLE[m_idx]['mod']})</div>"""
legend_html += "</div>"
m.get_root().html.add_child(folium.Element(legend_html))

map_data = st_folium(m, width=1000, height=600, returned_objects=["all_drawings"], key=f"ptmp_map_{st.session_state.map_key}")

# --- 4. Handle Drawing Events ---
if map_data and map_data.get("all_drawings") is not None:
    current_drawings = map_data["all_drawings"]
    
    st.session_state.all_drawings = current_drawings
    
    new_point = next((d for d in current_drawings if d["geometry"]["type"] == "Point"), None)
    
    if new_point:
        lon, lat = new_point["geometry"]["coordinates"]
        add_ap(lat, lon)
        st.session_state.map_center = [lat, lon]
        st.session_state.map_zoom = 15
        st.session_state.all_drawings = []
        st.session_state.map_key += 1
        st.rerun()
