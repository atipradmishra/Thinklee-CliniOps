"""OpenAI model choices shared by agent settings and generation services."""

import re

DEFAULT_MODEL = "gpt-5.6-sol"
LIGHTWEIGHT_MODEL = "gpt-6-luna"


def resolve_model(model):
    name = (model or "").strip()
    legacy = name.lower()
    if legacy.startswith(("gpt-4o", "gpt-4.1", "chatgpt-4o")):
        return LIGHTWEIGHT_MODEL
    if not name or re.match(r"^gpt-[1-4](?:[.-]|$)", legacy):
        return DEFAULT_MODEL
    return name


def agent_model_options(model, temperature):
    name = resolve_model(model)
    if name in (DEFAULT_MODEL, LIGHTWEIGHT_MODEL):
        return {"model": name}
    return {"model": name, "temperature": temperature}
