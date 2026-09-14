# Project 1 — Honeypot Documentation Audit

An agentic pipeline that audits open-source "honeypot" repositories on GitHub
and reports whether their documentation says anything about the ethical or
legal considerations of deploying one.

The agent is not simulated. Every repository it reports on is fetched live from
the GitHub REST API, and every quoted sentence is verified against the text
that was actually retrieved.

## The five patterns

| Pattern | Chapter | Where it lives | What it does here |
|---|---|---|---|
| Tool Use | 5 | `tools.py` | Three real GitHub API tools: repository metadata, README text, documentation file listing |
| Routing | 2 | `pipeline.py :: classify` | Classifies each repository as honeypot / detection_tool / other. Only honeypots continue to extraction; the rest short-circuit. Unrecognised labels fall to a default branch |
| Prompt Chaining | 1 | `pipeline.py :: extract_ethics` | Step 1 reads the documentation and reports ethics-related content as prose. Step 2 converts that prose into structured JSON |
| Reflection | 4 | `pipeline.py :: verify` | A critic checks that every extracted quote really occurs in the source. A deterministic substring check runs first; the LLM critic only adjudicates near-misses. Rejected quotes are discarded |
| Parallelization | 3 | `pipeline.py :: audit_all` | Repositories are audited concurrently with `asyncio.gather`, bounded by a semaphore to respect API rate limits |

## Setup

1. Install [uv](https://docs.astral.sh/uv/) if you do not have it.

2. From the repository root, install dependencies:

   ```
   uv sync
   uv add requests
   ```

3. Create a `.env` file in the repository root:

   ```
   GOOGLE_API_KEY=your_key_here
   ```

   Get a free key at https://aistudio.google.com/apikey.

   Optional:

   ```
   GEMINI_MODEL=gemini-2.5-flash   # override the default model
   GITHUB_TOKEN=ghp_...            # raises GitHub's rate limit from 60 to 5000/hr
   ```

4. Open `demo.ipynb` and select the `.venv` kernel, then run the cells top to
   bottom.

## Running from the command line

```python
import pipeline

repos = ["telekom-security/tpotce", "cowrie/cowrie", "paralax/awesome-honeypots"]
results = pipeline.audit(repos)

print(pipeline.to_table(results))
print(pipeline.summary(results))
```

## Caching

Every model response and every GitHub fetch is cached on disk under
`.cache/`, keyed by a hash of its input.

This matters because the Gemini free tier limits requests per day. Without a
cache, a handful of development runs would exhaust the quota. With it, re-running
the pipeline over repositories already seen costs nothing and needs no network.

To inspect or reset the cache:

```python
import cache
cache.stats()          # entries per namespace
cache.clear("llm")     # force fresh model calls
```

## Notes on model selection

`gemini-2.0-flash` has been retired by Google; the default here is
`gemini-2.5-flash`. If a run returns a 404 naming a replacement model, set
`GEMINI_MODEL` in `.env` accordingly.
