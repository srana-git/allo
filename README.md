# allo

A Québec French / English phone agent for a fictional Laval car dealership, built on the
ElevenLabs Agents Platform. The agent, its tools, its tests and its results are all in this repo
as code.

It answers one question a Canadian contact centre asks before it buys: **can an ElevenLabs
agent serve callers in Québec French by default, switch to English when the caller does, and
safely write to a real system?**

**Short answer: yes for French and for mid-call switches, with one measured weak point.**
English-first callers are sometimes answered in French. The fix is architectural, not a prompt
tweak (see the recommendation below). The one-page report for an IT lead is
[`docs/VALIDATION-REPORT.md`](docs/VALIDATION-REPORT.md) ([français](docs/VALIDATION-REPORT.fr.md)).

## The numbers

| What | Result |
| --- | --- |
| Held-out suite, 12 scenarios kept out of every dev run, × 2, on `agent-frozen-v1` | **16/24 runs passed (67%)**. 2 of the 8 fails were my test design, not the agent; without them 18/24 (75%). |
| Language fidelity, held-out (every agent turn, deterministic language ID) | **139/140 turns (99%)** in the caller's language |
| Dev suite, first run, baseline agent (44 tests × 3) | 79/132 runs (60%); 20/44 passed all 3 runs |
| Dev suite after fixes: the 24 scenarios with a failure, rerun × 3 / the other 20 as a regression check | 44/72 runs (was 19/72) / 19/20 |
| Language fidelity by caller group, dev run 1 → after fixes (all 44 scenarios) | French 99% → 100% · mid-call switch 87% → 98% · English 80% → 92% |
| `language_detection` trigger on an English first turn (single-turn tests × 5) | gemini-3.5-flash-lite 29/30, gemini-3.5-flash 28/30, gpt-5.6-luna 26/30 |
| Worker tests (vitest) | 33/33 |
| Voice A/B, 3 voices × 6 lines, blind, one native Québec rater | Inconclusive: the Québec voice was top pick on 3/6 lines, but the rater picked the same letter on all 6 ([details](evals/voice-ab/RESULTS.md)) |
| Live phone calls over the Telnyx SIP trunk | Not run. The trunk is configured and locked and [call scripts](docs/CALL-SCRIPTS.md) are written; no call was placed |

Misses in the held-out run, all real and all kept: cancellation policy not stated in full
(H06, 2/2), one invented detail about the Wi-Fi password (H02), one tire-wear call that offered
new tires instead of an inspection or an advisor (H03), one switch to English when a French
caller said their phone number in English digits (H11), one shortened read-back after a slot
was taken (H01).

`agent-frozen-v1` carries two changes made after the 44/72 and 19/20 runs: the server-side
booking token and the bilingual greeting. They were checked on subsets only: the token run
passed 18/24 runs on 8 scenarios; the greeting run passed 2/4, and 2/3 on its regression check,
where S02 missed once (an English "One moment." after the caller switched to French).

The suite was edited four times: three times for test errors, once to follow the two-step
booking API. Every edit and its reason is in [`evals/SCENARIOS.md`](evals/SCENARIOS.md) and
[`docs/PHASE1-NOTES.md`](docs/PHASE1-NOTES.md). Dev run 1 pass/fail was never re-scored. The
language scorer was revised after run 1; every language number here comes from the final
scorer.

## How it is built

```
caller ── Telnyx (+1 438 number, SIP/TCP, inbound ACL = Telnyx IPs) ── ElevenLabs agent
                                                                         │ webhook tools
                                                     Cloudflare Worker allo-tools + D1
                                                     ├─ decode_vin        NHTSA vPIC
                                                     ├─ check_recalls     Transport Canada, FR/EN text
                                                     ├─ find_slots        fake service calendar
                                                     ├─ prepare_booking → token + read-back sentence
                                                     ├─ book_appointment / move_appointment (token + confirmed)
                                                     └─ lookup_appointment
```

- **Voices:** a Québec French voice by default, a Canadian English voice through the `en`
  language preset; `language_detection` is on for the whole call, not only the first turns.
- **LLM:** `gemini-3.5-flash-lite`, chosen on measured trigger accuracy and price
  ([`docs/MODEL-CHOICE.md`](docs/MODEL-CHOICE.md)).
- **Writes are gated in code, not only in the prompt.** `prepare_booking` freezes the details
  and returns a read-back sentence and a token. The Worker refuses `book_appointment` and
  `move_appointment` without that token and `confirmed: true`, so no write can happen without a
  server-generated read-back. Whether the caller heard and accepted it still depends on the
  model; the W-rule tests measure that.
- **No live transfer.** When the caller wants a person, the agent names the right department,
  promises a callback and ends the call. The post-call webhook stores the call summary and the
  collected fields (intent, transferred, booking ref) in D1.
- **Recalls come only from Transport Canada.** The tool returns the French or English text
  from the government record; the prompt forbids describing any recall the tool did not return.

## Reproduce it

```bash
make install         # npm install in worker/, uv sync at the root
make deploy-worker   # D1 schema + seed, Worker secrets, wrangler deploy
make push-agent      # agent/, its tools and the knowledge base to ElevenLabs
make test-agent      # run a suite, write evals/results/
make test-worker     # the Worker's vitest suite
make lint            # python compile, tsc, gitleaks
```

`scripts/run_tests.py --suite tests/heldout --repeat 2` reruns the held-out suite;
`--fixture` reseeds the calendar first. Keys come from `pass`; nothing secret is in this repo.

## Layout

```
agent/     the agent as code: config, system prompt, tool schemas, voices
kb/        the bilingual FAQ the agent answers from (fictional dealer)
worker/    Cloudflare Worker (TypeScript) + D1 schema and seed + vitest suite
tests/     suite-v1 (44 dev tests), heldout (12), lang-trigger (8)
evals/     scenario specs, results (one JSON per run), voice A/B clips
scripts/   runner, language scorer, report, push, voice A/B scorer
docs/      validation report, results, model choice, telephony, call scripts
```

## Versions

- `agent-frozen-v1`: the agent the held-out numbers belong to.
- `v1.1-phone`: the live-call version. Transfer replaced by callback + hang-up, and one prompt
  example fixed (an English caller was answered in French in the example itself). Not
  re-measured.

Groupe Auto Laval is fictional. No real dealer, customer or recording is in this repo.
