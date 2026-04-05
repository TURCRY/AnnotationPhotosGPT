from helper_paths import chroma_client

print("chroma_client =", chroma_client)
if chroma_client:
    try:
        print("heartbeat:", chroma_client.heartbeat())
        coll = chroma_client.get_or_create_collection("test_flask_client")
        print("collection OK:", coll.name)
    except Exception as e:
        import traceback
        print("EXCEPTION:")
        traceback.print_exc()