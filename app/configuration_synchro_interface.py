import streamlit as st
import json
import os

from utils import sauvegarder_infos_projet

def config_synchro_interface():
    st.title("⚙️ Configuration de la synchronisation")

    with open(os.path.join("data", "infos_projet.json"), "r", encoding="utf-8") as f:
        infos = json.load(f)

    st.subheader("🔢 Paramètres de départ")

    photo_depart = st.number_input("📸 Photo de départ", min_value=1, value=infos.get("photo_depart", 1))
    audio_depart = st.number_input("🎧 Position audio de départ (en secondes)", min_value=0, value=infos.get("audio_depart", 0))
    retour_arriere = st.number_input("⏪ Durée de retour arrière (s)", min_value=1, value=infos.get("retour_arriere", 10))

    if st.button("💾 Enregistrer les paramètres"):
        infos["photo_depart"] = photo_depart
        infos["audio_depart"] = audio_depart
        infos["retour_arriere"] = retour_arriere
        sauvegarder_infos_projet(infos)
        st.success("✅ Paramètres enregistrés.")
