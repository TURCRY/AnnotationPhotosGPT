
import os
import csv
import re
import docx
from tkinter import Tk
from tkinter.filedialog import askopenfilename
from datetime import timedelta

def choisir_fichier_docx():
    Tk().withdraw()
    return askopenfilename(title="Sélectionner un fichier Word", filetypes=[("Word files", "*.docx")])

def convertir_temps(temps_str):
    if temps_str.count(":") == 1:
        minutes, secondes = map(int, temps_str.split(":"))
        return f"00:{minutes:02d}:{secondes:02d}"
    elif temps_str.count(":") == 2:
        heures, minutes, secondes = map(int, temps_str.split(":"))
        return f"{heures:02d}:{minutes:02d}:{secondes:02d}"
    else:
        return "00:00:00"

def nettoyer_texte(texte):
    # Supprime les tirets, égalités ou préfixes parasites au début
    return re.sub(r"^[-=–\s]*", "", texte).strip()

def extraire_blocs_transcription(doc):
    blocs = []
    locuteur, horodatage, texte = None, None, []
    debut_detecte = False

    for para in doc.paragraphs:
        texte_para = para.text.strip()

        # Ignorer les lignes vides ou non pertinentes
        if not texte_para:
            continue

        if re.match(r"^Speaker \d+\s+\d{1,2}:\d{2}(?::\d{2})?$", texte_para):
            debut_detecte = True
            if locuteur and horodatage and texte:
                blocs.append((horodatage, locuteur, " ".join(texte).strip()))
                texte = []
            match = re.match(r"^(Speaker \d+)\s+(\d{1,2}:\d{2}(?::\d{2})?)$", texte_para)
            if match:
                locuteur = match.group(1)
                horodatage = convertir_temps(match.group(2))
        elif debut_detecte:
            texte.append(nettoyer_texte(texte_para))

    if locuteur and horodatage and texte:
        blocs.append((horodatage, locuteur, " ".join(texte).strip()))
    return blocs

def enregistrer_csv(blocs, fichier_sortie):
    with open(fichier_sortie, mode='w', encoding='utf-8-sig', newline='') as f:
        writer = csv.writer(f, delimiter=';')
        writer.writerow(['horodatage', 'locuteur', 'texte'])
        for horodatage, locuteur, texte in blocs:
            writer.writerow([horodatage, locuteur, texte])

def main():
    fichier_docx = choisir_fichier_docx()
    if not fichier_docx:
        print("Aucun fichier sélectionné.")
        return

    print(f"Traitement de : {fichier_docx}")
    doc = docx.Document(fichier_docx)
    blocs = extraire_blocs_transcription(doc)

    fichier_csv = os.path.splitext(fichier_docx)[0] + ".csv"
    enregistrer_csv(blocs, fichier_csv)

    print(f"Fichier CSV généré : {fichier_csv}")

if __name__ == "__main__":
    main()
