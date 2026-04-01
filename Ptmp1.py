import streamlit as st
import folium
from streamlit_folium import st_folium

# --- 1. Session State Initialization ---
# We use session state to remember APs across reruns when the user clicks or types
if 'aps' not in st.session_state:
    st.session_state.aps = []
if 'ap_counter' not in st.session_state:
    st.session_state.ap_counter = 1
if 'last_clicked' not in st.session_state:
    st.session_state.last_clicked = None

# Function to add a new AP
def add_ap(lat, lon, name=None):
    if name is None:
        name = f"AP {st.session_state.ap_counter}"
        st.session_state.ap_counter += 1
        
    st.session_state.aps.append({
        "name": name,
        "lat": lat,
        "lon": lon,
        "height": 10.0,       # Default height
        "bw": 20,             # Default Channel BW
        "channel": 1          # Default Channel Number
    })

# --- 2. Main UI & Sidebar ---
st.set_page_config(page_title="PtMP Planner", layout="wide")
st.title("📡 Point-to-Multipoint Planning App")

with st.sidebar:
    st.header("AP Management")
    
    # Manual AP Entry
    with st.expander("➕ Add AP Manually"):
        man_lat = st.number_input("Latitude", value=32.1750, format="%.6f")
        man_lon = st.number_input("Longitude", value=34.9069, format="%.6f")
        if st.button("Add to Map"):
            add_ap(man_lat, man_lon)
            st.rerun()
            
    st.divider()
    st.subheader("Existing APs")
    
    # List and Edit Existing APs
    for i, ap in enumerate(st.session_state.aps):
        # st.expander creates the clickable arrow
        with st.expander(ap["name"]):
            # We use dynamic keys based on the index 'i' so Streamlit can track each input independently
            new_name = st.text_input("Name", value=ap["name"], key=f"name_{i}")
            new_lat = st.number_input("Latitude", value=ap["lat"], format="%.6f", key=f"lat_{i}")
            new_lon = st.number_input("Longitude", value=ap["lon"], format="%.6f", key=f"lon_{i}")
            new_h = st.number_input("Height (m)", value=ap["height"], step=1.0, key=f"h_{i}")
            new_bw = st.selectbox("Channel BW (MHz)", options=[20, 40, 80, 160], index=[20, 40, 80, 160].index(ap["bw"]), key=f"bw_{i}")
            new_ch = st.number_input("Channel Number", value=ap["channel"], step=1, key=f"ch_{i}")
            
            # If the user changes any value, update the session state and rerun to reflect changes
            if (new_name != ap["name"] or new_lat != ap["lat"] or new_lon != ap["lon"] or 
                new_h != ap["height"] or new_bw != ap["bw"] or new_ch != ap["channel"]):
                
                st.session_state.aps[i].update({
                    "name": new_name, "lat": new_lat, "lon": new_lon,
                    "height": new_h, "bw": new_bw, "channel": new_ch
                })
                st.rerun()

# --- 3. Map Generation ---
# Center the map on the first AP, or use Kefar Sava coordinates as a default starting point
start_loc = [st.session_state.aps[0]["lat"], st.session_state.aps[0]["lon"]] if st.session_state.aps else [32.1750, 34.9069]
m = folium.Map(location=start_loc, zoom_start=13)

# Place markers for every AP in our session state
for ap in st.session_state.aps:
    folium.Marker(
        [ap["lat"], ap["lon"]],
        popup=ap["name"],
        tooltip=ap["name"],
        icon=folium.Icon(color="blue", icon="wifi", prefix="fa")
    ).add_to(m)

# Render the map and capture any user interactions (like clicks)
map_data = st_folium(m, width=800, height=600)

# --- 4. Handle Map Clicks ---
# If the user clicks the map, add an AP at that exact location
if map_data and map_data.get("last_clicked"):
    clicked_lat = map_data["last_clicked"]["lat"]
    clicked_lon = map_data["last_clicked"]["lng"]
    
    # We check against the last clicked coordinate to prevent adding duplicates from a single click event
    current_click = (clicked_lat, clicked_lon)
    if st.session_state.last_clicked != current_click:
        st.session_state.last_clicked = current_click
        add_ap(clicked_lat, clicked_lon)
        st.rerun()
