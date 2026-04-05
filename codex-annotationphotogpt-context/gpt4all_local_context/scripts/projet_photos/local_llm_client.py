# local_llm_client.py
from __future__ import annotations

import os
import requests
from typing import Optional, Dict, Any, List
from requests.adapters import HTTPAdapter

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
        timeout: float = 120.0,
    ):
        self.base_url = (base_url or os.getenv("LOCAL_LLM_BASE_URL", "http://127.0.0.1:5050")).rstrip("/")
        self.api_key = api_key or os.getenv("LOCAL_LLM_API_KEY", "")
        self.timeout = float(timeout)
        self.session = requests.Session()
        adapter = HTTPAdapter(
            pool_connections=1,
            pool_maxsize=1,
            max_retries=0,   # IMPORTANT : on gère nous-mêmes les retries
            pool_block=True  # bloque si déjà une requête en cours via le pool
        )
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
        

    def _h(self, request_id: Optional[str] = None) -> Dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self.api_key:
            h["x-api-key"] = self.api_key
        if request_id:
            h["X-Request-Id"] = request_id
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
        overrides: Optional[dict] = None,
        marge: Optional[int] = None,
        min_prompt_tokens: Optional[int] = None,
        json_key: str = "texte",
        prefer_dictee: Optional[bool] = None,
        request_id: Optional[str] = None,
    ) -> str:

        system = (system or "").strip()
        prompt = (prompt or "").strip()

        payload: Dict[str, Any] = {
            "prompt": prompt,
            "system": system,
            "temperature": float(temperature),
            "expect_json": bool(expect_json),
        }

        if prefer_dictee is not None:
            payload["prefer_dictee"] = bool(prefer_dictee)

        if model:
            payload["model_name"] = model

        if max_tokens is not None:
            payload["max_tokens"] = int(max_tokens)

        if stop and not expect_json:
            payload["stop"] = stop

        if task:
            payload["task"] = str(task).strip().lower()

        if salient_families:
            payload["salient_families"] = salient_families

        if overrides:
            payload["overrides"] = overrides
        if marge is not None:
            payload["marge"] = int(marge)
        if min_prompt_tokens is not None:
            payload["min_prompt_tokens"] = int(min_prompt_tokens)

        r = self.session.post(
            self._url("/annoter"),
            json=payload,
            headers=self._h(request_id),
            timeout=self.timeout,
        )

        srv_rid = (r.headers.get("X-Request-Id") or request_id or "").strip()
        if request_id and srv_rid and srv_rid != request_id:
            raise RuntimeError(f"RID_MISMATCH send={request_id} recv={srv_rid}")
        print(f"[BATCH] HTTP {r.status_code} rid_send={request_id} rid_recv={srv_rid}")

        if request_id and not srv_rid:
            # serveur ne renvoie pas l'ID => impossible de faire votre test
            raise RuntimeError("RID_MISSING_IN_RESPONSE")

        r.raise_for_status()

        ct = (r.headers.get("content-type") or "").lower()
        if "application/json" in ct:
            data = r.json()
            errs = data.get("validation_errors") or []

            if errs:
                payload_snip = (r.text or "")[:1200]
                raise ValueError(
                    f"SERVER_REJECT|{task or ''}|{','.join(map(str, errs))}|rid={srv_rid}||{payload_snip}"
                )

            rj = data.get("reponse_json")
            if isinstance(rj, dict) and json_key in rj:
                return str(rj.get(json_key) or "").strip()

            return (data.get("reponse") or "").strip()

        # fallback non-JSON
        return (r.text or "").strip()



