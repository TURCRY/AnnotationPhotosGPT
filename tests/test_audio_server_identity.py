import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


ROOT = Path(__file__).parents[1].absolute()
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "app"))


class _FakeStreamlit(types.ModuleType):
    def __init__(self):
        super().__init__("streamlit")
        self.session_state = {}
        self.__path__ = []


fake_st = _FakeStreamlit()
components = types.ModuleType("streamlit.components")
components.__path__ = []
components_v1 = types.ModuleType("streamlit.components.v1")
components_v1.html = lambda *args, **kwargs: None

import audio_server
import traitement_audio as ta
ta.st = fake_st
sys.modules.pop("streamlit", None)
sys.modules.pop("streamlit.components", None)
sys.modules.pop("streamlit.components.v1", None)


class AudioServerIdentityTests(unittest.TestCase):
    def setUp(self):
        fake_st.session_state.clear()

    def _audio_file(self, root: Path, name: str, payload: bytes) -> Path:
        path = root / name
        path.write_bytes(payload)
        return path

    def _fake_proc(self):
        proc = Mock()
        proc.poll.return_value = None
        proc.terminate.return_value = None
        return proc

    def test_audio_info_matches_file_really_served(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._audio_file(Path(tmp), "served.wav", b"RIFFserved")
            with patch.object(audio_server, "AUDIO_FILE_PATH", str(path)):
                response = audio_server.app.test_client().get("/audio/info")

            self.assertEqual(200, response.status_code)
            data = response.get_json()
            self.assertEqual(os.path.realpath(os.path.abspath(path)), data["source_path"])
            self.assertEqual(path.stat().st_size, data["size"])
            self.assertEqual(path.stat().st_mtime_ns, data["mtime_ns"])

    def test_no_server_starts_with_requested_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            file_a = self._audio_file(Path(tmp), "a.wav", b"A")
            expected = ta.audio_file_identity(str(file_a))
            proc = self._fake_proc()

            with patch.object(ta, "_port_open", side_effect=[False, True]), \
                 patch.object(ta, "_get_server_audio_info", return_value=expected), \
                 patch.object(ta.subprocess, "Popen", return_value=proc) as popen:
                result = ta.start_audio_server_if_needed(str(file_a))

            self.assertEqual(expected, result)
            self.assertEqual(str(file_a.resolve()), popen.call_args.kwargs["env"]["AUDIO_FILE_PATH"])

    def test_server_serving_same_file_is_reused(self):
        with tempfile.TemporaryDirectory() as tmp:
            file_a = self._audio_file(Path(tmp), "a.wav", b"A")
            expected = ta.audio_file_identity(str(file_a))

            with patch.object(ta, "_port_open", return_value=True), \
                 patch.object(ta, "_get_server_audio_info", return_value=expected), \
                 patch.object(ta, "_stop_stale_audio_servers_on_port") as stop_stale, \
                 patch.object(ta.subprocess, "Popen") as popen:
                result = ta.start_audio_server_if_needed(str(file_a))

            self.assertEqual(expected, result)
            stop_stale.assert_not_called()
            popen.assert_not_called()

    def test_server_serving_different_file_is_replaced(self):
        with tempfile.TemporaryDirectory() as tmp:
            file_a = self._audio_file(Path(tmp), "a.wav", b"A")
            file_b = self._audio_file(Path(tmp), "b.wav", b"B")
            identity_a = ta.audio_file_identity(str(file_a))
            identity_b = ta.audio_file_identity(str(file_b))
            proc = self._fake_proc()

            with patch.object(ta, "_port_open", side_effect=[True, False, True]), \
                 patch.object(ta, "_get_server_audio_info", side_effect=[identity_a, identity_b]), \
                 patch.object(ta, "_stop_stale_audio_servers_on_port", return_value=[123]) as stop_stale, \
                 patch.object(ta.subprocess, "Popen", return_value=proc):
                result = ta.start_audio_server_if_needed(str(file_b))

            self.assertEqual(identity_b, result)
            stop_stale.assert_called_once_with(ta.AUDIO_SERVER_PORT)

    def test_unreferenced_wrong_server_is_replaced_by_listener_pid(self):
        with tempfile.TemporaryDirectory() as tmp:
            file_a = self._audio_file(Path(tmp), "a.wav", b"A")
            file_b = self._audio_file(Path(tmp), "b.wav", b"B")
            identity_a = ta.audio_file_identity(str(file_a))
            identity_b = ta.audio_file_identity(str(file_b))
            proc = self._fake_proc()

            with patch.object(ta, "_port_open", side_effect=[True, False, True]), \
                 patch.object(ta, "_get_server_audio_info", side_effect=[identity_a, identity_b]), \
                 patch.object(ta, "_listener_pids_on_port", return_value={456}), \
                 patch.object(ta, "_is_our_audio_server_process", return_value=True), \
                 patch.object(ta, "_terminate_process_tree") as terminate, \
                 patch.object(ta.subprocess, "Popen", return_value=proc):
                result = ta.start_audio_server_if_needed(str(file_b))

            self.assertEqual(identity_b, result)
            terminate.assert_called_once_with(456)

    def test_failed_replacement_raises_without_silent_reuse(self):
        with tempfile.TemporaryDirectory() as tmp:
            file_a = self._audio_file(Path(tmp), "a.wav", b"A")
            file_b = self._audio_file(Path(tmp), "b.wav", b"B")
            identity_a = ta.audio_file_identity(str(file_a))

            with patch.object(ta, "_port_open", return_value=True), \
                 patch.object(ta, "_get_server_audio_info", return_value=identity_a), \
                 patch.object(ta, "_stop_stale_audio_servers_on_port", return_value=[]), \
                 patch.object(ta.subprocess, "Popen") as popen:
                with self.assertRaises(RuntimeError):
                    ta.start_audio_server_if_needed(str(file_b))

            popen.assert_not_called()

    def test_fingerprint_url_and_component_key_differ_between_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            file_a = self._audio_file(Path(tmp), "a.wav", b"A")
            file_b = self._audio_file(Path(tmp), "b.wav", b"BB")
            identity_a = ta.audio_file_identity(str(file_a))
            identity_b = ta.audio_file_identity(str(file_b))

            self.assertNotEqual(
                ta.audio_identity_fingerprint(identity_a),
                ta.audio_identity_fingerprint(identity_b),
            )
            self.assertNotEqual(
                ta.audio_component_key_for_identity(identity_a),
                ta.audio_component_key_for_identity(identity_b),
            )
            self.assertIn("?v=", ta.audio_url_for_identity(identity_a))


if __name__ == "__main__":
    unittest.main()
