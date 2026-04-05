from flask import Blueprint, request, jsonify
from utils.modele_loader import get_model

gpt4all_blueprint = Blueprint("gpt4all", __name__)
model = get_model()

API_KEY = "MA_CLE_API_SECRET"

@gpt4all_blueprint.route("/annoter", methods=["POST"])
def annoter():
    if request.headers.get("x-api-key") != API_KEY:
        return jsonify({"error": "Clé API invalide"}), 403

    data = request.get_json()
    transcription = data.get("transcription", "")
    mission = data.get("mission", "")
    photo = data.get("photo", "")

    prompt = f"""Tu es un expert du bâtiment.
Photo : {photo}
Mission : {mission}
Transcription : {transcription}
Réponds avec :
Libellé : ...
Commentaire : ..."""

    with model:
        reponse = model.generate(prompt, max_tokens=300)

    lignes = reponse.strip().splitlines()
    libelle, commentaire = "", ""
    for ligne in lignes:
        if ligne.lower().startswith("libellé"):
            libelle = ligne.split(":", 1)[-1].strip()
        elif ligne.lower().startswith("commentaire"):
            commentaire = ligne.split(":", 1)[-1].strip()

    return jsonify({"libelle": libelle, "commentaire": commentaire})
