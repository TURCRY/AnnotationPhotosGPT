from __future__ import annotations

import ast
from pathlib import Path
import subprocess
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
UI_FILES = (
    REPO_ROOT / "app" / "annotation_interface_gpt.py",
    REPO_ROOT / "app" / "selection_fichiers_interface.py",
    REPO_ROOT / "app" / "utils.py",
)

MOJIBAKE_MARKERS = (
    "Ã°Å¸",
    "Ã¢â‚¬",
    "Ã¢â€ ",
    "Ã¢Å“",
    "Ã¢Å¡",
    "Ã¯Â¸",
    "ÃƒÂ©",
    "ÃƒÂ¨",
    "Ãƒ",
    "Ã‚",
    "ï¿½",
    "ðŸ",
    "âœ",
    "â",
    "â†",
    "ï¸",
    "l?op?ration",
    "?criture",
    "n?a ?t?",
    "?cras?e",
    "Enregistr? localement ? publication",
)

EXPECTED_TEXT = (
    "🖋️ Annotation guidée avec GPT",
    "📸",
    "⏱️",
    "t₀",
)

FUNCTIONAL_CALL_PREFIXES = ("st.", "audio_html", "components.html")


def _functional_string_literals(path: Path) -> list[tuple[int, str]]:
    text = path.read_text(encoding="utf-8")
    return _functional_string_literals_from_text(text, path)


def _functional_string_literals_from_text(text: str, path: Path) -> list[tuple[int, str]]:
    tree = ast.parse(text, filename=str(path))
    lines = text.splitlines()
    values: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        line = lines[node.lineno - 1] if 1 <= node.lineno <= len(lines) else ""
        if any(prefix in line for prefix in FUNCTIONAL_CALL_PREFIXES):
            values.append((node.lineno, node.value))
    return values


def _mojibake_failures_for_text(text: str, path: Path) -> list[str]:
    failures: list[str] = []
    for line_no, value in _functional_string_literals_from_text(text, path):
        markers = [marker for marker in MOJIBAKE_MARKERS if marker in value]
        has_c1_control = any(0x80 <= ord(ch) <= 0x9F for ch in value)
        if markers or has_c1_control:
            failures.append(f"{path}:{line_no}: {value!r}")
    return failures


class UiTextEncodingTests(unittest.TestCase):
    def test_functional_ui_literals_do_not_contain_common_mojibake(self) -> None:
        failures: list[str] = []
        for path in UI_FILES:
            for failure in _mojibake_failures_for_text(path.read_text(encoding="utf-8"), path):
                failures.append(str(Path(failure.split(":", 1)[0]).relative_to(REPO_ROOT)) + ":" + failure.split(":", 1)[1])
        self.assertEqual([], failures)

    def test_git_head_vs_worktree_mojibake_source_is_explicit(self) -> None:
        try:
            subprocess.check_output(["git", "rev-parse", "--show-toplevel"], cwd=REPO_ROOT)
        except Exception:
            self.skipTest("git repository unavailable")

        head_failures: list[str] = []
        worktree_failures: list[str] = []
        for path in UI_FILES:
            rel = path.relative_to(REPO_ROOT).as_posix()
            try:
                head_text = subprocess.check_output(
                    ["git", "show", f"HEAD:{rel}"],
                    cwd=REPO_ROOT,
                    stderr=subprocess.DEVNULL,
                ).decode("utf-8")
            except Exception:
                head_text = ""
            head_failures.extend(_mojibake_failures_for_text(head_text, Path(rel)) if head_text else [])
            worktree_failures.extend(_mojibake_failures_for_text(path.read_text(encoding="utf-8"), path))

        introduced_only = [
            failure for failure in worktree_failures
            if failure not in head_failures
        ]
        self.assertEqual(
            [],
            worktree_failures,
            "Mojibake in the actual working tree used by Streamlit.\n"
            f"Already present in HEAD: {head_failures!r}\n"
            f"Introduced only by uncommitted changes: {introduced_only!r}",
        )

    def test_expected_unicode_ui_strings_are_present(self) -> None:
        text = (REPO_ROOT / "app" / "annotation_interface_gpt.py").read_text(encoding="utf-8")
        missing = [expected for expected in EXPECTED_TEXT if expected not in text]
        self.assertEqual([], missing)


if __name__ == "__main__":
    unittest.main()
