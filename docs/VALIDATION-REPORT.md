# Technical validation — bilingual Québec phone agent on ElevenLabs

**For:** an IT lead at a Canadian company with Québec callers · **System:** allo (demo, fictional
dealer "Groupe Auto Laval") · **Date:** October 2026 · **Status:** suites complete; voice rating
inconclusive; no live calls placed

## Verdict

ElevenLabs can run a French-first phone line for Québec today. French callers were answered in
French on 99–100% of agent turns. Callers who switch language mid-call were followed on 98% of
turns after one round of fixes. **The weak point is the English-first caller.** In full
conversations the agent sometimes stays in French after an English opening line (80–92% of
English-group turns correct). Fix it with deterministic language routing on the first
utterance, not with more prompt work.

## What was tested

| Area | How |
| --- | --- |
| Booking and moving service appointments | Webhook tools into a calendar (Cloudflare Worker + D1) |
| Safety recalls | Live Transport Canada recall API, French or English text |
| FAQ (hours, shuttle, tires, policies) | Bilingual knowledge base with RAG |
| Language behaviour | Every agent turn scored by a deterministic language detector, not by an LLM |
| Robustness | Joual, loanwords, prompt injection, fake authority, angry callers, unclear speech (simulated as text) |

Method: 40 dev scenarios (16 French, 12 English, 8 mid-call switches, 4 adversarial) plus tool-call
tests, each run 3 times on the ElevenLabs simulation API. Then 12 **held-out** scenarios, written
during dev from situations not in the dev suite, kept out of every dev run, and run twice only
after the agent was frozen. No agent change was made because of their results.

## Results

| Measure | Result |
| --- | --- |
| Held-out scenarios, frozen agent (`agent-frozen-v1`) | **16/24 runs (67%)** · 18/24 (75%) excluding 2 test-design errors |
| Held-out language fidelity | **139/140 agent turns (99%)** |
| Dev suite, first run | 79/132 runs (60%); 20/44 tests passed all 3 runs |
| The 24 scenarios with a failure, rerun × 3 after fixes | 19/72 → 44/72 runs; the other 20, as a regression check: 19/20 |
| Language fidelity, first run → after fixes (all 44 scenarios) | French 99% → 100% · mid-call switch 87% → 98% · English 80% → 92% |

The frozen agent carries two changes made after those reruns: a server-side booking token and a
bilingual greeting. They were checked on subsets only. The token run passed 18/24 runs on 8
scenarios. The greeting run passed 2/4, and 2/3 on its regression check, where one switch
scenario missed once: the agent said "One moment." in English after the caller had switched to
French.

Held-out misses, kept as found: cancellation policy not stated in full (2/2 runs); one invented
detail about Wi-Fi; one tire-wear call that offered new tires instead of an inspection or an
advisor; one reply in English to a French caller who gave digits in English; one shortened
read-back after a slot was taken.

## Limits of this evidence

- Simulated callers are text. They test the dialogue logic, not speech recognition of accents,
  phone audio or background noise. No live call was placed, so the phone path is configured
  but untested.
- Small samples: 2–3 runs per scenario. A 67% held-out score has wide error bars.
- One fictional business, one knowledge base. Your FAQ and systems will shift the numbers.
- Voice quality was rated blind by one native Québec speaker. The result is inconclusive: the
  same letter was picked on all six lines. A real answer needs several listeners.
- Built on the Creator plan. Concurrent calls and latency under load were not tested.
- SIP ran over TCP with media encryption allowed, not required. TLS and required SRTP are
  available on every plan and belong in production.

## Recommendation

1. **Route the language before the LLM.** Detect the language of the first caller utterance
   with the speech recogniser and set the session language from it at turn one. Keep the
   LLM-driven `language_detection` tool for later switches, where it scored 98%. Charter of
   the French language practice (as amended by Bill 96) still holds: greet in French first.
2. **Put every write behind a server-side token.** The server refuses a booking or a move
   without a token minted by `prepare_booking`, which freezes the details and returns the exact
   read-back sentence. A write without a server-generated read-back is therefore impossible.
   Whether the caller heard and accepted that read-back still depends on the model; the tests
   measure it, and held-out H01 is one miss. Before the token, the "caller changes a detail
   during the read-back" scenario passed 1 of 3 in two runs; after it, 3 of 3.
3. **Generate test fact lists from the knowledge base.** Hand-copied allow-lists drifted three
   times in this project and caused false fails.
4. **Gate releases on a held-out suite.** Freeze the agent, then run scenarios it was never
   tuned on.

## What an Enterprise deployment adds

- **Concurrency and SLA** sized to call volume; this test ran one call at a time.
- **Data handling:** zero-retention mode, and data residency in the EU, India or Singapore.
  None of these regions is in Canada, so Québec Law 25 requires a privacy impact assessment in
  every configuration before personal information leaves Québec.
- **Network:** a static IP range for outbound SIP allow-lists. This test locked the inbound side
  to the carrier's signaling IPs instead.
- **Integration:** the same webhook-tool pattern connects to a real DMS or CRM; only the Worker
  changes.

Repo, results files and scripts to reproduce every number: `README.md`, `evals/results/`.
