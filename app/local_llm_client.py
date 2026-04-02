# local_llm_client.py
from __future__ import annotations

import os
import requests
from typing import Optional, Dict, Any, List, Union

from pathlib import Path


class LocalLLMClient:
    """
    Client minimal pour un serveur Flask type gpt4all_flask.py.
    Endpoint principal : /annoter
    Auth : header x-api-key (optionnel)
    """

    # (Optionnels) : utiles uniquement si vous utilisez des STOP en mode non-JSON
    STOP_LIBELLE = ["COMMENTAIRE:", "Commentaire:"]
    STOP_COMMENTAIRE = ["LIBELLE:", "Libellé:"]

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout: float = 30.0,
    ):
        self.base_url = (base_url or os.getenv("LOCAL_LLM_BASE_URL", "http://127.0.0.1:5050")).rstrip("/")
        self.api_key = api_key or os.getenv("LOCAL_LLM_API_KEY", "")
        self.timeout = float(timeout)

    def _h(self) -> Dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self.api_key:
            h["x-api-key"] = self.api_key
        return h

    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    def generate(
        self,
        prompt: str,
        system: str = "",
        model: Optional[str] = None,
        salient_families: list[str] | None = None,
        temperature: float = 0.3,
        max_tokens: Optional[int] = None,
        stop: Optional[List[str]] = None,
        task: Optional[str] = None,
        expect_json: bool = False,
        json_key: str = "texte",
    ) -> str:
        """
        Appelle POST /annoter.

        - Si expect_json=True : le serveur doit renvoyer reponse_json={"texte": "..."}.
          Dans ce cas, on retourne en priorité reponse_json[json_key].
        - Important : en mode JSON, il est recommandé de NE PAS passer stop (risque de JSON tronqué).
        """

        system = (system or "").strip()
        prompt = (prompt or "").strip()

        payload: Dict[str, Any] = {
            "prompt": prompt,
            "system": system,
            "temperature": float(temperature),
            "expect_json": bool(expect_json),
        }

        # Modèle (clé canonique côté serveur : model_name)
        if model:
            payload["model_name"] = model

        if max_tokens is not None:
            payload["max_tokens"] = int(max_tokens)

        # ⚠️ Garde-fou : en JSON strict, éviter stop (sinon sortie tronquée)
        if stop and not expect_json:
            payload["stop"] = stop

        if task:
            payload["task"] = str(task).strip().lower()

        if salient_families:
            payload["salient_families"] = salient_families

        r = requests.post(
            self._url("/annoter"),
            json=payload,
            headers=self._h(),
            timeout=self.timeout,
        )
        r.raise_for_status()

        ct = (r.headers.get("content-type") or "").lower()
        ct = (r.headers.get("content-type") or "").lower()
        if "application/json" in ct:
            data = r.json()
            rj = data.get("reponse_json")
            if isinstance(rj, dict) and json_key in rj:
                return str(rj.get(json_key) or "").strip()

            return (
                data.get("reponse")
                or data.get("text")
                or data.get("completion")
                or data.get("output")
                or data.get("response")
                or ""
            ).strip()

        # fallback non-JSON
        return (r.text or "").strip()

    def upload_file_bytes(
        self,
        file_bytes: bytes,
        filename: str,
        project_id: str,
        area: str = "asr_in",
        overwrite: bool = True,
        subdir: str = "",
    ) -> str:
        """
        Upload vers Flask /files (alias /upload_file).
        Retour: path absolu côté PC fixe.
        """
        headers = {}
        if self.api_key:
            headers["x-api-key"] = self.api_key

        data = {
            "project_id": project_id,
            "area": area,
            "filename": filename,
            "overwrite": "true" if overwrite else "false",
        }
        if subdir:
            data["subdir"] = subdir

        files = {"file": (filename, file_bytes, "application/octet-stream")}

        r = requests.post(self._url("/files"), data=data, files=files, headers=headers, timeout=self.timeout)
        r.raise_for_status()
        j = r.json()
        if not j.get("ok") or not j.get("path"):
            raise RuntimeError(f"Upload KO: {j}")
        return str(j["path"])



    def asr_voxtral(
        self,
        audio_path: str,
        lang: str = "fr",
        timestamps: bool = False,
        auto_chunk: bool = True,
        output_csv_dir: Optional[str] = None,
        export_raw_csv: bool = True,
        export_photo_csv: bool = True,
        export_chat_csv: bool = False,
        export_chat_docx: bool = False,
        excel_encoding: str = "utf-8-sig",
        excel_decimal: str = "comma",
        return_payload: bool = False,
        **kwargs: Any,
    ) -> Union[str, Dict[str, Any]]:
        """
        Appelle /asr_voxtral avec un chemin côté serveur.

        - Si return_payload=False (défaut): retourne le texte transcrit (str)
        - Si return_payload=True: retourne le JSON complet (dict), utile pour csv_path/photo_csv_path

        Paramètres clés:
        - output_csv_dir: chemin ABSOLU côté PC fixe où écrire les CSV (ex: ...\\asr_out)
        - export_* : contrôle quels exports sont écrits
        """

        payload: Dict[str, Any] = {
            "audio_path": audio_path,
            "lang": lang,
            "timestamps": bool(timestamps),
            "auto_chunk": bool(auto_chunk),
            "export_raw_csv": bool(export_raw_csv),
            "export_photo_csv": bool(export_photo_csv),
            "export_chat_csv": bool(export_chat_csv),
            "export_chat_docx": bool(export_chat_docx),
            "excel_encoding": excel_encoding,
            "excel_decimal": excel_decimal,
        }

        if output_csv_dir:
            payload["output_csv_dir"] = str(output_csv_dir)

        # permet de passer model_key, chunk, diarize, etc.
        payload.update(kwargs)

        r = requests.post(
            self._url("/asr_voxtral"),
            json=payload,
            headers=self._h(),
            timeout=max(self.timeout, 600),
        )
        r.raise_for_status()
        j = r.json()

        if j.get("error"):
            raise RuntimeError(f"ASR KO: {j['error']}")

        if return_payload:
            return j

        return str(j.get("text") or "").strip()

