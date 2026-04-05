from flask import Flask, request, Response, jsonify, abort
from flask_cors import CORS
import os, re, mimetypes
from pathlib import Path
from werkzeug.utils import safe_join
import io
import soundfile as sf
import wave
import hashlib




app = Flask(__name__)
CORS(app)

AUDIO_FOLDER = Path(r"C:\AnnotationPhotosGPT\data\temp")
AUDIO_FILE_PATH = os.environ.get(
    "AUDIO_FILE_PATH",
    str(AUDIO_FOLDER / "audio_compatible.wav")
)

CHUNK_SIZE = 1024 * 1024  # 1 MB
print("### AUDIO SERVER VERSION: audio_clip ACTIVE ###", flush=True)


def _stream_file(path, start, end):
    with open(path, "rb") as f:
        f.seek(start)
        remaining = end - start + 1
        while remaining > 0:
            chunk = f.read(min(CHUNK_SIZE, remaining))
            if not chunk:
                break
            yield chunk
            remaining -= len(chunk)

def _audio_response(path, range_header):
    if not os.path.isfile(path):
        abort(404)

    size = os.path.getsize(path)
    mime = mimetypes.guess_type(path)[0] or "audio/wav"

    # HEAD : utile pour certains clients
    if request.method == "HEAD":
        resp = Response(status=200)
        resp.headers["Content-Type"] = mime
        resp.headers["Accept-Ranges"] = "bytes"
        resp.headers["Content-Length"] = str(size)
        return resp

    # Range
    if range_header:
        m = re.match(r"bytes=(\d+)-(\d*)", range_header)
        if m:
            start = int(m.group(1))
            end = int(m.group(2)) if m.group(2) else size - 1
            start = max(0, min(start, size - 1))
            end = max(start, min(end, size - 1))
            length = end - start + 1

            resp = Response(_stream_file(path, start, end), status=206, mimetype=mime, direct_passthrough=True)
            resp.headers["Content-Range"] = f"bytes {start}-{end}/{size}"
            resp.headers["Accept-Ranges"] = "bytes"
            resp.headers["Content-Length"] = str(length)
            resp.headers["Cache-Control"] = "no-store"
            return resp

    # Sans Range
    resp = Response(_stream_file(path, 0, size - 1), status=200, mimetype=mime, direct_passthrough=True)
    resp.headers["Accept-Ranges"] = "bytes"
    resp.headers["Content-Length"] = str(size)
    resp.headers["Cache-Control"] = "no-store"
    return resp

@app.get("/ping")
def ping():
    p = Path(AUDIO_FILE_PATH)
    return jsonify({
        "ok": True,
        "audio_path": str(p),
        "exists": p.exists(),
        "size": p.stat().st_size if p.exists() else None,
    })

@app.get("/info")
def info():
    p = Path(AUDIO_FILE_PATH)
    if not p.exists():
        return jsonify({
            "ok": False,
            "error": "audio file not found",
            "audio_path": str(p),
        }), 404

    return jsonify({
        "ok": True,
        "filename": p.name,
        "audio_path": str(p),
        "size_bytes": p.stat().st_size,
    })


@app.route("/audio/<path:filename>", methods=["GET", "HEAD"])
def serve_audio(filename):
    full = safe_join(str(AUDIO_FOLDER), filename)
    if not full:
        abort(404)
    range_header = request.headers.get("Range")
    return _audio_response(full, range_header)

@app.get("/wav_info")
def wav_info():
    import wave
    p = AUDIO_FILE_PATH
    if not os.path.exists(p):
        abort(404)
    with wave.open(p, "rb") as w:
        return jsonify({
            "nchannels": w.getnchannels(),
            "sampwidth": w.getsampwidth(),
            "framerate": w.getframerate(),
            "nframes": w.getnframes(),
            "duration": w.getnframes()/float(w.getframerate()),
            "comptype": w.getcomptype(),
            "compname": w.getcompname(),
        })

@app.get("/audio/audio_compatible.wav")
def serve_main_audio():
    range_header = request.headers.get("Range")
    return _audio_response(AUDIO_FILE_PATH, range_header)


@app.get("/audio_clip")
def audio_clip():
    start = float(request.args.get("start", "0") or 0.0)
    end   = float(request.args.get("end", "0") or 0.0)
    if end <= start:
        abort(400)
    path = AUDIO_FILE_PATH
    if not os.path.exists(path):
        abort(404)

    with wave.open(path, "rb") as w:
        sr = w.getframerate()
        nch = w.getnchannels()
        sampw = w.getsampwidth()
        nframes = w.getnframes()
        dur = nframes / float(sr)

        start_c = max(0.0, min(start, dur))
        end_c   = max(start_c, min(end, dur))

        i0 = int(start_c * sr)
        i1 = int(end_c * sr)
        frames = i1 - i0
        if frames <= 0:
            abort(416)

        # --- lecture brute à l’offset ---
        w.setpos(i0)
        raw = w.readframes(frames)

        # --- debug : empreinte du début du raw (permet de prouver que ce n’est pas le début du fichier) ---
        sig = hashlib.sha1(raw[:200_000]).hexdigest()  # empreinte sur ~2 sec
        app.logger.warning(
            "CLIP wave start=%.3f end=%.3f sr=%d dur=%.3f i0=%d frames=%d nch=%d sampw=%d sha1_200k=%s",
            start_c, end_c, sr, dur, i0, frames, nch, sampw, sig
        )

        # --- ré-encapsuler en WAV ---
        buf = io.BytesIO()
        with wave.open(buf, "wb") as out:
            out.setnchannels(nch)
            out.setsampwidth(sampw)
            out.setframerate(sr)
            out.writeframes(raw)

    wav_bytes = buf.getvalue()
    return Response(
        wav_bytes,
        mimetype="audio/wav",
        headers={"Cache-Control": "no-store", "Content-Length": str(len(wav_bytes))}
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)

