# test_qdrant.py
from qdrant_client import QdrantClient
q = QdrantClient(host="localhost", port=6333)
print(q.get_locks())  # simple GET pour valider la connexion