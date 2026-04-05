# GPT4All_local context for Codex

This folder is a read-only context snapshot copied from the `GPT4All_local` repository, branch `sandbox-codex`.

## Purpose
Provide execution and architectural context for validating/adapting AnnotationPhotosGPT-related changes on laptop.

## Main folders
- `flask_server/`: runtime server code on PC fixe
- `config/`: server configuration and local model references
- `docs/app_reference/`: reference documentation for Codex
- `scripts/`: supporting scripts and workflow context

## Important distinction
- `flask_server/` contains the effective Python runtime code
- `docs/app_reference/` contains documentation/reference copies, not the runtime source of truth

## Files of special interest
- `flask_server/create_affaire.py`
- `flask_server/gpt4all_flask.py`
- `docs/app_reference/annotationphotogpt/...`
- `docs/app_reference/openai-adapter/...`

## Status
This snapshot is informative. Validation and integration must be performed in the target laptop-oriented repository.