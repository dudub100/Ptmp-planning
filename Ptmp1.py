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
from fpdf import FPDF
from datetime import datetime

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

# --- Export Generators (KML & PDF) ---
def hex_to_kml_color(hex_str, opacity="7f"):
    h = hex_str.lstrip('#')
    return f"{opacity}{h[4:6]}{h[2:4]}{h[0:2]}"

def generate_kml():
    kml = ['<?xml version="1.0" encoding="UTF-8"?>', '<kml xmlns="http://www.opengis.net/kml/2.2">', '<Document>', '<name>PtMP Network Plan</name>']
    
    # Map AP names to their heights for correct 3D link generation
    ap_heights = {ap["name"]: ap["height"] for ap in st.session_state.aps}
    
    for ap in st.session_state.aps:
        kml.append(f'<Placemark><name>{ap["name"]}</name><Point><extrude>1</extrude><altitudeMode>relativeToGround</altitudeMode><coordinates>{ap["lon"]},{ap["lat"]},{ap["height"]}</coordinates></Point></Placemark>')
        mcs_data = calculate_all_mcs_radii(ap["lat"], ap["lon"], st.session_state.glob_freq, ap["tx_power"], ap["antenna_gain"], st.session_state.glob_cpe_gain, st.session_state.glob_cpe_nf, ap.get("channel_bw", 80), st.session_state.glob_avail)
        start_angle = ap.get("azimuth", 0) 
        for sector in sorted(ap.get("sectors", []), key=lambda x: x["id"]):
            end_angle = start_angle + ap["beam_width"]
            for mcs_level in range(12):
                if mcs_level < st.session_state.glob_min_mcs: continue
                poly_pts = get_sector_polygon(ap["lat"], ap["lon"], mcs_data[mcs_level]['radius_m'], start_angle, end_angle)
                coords_str = " ".join([f"{lon},{lat},0" for lat, lon in poly_pts])
                kml_color = hex_to_kml_color(MCS_COLORS[mcs_level], "40") 
                kml.append(f"""
                <Placemark><name>{ap["name"]} Sec {sector["id"]} MCS {mcs_level}</name>
                <Style><PolyStyle><color>{kml_color}</color></PolyStyle><LineStyle><width>0</width></LineStyle></Style>
                <Polygon><altitudeMode>clampToGround</altitudeMode><outerBoundaryIs><LinearRing><coordinates>{coords_str}</coordinates></LinearRing></outerBoundaryIs></Polygon></Placemark>
                """)
            start_angle = end_angle

    for cpe in st.session_state.cpes:
        cpe_color = hex_to_kml_color(cpe.get("color", "#0000FF"), "ff")
        kml.append(f"""
        <Placemark><name>{cpe["name"]} ({cpe.get("mcs", "Unassigned")})</name>
        <Style><IconStyle><color>{cpe_color}</color><scale>1.0</scale></IconStyle></Style>
        <Point><extrude>1</extrude><altitudeMode>relativeToGround</altitudeMode><coordinates>{cpe["lon"]},{cpe["lat"]},{cpe["height"]}</coordinates></Point></Placemark>
        """)
        
        if cpe.get("line") and isinstance(cpe["line"], list) and len(cpe["line"]) == 2:
            ap_name = cpe.get("ap")
            ap_h = ap_heights.get(ap_name, 10.0)
            cpe_h = cpe.get("height", 8.0)
            
            ap_lat, ap_lon = cpe['line'][0]
            cpe_lat, cpe_lon = cpe['line'][1]
            
            line_coords = f"{ap_lon},{ap_lat},{ap_h} {cpe_lon},{cpe_lat},{cpe_h}"
            
            kml.append(f"""
            <Placemark><name>Link: {cpe['name']} to {ap_name}</name>
            <Style><LineStyle><color>{cpe_color}</color><width>2</width></LineStyle></Style>
            <LineString><altitudeMode>relativeToGround</altitudeMode><coordinates>{line_coords}</coordinates></LineString></Placemark>
            """)
    
    kml.extend(['</Document>', '</kml>'])
    return "\n".join(kml)

def generate_pdf():
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", 'B', 16)
    pdf.cell(200, 10, txt=f"PtMP Network Planning Report - {datetime.now().strftime('%Y-%m-%d')}", ln=True, align='C')
    pdf.set_font("Arial", 'B', 12)
    pdf.cell(200, 10, txt="Base Stations (APs)", ln=True)
    pdf.set_font("Arial", '', 10)
    for ap in st.session_state.aps:
        pdf.cell(200, 8, txt=f"Name: {ap['name']} | Lat: {ap['lat']} | Lon: {ap['lon']} | Azimuth: {ap.get('azimuth', 0)}° | H: {ap['height']}m", ln=True)
        pdf.cell(200, 8, txt=f"    Tx: {ap['tx_power']}dBm | Gain: {ap['antenna_gain']}dBi | BW: {ap['channel_bw']}MHz | Sec: {ap['num_sectors']}x{ap['beam_width']}°", ln=True)
    pdf.ln(10)
    pdf.set_font("Arial", 'B', 12)
    pdf.cell(200, 10, txt="CPE Assignments & Link Status", ln=True)
    pdf.set_font("Arial", '', 10)
    for cpe in st.session_state.cpes:
        pdf.cell(200, 8, txt=f"CPE: {cpe['name']} | H: {cpe['height']}m | AP: {cpe.get('ap', 'None')} | Status: {cpe.get('mcs', 'N/A')}", ln=True)
    return pdf.output(dest='S').encode('latin-1')

# --- Spatial & Geometry Math ---
def haversine(lat1, lon1, lat2, lon2):
    R = 6371000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi, dlam = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlam/2)**2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))

def get_bearing(lat1, lon1, lat2, lon2):
    dLon = math.radians(lon2 - lon1)
    y = math.sin(dLon) * math.cos(math.radians(lat2))
    x = math.cos(math.radians(lat1)) * math.sin(math.radians(lat2)) - math.sin(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.cos(dLon)
    return (math.degrees(math.atan2(y, x)) + 360) % 360

def is_in_sector(bearing, ap):
    start_angle = ap.get("azimuth", 0)
    sorted_sectors = sorted(ap.get("sectors", []), key=lambda x: x["id"])
    for sector in sorted_sectors:
        end_angle = start_angle + ap["beam_width"]
        norm_start, norm_end = start_angle % 360, end_angle % 360
        if norm_start < norm_end:
            if norm_start <= bearing <= norm_end: return True
        else:
            if bearing >= norm_start or bearing <= norm_end: return True
        start_angle = end_angle
    return False

def get_elevation_profile(lats, lons):
    locations = "|".join([f"{lat},{lon}" for lat, lon in zip(lats, lons)])
    try:
        res = requests.get(f"https://api.opentopodata.org/v1/srtm90m?locations={locations}", timeout=5)
        if res.status_code == 200: return [r['elevation'] for r in res.json()['results']]
    except: pass
    try:
        payload = {"locations": [{"latitude": lat, "longitude": lon} for lat, lon in zip(lats, lons)]}
        res = requests.post("https://api.open-elevation.com/api/v1/lookup", json=payload, timeout=5)
        if res.status_code == 200: return [r['elevation'] for r in res.json()['results']]
    except: pass
    return [0] * len(lats)

def check_line_of_sight(lat1, lon1, h1, lat2, lon2, h2):
    num_points = 10
    lats = [lat1 + (lat2 - lat1) * i / (num_points - 1) for i in range(num_points)]
    lons = [lon1 + (lon2 - lon1) * i / (num_points - 1) for i in range(num_points)]
    elevations = get_elevation_profile(lats, lons)
    alt1 = elevations[0] + h1
    alt2 = elevations[-1] + h2
    for i in range(1, num_points - 1):
        wave_alt = alt1 + (alt2 - alt1) * i / (num_points - 1)
        if elevations[i] >= wave_alt: return False
    return True

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
        headers = {'User-Agent': 'PtMP-Planner/1.2'}
        response = requests.get(overpass_url, params={'data': overpass_query}, headers=headers)
        if response.status_code == 200: return response.json().get('elements', []), None
        return [], f"HTTP Error {response.status_code}"
    except Exception as e: return [], str(e)

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
            else: max_d_km = mid_d
                
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
DATA_FILE = "ap_data.json"
CPE_FILE = "cpe_data.json"

if 'glob_freq' not in st.session_state: st.session_state.glob_freq = 26
if 'glob_avail' not in st.session_state: st.session_state.glob_avail = 99.9
if 'glob_min_mcs' not in st.session_state: st.session_state.glob_min_mcs = 0
if 'glob_cpe_gain' not in st.session_state: st.session_state.glob_cpe_gain = 15.0
if 'glob_cpe_nf' not in st.session_state: st.session_state.glob_cpe_nf = 7.0
if 'marker_mode' not in st.session_state: st.session_state.marker_mode = "Drop AP"

def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            try: return json.load(f)
            except json.JSONDecodeError: return []
    return []

def load_cpes():
    if os.path.exists(CPE_FILE):
        with open(CPE_FILE, "r") as f:
            try: return json.load(f)
            except json.JSONDecodeError: return []
    return []

def save_data():
    with open(DATA_FILE, "w") as f: json.dump(st.session_state.aps, f)

def save_cpes():
    with open(CPE_FILE, "w") as f: json.dump(st.session_state.cpes, f)

if 'aps' not in st.session_state: st.session_state.aps = load_data()
if 'ap_counter' not in st.session_state: st.session_state.ap_counter = max([int(a['name'].split()[-1]) for a in st.session_state.aps if a['name'].split()[-1].isdigit()] + [0]) + 1
if 'cpes' not in st.session_state: st.session_state.cpes = load_cpes()
if 'cpe_counter' not in st.session_state: st.session_state.cpe_counter = max([int(c['name'].split()[-1]) for c in st.session_state.cpes if c['name'].split()[-1].isdigit()] + [0]) + 1

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
        "azimuth": 0,
        "sectors": [{"id": i+1, "channel": (i % 2) + 1} for i in range(6)]
    })

def add_cpe(lat, lon, height=8.0):
    st.session_state.cpes.append({
        "name": f"CPE {st.session_state.cpe_counter}", 
        "lat": round(float(lat), 6), "lon": round(float(lon), 6), 
        "height": height, "ap": "None", "mcs": "N/A", "color": "#0000FF", "line": None
    })
    st.session_state.cpe_counter += 1

# --- 2. Main UI & Sidebar ---
st.set_page_config(page_title="PtMP Planner Pro", layout="wide")
st.title("📡 Point-to-Multipoint Planning App")

with st.sidebar:
    st.info("🗺️ **Map Pin Tool Controls:**")
    st.session_state.marker_mode = st.radio(
        "Select what the 📍 Pin icon draws on the map:", 
        ["Drop AP", "Drop CPE"], 
        horizontal=True
    )
    st.divider()
    
    st.header("Global Settings")
    st.session_state.glob_freq = st.selectbox("Frequency Band (GHz)", options=[5, 26, 60], index=[5, 26, 60].index(st.session_state.glob_freq))
    st.session_state.glob_avail = st.number_input("Availability Target (%)", value=st.session_state.glob_avail, min_value=90.0, max_value=99.999, step=0.01, format="%.3f")
    st.session_state.glob_min_mcs = st.selectbox("Minimum Displayed MCS", options=list(range(12)), index=st.session_state.glob_min_mcs, format_func=lambda x: f"MCS {x} ({MCS_TABLE[x]['mod']})")
    
    col_cpe1, col_cpe2 = st.columns(2)
    st.session_state.glob_cpe_gain = col_cpe1.number_input("Global CPE Gain (dBi)", value=st.session_state.glob_cpe_gain, step=1.0)
    st.session_state.glob_cpe_nf = col_cpe2.number_input("CPE Noise Fig (dB)", value=st.session_state.glob_cpe_nf, step=0.5) 
    
    st.divider()

    st.header("CPE Discovery & Assignment")
    max_cpes = st.number_input("Max Buildings to Detect", value=64, min_value=1, step=10)
    
    col_btn1, col_btn2 = st.columns(2)
    if col_btn1.button("🏗️ Detect Buildings", use_container_width=True):
        polygons = [d for d in st.session_state.all_drawings if d["geometry"]["type"] in ["Polygon", "Rectangle"]]
        if not polygons: st.warning("Draw a polygon first.")
        else:
            with st.spinner("Detecting buildings..."):
                coords = polygons[-1]["geometry"]["coordinates"][0]
                poly_str = " ".join([f"{pt[1]} {pt[0]}" for pt in coords])
                lats, lons = [pt[1] for pt in coords], [pt[0] for pt in coords]
                buildings, error = fetch_buildings_from_osm_poly(poly_str)
                
                if error: st.error(f"Error: {error}")
                elif not buildings: st.warning("0 buildings found.")
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
                        
                    save_cpes()
                    st.session_state.map_center = [(min(lats) + max(lats)) / 2, (min(lons) + max(lons)) / 2]
                    st.session_state.map_zoom = 16
                    st.session_state.all_drawings = []
                    st.session_state.map_key += 1 
                    st.success(f"Added {added_count} buildings!")
                    st.rerun()

    # --- UPGRADED ASSIGNMENT ENGINE: Tracking Failure Reasons ---
    if col_btn2.button("🔗 Assign CPEs", type="primary", use_container_width=True):
        if not st.session_state.aps:
            st.error("No APs exist to assign CPEs to!")
        else:
            with st.spinner("Calculating Links & Checking Line of Sight..."):
                ap_radii_cache = {}
                for ap in st.session_state.aps:
                    ap_radii_cache[ap['name']] = calculate_all_mcs_radii(ap["lat"], ap["lon"], st.session_state.glob_freq, ap["tx_power"], ap["antenna_gain"], st.session_state.glob_cpe_gain, st.session_state.glob_cpe_nf, ap.get("channel_bw", 80), st.session_state.glob_avail)

                success_count = 0
                for i, cpe in enumerate(st.session_state.cpes):
                    valid_aps = []
                    in_range_any = False
                    
                    for ap in st.session_state.aps:
                        dist = haversine(ap['lat'], ap['lon'], cpe['lat'], cpe['lon'])
                        bearing = get_bearing(ap['lat'], ap['lon'], cpe['lat'], cpe['lon'])
                        max_radius = ap_radii_cache[ap['name']][0]['radius_m']
                        
                        if dist <= max_radius:
                            in_range_any = True
                            if is_in_sector(bearing, ap):
                                valid_aps.append({"ap": ap, "dist": dist})
                    
                    valid_aps.sort(key=lambda x: x["dist"])
                    
                    assigned = False
                    los_failed = False
                    
                    for candidate in valid_aps:
                        ap = candidate["ap"]
                        dist = candidate["dist"]
                        has_los = check_line_of_sight(ap['lat'], ap['lon'], ap['height'], cpe['lat'], cpe['lon'], cpe['height'])
                        
                        if has_los:
                            best_mcs = 0
                            capacity = 0
                            radii_data = ap_radii_cache[ap['name']]
                            for m_idx in range(11, -1, -1):
                                if dist <= radii_data[m_idx]['radius_m']:
                                    best_mcs = m_idx
                                    capacity = radii_data[m_idx]['capacity']
                                    break
                            
                            st.session_state.cpes[i].update({
                                "ap": ap['name'], "mcs": f"MCS {best_mcs} ({capacity}M)",
                                "color": MCS_COLORS[best_mcs], "line": [(ap['lat'], ap['lon']), (cpe['lat'], cpe['lon'])]
                            })
                            assigned = True
                            success_count += 1
                            break
                        else:
                            los_failed = True
                    
                    if not assigned:
                        # Determine specific failure reason
                        if los_failed:
                            fail_reason = "Blocked (No LoS)"
                        elif in_range_any:
                            fail_reason = "Outside Sector"
                        else:
                            fail_reason = "Out of Range"
                            
                        st.session_state.cpes[i].update({
                            "ap": "Failed", "mcs": fail_reason, "color": "#555555", "line": None
                        })
                
                save_cpes()
                st.session_state.map_key += 1 
                st.success(f"Assigned {success_count}/{len(st.session_state.cpes)} CPEs!")
                st.rerun()

    with st.expander("➕ Add CPE Manually"):
        m_cpe_lat = st.number_input("CPE Latitude", value=32.1750, format="%.6f", key="m_cpe_lat")
        m_cpe_lon = st.number_input("CPE Longitude", value=34.9069, format="%.6f", key="m_cpe_lon")
        m_cpe_h = st.number_input("CPE Height (m)", value=8.0, step=1.0, key="m_cpe_h")
        if st.button("Add CPE to Map"):
            add_cpe(m_cpe_lat, m_cpe_lon, m_cpe_h)
            save_cpes()
            st.session_state.map_center = [m_cpe_lat, m_cpe_lon]
            st.session_state.map_key += 1
            st.rerun()

    with st.expander(f"🏠 Managed CPEs ({len(st.session_state.cpes)})", expanded=False):
        if st.session_state.cpes:
            if st.button("🗑️ Clear All Buildings", type="primary", use_container_width=True):
                st.session_state.cpes, st.session_state.cpe_counter = [], 1
                save_cpes()
                st.session_state.map_key += 1
                st.rerun()
                
            safe_cpes = [{"name": c["name"], "lat": c["lat"], "lon": c["lon"], "height": c["height"], "ap": c.get("ap", "None"), "mcs": c.get("mcs", "N/A")} for c in st.session_state.cpes]
            
            edited_cpes = st.data_editor(
                safe_cpes,
                column_config={"name": "Name", "lat": st.column_config.NumberColumn("Lat", disabled=True, format="%.5f"), "lon": st.column_config.NumberColumn("Lon", disabled=True, format="%.5f"), "height": st.column_config.NumberColumn("H(m)"), "ap": st.column_config.TextColumn("Assigned AP", disabled=True), "mcs": st.column_config.TextColumn("Status/Capacity", disabled=True)},
                hide_index=True, num_rows="dynamic", key="cpe_editor"
            )
            
            if json.dumps(safe_cpes) != json.dumps(edited_cpes):
                new_cpes = []
                for edited in edited_cpes:
                    orig = next((c for c in st.session_state.cpes if c["lat"] == edited["lat"] and c["lon"] == edited["lon"]), None)
                    if orig:
                        orig["name"] = edited["name"]
                        orig["height"] = edited["height"]
                        new_cpes.append(orig)
                    else:
                        new_cpes.append({
                            "name": edited["name"], "lat": edited.get("lat", 0.0), "lon": edited.get("lon", 0.0), 
                            "height": edited.get("height", 8.0), "ap": "None", "mcs": "N/A", "color": "#0000FF", "line": None
                        })
                st.session_state.cpes = new_cpes
                save_cpes()
                st.rerun()
        else:
            st.info("No CPEs added yet.")
                
    st.divider()

    st.header("AP Management")
    with st.expander("Existing APs", expanded=False):
        for i, ap in enumerate(st.session_state.aps):
            if "channel_bw" not in ap: ap["channel_bw"] = 80
            st.markdown(f"**{ap['name']}**")
            st.session_state.aps[i]["name"] = st.text_input("Name", value=ap["name"], key=f"name_{i}", label_visibility="collapsed")
            st.session_state.aps[i]["azimuth"] = st.slider("Azimuth/Rotation (°)", min_value=0, max_value=359, value=int(ap.get("azimuth", 0)), step=1, key=f"azi_{i}")
            col1, col2 = st.columns(2)
            st.session_state.aps[i]["lat"] = col1.number_input("Lat", value=float(ap["lat"]), format="%.6f", key=f"lat_{i}")
            st.session_state.aps[i]["lon"] = col2.number_input("Lon", value=float(ap["lon"]), format="%.6f", key=f"lon_{i}")
            col_h, col_bw = st.columns(2)
            st.session_state.aps[i]["height"] = col_h.number_input("H(m)", value=float(ap["height"]), step=1.0, key=f"h_{i}")
            st.session_state.aps[i]["channel_bw"] = col_bw.selectbox("BW", options=[40, 80, 160, 320], index=[40, 80, 160, 320].index(ap["channel_bw"]), key=f"cbw_{i}")
            col3, col4 = st.columns(2)
            st.session_state.aps[i]["tx_power"] = col3.number_input("Tx(dBm)", value=float(ap["tx_power"]), step=1.0, key=f"tx_{i}")
            st.session_state.aps[i]["antenna_gain"] = col4.number_input("Gain", value=float(ap["antenna_gain"]), step=1.0, key=f"gain_{i}")
            st.session_state.aps[i]["num_sectors"] = col3.number_input("Sec", value=int(ap["num_sectors"]), min_value=1, step=1, key=f"numsec_{i}")
            st.session_state.aps[i]["beam_width"] = col4.number_input("BW(°)", value=int(ap["beam_width"]), min_value=1, step=1, key=f"bw_{i}")
            
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
                    new_ch = st.number_input(f"Ch {s_idx+1}", value=int(sector["channel"]), step=1, key=f"ch_{i}_{s_idx}")
                    updated_sectors.append({"id": s_idx + 1, "channel": new_ch})
            st.session_state.aps[i]["sectors"] = updated_sectors
            
            if st.button("🗑️ Delete", type="primary", key=f"del_{i}"):
                st.session_state.aps.pop(i)
                save_data()
                st.rerun()
            st.markdown("---")

    st.divider()
    st.header("💾 Save, Load & Export")
    
    export_dict = {
        "global_settings": {
            "freq": st.session_state.glob_freq, "avail": st.session_state.glob_avail,
            "min_mcs": st.session_state.glob_min_mcs, "cpe_gain": st.session_state.glob_cpe_gain, "cpe_nf": st.session_state.glob_cpe_nf
        },
        "aps": st.session_state.aps,
        "cpes": st.session_state.cpes
    }
    json_str = json.dumps(export_dict, indent=4)
    st.download_button(label="1️⃣ Save Planning to File (JSON)", data=json_str, file_name="ptmp_plan.json", mime="application/json", use_container_width=True)
    
    uploaded_file = st.file_uploader("2️⃣ Load Saved Planning", type=["json"])
    if uploaded_file is not None:
        if st.button("Load File", use_container_width=True):
            data = json.load(uploaded_file)
            st.session_state.glob_freq = data.get("global_settings", {}).get("freq", 26)
            st.session_state.glob_avail = data.get("global_settings", {}).get("avail", 99.9)
            st.session_state.glob_min_mcs = data.get("global_settings", {}).get("min_mcs", 0)
            st.session_state.glob_cpe_gain = data.get("global_settings", {}).get("cpe_gain", 15.0)
            st.session_state.glob_cpe_nf = data.get("global_settings", {}).get("cpe_nf", 7.0)
            st.session_state.aps = data.get("aps", [])
            st.session_state.cpes = data.get("cpes", [])
            
            ap_ids = [int(a['name'].split()[-1]) for a in st.session_state.aps if a['name'].split()[-1].isdigit()]
            st.session_state.ap_counter = max(ap_ids + [0]) + 1 if ap_ids else 1
            cpe_ids = [int(c['name'].split()[-1]) for c in st.session_state.cpes if c['name'].split()[-1].isdigit()]
            st.session_state.cpe_counter = max(cpe_ids + [0]) + 1 if cpe_ids else 1
            
            st.session_state.map_key += 1
            st.rerun()
            
    kml_data = generate_kml()
    st.download_button(label="3️⃣ Export Map to Google Earth (KML)", data=kml_data, file_name="ptmp_map.kml", mime="application/vnd.google-earth.kml+xml", use_container_width=True)

    pdf_data = generate_pdf()
    st.download_button(label="4️⃣ Download PDF Report", data=pdf_data, file_name="ptmp_report.pdf", mime="application/pdf", use_container_width=True)

# --- 3. Clean Map Generation ---
if st.session_state.map_center:
    start_loc, zoom = st.session_state.map_center, st.session_state.map_zoom
elif st.session_state.aps:
    start_loc, zoom = [st.session_state.aps[0]["lat"], st.session_state.aps[0]["lon"]], 13
else:
    start_loc, zoom = [32.1750, 34.9069], 13

m = folium.Map(location=start_loc, zoom_start=zoom, control_scale=True)

for drawing in st.session_state.all_drawings:
    if drawing["geometry"]["type"] in ["Polygon", "Rectangle"]:
        folium.GeoJson(drawing, style_function=lambda x: {'color': 'blue', 'fillOpacity': 0.2}).add_to(m)

Draw(export=False, draw_options={'polyline': False, 'polygon': True, 'rectangle': True, 'circle': False, 'marker': True, 'circlemarker': False}).add_to(m)

for ap in st.session_state.aps:
    mcs_data = calculate_all_mcs_radii(ap["lat"], ap["lon"], st.session_state.glob_freq, ap["tx_power"], ap["antenna_gain"], st.session_state.glob_cpe_gain, st.session_state.glob_cpe_nf, ap.get("channel_bw", 80), st.session_state.glob_avail)
    
    start_angle = ap.get("azimuth", 0) 
    
    for mcs_level in range(12):
        if mcs_level < st.session_state.glob_min_mcs: continue
        folium.Circle(location=[ap["lat"], ap["lon"]], radius=mcs_data[mcs_level]['radius_m'], color=MCS_COLORS[mcs_level], weight=1, fill=False, dash_array='3, 4').add_to(m)

    for idx, sector in enumerate(sorted(ap.get("sectors", []), key=lambda x: x["id"])):
        end_angle = start_angle + ap["beam_width"]
        for mcs_level in range(12):
            if mcs_level < st.session_state.glob_min_mcs: continue 
            polygon_points = get_sector_polygon(ap["lat"], ap["lon"], mcs_data[mcs_level]['radius_m'], start_angle, end_angle)
            folium.Polygon(locations=polygon_points, stroke=False, fill=True, fill_color=MCS_COLORS[mcs_level], fill_opacity=0.15, tooltip=f"{ap['name']} Sec {sector['id']} - MCS {mcs_level}").add_to(m)
        largest_polygon = get_sector_polygon(ap["lat"], ap["lon"], mcs_data[st.session_state.glob_min_mcs]['radius_m'], start_angle, end_angle)
        folium.PolyLine(locations=largest_polygon, color='black', weight=1, opacity=0.4).add_to(m)
        start_angle = end_angle

    folium.Marker([ap["lat"], ap["lon"]], popup=f"{ap['name']} ({st.session_state.glob_freq}GHz)", tooltip=ap["name"], icon=folium.Icon(color="black", icon="wifi", prefix="fa")).add_to(m)

# --- UPGRADED CPE MAP TOOLTIPS ---
for cpe in st.session_state.cpes:
    c_color = cpe.get("color", "#0000FF") 
    
    # Append the reason/status to the tooltip so it's visible on hover!
    tooltip_text = f"{cpe['name']} (H: {cpe['height']}m)"
    if cpe.get("mcs") and cpe.get("mcs") != "N/A":
        tooltip_text += f" | {cpe['mcs']}"
        
    folium.CircleMarker(
        location=[cpe["lat"], cpe["lon"]], radius=5, color="black", weight=1, fill=True, fill_color=c_color, fill_opacity=1.0, 
        tooltip=tooltip_text
    ).add_to(m)
    
    if cpe.get("line") and isinstance(cpe["line"], list) and len(cpe["line"]) == 2:
        folium.PolyLine(
            locations=cpe["line"], color=c_color, weight=2, dash_array='5, 5', opacity=0.8,
            tooltip=f"{cpe['name']} to {cpe['ap']} ({cpe['mcs']})"
        ).add_to(m)

legend_html = """
<div style="position: absolute; bottom: 50px; left: 10px; width: 140px; background-color: rgba(255, 255, 255, 0.95); border: 1px solid grey; z-index: 9999; font-size: 11px; padding: 6px; border-radius: 4px; color: black !important; font-family: Arial, sans-serif;">
<div style="font-weight: bold; margin-bottom: 4px; text-align: center;">Capacity</div>
"""
for m_idx in range(11, st.session_state.glob_min_mcs - 1, -1):
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
        if st.session_state.marker_mode == "Drop AP":
            add_ap(lat, lon)
        else:
            add_cpe(lat, lon, height=8.0)
            save_cpes()
            
        st.session_state.map_center = [lat, lon]
        st.session_state.map_zoom = 15
        st.session_state.all_drawings = []
        st.session_state.map_key += 1
        st.rerun()
