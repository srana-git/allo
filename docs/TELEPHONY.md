# allo — telephony: Telnyx number ↔ ElevenLabs over SIP trunk

Built 2026-10-15. The number is live in Telnyx, the trunk is configured in both directions,
and the number is imported into ElevenLabs. **It is NOT assigned to the agent.** No test call
was placed, so every statement below is a configuration fact read back from the two APIs, not
a proven call path. See "What is not verified".

## 1. What was created

| Thing | Value |
| --- | --- |
| Phone number (E.164) | `+14388020416` — Montréal rate center, area code 438 (514 had no inventory) |
| Telnyx phone number id | `3071378628206921713` (status `active`) |
| Telnyx number order id | `04812948-26ad-4dd3-ba96-f6cfb7ddf0b6` (status `success`) |
| Cost | **$0.39 USD upfront + $0.39 USD / month** — from the availability-search `cost_information` at buy time (`upfront_cost 0.3900000`, `monthly_cost 0.39000`). The number-order payload returned `cost_information: null`, so the invoice in the Telnyx portal is the authoritative figure. |
| Telnyx connection | `allo-elevenlabs`, id `3071378538985687012`, type `fqdn_connection`, active, transport `TCP` |
| Telnyx FQDN record | `sip.rtc.elevenlabs.io`, id `3071378587480229866`, port 5060, DNS record type `a` |
| Telnyx outbound voice profile | `allo-outbound`, id `3071378410950363081` — conversational / global / rate-deck, `whitelisted_destinations: ["CA","US"]` |
| ElevenLabs phone number id | `phnum_3801m50711mpfwt80bs3thfndvwa` — provider `sip_trunk`, `agent_id: null` |
| SIP credentials | `pass` entry `apis/allo-sip` — line 1 username, line 2 password. Never in this repo, never printed. |

The agent (`agent_2301m5040drafgn9e5gcv5pc21qq`) was not touched: no prompt, tool, test or
setting was changed. The only write to ElevenLabs was the phone-number import.

## 2. Required settings, and where they come from

Sources read 2026-10-15: `elevenlabs.io/docs` — *SIP trunking*, *Telnyx SIP trunking*,
*Import phone number* (API reference), *Update phone number* (API reference) — and
`developers.telnyx.com` — *Create an FQDN connection*, *Create an FQDN*,
*Create an outbound voice profile*, *Create a number order*, *List available phone numbers*.

| Setting | Value used | Why |
| --- | --- | --- |
| Inbound SIP host (Telnyx → ElevenLabs) | `sip.rtc.elevenlabs.io` | The ElevenLabs SIP endpoint. Telnyx delivers calls for the assigned number to it as an FQDN connection. |
| Transport / port | **TCP / 5060** | Telnyx's own ElevenLabs guide: signaling TCP, media RTP over UDP. ElevenLabs also serves TLS on 5061 and recommends it in general, but TLS adds two certificate rules it would then have to satisfy — ElevenLabs validating our server's cert for BYE/REFER, and the `Remote domains` field on our side. Not worth it for a first working trunk; switch later once a call is proven. |
| UDP | not used | ElevenLabs marks UDP experimental. |
| Codecs | G.722, G.711 PCMU, G.711 PCMA | The three in ElevenLabs' allowed set (`G722/8000`, `PCMU/8000`, `PCMA/8000`). The Telnyx connection advertises G722, G711U, G711A, G729. Outbound `enabled_codecs` left empty on the ElevenLabs side, which offers the full supported set — the intersection is the three above. |
| Inbound auth model | ACL, no digest | ElevenLabs' Telnyx page: "Telnyx inbound trunks don't use digest authentication". ElevenLabs `inbound_trunk.allowed_addresses` is therefore `0.0.0.0/0`. |
| Number format | `+E.164` both ends | Telnyx `inbound.dnis_number_format = "+e164"`; the ElevenLabs number was imported **with** the leading `+`. ElevenLabs' FAQ warns that the SIP URI and the imported number must use the same format. |
| Outbound credentials (ElevenLabs → Telnyx) | digest username/password on the Telnyx connection, copied to ElevenLabs `outbound_trunk.credentials` | Telnyx guide step "Configure authentication": method *Credentials*, then add the FQDN. Telnyx stores them as the connection's `user_name` / `password`. |
| Outbound address (ElevenLabs → Telnyx) | `sip.telnyx.com`, transport `tcp` | The Telnyx termination host. Hostname only — ElevenLabs rejects a full SIP URI there. |
| Media encryption | `allowed` on both sides | Permits SRTP without requiring it, so an SRTP mismatch cannot kill the first call. |

## 3. Telnyx side — what was created

FQDN connection `allo-elevenlabs` (`3071378538985687012`), as read back from the API:

```
connection_name      allo-elevenlabs
record_type          fqdn_connection
active               true
transport_protocol   TCP
user_name            alloelevenlabs
password             set (not printed)
inbound.dnis_number_format   +e164
inbound.sip_region           US
inbound.codecs               G722, G711U, G711A, G729
outbound.outbound_voice_profile_id   3071378410950363081
outbound.fqdn_authentication_method  credential-authentication
```

Notes:

- Telnyx rejected the first two attempts and the errors are worth keeping:
  a username may contain **letters and digits only** (no hyphen), and the only valid
  outbound-voice-profile combination today is `conversational` + `global` + `rate-deck`.
- `outbound.fqdn_authentication_method` reads back as `credential-authentication` — the
  mechanism the Telnyx guide asks for. The field is not in the published schema; the value is
  what the API returns.

## 4. ElevenLabs side — what was created

`POST /v1/convai/phone-numbers` with `provider: sip_trunk`, `agent_id` omitted:

```json
{
  "provider": "sip_trunk",
  "label": "allo — Groupe Auto Laval (service) — Telnyx Montréal",
  "phone_number": "+14388020416",
  "inbound_trunk_config": { "media_encryption": "allowed" },
  "outbound_trunk_config": {
    "address": "sip.telnyx.com",
    "transport": "tcp",
    "media_encryption": "allowed",
    "credentials": { "username": "alloelevenlabs", "password": "<pass show apis/allo-sip line 2>" }
  }
}
```

Read back, ElevenLabs confirms: `provider_config.address = sip.telnyx.com`,
`transport = tcp`, `media_encryption = allowed`, `has_auth_credentials = true`,
`username = alloelevenlabs`, `inbound_trunk.allowed_addresses = ["0.0.0.0/0"]`,
`supports_inbound = true`, `supports_outbound = true`, `agent_id = null`.

## 5. Pre-existing, untouched

Every existing Telnyx number, connection, outbound voice profile, messaging profile and
call-control app on the account was read before any write and left unchanged. Every write this
task made was a POST that created a new object, plus one number order for the new number. The
new number has no messaging profile and is attached to no call-control app.

## 6. Assigning the number to the agent — NOT DONE

The number is deliberately unassigned. When the driver says go, this is the whole change:

```bash
EL=$(pass show apis/elevenlabs-agents | head -1)
curl -s -X PATCH \
  -H "xi-api-key: $EL" -H "Content-Type: application/json" \
  -d '{"agent_id":"agent_2301m5040drafgn9e5gcv5pc21qq"}' \
  "https://api.elevenlabs.io/v1/convai/phone-numbers/phnum_3801m50711mpfwt80bs3thfndvwa"
```

Unassign (revert to no agent) is the same call with `"agent_id": null`.

## 7. Verification (API reads only — no call was placed)

Telnyx number, read after the order:

```
{"id":"3071378628206921713","phone_number":"+14388020416","status":"active",
 "connection_id":"3071378538985687012","connection_name":"allo-elevenlabs",
 "phone_number_type":"local","messaging_profile_id":null,"purchased_at":"2026-10-15T16:41:04Z"}
```

Telnyx connection (secrets masked in this doc):

```
{"id":"3071378538985687012","connection_name":"allo-elevenlabs","record_type":"fqdn_connection",
 "active":true,"transport_protocol":"TCP","user_name":"alloelevenlabs","has_password":true,
 "inbound":{"dnis_number_format":"+e164","sip_region":"US","codecs":["G722","G711U","G711A","G729"]},
 "outbound":{"outbound_voice_profile_id":"3071378410950363081",
             "fqdn_authentication_method":"credential-authentication"},
 "created_at":"2026-10-15T16:40:53Z"}
```

Telnyx FQDN record:

```
{"id":"3071378587480229866","connection_id":"3071378538985687012",
 "fqdn":"sip.rtc.elevenlabs.io","port":5060,"dns_record_type":"a","record_type":"fqdn"}
```

ElevenLabs phone number:

```
{"phone_number_id":"phnum_3801m50711mpfwt80bs3thfndvwa","phone_number":"+14388020416",
 "label":"allo — Groupe Auto Laval (service) — Telnyx Montréal","provider":"sip_trunk",
 "agent_id":null,"supports_inbound":true,"supports_outbound":true,
 "provider_config":{"address":"sip.telnyx.com","transport":"tcp","media_encryption":"allowed",
   "username":"alloelevenlabs","has_auth_credentials":true,"has_outbound_trunk":true,
   "enabled_codecs":[]},
 "inbound_trunk":{"allowed_addresses":["0.0.0.0/0"],"media_encryption":"allowed"}}
```

## 8. What is not verified

- **No call was placed** (the task forbade it). Inbound routing Telnyx → ElevenLabs and
  outbound INVITE ElevenLabs → Telnyx are configured per the vendor guides and nothing more.
  The first real test is a call to `+1 438-802-0416` after the number is assigned.
- **Media path untested.** RTP/UDP, SRTP negotiation and codec agreement are all unproven.
- **TLS not used.** If it is wanted later: change the Telnyx FQDN port to 5061, set the
  ElevenLabs transport to `tls`, and add Telnyx's certificate FQDN to the ElevenLabs
  `remote_domains` field, or BYE/REFER over TLS will fail validation.
- **Cost is list price.** No invoice was read. The order API returns no cost.

## 8a. Inbound ACL — locked to Telnyx (2026-10-20)

`inbound_trunk.allowed_addresses` was `0.0.0.0/0`, so any host could send INVITEs to the
trunk. It is now the Telnyx signaling IPs only, read back from the API after the PATCH:

| IP | Telnyx role |
| --- | --- |
| `192.76.120.10/32`, `64.16.250.10/32` | US primary / secondary — the connection's `sip_region` is `US` |
| `192.76.120.31/32`, `64.16.250.13/32` | CA primary / secondary — fallback in case Telnyx routes from its Canadian edge |

Source: https://sip.telnyx.com/ and https://sip.telnyx.com/voice.json (version 2026-05-25), read
2026-10-20. ElevenLabs applies this list on TCP/TLS only, which is the transport in use.

```bash
EL=$(pass show apis/elevenlabs-agents | head -1)
curl -s -X PATCH -H "xi-api-key: $EL" -H "Content-Type: application/json" \
  -d '{"inbound_trunk_config":{"allowed_addresses":["192.76.120.10/32","64.16.250.10/32","192.76.120.31/32","64.16.250.13/32"],"media_encryption":"allowed"}}' \
  "https://api.elevenlabs.io/v1/convai/phone-numbers/phnum_3801m50711mpfwt80bs3thfndvwa"
```

If the first call never reaches the agent, check this list first: put `0.0.0.0/0` back for one
call, and if that call connects, Telnyx is sending from an IP not listed above.

## 9. Teardown

Order matters: release the number before deleting the connection it depends on, and delete
the ElevenLabs number so it does not hold a dangling trunk config.

```bash
TK=<your Telnyx API key>
EL=$(pass show apis/elevenlabs-agents | head -1)

# 1. ElevenLabs: delete the imported number
curl -X DELETE -H "xi-api-key: $EL" \
  "https://api.elevenlabs.io/v1/convai/phone-numbers/phnum_3801m50711mpfwt80bs3thfndvwa"

# 2. Telnyx: release the number
curl -X DELETE -H "Authorization: Bearer $TK" \
  "https://api.telnyx.com/v2/phone_numbers/3071378628206921713"

# 3. Telnyx: delete the FQDN record, then the connection
curl -X DELETE -H "Authorization: Bearer $TK" \
  "https://api.telnyx.com/v2/fqdns/3071378587480229866"
curl -X DELETE -H "Authorization: Bearer $TK" \
  "https://api.telnyx.com/v2/fqdn_connections/3071378538985687012"

# 4. Telnyx: delete the outbound voice profile (only after step 3 — it is in use until then)
curl -X DELETE -H "Authorization: Bearer $TK" \
  "https://api.telnyx.com/v2/outbound_voice_profiles/3071378410950363081"

# 5. Credentials
pass rm apis/allo-sip
```

If the number was assigned to the agent first, unassign it (section 6) before step 1.
