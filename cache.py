"""
Disk-backed cache for LLM responses and HTTP fetches.

Why this exists: the Gemini free tier allows a limited number of requests per
day per model. A five-pattern pipeline over N repositories makes several calls
per repository, so development re-runs would exhaust the quota almost
immediately. Every response is cached on disk keyed by a hash of its input, so
re-running the pipeline costs nothing for inputs that have already been seen.

This also makes the demo reproducible: the cached run can be replayed without
network access.
"""

import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Optional

CACHE_DIR = Path(__file__).parent / ".cache"


def _key(namespace: str, payload: str) -> Path:
    """Hash the payload into a stable filename under the namespace."""
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]
    folder = CACHE_DIR / namespace
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"{digest}.json"


def get(namespace: str, payload: str) -> Optional[Any]:
    """Return the cached value for this payload, or None if not cached."""
    path = _key(namespace, payload)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))["value"]
    except (json.JSONDecodeError, KeyError):
        return None


def put(namespace: str, payload: str, value: Any) -> None:
    """Store a value for this payload."""
    path = _key(namespace, payload)
    path.write_text(
        json.dumps({"payload": payload, "value": value}, indent=2),
        encoding="utf-8",
    )


def cached(namespace: str, payload: str, produce: Callable[[], Any]) -> Any:
    """
    Return the cached value if present, otherwise call produce(), store the
    result, and return it.

        text = cached("llm", prompt, lambda: llm.invoke(prompt).content)
    """
    hit = get(namespace, payload)
    if hit is not None:
        return hit
    value = produce()
    put(namespace, payload, value)
    return value


def stats() -> dict:
    """Count cached entries per namespace — useful for the demo writeup."""
    if not CACHE_DIR.exists():
        return {}
    return {
        folder.name: len(list(folder.glob("*.json")))
        for folder in CACHE_DIR.iterdir()
        if folder.is_dir()
    }


def clear(namespace: Optional[str] = None) -> None:
    """Delete cached entries — all of them, or just one namespace."""
    target = CACHE_DIR / namespace if namespace else CACHE_DIR
    if not target.exists():
        return
    for path in target.rglob("*.json"):
        path.unlink()
