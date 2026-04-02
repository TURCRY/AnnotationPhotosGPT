import streamlit as st
import streamlit.components.v1 as components

def lecteur_audio_avec_retour_temps(start_sec=0):
    st.markdown("""
    <style>
    .ws-controls button {
        font-size: 1rem;
        padding: 0.4em 1em;
        margin: 0.2em;
    }
    .ws-controls {
        margin-top: 1em;
        margin-bottom: 1em;
    }
    </style>
    """, unsafe_allow_html=True)

    html_code = f"""
    <div id=\"wavesurfer-container\"></div>
    <div class=\"ws-controls\">
        <button onclick=\"handlePlay()\">▶️ Lecture / Pause</button>
        <button onclick=\"captureTime()\">📍 C’est ce moment-là</button>
        <button onclick=\"rejouer10sec()\">⏪ Réécouter 10 secondes avant</button>
    </div>
    <p id=\"current-time\">⏱ Temps: 0.00s</p>
    <script src=\"https://unpkg.com/wavesurfer.js\"></script>
    <script>
      var wavesurfer = WaveSurfer.create({{
        container: '#wavesurfer-container',
        waveColor: 'violet',
        progressColor: 'purple',
        height: 80
      }});

      var alreadyLoaded = false;

      function handlePlay() {{
        if (!alreadyLoaded) {{
          wavesurfer.load('http://127.0.0.1:8888/audio');
          wavesurfer.on('ready', function () {{
            wavesurfer.play();
          }});
          alreadyLoaded = true;
        }} else {{
          wavesurfer.playPause();
        }}
      }}

      function captureTime() {{
        var t = wavesurfer.getCurrentTime();
        window.parent.postMessage({{ type: "T_AUDIO", value: t.toFixed(2) }}, "*");
        wavesurfer.pause();
      }}

      function rejouer10sec() {{
        var t = wavesurfer.getCurrentTime();
        wavesurfer.seekTo(Math.max(0, (t - 10) / wavesurfer.getDuration()));
      }}

      wavesurfer.on('audioprocess', function () {{
        var t = wavesurfer.getCurrentTime();
        document.getElementById("current-time").innerText = "⏱ Temps: " + t.toFixed(2) + "s";
      }});

      // Écoute du message depuis le postMessage et injection dans le DOM
      window.addEventListener("message", (event) => {{
        if (event.data && event.data.type === "T_AUDIO") {{
          const t = event.data.value;
          console.log("📍 Capturé :", t);
          const retour = document.createElement("input");
          retour.type = "hidden";
          retour.id = "t_audio_value";
          retour.value = t;
          document.body.appendChild(retour);
        }}
      }});
    </script>
    """

    components.html(html_code, height=300)

    # Ajout d’un script invisible pour récupérer la valeur de t_audio en retour JS
    components.html("""
    <script>
    const checkValue = () => {
      const el = document.getElementById("t_audio_value");
      if (el) {
        const valeur = el.value;
        Streamlit.setComponentValue(valeur);
      } else {
        Streamlit.setComponentValue(null);
      }
    };
    setTimeout(checkValue, 500);
    </script>
    """, height=0)

    return None
