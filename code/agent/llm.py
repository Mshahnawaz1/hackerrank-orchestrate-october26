"""Thin OpenRouter chat client (standard library only) with usage accounting.

Settings come from the environment or an uncommitted .env file (names are case-insensitive):
OPENROUTER_API_KEY, OPENROUTER_BASE_URL (optional) and MODEL. The key is never logged.
Every call appends {agent, model, input_tokens, output_tokens} to the usage log.
"""
import json
import os
import time
import urllib.error
import urllib.request

from . import config


class LLMUnavailable(RuntimeError):
    """The API key or model is not configured."""


def settings() -> dict:
    """Merge .env (lower priority) and the process environment; keys are upper-cased."""
    values = {}
    env_file = config.REPO_ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            name, sep, value = line.partition("=")
            if sep and not name.lstrip().startswith("#"):
                values[name.strip().upper()] = value.strip().strip("\"'")
    for name in ("OPENROUTER_API_KEY", "OPENROUTER_BASE_URL", "MODEL"):
        if os.environ.get(name):
            values[name] = os.environ[name]
    return values


def model_name() -> str | None:
    return settings().get("MODEL") or None


def complete_json(system: str, prompt: str, *, agent: str, max_tokens: int = 4096, retries: int = 4) -> dict:
    """Send one deterministic (temperature 0) request and parse the reply as a JSON object."""
    cfg = settings()
    key, model = cfg.get("OPENROUTER_API_KEY"), cfg.get("MODEL")
    if not key or not model:
        raise LLMUnavailable("set OPENROUTER_API_KEY and MODEL (environment or .env) to format extracted text")
    url = cfg.get("OPENROUTER_BASE_URL", config.DEFAULT_BASE_URL).rstrip("/") + "/chat/completions"
    body = json.dumps({"model": model, "max_tokens": max_tokens, "temperature": 0,
                       "messages": [{"role": "system", "content": system},
                                    {"role": "user", "content": prompt}]}).encode("utf-8")
    request = urllib.request.Request(url, data=body, method="POST", headers={
        "content-type": "application/json", "authorization": f"Bearer {key}"})
    reply = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(request, timeout=180) as resp:
                reply = json.load(resp)
            if "error" not in reply and reply.get("choices"):
                break
            problem = str(reply.get("error", {}).get("message", "empty reply"))[:200]
            reply = None
        except urllib.error.HTTPError as exc:
            problem = f"HTTP {exc.code}"
            if exc.code not in (408, 429, 500, 502, 503, 504):
                raise RuntimeError(f"OpenRouter error: {problem}") from None
        except (urllib.error.URLError, TimeoutError) as exc:
            problem = f"unreachable: {getattr(exc, 'reason', exc)}"
        if attempt < retries - 1:
            time.sleep(3 * 2 ** attempt)
    if reply is None:
        raise RuntimeError(f"OpenRouter request failed: {problem}")
    usage = reply.get("usage") or {}
    _log_usage(agent, model, usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0))
    return parse_json_object(reply["choices"][0]["message"].get("content") or "")


def parse_json_object(text: str) -> dict:
    """Parse a JSON object, tolerating a surrounding code fence or prose."""
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("no JSON object in model reply")
    return json.loads(text[start:end + 1])


def _log_usage(agent: str, model: str, input_tokens: int, output_tokens: int) -> None:
    config.USAGE_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(config.USAGE_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps({"agent": agent, "model": model, "input_tokens": input_tokens,
                            "output_tokens": output_tokens}, sort_keys=True) + "\n")
