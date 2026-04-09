from __future__ import annotations

from typing import Any


_STRUCTURED_ROOT_KEYS = (
    "structured_affaire_captation",
    "affaire_captation",
    "structured_config",
)


def _as_clean_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _extract_id_from_node(node: Any, keys: tuple[str, ...]) -> str:
    if not isinstance(node, dict):
        return ""
    for key in keys:
        if key in node:
            value = _as_clean_str(node.get(key))
            if value:
                return value
    return ""


def _extract_structured_id(infos: dict, entity: str) -> str:
    """Extraction tolérante d'ID depuis un overlay structuré optionnel.

    Fail-open: toute structure invalide est ignorée et renvoie "".
    """
    if not isinstance(infos, dict):
        return ""

    if entity == "affaire":
        entity_keys = ("affaire", "project")
        id_keys = ("id_affaire", "project_id", "id")
    else:
        entity_keys = ("captation",)
        id_keys = ("id_captation", "captation_id", "id")

    try:
        for root_key in _STRUCTURED_ROOT_KEYS:
            root = infos.get(root_key)
            if not isinstance(root, dict):
                continue

            # Variante 1: root[entity] = {...}
            for ek in entity_keys:
                value = _extract_id_from_node(root.get(ek), id_keys)
                if value:
                    return value

            # Variante 2: root contient directement les clés d'identifiant
            value = _extract_id_from_node(root, id_keys)
            if value:
                return value
    except Exception:
        # Fail-open strict: jamais bloquer le flux legacy.
        return ""

    return ""


def normalize_infos_aliases(infos: dict) -> dict:
    """Normalise les alias affaire/captation sans casser le contrat legacy.

    Règles:
    - id_affaire/id_captation restent les pivots legacy.
    - project_id/captation_id sont des alias additifs.
    - overlay structuré optionnel, utilisé seulement en secours.
    - fail-open: aucune exception propagée.
    """
    if not isinstance(infos, dict):
        return infos

    try:
        legacy_affaire = _as_clean_str(infos.get("id_affaire"))
        legacy_captation = _as_clean_str(infos.get("id_captation"))

        alias_affaire = _as_clean_str(infos.get("project_id"))
        alias_captation = _as_clean_str(infos.get("captation_id"))

        structured_affaire = _extract_structured_id(infos, "affaire")
        structured_captation = _extract_structured_id(infos, "captation")

        resolved_affaire = legacy_affaire or alias_affaire or structured_affaire
        resolved_captation = legacy_captation or alias_captation or structured_captation

        # Legacy d'abord (pivot inchangé)
        if resolved_affaire:
            infos["id_affaire"] = resolved_affaire
        if resolved_captation:
            infos["id_captation"] = resolved_captation

        # Alias additifs (jamais substitutifs)
        if resolved_affaire:
            infos["project_id"] = resolved_affaire
        if resolved_captation:
            infos["captation_id"] = resolved_captation

        return infos
    except Exception:
        # Fail-open global
        return infos
