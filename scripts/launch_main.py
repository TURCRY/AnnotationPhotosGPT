import subprocess
import os

# Chemin vers le script principal Streamlit
MAIN_SCRIPT = os.path.join("app", "main.py")

# Lancement de l'application avec Streamlit
subprocess.run(["streamlit", "run", MAIN_SCRIPT])
