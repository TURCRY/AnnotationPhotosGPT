from __future__ import annotations

import hashlib
import os
import shutil
import uuid
from pathlib import Path


PCFIXE_AFFAIRES_SMB_ROOTS = (
    r"\\10.0.1.10\Affaires",
    r"\\192.168.0.155\Affaires",
    r"\\192.168.0.120\Affaires",
)
NAS_AFFAIRES_SMB_ROOT = r"\\192.168.1.20\Affaires"
PCFIXE_LOCAL_AFFAIRES_ROOT = r"C:\Affaires"


def pcfixe_smb_roots(pcfixe: dict | None = None, *, vpn_active: bool = False) -> list[str]:
    def dedupe(values: list[str]) -> list[str]:
        roots: list[str] = []
        seen: set[str] = set()
        for value in values:
            root = str(value or "").strip().rstrip("\\/")
            key = root.casefold()
            if root and key not in seen:
                roots.append(root)
                seen.add(key)
        return roots

    configured = str((pcfixe or {}).get("root_affaires") or "").strip().rstrip("\\/")
    if configured.casefold() == NAS_AFFAIRES_SMB_ROOT.casefold():
        configured = ""

    if vpn_active:
        roots = [PCFIXE_AFFAIRES_SMB_ROOTS[0]]
        if configured.startswith(r"\\10.0.1."):
            roots.append(configured)
        return dedupe(roots[:2])

    roots = []
    if configured.startswith(r"\\192.168.0."):
        roots.append(configured)
    roots.extend(PCFIXE_AFFAIRES_SMB_ROOTS[1:])
    return dedupe(roots)[:2]


def first_available_pcfixe_smb_root(
    pcfixe: dict | None = None,
    *,
    vpn_active: bool = False,
) -> str:
    for root in pcfixe_smb_roots(pcfixe, vpn_active=vpn_active):
        try:
            if Path(root).is_dir():
                return root
        except OSError:
            continue
    return ""


def server_affaires_path_to_smb(smb_root: str, server_path: str | Path) -> Path:
    raw = str(server_path or "").strip()
    prefix = PCFIXE_LOCAL_AFFAIRES_ROOT
    if raw.casefold() == prefix.casefold():
        suffix = ""
    elif raw.casefold().startswith((prefix + "\\").casefold()):
        suffix = raw[len(prefix):].strip("\\/")
    else:
        raise ValueError(f"Chemin hors racine runtime PC fixe {prefix}: {raw}")
    return Path(str(smb_root).rstrip("\\/")) / Path(suffix) if suffix else Path(smb_root)


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_tmp_path(target: Path) -> Path:
    return target.with_name(f".apg-tmp-{os.getpid()}-{uuid.uuid4().hex}-{target.name}.tmp")


def _fsync_path(path: Path) -> None:
    try:
        with Path(path).open("rb") as handle:
            os.fsync(handle.fileno())
    except Exception:
        pass


def copy_file_atomic(src: str | Path, dst: str | Path) -> Path:
    src_path = Path(src)
    dst_path = Path(dst)
    if not src_path.is_file():
        raise FileNotFoundError(f"Fichier source introuvable : {src_path}")
    dst_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = _atomic_tmp_path(dst_path)
    try:
        shutil.copy2(str(src_path), str(tmp))
        _fsync_path(tmp)
        os.replace(str(tmp), str(dst_path))
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
    return dst_path


def copy_file_atomic_verified(src: str | Path, dst: str | Path) -> dict:
    src_path = Path(src)
    dst_path = Path(dst)
    if not src_path.is_file():
        raise FileNotFoundError(f"Fichier source introuvable : {src_path}")
    source_hash = sha256_file(src_path)
    dst_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = _atomic_tmp_path(dst_path)
    try:
        shutil.copy2(str(src_path), str(tmp))
        _fsync_path(tmp)
        temporary_hash = sha256_file(tmp)
        if temporary_hash != source_hash:
            raise RuntimeError(
                f"SHA-256 différent avant publication PC fixe : {src_path} -> {dst_path}"
            )
        os.replace(str(tmp), str(dst_path))
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)

    destination_hash = sha256_file(dst_path)
    if destination_hash != source_hash:
        raise RuntimeError(
            f"SHA-256 différent après publication PC fixe : {src_path} -> {dst_path}"
        )
    return {
        "source": str(src_path),
        "destination": str(dst_path),
        "sha256_source": source_hash,
        "sha256_destination": destination_hash,
    }
