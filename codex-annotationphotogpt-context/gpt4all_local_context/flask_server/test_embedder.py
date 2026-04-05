# test_embedder.py (à lancer une fois)
from helpers_embed import load_embedder
m = load_embedder("Nomic_Embed")
print("TYPE:", type(m), "HAS_ENCODE:", hasattr(m, "encode"))
print("LEN:", len(m.encode(["Bonjour le monde"], normalize_embeddings=True)[0]))
