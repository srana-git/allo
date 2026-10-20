# Voice A/B — listening instructions

You are the listener. You speak Québec French as a first language. Your job is to say which
of the three clips of each line sounds most natural to a Québec customer.

## The clips

`clips/` holds 18 files, three per line: `L1-A.mp3` and `L1-B.mp3` and `L1-C.mp3`, then
`L2-A.mp3` … `L6-C.mp3`.

The three voices behind A, B and C are **hidden, and they are re-shuffled for every line**.
A is not the same voice in L1 and L2. Do not try to guess who is who; judge only what you
hear.

Play them in any order you like. Headphones are better than speakers. Each file is 4 to 7
seconds.

## What the line is used for

- **L1** — greeting. The first thing a caller hears.
- **L2** — offer of an appointment slot with a date and a time.
- **L3** — read-back of a phone number in digit groups.
- **L4** — summary of a recall, read to the caller.
- **L5** — the hand-off line: "je vous transfère à un conseiller".
- **L6** — Québec words: pneus d'hiver, changement d'huile, rendez-vous.

The exact text of each line is in `LINES.md`.

## What to judge

1. **Accent.** Does this sound like someone who lives here, or like someone from outside
   Québec reading our text?
2. **Naturalness for a Québec customer.** A Laval caller on the service line. Does it sound
   like a real person at a real dealership, or like a machine?
3. **Pronunciation.** Flag every mispronounced word, especially: dates ("le 16 octobre"),
   times ("neuf heures trente"), digit groups ("cinq-un-quatre, cinq-cinq-cinq"), the
   Québec vowel in "pneus d'hiver", the "in" in "changement d'huile", and the liaison in
   "un rendez-vous".
4. **Rhythm.** Rushed, flat, or singsong? A phone agent should sound calm and quick.

Do not rank on audio quality, volume or file size. All three clips come from the same
model and the same settings. Only the voice changes.

## How to answer

For each line, write the three letters from most natural to least natural, separated by
` > `. For example, `L1: B > A > C` means: B was the most natural for a Québec customer, then
A, and C was the least natural.

Then add a `flags:` line for that same line, and write every mispronunciation or oddity you
heard. Write `none` if the line was clean.

Everyone ranks all three, even when two of them are close.

## Answer template — fill this in and save it outside the repo

```text
L1:
L1 flags:
L2:
L2 flags:
L3:
L3 flags:
L4:
L4 flags:
L5:
L5 flags:
L6:
L6 flags:
```

Score your filled-in answers with:

```bash
python3 scripts/voice_ab_score.py <your answers file>
```

The scorer reads the hidden key and prints, per voice: how many times it was ranked first,
its mean rank, and the result of every line. Keep the answers file outside this repository —
it is a raw opinion, not a repo artifact.
