import streamlit as st
from streamlit.runtime.scriptrunner.script_runner import RerunException

if st.button("Rerun"):
    # Lever l'exception avec un argument vide
    raise RerunException(rerun_data=None)

st.write("Test de rerun")
