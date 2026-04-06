import streamlit as st
import folium
from streamlit_folium import st_folium

st.title("Map Test")

# Dead-simple map
m = folium.Map(location=[32.1750, 34.9069], zoom_start=13)

# Render it with zero extra settings
st_folium(m)

st.write("If you see the map above, the library works. If not, the installation is broken.")
