"""
Real tools for the honeypot documentation audit.

PATTERN: Tool Use (Chapter 5)

These are not simulated handlers. Each function performs a real network call
against the GitHub REST API and returns real data. The agent's knowledge of a
repository comes entirely from what these tools retrieve, which is what makes
the provenance checks in reflection.py meaningful: every claim the pipeline
makes can be traced back to text that was actually fetched.

No authentication is required for public repositories at low request volume.
GitHub allows 60 unauthenticated requests per hour per IP; set GITHUB_TOKEN in
.env to raise that to 5000 if you need it.
"""

import base64
import os
from typing import Optional

import requests
from langchain_core.tools import tool

import cache

API = "https://api.github.com"
TIMEOUT = 20


def _headers() -> dict:
    headers = {"Accept": "application/vnd.github+json"}
    token = os.getenv("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _get_json(url: str) -> Optional[dict]:
    """GET a JSON endpoint, caching the response on disk."""

    def fetch():
        response = requests.get(url, headers=_headers(), timeout=TIMEOUT)
        if response.status_code != 200:
            return {"_error": response.status_code}
        return response.json()

    result = cache.cached("github", url, fetch)
    if isinstance(result, dict) and "_error" in result:
        cache.put("github", url, None)   # don't persist transient failures
        return None
    return result


@tool
def fetch_repo_metadata(repo: str) -> str:
    """Fetch a GitHub repository's description, topics, stars, and language.

    Args:
        repo: repository in "owner/name" form, e.g. "telekom-security/tpotce"
    """
    data = _get_json(f"{API}/repos/{repo}")
    if not data:
        return f"Could not fetch metadata for {repo}."
    return (
        f"Repository: {data.get('full_name')}\n"
        f"Description: {data.get('description') or '(none)'}\n"
        f"Topics: {', '.join(data.get('topics', [])) or '(none)'}\n"
        f"Language: {data.get('language') or '(unknown)'}\n"
        f"Stars: {data.get('stargazers_count', 0)}\n"
        f"Archived: {data.get('archived', False)}"
    )


@tool
def fetch_readme(repo: str) -> str:
    """Fetch the full README text of a GitHub repository.

    Args:
        repo: repository in "owner/name" form
    """
    data = _get_json(f"{API}/repos/{repo}/readme")
    if not data or "content" not in data:
        return f"No README found for {repo}."
    try:
        return base64.b64decode(data["content"]).decode("utf-8", errors="replace")
    except Exception as exc:  # noqa: BLE001
        return f"Could not decode README for {repo}: {exc}"


@tool
def list_doc_files(repo: str) -> str:
    """List documentation-like files at the root of a repository.

    Useful when ethics or legal statements live in LICENSE, DISCLAIMER,
    CONTRIBUTING, or a docs/ folder rather than the README.

    Args:
        repo: repository in "owner/name" form
    """
    data = _get_json(f"{API}/repos/{repo}/contents/")
    if not isinstance(data, list):
        return f"Could not list files for {repo}."
    interesting = [
        item["name"]
        for item in data
        if item["name"].lower().startswith(
            ("readme", "license", "disclaimer", "legal", "notice",
             "contributing", "code_of_conduct", "security", "docs")
        )
    ]
    return ", ".join(interesting) if interesting else "(no documentation files found)"


# Plain (non-@tool) versions for direct use inside the pipeline, where we call
# the functions ourselves rather than letting an LLM choose them.
def get_metadata(repo: str) -> str:
    return fetch_repo_metadata.invoke({"repo": repo})


def get_readme(repo: str) -> str:
    return fetch_readme.invoke({"repo": repo})


def get_doc_files(repo: str) -> str:
    return list_doc_files.invoke({"repo": repo})


ALL_TOOLS = [fetch_repo_metadata, fetch_readme, list_doc_files]
