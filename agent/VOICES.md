# Voices

Chosen 2026-10-15 from the ElevenLabs shared voice library, via
`uv run python scripts/pick_voices.py`. The full candidate dump is in
`evals/results/voices-<timestamp>.json`.

## What the agent uses

| Role | voice_id | Library name | Accent (library) | Use case | Gender |
| --- | --- | --- | --- | --- | --- |
| **Primary (French, default)** | `UJCi4DDncuo0VJDSIegj` | Amélie - Young, Confident and Friendly | `quebec` / fr-CA | `conversational` | female |
| **English (`language_presets.en`)** | `3dFvxgatkQD7GURadL7Y` | Danielle | `canadian` | `conversational` | female |

### Why Amélie is the French voice

- **Accent.** `quebec`, locale `fr-CA`. This is the whole point of the build: a Québec
  caller should hear Québec French, not France French.
- **Use case.** `conversational`, and the voice's own description says it is *"ideal for
  phone systems and IVR, professional business p…"* — a voice authored for exactly this job.
- **Track record.** 92.1M characters used in the last year, verified across 44
  language/model combinations (including `eleven_flash_v2_5`, the TTS model we run).
  High usage on a library voice is the closest thing to a reliability signal the API offers.
- **Gender matches the persona.** The agent introduces itself as "Léa", so the voice must be
  female, or the first sentence is a lie.
- **Free to use** (`free_users_allowed: true`), so it stays usable if the workspace tier changes.

Runners-up, in order: `WW0JfNPk5DgcQdM0d6X6` (Claudia — warm, confident, Québec,
conversational, 12.4M chars) and `J5dDk0L6xsLExSLfGlBE` (Julia — courteous and warm, but a
`narrative_story`-adjacent description and only 479k chars of usage).

### Why Danielle is the English voice

- Accent `canadian`, use case `conversational`, verified across 41 language/model combos.
  A Laval dealer's English line should not sound American; a Canadian accent keeps the same
  business on both sides of the language switch.
- Female, so the agent keeps one persona across the switch instead of changing sex mid-call.
- Backup if it is ever unavailable: `k56mKR2rds72oUAqTsob` (Megan — expressive, playful,
  Canadian, conversational) or `WW6sLeD5qongZzLpuGuQ` (Aubrey — warm, natural, Canadian).

## Recorded for the Phase 3 A/B (not used by the agent)

| Role | voice_id | Library name | Accent | Use case |
| --- | --- | --- | --- | --- |
| **France French comparison** | `YxrwjAKoUKULGd0g8K9Y` | Lucie - Support Agent | `standard` (France) | `conversational` |

Lucie is the right comparison voice because she is also a *support agent* voice, so the A/B
isolates accent rather than use case. Phase 3 reads the same ten French lines with Amélie,
Lucie and Danielle and Shaw rates them blind.

## Not added to the account — and why that is fine

`POST /v1/voices/add/{public_user_id}/{voice_id}` returns
`missing_permissions: voices_write` for the current API key, so none of the three voices
was copied into the workspace. **They do not need to be.** Verified live 2026-10-15:

- `POST /v1/text-to-speech/UJCi4DDncuo0VJDSIegj` with `eleven_flash_v2_5` returns HTTP 200
  and a 51 KB MP3 — a shared voice id works directly.
- The agent accepted the same ids in `tts.voice_id` and
  `language_presets.en.overrides.tts.voice_id` and was created without error.

If Shaw wants the voices copied into the workspace (so they survive the library removing
them), the fix is on the key, not the code: add the `voices_write` scope to
`apis/elevenlabs-agents` and re-run `scripts/pick_voices.py --add`.

## TTS model

`eleven_flash_v2_5` — "ultra low latency model in 32 languages, ideal for conversational use
cases". Chosen over `eleven_v4_turbo` for one concrete reason: Amélie's `verified_languages`
list names `eleven_flash_v2_5` (and `eleven_turbo_v2_5`, `eleven_v2_5_flash`,
`eleven_multilingual_v2`) but has no `v4` entry. On a phone line, latency is the product, and
a voice the library has actually verified for the model is the safer pairing.
