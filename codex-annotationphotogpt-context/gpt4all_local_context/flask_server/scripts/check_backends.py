from chromadb import HttpClient
from qdrant_client import QdrantClient

c = HttpClient(host="localhost", port=8800)
print("Chroma OK:", c.heartbeat())

q = QdrantClient(host="localhost", port=6333)
print("Qdrant OK, collections:", q.get_collections())
