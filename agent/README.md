# `agent/` — the allo agent as code

Everything that defines the agent on ElevenLabs lives here as a file. Nothing is configured
by clicking around in the dashboard.

| File | What it is |
| --- | --- |
| `agent.json` | the agent definition, with `{{placeholders}}` for values that only exist after provisioning |
| `prompts/system_prompt.md` | the system prompt, kept as markdown because it is prose, not a JSON string |
| `tools/*.json` | the six webhook tools, one file each |
| `deploy.json` | non-secret deployment values: Worker URL, voice ids, transfer number, pass entry names |
| `state.json` | ids ElevenLabs returned (agent, tools, knowledge base, webhook). Written by `push_agent.py` |
| `VOICES.md` | which voices, why, and what was rejected |

## Push

```bash
make push-agent                 # == uv run python scripts/push_agent.py
uv run python scripts/push_agent.py --dry-run
```

The push is idempotent: it looks everything up by name and updates in place, so running it
twice changes nothing. It refuses to push if any `{{placeholder}}` is left unresolved.

Order: workspace secret → knowledge base (+RAG index) → six tools → post-call webhook → agent.

## Secrets

The tools shared secret is **never in this directory**. It lives in `pass` at
`apis/allo-tools-secret` and is uploaded to ElevenLabs as the stored workspace secret
`ALLO_TOOLS_SECRET`. The tools reference it as `{"secret_id": "..."}` in their
`X-Allo-Secret` header, so ElevenLabs injects the value server-side and it never appears in
the config, in a log, or in this repo.

## Choices made, and why

**LLM: `gemini-3.5-flash-lite`.** Picked as the lowest-latency model that handles French well
and is not deprecated, from `GET /v1/convai/llm/list` (110 models). 1M context, parallel tool
calls supported, no deprecation notice. The spec asked for a Gemini Flash class or GPT mini
class model; this is the current non-deprecated Gemini Flash-lite generation. The GPT-mini
alternative is `gpt-5.4-mini`.

**Analysis LLM: `gemini-2.5-flash`.** Only because the platform rejects the agent LLM for
post-call analysis (`LLM 'gemini-3.5-flash-lite' is not supported for analysis`), and
`gemini-2.5-flash` is the platform's own documented default for this field.

**TTS: `eleven_flash_v2_5`.** See `VOICES.md` — chosen because the library voice is verified
for it.

**Languages.** Default `fr`. English is a `language_presets.en` entry that swaps the TTS
voice to the Canadian English voice and sets `agent.language` to `en`. The
`language_detection` system tool is enabled with `only_at_conversation_start: false`, so the
switch can happen at any point in the call, not just in the first two turns. That setting is
the whole point — the mid-call switch is what this build exists to measure.

See "Automatic language switching" below for what the docs say and what dev run 1 changed.

**Transfer number: `+1 514 555-0100` — PLACEHOLDER.** Shaw sets the real human service line
later. 555-01xx is the reserved fictional block, so it cannot ring a real person by accident.

**Post-call webhook.** Created through the API with `auth_type: hmac`, so ElevenLabs signs
every delivery. The signing secret is returned once at creation, stored in `pass` at
`apis/allo-webhook-secret`, and must be set on the Worker as `ELEVENLABS_WEBHOOK_SECRET`
(`cd worker && wrangler secret put ELEVENLABS_WEBHOOK_SECRET`). With it set, the Worker
verifies the signature and rejects a bad one. Without it, the Worker falls back to the shared
header.

**Prompt-injection guardrail: OFF.** The built-in guardrail *aborts the call* when it fires.
In iteration 1 of the suite it hung up on a caller who said "ignore tes instructions", which
made the behaviour both worse than the injection and untestable. Injection resistance is
handled in the system prompt instead and measured by test 05. Documented in `agent.json`
next to the flag.

## Automatic language switching — what the docs say

Source: `elevenlabs.io/docs` (fetched 2026-10-15, via `curl`).

- **`eleven-agents/customization/tools/system-tools/language-detection`.** Switching on
  heard speech *is* supported and it is the `language_detection` system tool that does it.
  The tool "triggers language switching in two cases, both based on the received audio's
  detected language and content": `detection` — "if a user speaks a different language than
  the current output language, a switch will be triggered" — and `content`, when the caller
  asks in the current language to switch. Two conditions: the target language must be one the
  agent supports, and the tool must be enabled. The tool takes `reason` and `language` and is
  called by the LLM, so the switch is *triggered* by the audio but still *executed* by the
  model choosing to call it. The tool's description is explicitly customizable "to
  accommodate your specific use case".
- **`eleven-agents/customization/voice/customization/language`.** Each additional language is
  a `conversation_config.language_presets` entry, and a preset can override conversation
  config per language, including `first_message` and the voice. Additional languages switch
  the agent to the v2.5 multilingual TTS model (English stays on v2) — this agent is already
  on `eleven_flash_v2_5`, so nothing to change.
- **`eleven-agents/customization/conversation-flow`.** The static `soft_timeout_config.message`
  "supports **language overrides**: auto-translates to additional languages configured for
  your agent". The API schema names the field: `language_presets.<lang>.soft_timeout_translation`,
  alongside `language_presets.<lang>.overrides.turn.soft_timeout_config.message`.
- There is **no ASR language auto-detect setting**. `AsrConversationalConfig` exposes
  `quality`, `provider`, `user_input_audio_format` and `keywords` only. Language is an
  agent-level (`agent.language`) plus per-preset property, not an ASR property.
- **Endpoint caveat:** the docs page says language selection is fixed for the duration of the
  call — that sentence sits under *Starting a call* and describes the **widget's** language
  picker, not the agent. Mid-call switching is the documented purpose of the
  `language_detection` tool, with `only_at_conversation_start: false` allowing it on any turn.

## Config changes after dev run 1

Dev run 1 (`docs/RESULTS.md`) had English callers answered in French in E04–E08, A01, A03 and
S03 — the agent only switched on an explicit request. Root cause: nothing told the model to
call `language_detection`, so it just kept answering in the language it was already in.

| Change | Where | Why |
| --- | --- | --- |
| Top-priority per-turn language rule ("call `language_detection` first, on every turn, without being asked"; loanword and mixed-sentence rules) | `prompts/system_prompt.md` | The tool is only called if the model decides to call it. |
| `language_detection` description rewritten to the same effect | `agent.json` | The docs make this description the supported way to steer when the tool fires. |
| `language_presets.en.overrides.turn.soft_timeout_config.message = "One moment."` | `agent.json` | `soft_timeout_config.message` is static, and the FR string was heard on EN calls. Per-language override is the documented fix; the base message stays French for French callers. Verified live: the override round-trips through `PATCH`/`GET`. |
| VIN rules: count 17, never add/drop/change a character, no `decode_vin` below or above 17, read back in groups and get a yes, uppercase, no spaces/dashes; French letter-name list | `prompts/system_prompt.md`, `tools/decode_vin.json` | E03 (silent character added), F04 (VIN corrupted while spelling). |
| `decode_vin` description: the Worker normalizes case and separators but never repairs length | `tools/decode_vin.json` | Keeps the model's job (get the characters right) separate from the tool's (normalize). |
| Booking reference read back character for character, never regenerated; concrete example references removed from the prompt | `prompts/system_prompt.md`, `tools/book_appointment.json` | E01: the agent read out the *example* reference from the prompt instead of the tool's. The examples now say "the five characters the tool returned". |
| Any change after a read-back voids the yes — new full read-back, new yes | `prompts/system_prompt.md` | F15. |
| No claim before a tool result; no detail the KB did not give (no "42 points") | `prompts/system_prompt.md` | F10, E07, F07. |
| Unclear speech: ask again, never guess, never open a booking flow on a guess, transfer after two unclear turns | `prompts/system_prompt.md` | A04. |
| Out-of-scope transfer: name the department in one short sentence, in the caller's language | `prompts/system_prompt.md` | F13. |
| VIN normalization in the Worker (`normalizeVin`: strip spaces/dashes, uppercase, then the unchanged 17-char + no-I/O/Q check) + 2 vitest cases | `worker/src/index.ts`, `worker/test/worker.test.ts` | Defence in depth: whatever the model sends, the boundary normalizes. |

**Other static text, audited.** `first_message` — French by design, and the suite's own
evaluation criterion exempts the first turn ("which is always French by design"), so it is
left alone. `max_conversation_duration_message` — empty, so the agent speaks nothing when the
900 s cap is reached. `silence_end_call_message` — null. `transfer_to_number` has no text
field, only `enable_client_message: true` (a platform-generated message); the transfer
sentence itself comes from the prompt and is therefore already in the caller's language.
There is no other static caller-facing string in the config.

**Not live-verified.** The per-language soft-timeout override round-trips through the API, but
only a real call proves it fires at runtime. Everything else here was verified against the
live agent (prompt byte-for-byte, tool descriptions) and the deployed Worker (`curl`).
