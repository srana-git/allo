# Voice A/B — the six lines

Six short French lines, each in the voice of Léa, the Groupe Auto Laval service agent.
Every line is under 110 characters. The six lines total **551 characters**, so 18 clips
(6 lines × 3 voices) cost about **1,653 credits**.

The text below is the exact text sent to the text-to-speech API. Nothing else is sent:
no voice settings, no language code, model `eleven_flash_v2_5` for all three voices.

## L1 — greeting

> Bonjour, hi! Service à la clientèle de Groupe Auto Laval, ici Léa. Comment puis-je vous aider?

## L2 — slot offer with a date and a time

> J'ai une place jeudi le 16 octobre à neuf heures trente. Est-ce que ça vous convient?

## L3 — read-back of a phone number in digit groups

> Votre numéro, c'est cinq-un-quatre, cinq-cinq-cinq, zéro-un-quatre-trois. C'est bien ça?

## L4 — recall summary read to the caller

> Il y a un rappel ouvert sur votre véhicule : la pompe à carburant peut s'arrêter sans avertissement.

## L5 — transfer to a service advisor

> Un instant s'il vous plaît, je vous transfère à un conseiller du service. Ne quittez pas.

## L6 — Québec vocabulary: pneus d'hiver, changement d'huile, rendez-vous

> Pour vos pneus d'hiver ou un changement d'huile, je peux fixer votre rendez-vous tout de suite.

## What to listen for

- **L1** — the first thing a caller hears. Does "Bonjour, hi!" land the way a Québec
  service desk says it, or does it sound like a translation?
- **L2** — a date and a time read plainly. Listen for "jeudi le 16 octobre" and
  "neuf heures trente".
- **L3** — the digit groups of a phone number. This is where a non-local voice shows.
- **L4** — a recall read as one calm sentence. No drama, no stumble.
- **L5** — the hand-off line. Warm, quick, final.
- **L6** — Québec words: "pneus d'hiver", "changement d'huile", "rendez-vous".

The listener instructions and the answer template are in `RATE.md`.
