from docx import Document
import pandas as pd
from pathlib import Path
import re
import sys

def extract_entries(docx_path):
    doc = Document(docx_path)
    entries = []
    current_time = ""
    current_speaker = ""
    current_text = ""

    for para in doc.paragraphs:
        text = para.text.strip()
        if not text:
            continue

        # Détecte horodatage
        match_time = re.match(r"\[(\d{1,2}):(\d{2})\]", text)
        if match_time:
            if current_time and current_text:
                entries.append([current_time, current_speaker, current_text.strip()])
            current_time = f"00:{match_time.group(1).zfill(2)}:{match_time.group(2)}"
            current_text = ""
            continue

        # Détecte locuteur
        if text.endswith(":") and len(text.split()) <= 3:
            current_speaker = text[:-1].strip()
            continue

        # Sinon, c’est le texte
        if current_time:
            current_text += (" " + text)

    # Dernier bloc
    if current_time and current_text:
        entries.append([current_time, current_speaker, current_text.strip()])

    return entries

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python convert_transcription_docx.py fichier.docx")
        sys.exit(1)

    docx_path = Path(sys.argv[1])
    output_csv = docx_path.with_suffix(".csv")

    data = extract_entries(docx_path)
    df = pd.DataFrame(data, columns=["temps", "locuteur", "texte"])
    df.to_csv_