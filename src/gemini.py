"""Minimal Gemini REST client (stdlib only). Key from GEMINI_API_KEY; model from GEMINI_MODEL."""
import json
import os
import urllib.error
import urllib.request

DEFAULT_MODEL = "gemini-2.5-flash"


class GeminiError(Exception):
    pass


def get_api_key():
    return os.environ.get("GEMINI_API_KEY") or None


def call(prompt, system=None, json_mode=False, key=None, timeout=60):
    key = key or get_api_key()
    if not key:
        raise GeminiError("GEMINI_API_KEY is not set")
    model = os.environ.get("GEMINI_MODEL", DEFAULT_MODEL)
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    if system:
        payload["systemInstruction"] = {"parts": [{"text": system}]}
    if json_mode:
        payload["generationConfig"] = {"responseMimeType": "application/json"}
    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json", "x-goog-api-key": key})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.load(r)
        text = "".join(p.get("text", "") for p in data["candidates"][0]["content"]["parts"])
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:300]
        raise GeminiError(f"HTTP {e.code}: {body}") from e
    except Exception as e:
        raise GeminiError(str(e)) from e
    if not text.strip():
        raise GeminiError("empty response")
    return text