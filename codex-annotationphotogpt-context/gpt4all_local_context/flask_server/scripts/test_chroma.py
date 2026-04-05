# test_chroma.py (nouvelle version)
import os

HOST = os.getenv("CHROMA_HOST", "localhost")
PORT = int(os.getenv("CHROMA_PORT", "8800"))

try:
    from chromadb import HttpClient
except ImportError:
    raise SystemExit(
        "HttpClient introuvable. Installe d'abord le client REST : "
        "pip install -U chromadb-client"
    )

c = HttpClient(host=HOST, port=PORT)
print("Heartbeat:", c.heartbeat())  # doit imprimer un entier
