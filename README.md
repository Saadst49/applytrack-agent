# ApplyTrack Agent

ApplyTrack Agent is a bounded Job Application Tracker for fictional sandbox records. It helps a user search applications, add a new record, update an existing record, and prepare a follow-up draft without sending messages or taking actions on external services.

## Problem statement

The narrow operational goal is to turn natural-language job-search requests into safe, validated changes or read-only results in a small application tracker. A request is complete only when the intended sandbox operation has a validated result, or when the assistant clearly asks for missing or ambiguous information.

## Agent Design Canvas

1. **Operational goal:** Maintain and query fictional job application records.
2. **Completion condition:** A validated search, add, update, or draft result satisfies the request; otherwise the agent asks for clarification, blocks an unsafe action, or reports a bounded failure.
3. **System boundary:** The agent can access only the in-memory sandbox repository and registered local tools. It cannot access job portals, email, LinkedIn, or real accounts.
4. **Observations:** User request, bounded conversation history, runtime state, trusted tool results, and explicitly labeled untrusted external content.
5. **Actions/tools:** `search_applications`, `add_application`, `update_application`, and `generate_followup_draft`.
6. **State:** Per-run agent state plus bounded per-session conversation history and a session-scoped sandbox repository.
7. **Autonomy boundary:** No real submission, external email, login, withdrawal, or external account mutation. Follow-ups are drafts only.
8. **Primary risks:** Ambiguous records, invented critical fields, prompt injection, malformed model output, tool failure, repeated actions, and unbounded execution.
9. **Evaluation criteria:** Task success, contract validity and repair, correct action selection, safe handling of ambiguity and untrusted content, bounded steps, retry behavior, latency, and provider usage when available.

## Architecture

```text
OBSERVE -> DECIDE -> VALIDATE -> ACT -> OBSERVE RESULT
```

The application owns decision validation, typed tool validation, semantic checks, retries, step limits, and stopping. The model proposes one `AgentDecision`; it does not directly mutate state or decide whether a tool result is trustworthy.

## Tools

- `search_applications`: Search by optional `application_id`, `company`, or `role`.
- `add_application`: Add a record with required `company`, `role`, `application_date`, and `status`; optional URL, location, deadline, and notes are supported.
- `update_application`: Update an identified record. `application_id` is required and at least one update field must be provided.
- `generate_followup_draft`: Produce a draft for an `application_id`, with optional purpose and context. It never sends the draft.

All tools are registered in a central gateway. Inputs and outputs are validated with Pydantic models. Repository mutations are guarded by duplicate, missing-record, no-change, and malformed-output handling.

## Prompt and context design

The system prompt is the authoritative policy. Each decision prompt separates:

- trusted system policy and autonomy rules;
- lower-priority conversation history;
- the current user request;
- runtime state as data;
- external content labeled untrusted data only;
- the latest validated tool observation.

The prompt includes compact tool signatures derived from the real Pydantic input contracts and instructs the model to use observations instead of repeating resolved searches or state changes.

## Structured contract

`AgentDecision` contains a status, optional action, arguments, and optional user message.

Statuses are `continue`, `needs_clarification`, `completed`, `blocked`, and `failed`. The allowed actions are the four registered tools above. Pydantic validation checks the shape, allowed status/action combinations, required messages, and tool argument fields. Semantic validation and the tool gateway then check registered actions, typed arguments, duplicates, missing records, and meaningful updates.

## Reliability

- **Ambiguity:** Search results with multiple matches lead to clarification instead of guessing.
- **Prompt injection:** External recruiter or job text is data only and cannot override system policy.
- **Invalid decisions:** The bounded repair path asks for a corrected contract and returns `contract_error` when repair is exhausted.
- **Tool timeout:** A timeout receives bounded retries and becomes `tool_error` if the retry budget is exhausted.
- **Malformed tool output:** The gateway validates output and restores a mutation snapshot before retrying.
- **Execution budget:** The configured maximum step count includes decision and repair work.
- **Autonomy boundary:** Real submissions, external email, logins, and external mutations are blocked; drafting remains local and draft-only.

## Memory and state policy

Chat history is bounded to six recent turns (12 messages) and a 24,000-character ceiling, with at most 100 sessions retained. Chat application records are stored in a separate session-scoped in-memory sandbox repository. Reset clears both conversation history and that repository. `/arena/run` creates isolated per-request repository state and does not use chat history. All in-memory state is lost on server restart, and deployment assumes one worker.

## Cost and budget controls

- Maximum agent steps: 6, configurable within the contract limit.
- Maximum tool/contract repair retries: 2.
- Maximum model output tokens: 512 by default.
- Run timeout: 40 seconds maximum.
- Response size is bounded at 50,000 bytes.

Unknown provider token usage and cost are recorded as `null`, never as fabricated zeroes.

## Testing evidence

Verified locally:

- **29/29 unit tests pass**
- **13/13 deterministic public Arena cases pass**

The deterministic tests use scripted models and do not call Gemini.

## Model-selection experiment

The comparison harness is implemented in `evaluation/run_model_comparison.py` and uses the same 10 cases for every requested model. It records task success, structured-output validity and repairs, action selection, latency, provider token metadata, and explicitly configured costs.

The first real run was quota-limited and is archived as:

- `evaluation/model_comparison_results_quota_limited.json`
- `evaluation/model_comparison_results_quota_limited.csv`

A final balanced two-model comparison and default-model recommendation are still pending provider quota availability. No final recommendation is claimed here.

## Local setup

Use Python 3.12 or newer on Windows:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Set `MODEL_PROVIDER=gemini`, a valid `MODEL_NAME`, and `GEMINI_API_KEY` in `.env`. Never commit `.env`.

Start the app:

```powershell
.\.venv\Scripts\python.exe run.py
```

Open `http://127.0.0.1:8000/` or `/docs`.

Run tests:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe evaluation\run_public_tests.py
```

The model comparison is intentionally separate and can incur provider cost:

```powershell
.\.venv\Scripts\python.exe evaluation\run_model_comparison.py --models MODEL_A MODEL_B --resume
```

## Deployment

Render can run the service as a one-worker Web Service:

- Build command: `pip install -r requirements.txt`
- Start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT --workers 1`
- Health check: `/health`

Configure `MODEL_PROVIDER`, `MODEL_NAME`, and the provider key through Render environment settings. Do not upload `.env`. `render.yaml` remains compatible with this setup. Verify `/health`, the browser interface, and `/docs` after deployment.

### Deployment checklist

1. Push the final code to a private GitHub repository.
2. Invite the instructor or required collaborator.
3. Create a Render Web Service from that repository.
4. Configure secret environment variables in Render.
5. Deploy with one worker.
6. Verify `/health`, `/arena/run`, `/arena/manifest`, `/docs`, and the browser interface externally.
7. Record the final commit hash.
8. Update `SUBMISSION.md` with the repository and live-service metadata.
9. Create the final ZIP and PDF submission package.

## Limitations

- Records are fictional sandbox data only.
- No real email is sent.
- No real job application is submitted.
- Persistence is in-memory and lost on restart.
- One-worker deployment is assumed for session isolation.
- Provider availability, quota, latency, and pricing can limit real model experiments.
