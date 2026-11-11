import ast
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).parents[1].absolute()
UI_SOURCE = ROOT / "app" / "annotation_interface_gpt.py"
LAPTOP_BATCH_SOURCE = ROOT / "scripts" / "batch_photos_vlm_llm.py"
PCFIXE_BATCH_SOURCE = ROOT / "batch_pcfixe" / "batch_all_photos_pcfixe.py"
MODEL_PREFIXES = ("gpt-5", "gpt-6", "o1", "o3", "o4")
OPENAI_CALL_SOURCES = (UI_SOURCE, LAPTOP_BATCH_SOURCE, PCFIXE_BATCH_SOURCE)


class DummyCompletions:
    def __init__(self, text):
        self.text = text
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=self.text))]
        )


class DummyClient:
    def __init__(self, text):
        self.completions = DummyCompletions(text)
        self.chat = SimpleNamespace(completions=self.completions)


def _load_functions(path: Path, names: set[str], namespace: dict) -> dict:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    selected = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in names
    ]
    module = ast.Module(body=selected, type_ignores=[])
    ast.fix_missing_locations(module)
    exec(compile(module, str(path), "exec"), namespace)
    return namespace


class OpenAIParameterBuilderTests(unittest.TestCase):
    def test_all_requested_model_families_use_reasoning_parameters(self):
        for source in OPENAI_CALL_SOURCES:
            namespace = _load_functions(
                source,
                {"_openai_chat_completion_kwargs"},
                {"_OPENAI_REASONING_MODEL_PREFIXES": MODEL_PREFIXES},
            )
            build = namespace["_openai_chat_completion_kwargs"]
            for model in ("gpt-5-test", "gpt-6-luna", "o1-preview", "o3-mini", "o4-mini"):
                with self.subTest(source=source.name, model=model):
                    call = build(model, 321, 0.25, [{"role": "user", "content": "test"}])
                    self.assertEqual(call["max_completion_tokens"], 321)
                    self.assertNotIn("max_tokens", call)
                    self.assertNotIn("temperature", call)


class LaptopBatchOpenAICompatibilityTests(unittest.TestCase):
    def _call(self, model):
        client = DummyClient("texte laptop")
        config = {
            "llm_backend": "openai",
            "openai_api_key": "sk-test",
            "model": model,
            "temperature": 0.25,
            "max_tokens": 120,
        }
        namespace = _load_functions(
            LAPTOP_BATCH_SOURCE,
            {"_openai_chat_completion_kwargs", "call_llm"},
            {
                "_OPENAI_REASONING_MODEL_PREFIXES": MODEL_PREFIXES,
            },
        )
        openai_module = SimpleNamespace(OpenAI=lambda api_key: client)
        import sys
        previous = sys.modules.get("openai")
        sys.modules["openai"] = openai_module
        try:
            result = namespace["call_llm"]("prompt laptop", config)
        finally:
            if previous is None:
                del sys.modules["openai"]
            else:
                sys.modules["openai"] = previous
        return result, client.completions.calls[0]

    def test_gpt6_parameters_messages_and_text(self):
        result, call = self._call("gpt-6-luna")

        self.assertEqual(result, "texte laptop")
        self.assertEqual(call["max_completion_tokens"], 120)
        self.assertNotIn("max_tokens", call)
        self.assertNotIn("temperature", call)
        self.assertEqual(call["messages"], [{"role": "user", "content": "prompt laptop"}])

    def test_historical_model_parameters_are_preserved(self):
        _result, call = self._call("gpt-4o-mini")

        self.assertEqual(call["max_tokens"], 120)
        self.assertEqual(call["temperature"], 0.25)
        self.assertNotIn("max_completion_tokens", call)


class PcfixeBatchOpenAICompatibilityTests(unittest.TestCase):
    def _call(self, model):
        client = DummyClient("texte pcfixe")
        requests_stub = SimpleNamespace(
            exceptions=SimpleNamespace(
                HTTPError=type("HTTPError", (Exception,), {}),
                Timeout=type("Timeout", (Exception,), {}),
                ConnectionError=type("ConnectionError", (Exception,), {}),
                RequestException=type("RequestException", (Exception,), {}),
            )
        )
        namespace = _load_functions(
            PCFIXE_BATCH_SOURCE,
            {"_openai_chat_completion_kwargs", "generate_with_retry"},
            {
                "_OPENAI_REASONING_MODEL_PREFIXES": MODEL_PREFIXES,
                "LLM_INFLIGHT": threading.BoundedSemaphore(value=1),
                "throttle": lambda _seconds: None,
                "time": SimpleNamespace(time=lambda: 1.0, sleep=lambda _seconds: None),
                "uuid": SimpleNamespace(uuid4=lambda: SimpleNamespace(hex="abcdef123456")),
                "requests": requests_stub,
                "random": SimpleNamespace(uniform=lambda _a, _b: 0.0),
                "_set_llm_err": lambda *_args, **_kwargs: None,
            },
        )
        trace = {}
        result = namespace["generate_with_retry"](
            client,
            llm_backend="openai",
            prompt="prompt pcfixe",
            system="systeme pcfixe",
            model=model,
            openai_api_key="sk-test",
            temperature=0.2,
            max_tokens=500,
            task="commentaire",
            expect_json=True,
            salient_families=[],
            prefer_dictee=False,
            b=trace,
            which="COM",
            max_attempts=1,
        )
        return result, client.completions.calls[0]

    def test_gpt6_parameters_messages_and_text(self):
        result, call = self._call("gpt-6-luna")

        self.assertEqual(result, "texte pcfixe")
        self.assertEqual(call["max_completion_tokens"], 500)
        self.assertNotIn("max_tokens", call)
        self.assertNotIn("temperature", call)
        self.assertEqual(call["messages"], [
            {"role": "system", "content": "systeme pcfixe"},
            {"role": "user", "content": "prompt pcfixe"},
        ])

    def test_historical_model_parameters_are_preserved(self):
        _result, call = self._call("gpt-4o-mini")

        self.assertEqual(call["max_tokens"], 500)
        self.assertEqual(call["temperature"], 0.2)
        self.assertNotIn("max_completion_tokens", call)


if __name__ == "__main__":
    unittest.main()
