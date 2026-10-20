# allo — a Québec French / English phone agent on ElevenLabs, with the proof

Status: design, 2026-10-15. Private repo until Shaw approves publishing.
Purpose: proof-of-work for ElevenLabs, Enterprise Solutions Engineer, Canada
(https://jobs.ashbyhq.com/elevenlabs/0d68b2a2-887e-491c-8b9b-56e8354f75fb).

## The question it answers

A Canadian enterprise asks the SE: "Can an ElevenLabs agent serve our Québec callers on the phone,
in Québec French by default, switching to English when the caller does, and call our systems?"
Nobody has published data on this. Competitor Deepgram says agents cannot switch language mid-call;
others say they can. allo answers it with a working agent and measured results, delivered the way an
SE delivers a POC: agent as code, tests as code, a one-page validation report an AE can hand over.

## The customer scenario

Service line for a fictional Montréal dealer group, "Groupe Auto Laval" (fictional; no real dealer named).
Shaw knows this domain (dealer operations, VinSight). Callers:
1. book or move a service appointment;
2. ask whether their vehicle has an open safety recall (by VIN or year/make/model);
3. ask hours, address, shuttle, loaner policy (knowledge base);
4. ask for a person, or get angry, or ask something out of scope -> transfer to a human.
French by default (Québec Bill 96 practice: greet in French), English on request or when the caller speaks English.

## Architecture

- ElevenAgents agent, defined as code with the ElevenLabs CLI (agent config + tests in the repo, `--dry-run` before push).
  - Voice: a native Québec French voice from the Voice Library + an English voice; language detection on;
    Scribe keyterms for dealer and car vocabulary (VIN letters, model names, "rappel", "entretien", "pneus d'hiver").
  - Knowledge base: one bilingual dealer FAQ document (written for this repo).
  - Webhook tools (server: Cloudflare Worker `allo-tools` on a personal Cloudflare account, with D1 for bookings):
    - `decode_vin(vin)` -> NHTSA vPIC (public, no key).
    - `check_recalls(make, model, year)` -> Transport Canada recall database (public, bilingual: *_ETXT / *_FTXT fields;
      the agent reads the French text to French callers). https://data.tc.gc.ca/v1.3/api/{eng|fra}/vehicle-recall-database/...
    - `find_slots(date_from, service_type)` / `book_appointment(...)` / `move_appointment(...)` -> D1 (fake calendar).
    - Every write tool requires the caller to confirm name, phone, slot read back. Writes log an audit row.
  - System tools: transfer_to_number (human line), end_call, language_detection.
  - Post-call webhook -> Worker stores transcript summary + outcome in D1.
- Telephony: a new Telnyx Montréal number (514/438) on an FQDN SIP connection to ElevenLabs. Separate from every
  existing number on the account; nothing existing changes.

## The proof (what gets measured)

1. Scenario suite: 40 ElevenLabs Simulation tests + tool-call tests, run from the CLI/API, stored as code.
   Mix: 16 Québec French, 12 English, 8 mid-call switches (FR->EN, EN->FR, mid-sentence), 4 adversarial
   (joual / slang, angry caller, prompt-injection-ish "ignore your rules", out-of-scope). Each test has a success
   condition and, where a tool must fire, the expected tool and arguments.
   Reported: pass rate overall and per group, pass^3 (each test run 3 times; all 3 must pass), tool-call accuracy.
2. Language fidelity: for every agent turn, did it answer in the caller's current language? Scored by a
   deterministic language ID on the transcript, checked by an LLM judge on disagreements. Settles the
   mid-call switching question with a number.
3. Voice: Québec voice vs France-French voice vs English-default multilingual voice reading the same 10 French lines.
   Blind A/B rating by a native Québec French speaker (Shaw), randomized order, scored in a small script.
   Small n, stated as such.
4. Phone reality: 10 real calls over the Telnyx line (Shaw places them, scripted from the suite). Per call:
   outcome, language behaviour, transfer behaviour, and per-turn latency from the conversation metadata
   (time to first audio, p50/p90). Real calls are measured, recordings stay private.
5. Cost: credits and agent minutes per call; projected cost per 1,000 calls at Creator vs Business list prices.

## Deliverables

- `agent/` agent config as code; `tests/` scenario suite as code; `worker/` Cloudflare Worker + D1 schema.
- `evals/` runner (Python) that runs the suite N times via API, pulls conversations, scores language fidelity,
  writes `evals/results/<date>.json` and renders `docs/RESULTS.md`.
- `docs/VALIDATION-REPORT.md` — one page, written for a Canadian customer's IT lead: what was tested, results,
  limits, what Enterprise would add (concurrency, residency, SLA). Also a French version.
- README: what it is, the numbers, how to reproduce (`make deploy`, `make eval`).
- A 2-minute screen recording or audio clip of a real switching call (Shaw decides whether to include).

## Rules

- Spend: inside the $250 cap across all three company builds. ElevenLabs Creator ~$11 first month, Telnyx number ~$1/mo.
- No real customer data, no real dealer names, no third-party call recordings. Shaw's voice on test calls is fine; recordings stay private unless Shaw says otherwise.
- Keys only from `pass`; never in the repo. gitleaks before any push.
- Honest numbers: report misses and failures, as mailroom did.

## Phases

0. Accounts (driver): Creator plan, full-scope ElevenLabs API key -> `pass apis/elevenlabs-agents`, Telnyx number + SIP.
1. Worker + D1 + tools; agent as code; first passing Simulation test. 
2. Scenario suite (40) + runner + language scoring; first full run; fix the agent; second run on the same suite;
   then a held-out run on 12 new scenarios written after the agent is frozen.
3. Voice A/B with Shaw; 10 real phone calls.
4. Report, README, private repo review; Shaw approves publishing.
