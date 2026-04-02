import streamlit as st
from PIL import Image
import os
from datetime import timedelta


def afficher_photo(photo_row, dossier_photos=None, max_width=400):
    """
    Affiche une photo à partir d’une ligne de DataFrame.
    :param photo_row: ligne contenant au moins 'nom_fichier_image' et potentiellement 'dossier_reduit'
    :param dossier_photos: chemin alternatif si non présent dans le CSV
    :param max_width: taille max d’affichage
    """
    nom_fichier = photo_row.get("nom_fichier_image")
    dossier = photo_row.get("dossier_reduit") or dossier_photos
    if not nom_fichier or not dossier:
        st.warning("Photo introuvable (fichier ou dossier manquant).")
        return

    chemin_photo = os.path.join(dossier, nom_fichier)
    if os.path.exists(chemin_photo):
        st.image(Image.open(chemin_photo), use_column_width=False, width=max_width)
    else:
        st.error(f"Fichier image non trouvé : {chemin_photo}")


def convertir_str_en_timedelta(duree_str):
    """
    Convertit une chaîne 'HH:MM:SS' ou 'MM:SS' en timedelta.
    """
    try:
        parts = duree_str.split(":")
        if len(parts) == 3:
            h, m, s = map(int, parts)
        elif len(parts) == 2:
            h = 0
            m, s = map(int, parts)
        else:
            return timedelta(seconds=int(duree_str))
        return timedelta(hours=h, minutes=m, seconds=s)
    except Exception:
        return timedelta(0)
