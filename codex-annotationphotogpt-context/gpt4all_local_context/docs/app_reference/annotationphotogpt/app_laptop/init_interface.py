
import streamlit as st
import json
from pathlib import Path

INFOS_PROJET_PATH = "data/infos_projet.json"

def init_project_interface():
    st.title("⚙️ Paramétrage du projet")

    st.markdown("""Ce panneau vous permet de sélectionner les fichiers nécessaires et de définir les paramètres du projet en cours.""")

    # Chargement éventuel des données existantes
    valeurs = {
        "audio": "",
        "photos": "",
        "transcription": "",
        "contexte": "",
        "lib_av": 30,
        "lib_ap": 15,
        "com_av": 120,
        "com_ap": 120,
        "modele": "gpt-4-turbo",
        "temperature": 0.4
    }

    if Path(INFOS_PROJET_PATH).exists():
        try:
            with open(INFOS_PROJET_PATH, "r", encoding="utf-8") as f:
                valeurs.update(json.load(f))
        except Exception as e:
            st.warning(f"Erreur lors du chargement de la configuration précédente : {e}")

    with st.form("formulaire_projet"):
        audio_path = st.text_input("Chemin du fichier audio (.wav)", value=valeurs["audio"])
        photos_csv_path = st.text_input("Chemin du fichier CSV des photos", value=valeurs["photos"])
        transcription_csv_path = st.text_input("Chemin du fichier CSV de transcription", value=valeurs["transcription"])
        contexte_general = st.text_area("Contexte général", value=valeurs["contexte"])

        st.markdown("### Réglage des plages par défaut utilisées pour le GPT")
        col1, col2 = st.columns(2)
        with col1:
            lib_av = st.number_input("Libellé : secondes avant", min_value=0, max_value=600, value=valeurs["lib_av"])
            com_av = st.number_input("Commentaire : secondes avant", min_value=0, max_value=600, value=valeurs["com_av"])
        with col2:
            lib_ap = st.number_input("Libellé : secondes après", min_value=0, max_value=600, value=valeurs["lib_ap"])
            com_ap = st.number_input("Commentaire : secondes après", min_value=0, max_value=600, value=valeurs["com_ap"])

        modele = st.selectbox("Modèle OpenAI", options=["gpt-4-turbo", "gpt-3.5-turbo"], index=0)
        temperature = st.slider("Température", min_value=0.0, max_value=1.0, value=valeurs["temperature"], step=0.1)

        submitted = st.form_submit_button("Valider les chemins et paramètres")

        if submitted:
            try:
                infos = {
                    "audio": audio_path,
                    "photos": photos_csv_path,
                    "transcription": transcription_csv_path,
                    "contexte": contexte_general,
                    "lib_av": lib_av,
                    "lib_ap": lib_ap,
                    "com_av": com_av,
                    "com_ap": com_ap,
                    "modele": modele,
                    "temperature": temperature
                }
                Path("data").mkdir(exist_ok=True)
                with open(INFOS_PROJET_PATH, "w", encoding="utf-8") as f:
                    json.dump(infos, f, ensure_ascii=False, indent=2)
                st.success("Paramètres enregistrés avec succès.")
            except Exception as e:
                st.error(f"Erreur lors de l'enregistrement : {e}")
