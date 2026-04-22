import os
import re
from pathlib import Path

import pandas as pd


_USER_HOME = Path(os.environ.get("USERPROFILE") or Path.home())
_USER_DOCUMENTS = _USER_HOME / "Documents"
_WINDOWS_USER_PREFIX = re.compile(r"^[A-Za-z]:\\Users\\[^\\]+(?:\\|$)", re.IGNORECASE)
PHOTO_PATH_COLUMNS = (
    "chemin_photo_native",
    "chemin_photo_reduite",
)


def _normalize_windows_path(value: str) -> str:
    return os.path.normpath(str(value or "").strip().replace("/", "\\"))


def resolve_migrated_user_profile_path(path_value: str) -> tuple[str, bool]:
    raw = str(path_value or "").strip()
    if not raw or raw.startswith("\\\\"):
        return raw, False

    normalized = _normalize_windows_path(raw)
    if not _WINDOWS_USER_PREFIX.match(normalized):
        return path_value, False

    if os.path.exists(normalized):
        return normalized, False

    lower = normalized.lower()
    docs_marker = "\\documents\\"

    if docs_marker in lower:
        idx = lower.index(docs_marker)
        suffix = normalized[idx + len(docs_marker):]
        candidate = str(_USER_DOCUMENTS / suffix) if suffix else str(_USER_DOCUMENTS)
    else:
        marker = "\\users\\"
        idx = lower.index(marker) + len(marker)
        next_sep = normalized.find("\\", idx)
        suffix = normalized[next_sep + 1:] if next_sep >= 0 else ""
        candidate = str(_USER_HOME / suffix) if suffix else str(_USER_HOME)

    candidate = _normalize_windows_path(candidate)
    if candidate and os.path.exists(candidate):
        return candidate, True
    return path_value, False


def migrate_local_user_paths(data):
    changed = False

    if isinstance(data, dict):
        migrated = {}
        for key, value in data.items():
            new_value, item_changed = migrate_local_user_paths(value)
            migrated[key] = new_value
            changed = changed or item_changed
        return migrated, changed

    if isinstance(data, list):
        migrated = []
        for value in data:
            new_value, item_changed = migrate_local_user_paths(value)
            migrated.append(new_value)
            changed = changed or item_changed
        return migrated, changed

    if isinstance(data, str):
        return resolve_migrated_user_profile_path(data)

    return data, False


def migrate_photo_dataframe_paths(df: pd.DataFrame) -> tuple[pd.DataFrame, bool]:
    if df is None or df.empty:
        return df, False

    migrated = df.copy()
    changed = False
    for column in PHOTO_PATH_COLUMNS:
        if column not in migrated.columns:
            continue
        values = []
        for value in migrated[column].tolist():
            new_value, item_changed = resolve_migrated_user_profile_path(value)
            values.append(new_value)
            changed = changed or item_changed
        migrated[column] = values
    return migrated, changed
