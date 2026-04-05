import os
import re
import json
import unicodedata
import socket
import struct
from flask import Flask, request, jsonify
from gpt4all import GPT4All

# === Configuration ===
NOM_MODELE = "Mistral_7B"
DOSSIER_MODELES = "C:/GPT4All_Models"
CHEMIN_MODELE = os.path.join(DOSSIER_MODELES, NOM_MODELE, f"{NOM_MODELE}.gguf")

PARAMETRES_PAR_DEFAUT = {
    "temperature": 0.7,
    "top_p": 0.9,
    "top_k": 40,
    "repeat_penalty": 1.1,
    "max_tokens": 200,
    "system": "Vous êtes un assistant juridique.",
    "web_search": False,
    "rag_files": [],
    "project_id": "default"
}

CLE_API_ATTENDUE = "hy^wQ#4d3HpnEl4x1Mg&"

# === Flask ===
app = Flask(__name__)

# === LLM ===
print(f"✅ Chargement du modèle : {NOM_MODELE}")
print(f"📄 Fichier : {CHEMIN_MODELE}")
llm = GPT4All(model_path=CHEMIN_MODELE, model_name=NOM_MODELE)
print("🕒 Modèle chargé.")
print("🧠 LLM prêt.")

# === Nettoyage Unicode ===
def nettoyer_prompt(prompt: str) -> str:
    prompt = re.sub(r'[\ud800-\udfff]', '', prompt)
    prompt = unicodedata.normalize("NFKC", prompt).encode("utf-8", "ignore").decode("utf-8")
    return prompt

# === Wake-on-LAN ===
def send_magic_packet(mac: str):
    mac = mac.replace("-", "").replace(":", "")
    if len(mac) != 12:
        raise ValueError("MAC address must be 12 hex digits")
    data = b"FF" * 6 + (mac.encode() * 16)
    send_data = b""
    for i in range(0, len(data), 2):
        send_data += struct.pack("B", int(data[i:i+2], 16))
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.sendto(send_data, ("<broadcast>", 9))

# === Routes ===
@app.route("/ping")
def ping():
    return jsonify({"status": "ok", "model": NOM_MODELE, "port": 5050})

@app.route("/annoter", methods=["POST"])
def annoter():
    print("\n=== /annoter appelé ===")
    try:
        print("Headers :", dict(request.headers))
        raw = request.data
        print("Raw data :", raw)
        data = request.get_json(force=True)
        print("Payload :", json.dumps(data, indent=2, ensure_ascii=False))

        if request.headers.get("X-Api-Key") != CLE_API_ATTENDUE:
            return jsonify({"error": "Clé API invalide."}), 403

        # Lecture et nettoyage
        prompt = nettoyer_prompt(data.get("prompt", ""))
        temperature = float(data.get("temperature", PARAMETRES_PAR_DEFAUT["temperature"]))
        top_p = float(data.get("top_p", PARAMETRES_PAR_DEFAUT["top_p"]))
        top_k = int(data.get("top_k", PARAMETRES_PAR_DEFAUT["top_k"]))
        repeat_penalty = float(data.get("repeat_penalty", PARAMETRES_PAR_DEFAUT["repeat_penalty"]))
        max_tokens = int(data.get("max_tokens", PARAMETRES_PAR_DEFAUT["max_tokens"]))
        system = nettoyer_prompt(data.get("system", PARAMETRES_PAR_DEFAUT["system"]))
        web_search = bool(data.get("web_search", False))
        rag_files = data.get("rag_files", [])
        project_id = data.get("project_id", "default")

        # Construction du prompt
        full_prompt = f"### System:\n{system}\n\n### User:\n{prompt}\n\n### Assistant:"

        # Exécution
        result = llm(
            full_prompt,
            temperature=temperature,
            top_p=top_p,
            top_k=top_k,
            repeat_penalty=repeat_penalty,
            max_tokens=max_tokens
        )

        return jsonify({"response": result})

    except Exception as e:
        print(f"❌ ERREUR /annoter : {e}")
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(debug=False, host="0.0.0.0", port=5050)
