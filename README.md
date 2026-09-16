# Project 1 - Honeypot Documentation Audit

**CSCI 5996 - Agentic AI**
Muhammad Wahab Khan 

An agentic pipeline that audits open-source "honeypot" repositories on GitHub
and reports whether their documentation says anything about the ethical or
legal considerations of deploying one.

The agent is not simulated. The examples in Chapters 1-5 use placeholder
handlers - `booking_handler(req)` returns the string `"Booking Handler
processed '{req}'"` and nothing is booked. This pipeline calls the live GitHub
REST API. Every repository it reports on is fetched at run time, and every
quoted sentence is checked against the text that was actually retrieved.

**Result:** of 9 honeypot repositories audited, 1 (11%) documents ethical or
legal considerations of deployment in its repository documentation.

## Quick start

Open **`demo.ipynb`** and run the cells top to bottom. It walks through all five
patterns with saved output, and the committed cache means it runs without an API
key or any quota. Full setup instructions are below if you want to run it fresh
against new repositories.

## The five patterns

| Pattern | Chapter | Where it lives | What it does here |
|---|---|---|---|
| Tool Use | 5 | `tools.py` | Three real GitHub API tools: repository metadata, README text, documentation file listing |
| Routing | 2 | `pipeline.py :: classify` | Classifies each repository as honeypot / detection_tool / other. Only honeypots continue to extraction; the rest short-circuit. An unrecognised label falls through to a default branch, so the router can never crash a run |
| Prompt Chaining | 1 | `pipeline.py :: extract_ethics` | Step 1 reads the documentation and reports ethics-related content as prose, quoting verbatim. Step 2 converts that prose into structured JSON |
| Reflection | 4 | `pipeline.py :: verify` | Each extracted quote is verified independently against the source. Whitespace is normalised and containment tested literally - a deterministic check that cannot itself hallucinate. Quotes that fail are dropped and the rest kept, so one paraphrase does not discard an otherwise sound extraction |
| Parallelization | 3 | `pipeline.py :: audit_all` | Repositories are audited concurrently with `asyncio.gather`, bounded by a semaphore to respect API rate limits |

## Setup

1. Install [uv](https://docs.astral.sh/uv/) if you do not have it.

2. From the project folder, create the environment and install dependencies:

   ```
   uv init --no-workspace
   uv add langchain-google-genai langchain-core requests python-dotenv ipykernel nest-asyncio
   ```

3. Create a `.env` file in the project folder (see `.env.example`):

   ```
   GOOGLE_API_KEY=your_key_here
   GEMINI_MODEL=gemini-3.6-flash
   ```

   Get a free key at https://aistudio.google.com/apikey.

   `GEMINI_MODEL` is required, not optional. Google retires model names
   regularly - `gemini-2.0-flash` and `gemini-2.5-flash` were both withdrawn
   during development of this project. If a run fails with a 404, the error
   message names the current replacement; set it here.

   Optional:

   ```
   GITHUB_TOKEN=ghp_...   # raises GitHub's rate limit from 60 to 5000/hr
   ```

   To re-run the committed results only, no key is needed at all - see
   [Caching](#caching) below.

4. Open `demo.ipynb`, select the `.venv` kernel, and run the cells top to
   bottom.

## Running from the command line

```python
import pipeline

repos = ["cowrie/cowrie", "telekom-security/tpotce", "thinkst/opencanary"]
results = pipeline.audit(repos)

print(pipeline.to_table(results))
print(pipeline.summary(results))
```

In a notebook, use the async entry point directly instead, since Jupyter
already runs an event loop:

```python
results = await pipeline.audit_all(repos, concurrency=3)
```

## Files

| File | Purpose |
|---|---|
| `demo.ipynb` | Walkthrough of all five patterns with live output - start here |
| `pipeline.py` | Routing, chaining, reflection, parallelization, reporting |
| `tools.py` | GitHub API tools |
| `cache.py` | Disk cache for model responses and HTTP fetches |
| `debug.py` | Diagnostic for inspecting extracted quotes against their source |
| `results.json` | Output of the most recent run |

## Caching

Every model response and every GitHub fetch is cached on disk under `.cache/`,
keyed by a hash of its input.

This matters because the Gemini free tier limits requests per day. Without a
cache, a handful of development runs would exhaust the quota. With it,
re-running the pipeline over repositories already seen costs nothing and needs
no network, which also makes the demo reproducible.

**The `.cache/` directory is committed to this repository**, so `demo.ipynb`
can be re-run end to end with no API key and no quota. Delete it, or call
`cache.clear()`, to force fresh calls.

```python
import cache
cache.stats()          # entries per namespace
cache.clear("llm")     # force fresh model calls
```

## Notes on the reflection design

The Reflection chapter presents an LLM critic, and notes separately that a
deterministic check inside the loop - tests, validators - is the strongest form
of critique. Both were implemented here and compared.

The deterministic check won. Normalising whitespace and testing for literal
containment answers "is this quote really in the source?" exactly, cannot
itself hallucinate, and costs no quota. The LLM critic (`critic_prompt`, still
present in `pipeline.py`) adds uncertainty to a question that already has a
certain answer. It is retained to document the comparison.

Verification is also per quote rather than per extraction. The first version
rejected a whole extraction if any quote failed. On `telekom-security/tpotce`
that discarded three verbatim quotes because a fourth had been paraphrased, and
the repository was wrongly recorded as documenting nothing. Checking each quote
independently keeps the sound ones and drops only the invented one.

## Scope and limitations

The audit reads only what the repository itself publishes: metadata, README,
and root-level documentation files. Cowrie's full documentation lives at
docs.cowrie.org, off-repo and outside this scope. The claim is therefore that
*the repository documentation* does not address ethics, not that the project
never does.

Routing decisions come from an LLM reading a README, and no ground-truth labels
exist for this corpus, so no accuracy figure is claimed. The three non-honeypot
repositories in the input set (a link list, a threat-intelligence SDK, and a
threat-sharing platform) were all classified as something other than honeypot,
which shows the router discriminates, but a hand-labelled sample would be
needed to state an accuracy figure. A rule-based triage layer in front of the
LLM router - as the Routing chapter suggests - would also cut cost, since
repositories with `honeypot` in their GitHub topics need no model call at all.