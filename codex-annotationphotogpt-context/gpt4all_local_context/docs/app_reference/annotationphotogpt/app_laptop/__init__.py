# app/__init__.py
import os
import streamlit as st
import streamlit.components.v1 as components

_COMPONENT_NAME = "wavesurfer_component"

# 1) URL dev (Vite: npm run dev)
DEV_URL = os.environ.get("WAVESURFER_DEV_URL")  # p.ex. http://localhost:5173

# 2) Builds “internes” au repo
APP_DIR = os.path.dirname(__file__)
INTERNAL_BUILD = os.path.join(APP_DIR, "frontend", "build")
INTERNAL_DIST  = os.path.join(APP_DIR, "frontend", "dist")

# 3) Chemin “externe” (ton WaveComponent)
EXTERNAL_PATH  = os.environ.get("WAVESURFER_COMPONENT_PATH")  # ...\frontend\dist ou ...\frontend\build

_component_func = None

candidates = []
if DEV_URL:
    candidates.append(("url", DEV_URL))
candidates += [
    ("path", INTERNAL_BUILD),
    ("path", INTERNAL_DIST),
    ("path", EXTERNAL_PATH if EXTERNAL_PATH else ""),
]

for kind, target in candidates:
    if kind == "url" and target:
        _component_func = components.declare_component(_COMPONENT_NAME, url=target)
        st.caption(f"🧩 Composant en mode DEV: {target}")
        break
    if kind == "path" and target and os.path.isdir(target):
        _component_func = components.declare_component(_COMPONENT_NAME, path=target)
        st.caption(f"🧩 Composant chargé depuis: {target}")
        break

if _component_func is None:
    def _component_func(**kwargs):
        st.info(
            "🧩 Composant Wavesurfer indisponible.\n"
            "→ Définis WAVESURFER_COMPONENT_PATH vers le dossier 'dist' (ou 'build'),\n"
            "ou lance Vite (npm run dev) et définis WAVESURFER_DEV_URL."
        )
        return None

def lecteur_audio(start_sec: float = 0.0):
    # API stable utilisée par le reste de l’app
    return _component_func(start_sec=float(start_sec), default=0.0)
