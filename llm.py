"""Pluggable LLM layer — keeps AI features cheap.

Provider priority is cost-first: a local Ollama model (free) is used when
reachable, then Google Gemini (cheap), then optionally Anthropic Claude. All
calls are plain HTTP (the `requests` dependency the app already uses) so there
is no heavy SDK and no provider lock-in. No Streamlit dependency here — the
caller passes a plain config dict.
"""
from __future__ import annotations

import requests

OLLAMA_DEFAULT_HOST = "http://localhost:11434"
OLLAMA_DEFAULT_MODEL = "llama3.1"
GEMINI_DEFAULT_MODEL = "gemini-2.0-flash"
CLAUDE_DEFAULT_MODEL = "claude-haiku-4-5"  # cheapest Claude tier for cost-sensitive use


def ollama_up(cfg):
    host = cfg.get("OLLAMA_HOST") or OLLAMA_DEFAULT_HOST
    try:
        r = requests.get(f"{host}/api/tags", timeout=2)
        return r.status_code == 200
    except requests.RequestException:
        return False


def active_provider(cfg):
    """Return the cheapest available provider, or None."""
    if ollama_up(cfg):
        return "ollama"
    if cfg.get("GEMINI_API_KEY"):
        return "gemini"
    if cfg.get("ANTHROPIC_API_KEY"):
        return "claude"
    return None


def provider_label(cfg):
    p = active_provider(cfg)
    if p == "ollama":
        return f"Ollama · {cfg.get('OLLAMA_MODEL') or OLLAMA_DEFAULT_MODEL} (local, free)"
    if p == "gemini":
        return f"Gemini · {cfg.get('GEMINI_MODEL') or GEMINI_DEFAULT_MODEL} (cheap)"
    if p == "claude":
        return f"Claude · {cfg.get('ANTHROPIC_MODEL') or CLAUDE_DEFAULT_MODEL}"
    return None


def _ollama(prompt, cfg):
    host = cfg.get("OLLAMA_HOST") or OLLAMA_DEFAULT_HOST
    model = cfg.get("OLLAMA_MODEL") or OLLAMA_DEFAULT_MODEL
    r = requests.post(
        f"{host}/api/generate",
        json={"model": model, "prompt": prompt, "stream": False},
        timeout=120,
    )
    r.raise_for_status()
    return r.json().get("response", "").strip()


def _gemini(prompt, cfg):
    model = cfg.get("GEMINI_MODEL") or GEMINI_DEFAULT_MODEL
    key = cfg["GEMINI_API_KEY"]
    r = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        params={"key": key},
        json={"contents": [{"parts": [{"text": prompt}]}]},
        timeout=60,
    )
    r.raise_for_status()
    cands = r.json().get("candidates", [])
    if not cands:
        return ""
    parts = cands[0].get("content", {}).get("parts", [])
    return "".join(p.get("text", "") for p in parts).strip()


def _claude(prompt, cfg):
    model = cfg.get("ANTHROPIC_MODEL") or CLAUDE_DEFAULT_MODEL
    r = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": cfg["ANTHROPIC_API_KEY"],
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": model,
            "max_tokens": 1024,
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=60,
    )
    r.raise_for_status()
    blocks = r.json().get("content", [])
    return "".join(b.get("text", "") for b in blocks if b.get("type") == "text").strip()


def generate(prompt, cfg, provider=None):
    """Run a prompt through the chosen (or cheapest available) provider.

    Returns (text, provider_used). On failure returns (None, error_string).
    """
    cfg = cfg or {}
    provider = provider or active_provider(cfg)
    if not provider:
        return None, "no_provider"
    try:
        if provider == "ollama":
            return _ollama(prompt, cfg), "ollama"
        if provider == "gemini":
            return _gemini(prompt, cfg), "gemini"
        if provider == "claude":
            return _claude(prompt, cfg), "claude"
    except requests.RequestException as e:
        return None, f"error: {e}"
    return None, "no_provider"
