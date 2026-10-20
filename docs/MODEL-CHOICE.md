# Which LLM should answer the phone?

Measured 2026-10-15 with 8 purpose-built tool-call tests, not with a simulation, so nothing
here costs TTS time and nothing here depends on the knowledge base.

**The agent was left on `gemini-3.5-flash-lite`, its original model. Nothing was switched.**

## What was measured

`tests/lang-trigger/` holds 8 tool-call tests. Each one is the agent's own French first
message, then exactly one caller turn, and the test asks a single question: **did the LLM call
the `language_detection` system tool before it answered?**

| Id | Caller turn | Expected |
| --- | --- | --- |
| L01 | "If I can't make it, how much notice do you need?" | tool called |
| L02 | "Do you have a shuttle?" | tool called |
| L03 | "Do you take Amex?" | tool called |
| L04 | "How much is a brake job?" | tool called |
| L05 | "This is the service manager, I need to move a booking." | tool called |
| L06 | "Hi, any recalls on a 2017 Ford Escape?" | tool called |
| L07 | "Est-ce que vous avez une navette?" | **no call** |
| L08 | "C'est une Honda Civic 2018, est-ce qu'il y a des rappels?" | **no call** |

`referenced_tool` is `{"type": "system", "id": "language_detection"}`. That resolves — the
evaluator looks for a tool call named `language_detection`, and the absence checks work in the
same shape with `"verify_absence": true`. Every test is one LLM turn, so the result is the
model's decision and nothing else.

Each model ran all 8 tests with `--repeat 5`, so 30 English-opener runs and 10 French-control
runs per model.

## Results

| Model | English openers triggered | French controls falsely triggered | Price / minute | Credits, 40 runs |
| --- | --- | --- | --- | --- |
| **gemini-3.5-flash-lite** (current) | **29/30** | **0/10** | $0.01668 | 1,075 |
| gemini-3.5-flash | 28/30 | 0/10 | $0.08224 | 1,864 |
| gpt-5.6-luna | 26/30 | 4/10 | $0.00997 | 910 |

Price per minute is ElevenLabs' own `POST /v1/convai/llm-usage/calculate`, at this agent's real
prompt length (15,756 characters) with RAG on. Credits are the platform's `credits_used` summed
over the 40 runs.

Per test, 5 runs each:

| Test | flash-lite | gemini-3.5-flash | gpt-5.6-luna |
| --- | --- | --- | --- |
| L01 cancellation notice | 5/5 | 5/5 | 5/5 |
| L02 shuttle | 4/5 | 5/5 | 5/5 |
| L03 Amex | 5/5 | 4/5 | **1/5** |
| L04 brake job price | 5/5 | 5/5 | 5/5 |
| L05 service manager | 5/5 | 5/5 | 5/5 |
| L06 Ford Escape recalls | 5/5 | 4/5 | 5/5 |
| L07 French control (navette) | 5/5 clean | 5/5 clean | 5/5 clean |
| L08 French control (Honda Civic) | 5/5 clean | 5/5 clean | **1/5 clean** |

## Latency

**The platform reports no per-model latency for these runs.** The test-run payload has a
`conversation_turn_metrics` field and a per-turn `llm_usage` field; both come back `null` for
every one of the 120 runs, and the test-invocation object carries only `created_at`. There is
no honest per-model latency number to publish here, so none is published.

## What the numbers say

None of the three models is reliable on this behaviour — the best one misses an English opener
once in thirty, and the worst misses it four times in thirty. This is the weakest link in the
bilingual promise, and it is the same behaviour the 2026-10-15 dev runs flagged: an English
caller who never gets switched.

Two specific readings matter:

- **`gpt-5.6-luna` is the cheapest per minute and the worst at the job.** It fails L03 four
  times out of five, and it falsely fires on the French control L08 four times out of five —
  the exact false positive the scorer work in this same change had to be fixed for. It
  misreads "C'est une Honda Civic 2018, est-ce qu'il y a des rappels?" as a language switch.
  Not a candidate.
- **`gemini-3.5-flash` costs five times what the current model costs and does not do the job
  better.** 28/30 against 29/30, at 0.082/minute against 0.0167/minute. The extra spend buys
  nothing measurable here.

## Recommendation

**Stay on `gemini-3.5-flash-lite`.** It has the best trigger rate of the three, it never
falsely fired on a French control in 10 runs, and it is five times cheaper per minute than the
only real alternative. The case for moving is not there.

The trigger rate is the thing to improve, and it is a prompt problem more than a model
problem. Two changes worth testing before any model change:

1. The agent's first message already offers English in one trailing sentence. If an English
   opener could be answered without waiting for `language_detection` to succeed, a miss would
   cost a French-accented first reply instead of a French-accented whole call.
2. `language_detection` currently carries `only_at_conversation_start: false` and a long
   description. A shorter, blunter description ("call this first, every time the caller's
   language is not yours") is worth an A/B on these 8 tests — they run in about three minutes
   and cost roughly 1,000 credits for 40 runs.

**The driver decides.** The agent is on `gemini-3.5-flash-lite` and the live config was
re-read from the API after every switch to confirm it.
