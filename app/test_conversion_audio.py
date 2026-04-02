import os
import subprocess
import soundfile as sf
from datetime import datetime

def convertir_audio(path):
    ext = os.path.splitext(path)[1].lower()
    chemin_temp = os.path.join("data", "temp")
    os.makedirs(chemin_temp, exist_ok=True)
    sortie = os.path.join(chemin_temp, "audio_compatible.wav")

    def conversion_ffmpeg(source, destination):
        cmd = [
            "ffmpeg", "-y",
            "-i", source,
            "-acodec", "pcm_s16le",
            "-ac", "1",
            "-ar", "44100",
            "-f", "wav",
            destination
        ]
        print(f"Conversion avec : {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True)
        print(result.stdout)
        print(result.stderr)
        return result.returncode == 0

    if ext == ".wav":
        try:
            info = sf.info(path)
            print(f"[INFO] WAV : {info.samplerate} Hz, {info.channels} canaux, {info.subtype}")
            if (
                info.samplerate == 44100 and
                info.channels == 1 and
                info.subtype.lower() in ["pcm_16", "pcm_s16le"]
            ):
                from shutil import copy2
                copy2(path, sortie)
                print("✅ WAV compatible copié tel quel.")
            else:
                if conversion_ffmpeg(path, sortie):
                    print("🔁 WAV converti automatiquement.")
                else:
                    print("❌ Erreur de conversion WAV.")
        except Exception as e:
            print(f"Erreur lecture WAV : {e}")

    elif ext == ".mp3":
        print("⚠️ MP3 détecté. Conversion nécessaire.")
        if conversion_ffmpeg(path, sortie):
            print("✅ MP3 converti en WAV compatible.")
        else:
            print("❌ Erreur de conversion MP3.")

    else:
        print("❌ Format non supporté")

if __name__ == "__main__":
    chemin = input("Chemin du fichier audio (.wav ou .mp3) : ").strip('"')
    convertir_audio(chemin)
