import streamlit as st
from streamlit_wavesurfer import wavesurfer

st.title("🎧 Test composant WaveSurfer")

audio_url = "http://127.0.0.1:5000/audio/audio_compatible.wav"  # ← Serveur audio en local

t_audio = wavesurfer(
    audio_url=audio_url,
    height=120,
    start_sec=0,
    key="test-audio"
)

if t_audio is not None:
    st.success(f"📍 Temps cliqué : {t_audio:.2f} s")
