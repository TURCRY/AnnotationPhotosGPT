import ast
import unittest
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).parents[1].absolute()
SOURCE = ROOT / "app" / "annotation_interface_gpt.py"


class DummyStatus:
    def __init__(self):
        self.messages = []

    def info(self, message):
        self.messages.append(("info", message))

    def warning(self, message):
        self.messages.append(("warning", message))

    def error(self, message):
        self.messages.append(("error", message))

    def empty(self):
        self.messages.append(("empty", ""))


class DummyStreamlit:
    def __init__(self):
        self.session_state = {}
        self.writes = []
        self.status = DummyStatus()

    def empty(self):
        return self.status

    def write(self, *args):
        self.writes.append(args)


class DummyResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class DummyRequests:
    class HTTPError(Exception):
        pass

    def __init__(self, response_payload):
        self.response_payload = response_payload
        self.calls = []

    def post(self, url, json, headers, timeout):
        self.calls.append({
            "url": url,
            "json": json,
            "headers": headers,
            "timeout": timeout,
        })
        return DummyResponse(self.response_payload)


class DummyOpenAI:
    calls = []

    def __init__(self, api_key):
        self.api_key = api_key
        self.chat = SimpleNamespace(
            completions=SimpleNamespace(create=self._create)
        )

    def _create(self, **kwargs):
        self.__class__.calls.append(kwargs)
        message = SimpleNamespace(content="reponse openai")
        choice = SimpleNamespace(message=message)
        return SimpleNamespace(choices=[choice])


def load_generer(response_payload=None, backend="local"):
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    selected = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "generer_texte_gpt"
    ]
    module = ast.Module(body=selected, type_ignores=[])
    ast.fix_missing_locations(module)

    st = DummyStreamlit()
    requests = DummyRequests(response_payload or {"ok": True, "reponse_json": {"texte": "texte local"}})
    DummyOpenAI.calls = []
    appcfg = {
        "llm_backend": backend,
        "openai_api_key": "sk-test",
        "model": "gpt-test",
        "temperature": 0.3,
        "max_tokens": 999,
        "local_llm": {
            "base_url": "http://local.test",
            "api_key": "local-key",
            "model": "local-model",
            "timeout": 12,
            "fallback_to_openai": False,
        },
        "wol": {},
    }
    namespace = {
        "OpenAI": DummyOpenAI,
        "_LOCAL_LLM_BUSY_RESULT": "[LLM local occupe, reessayez dans quelques secondes.]",
        "_load_app_config": lambda infos: appcfg,
        "lire_infos_projet": lambda: {"project_id": "test"},
        "resolve_flask_base_url": lambda: "http://fallback.test",
        "is_server_up": lambda *args, **kwargs: True,
        "requests": requests,
        "st": st,
        "time": SimpleNamespace(sleep=lambda seconds: None),
        "_strip_wrapping_quotes": lambda value: value,
    }
    exec(compile(module, str(SOURCE), "exec"), namespace)
    return namespace["generer_texte_gpt"], requests, st


class UIDictationContractTests(unittest.TestCase):
    def test_local_payload_includes_structured_dictation_only_when_non_empty(self):
        generer, requests, _st = load_generer()
        prompt = "TACHE - COMMENTAIRE\nsource\n\n[DICTEE MICRO]\ntexte dictee exact"

        result = generer("systeme", prompt, dictee_asr_text="  texte dictee exact  ")

        self.assertEqual(result, "texte local")
        payload = requests.calls[0]["json"]
        self.assertEqual(payload["prompt"], prompt)
        self.assertEqual(payload["prompt"].count("texte dictee exact"), 1)
        self.assertEqual(payload["dictee_asr_text"], "texte dictee exact")
        self.assertIs(payload["prefer_dictee"], True)
        self.assertEqual(payload["task"], "commentaire")

    def test_local_payload_without_dictation_keeps_existing_shape(self):
        generer, requests, _st = load_generer()

        generer("systeme", "TACHE - LIBELLE\nsource", dictee_asr_text="   ")

        payload = requests.calls[0]["json"]
        self.assertNotIn("dictee_asr_text", payload)
        self.assertNotIn("prefer_dictee", payload)
        self.assertEqual(payload["task"], "libelle")

    def test_soft_warning_response_text_is_accepted(self):
        generer, _requests, _st = load_generer({
            "ok": True,
            "reponse_json": {"texte": "texte accepte"},
            "validation_errors": ["warning_soft"],
        })

        self.assertEqual(generer("systeme", "TACHE - COMMENTAIRE\nsource"), "texte accepte")

    def test_hard_empty_response_keeps_empty_response_message(self):
        generer, _requests, _st = load_generer({
            "ok": True,
            "reponse": "",
            "reponse_json": {},
            "validation_errors": ["hard"],
        })

        self.assertEqual(
            generer("systeme", "TACHE - COMMENTAIRE\nsource"),
            "[Réponse LLM local vide ou inexploitable]",
        )

    def test_openai_backend_ignores_structured_dictation_argument(self):
        generer, requests, _st = load_generer(backend="openai")
        prompt = "prompt openai"

        result = generer("systeme", prompt, dictee_asr_text="texte dictee exact")

        self.assertEqual(result, "reponse openai")
        self.assertEqual(requests.calls, [])
        call = DummyOpenAI.calls[0]
        self.assertEqual(call["messages"], [
            {"role": "system", "content": "systeme"},
            {"role": "user", "content": prompt},
        ])
        self.assertNotIn("dictee_asr_text", str(call))
        self.assertNotIn("prefer_dictee", str(call))


if __name__ == "__main__":
    unittest.main()
