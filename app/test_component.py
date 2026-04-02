import streamlit as st
from wavesurfer_component import audio_component_custom  # ✅ bon import

st.title("🧪 Test composant renommé")

audio_url = "http://127.0.0.1:5000/audio/audio_compatible.wav"

retour = audio_component_custom(  # ✅ bon appel
    audio_url=audio_url,
    start=0,
    duration=10,
    key="wave_test"
)

st.write("⏱️ Retour =", retour)
