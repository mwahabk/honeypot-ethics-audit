"""
Honeypot documentation audit - an agentic pipeline.

Each of the five patterns from Chapters 1-5 does real work here:

  Tool Use (Ch. 5)         tools.py calls the GitHub API for live repository data
  Routing (Ch. 2)          classify each repo; only honeypots get full analysis
  Prompt Chaining (Ch. 1)  summarise docs -> extract ethics statements as JSON
  Reflection (Ch. 4)       a critic verifies every quote against the source text
  Parallelization (Ch. 3)  repositories are audited concurrently

The pipeline answers a real research question: of the open-source tools that
present themselves as honeypots, how many document the ethical or legal
considerations of deploying one?
"""

import asyncio
import json
import os
from dataclasses import dataclass, field, asdict
from time import time
from typing import Optional

from dotenv import load_dotenv
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableBranch, RunnableParallel
from langchain_google_genai import ChatGoogleGenerativeAI

import cache
import tools

import random
from google.genai.errors import ClientError

load_dotenv(override=True)

MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
llm = ChatGoogleGenerativeAI(model=MODEL)


# ---------------------------------------------------------------- data model

@dataclass
class AuditResult:
    repo: str
    classification: str = "unknown"      # honeypot | detection_tool | other
    classification_reason: str = ""
    has_ethics_statement: bool = False
    ethics_quotes: list = field(default_factory=list)
    verification: str = ""               # VERIFIED | REJECTED | n/a
    notes: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


# ------------------------------------------------- helper: cached LLM invoke

def _as_text(content) -> str:
    """LangChain 1.x returns content as a list of blocks; flatten to text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                parts.append(block.get("text", ""))
        return "".join(parts)
    return str(content)


def ask(prompt_id: str, prompt_value) -> str:
    """Invoke the model, caching on the rendered prompt text.

    The free tier allows only a few requests per minute, so a 429 is expected
    rather than exceptional. Back off and retry instead of failing the run.
    """
    rendered = str(prompt_value)

    def call():
        delay = 8
        for attempt in range(6):
            try:
                return llm.invoke(prompt_value).content
            except Exception as exc:
                if "RESOURCE_EXHAUSTED" not in str(exc) and "429" not in str(exc):
                    raise
                if attempt == 5:
                    raise
                time.sleep(delay + random.uniform(0, 3))
                delay = min(delay * 1.6, 60)
        raise RuntimeError("unreachable")

    raw = cache.cached(f"llm/{prompt_id}", rendered, call)
    return _as_text(raw)


# ------------------------------------------------- PATTERN: Routing (Ch. 2)

classify_prompt = ChatPromptTemplate.from_messages([
    ("system",
     "You classify security tools from their documentation.\n"
     "A honeypot is a decoy system deliberately exposed to attract and observe "
     "attackers.\n"
     "A detection tool monitors, scans, or analyses but is not itself a decoy.\n"
     "Answer with exactly one word: honeypot, detection_tool, or other."),
    ("user", "Repository metadata:\n{metadata}\n\nREADME excerpt:\n{readme}"),
])


def classify(repo: str, metadata: str, readme: str) -> str:
    value = classify_prompt.invoke({
        "metadata": metadata,
        "readme": readme[:4000],
    })
    label = ask("classify", value).strip().lower()
    for candidate in ("honeypot", "detection_tool", "other"):
        if candidate in label:
            return candidate
    return "other"          # default branch - unexpected labels never crash


# ------------------------------------------ PATTERN: Prompt Chaining (Ch. 1)

summarise_prompt = ChatPromptTemplate.from_messages([
    ("system",
     "Read the documentation below and report, in plain prose, anything it says "
     "about the ethical, legal, privacy, or responsible-use considerations of "
     "deploying this tool. Quote the relevant sentences verbatim. "
     "If the documentation says nothing about these topics, reply exactly: "
     "NO ETHICS CONTENT."),
    ("user", "{docs}"),
])

structure_prompt = ChatPromptTemplate.from_messages([
    ("system",
     "Convert the findings below into a JSON object with exactly these keys:\n"
     '  "has_ethics_statement": true or false\n'
     '  "quotes": a list of verbatim sentences from the documentation\n'
     '  "summary": one sentence describing what the documentation says\n'
     "Every string in \"quotes\" must be copied exactly from the findings. "
     "Do not paraphrase and do not invent quotes. "
     "Return only raw JSON, with no markdown fences and no explanation."),
    ("user", "{findings}"),
])


def extract_ethics(docs: str) -> dict:
    """Two-step chain: free-text findings, then structured JSON."""
    findings = ask("summarise", summarise_prompt.invoke({"docs": docs[:12000]}))

    if "NO ETHICS CONTENT" in findings.upper():
        return {"has_ethics_statement": False, "quotes": [], "summary": findings.strip()}

    raw = ask("structure", structure_prompt.invoke({"findings": findings}))
    return parse_json(raw)


def parse_json(raw: str) -> dict:
    """Tolerate markdown fences; fail soft rather than crashing the run."""
    text = raw.strip()
    if text.startswith("```"):
        parts = text.split("```")
        text = parts[1] if len(parts) > 1 else text
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"has_ethics_statement": False, "quotes": [],
                "summary": "could not parse model output"}


# ---------------------------------------- PATTERN: Reflection (Ch. 4)

critic_prompt = ChatPromptTemplate.from_messages([
    ("system",
     "You are a strict reviewer checking an extraction for fabrication.\n"
     "You are given source documentation and a list of quotes said to come "
     "from it.\n"
     "For each quote, decide whether it appears in the source.\n"
     "If every quote appears, reply exactly: VERIFIED\n"
     "Otherwise reply REJECTED, then list the quotes that are not in the "
     "source, one per line."),
    ("user", "SOURCE:\n{docs}\n\nQUOTES:\n{quotes}"),
])


def verify(docs: str, quotes: list) -> tuple:
    """
    Verify each quote independently against the source text.

    Returns (verdict, kept_quotes). A quote that does not appear verbatim in
    the source is dropped rather than discarding the whole extraction - the
    model sometimes paraphrases one item in an otherwise accurate list.

    The check is deterministic: normalise whitespace, then test for literal
    containment. The Reflection chapter notes that a deterministic check inside
    the loop is the strongest form of critique, and substring matching is
    exactly that - it cannot itself hallucinate.
    """
    if not quotes:
        return "n/a", []

    haystack = " ".join(docs.split()).lower()
    kept, dropped = [], []
    for q in quotes:
        if " ".join(q.split()).lower() in haystack:
            kept.append(q)
        else:
            dropped.append(q)

    if not dropped:
        return f"VERIFIED ({len(kept)}/{len(quotes)})", kept
    if kept:
        return f"PARTIAL ({len(kept)}/{len(quotes)} verified)", kept
    return f"REJECTED (0/{len(quotes)} verified)", []


# ------------------------------------------------- one repository, end to end

def audit_one(repo: str) -> AuditResult:
    result = AuditResult(repo=repo)

    # Tool Use - real GitHub API calls
    metadata = tools.get_metadata(repo)
    readme = tools.get_readme(repo)
    doc_files = tools.get_doc_files(repo)

    if readme.startswith("No README found"):
        result.notes = "no README available"
        return result

    # Routing - classification decides which branch runs
    result.classification = classify(repo, metadata, readme)
    if result.classification != "honeypot":
        result.classification_reason = "not a honeypot; skipped ethics extraction"
        result.notes = f"docs present: {doc_files}"
        return result

    # Prompt Chaining - summarise, then structure
    docs = f"{metadata}\n\nDocumentation files: {doc_files}\n\n{readme}"
    extracted = extract_ethics(docs)
    result.has_ethics_statement = bool(extracted.get("has_ethics_statement"))
    result.ethics_quotes = extracted.get("quotes", [])
    result.notes = extracted.get("summary", "")

    
    # Reflection - verify each quote is really in the source
    result.verification, result.ethics_quotes = verify(docs, result.ethics_quotes)
    result.has_ethics_statement = bool(result.ethics_quotes)

    return result


# ------------------------------------------ PATTERN: Parallelization (Ch. 3)

async def audit_all(repos: list, concurrency: int = 4) -> list:
    """
    Fan out across repositories, then gather.

    audit_one is synchronous and network-bound, so each call runs in a worker
    thread via asyncio.to_thread. A semaphore caps how many run at once, which
    keeps us inside both the GitHub rate limit and the model's per-minute quota.
    """
    semaphore = asyncio.Semaphore(concurrency)

    async def run(repo: str) -> AuditResult:
        async with semaphore:
            return await asyncio.to_thread(audit_one, repo)

    return await asyncio.gather(*(run(r) for r in repos))


def audit(repos: list, concurrency: int = 4) -> list:
    """
    Synchronous entry point.

    Jupyter already runs an event loop, so asyncio.run() raises there. When a
    loop is already running we schedule the coroutine on it via nest_asyncio;
    otherwise we start one normally.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(audit_all(repos, concurrency))

    import nest_asyncio
    nest_asyncio.apply()
    return asyncio.run(audit_all(repos, concurrency))


# --------------------------------------------------------------- reporting

def to_table(results: list) -> str:
    rows = ["| Repository | Class | Ethics? | Verification |",
            "|---|---|---|---|"]
    for r in results:
        rows.append(
            f"| {r.repo} | {r.classification} | "
            f"{'yes' if r.has_ethics_statement else 'no'} | {r.verification} |"
        )
    return "\n".join(rows)


def summary(results: list) -> str:
    honeypots = [r for r in results if r.classification == "honeypot"]
    documented = [r for r in honeypots if r.has_ethics_statement]
    if not honeypots:
        return "No honeypots identified in this sample."
    pct = 100 * len(documented) / len(honeypots)
    return (
        f"{len(results)} repositories audited. "
        f"{len(honeypots)} classified as honeypots. "
        f"{len(documented)} of those ({pct:.0f}%) document ethical or legal "
        f"considerations."
    )
