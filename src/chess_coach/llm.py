"""Local LLM client (Ollama). Standard library only, so there is nothing to install.

The model runs on this machine, so no position or key ever leaves it.
Start the server with `ollama serve` and fetch a model with `ollama pull <name>`.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Protocol

DEFAULT_MODEL = "qwen2.5:7b-instruct"
DEFAULT_HOST = "http://localhost:11434"

Message = dict[str, str]


class LLMError(RuntimeError):
    pass


class ChatClient(Protocol):
    model: str

    def chat(self, messages: list[Message], format: dict | None = None) -> str: ...


class OllamaClient:
    def __init__(
        self,
        model: str | None = None,
        host: str | None = None,
        temperature: float = 0.0,
        seed: int = 0,
        timeout: float = 300.0,
    ) -> None:
        self.model = model or os.environ.get("CHESS_COACH_MODEL", DEFAULT_MODEL)
        self.host = (host or os.environ.get("OLLAMA_HOST", DEFAULT_HOST)).rstrip("/")
        if not self.host.startswith("http"):
            self.host = f"http://{self.host}"
        self.temperature = temperature
        self.seed = seed
        self.timeout = timeout

    def chat(self, messages: list[Message], format: dict | None = None) -> str:
        """`format` is a JSON schema; Ollama then forces the reply to match it."""
        payload: dict = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            # Temperature 0 and a fixed seed keep evaluation runs reproducible.
            "options": {"temperature": self.temperature, "seed": self.seed},
        }
        if format is not None:
            payload["format"] = format
        body = json.dumps(payload).encode()
        req = urllib.request.Request(
            f"{self.host}/api/chat", data=body, headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.load(resp)
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")
            if e.code == 404:
                raise LLMError(
                    f"Model {self.model!r} not found. Run: ollama pull {self.model}\n{detail}"
                ) from e
            raise LLMError(f"Ollama returned HTTP {e.code}: {detail}") from e
        except (urllib.error.URLError, TimeoutError) as e:
            raise LLMError(
                f"Could not reach Ollama at {self.host}. Start it with `ollama serve`."
            ) from e
        return str(data["message"]["content"]).strip()
