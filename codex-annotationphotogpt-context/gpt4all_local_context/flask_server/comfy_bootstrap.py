# comfy_bootstrap.py intégré
import threading, subprocess
_boot_lock = threading.Lock()

def comfy_healthy(timeout=0.8) -> bool:
    try:
        r = requests.get(COMFY_URL + "/", timeout=timeout)
        return r.ok
    except Exception:
        return False

def ensure_comfy_ui(max_wait_s=45):
    if comfy_healthy():
        return True
    with _boot_lock:
        if comfy_healthy():
            return True
        creationflags = getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
        subprocess.Popen(
            [COMFY_CONF.get("python", r"D:\envs\sd\Scripts\python.exe"), "main.py",
             "--listen", COMFY_HOST, "--port", str(COMFY_PORT)],
            cwd=COMFY_CONF.get("cwd", r"D:\Apps\ComfyUI"),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=creationflags
        )
    deadline = time.time() + max_wait_s
    while time.time() < deadline:
        if comfy_healthy():
            return True
        time.sleep(1)
    return False
