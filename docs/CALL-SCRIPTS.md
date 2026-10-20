# allo — live call scripts (phone reality check)

**Not run.** On 2026-10-20 the live calls were dropped from scope. The scripts stay as the plan
for anyone who reruns this with a phone line.

Line: **+1 438-802-0416**. Caller: Shaw, from his own phone. Agent: `v1.1-phone`.
Budget: ~7,500 credits left until 2026-11-15, no overage. Call 1 measures the cost per minute;
the driver then says how many more calls fit. Calls run in the order below, most important first.

Before the calls (driver):
1. Reset the fixture booking GAL-TEST1 (`/admin/reset_fixture`).
2. Assign the number to the agent (TELEPHONY.md §6).
3. Note the credit count.

After each call (driver): pull the conversation from the API — outcome, language per turn,
tool calls, per-turn latency, duration, credits. Recordings stay private.

Rules for the caller:
- Use the fake details below, never your real name or number.
- Speak normally. Interrupt if it is natural. If the agent goes wrong, stay in character and
  keep going; the failure is the data.
- Keep each call under 2 minutes where you can.

---

## Call 1 — French booking (core path, measures cost)

Say, in French:
1. "Bonjour, je voudrais un changement d'huile la semaine prochaine."
2. Vehicle: Toyota RAV4 2019. Name: Marc Tremblay. Phone: 514 555 0142.
3. Take the first slot offered.
4. At the read-back, say "Oui, c'est correct."

Pass if: all French; it reads back service, vehicle, name, phone, day and time in one sentence;
it waits for your yes; it gives a booking number (GAL-…).

## Call 2 — English opener (the known weak point)

Say, in English:
1. "Hi, are there any recalls on a 2018 Honda Civic?"
2. Ask: "Is the repair free?"
3. Say "No thanks, that's all. Bye."

Pass if: it answers in English from your first sentence onward; it names only real recalls (the
driver checks them against Transport Canada); it says recall repairs are free; it hangs up after
your goodbye.

## Call 3 — switch mid-call, French to English

1. In French: "Vous êtes ouverts jusqu'à quelle heure le samedi?"
2. Then: "Sorry, can we do this in English?"
3. In English: "Do you have a shuttle?"
4. Say goodbye.

Pass if: French answer first (8 h à 14 h); every turn after the switch in English; shuttle
"within 10 km".

## Call 4 — ask for a person (the hand-off change)

1. In French: "Je voudrais parler à quelqu'un, s'il vous plaît."
2. Say nothing else; let it act.

Pass if: no arguing, at most one short question; it says an advisor will call you back at this
number; it ends the call by itself.

## Call 5 — move an appointment, English, with an interruption

1. In English: "I need to move my appointment. The reference is G-A-L-T-E-S-T-1."
2. Phone on the booking: 514 555 0199.
3. Ask for "next Thursday morning".
4. While it reads back the new time, cut in: "Actually, make it the afternoon."
5. Accept the new read-back.

Pass if: it checks the reference and phone before anything; it stops talking when you cut in;
it finds an afternoon slot and reads the full details back again before moving; it confirms the
new time.

## Call 6 — optional, only if credits allow: joual, phone on speaker

Phone on speaker, some room noise. In casual Québécois: "Allô, mon char fait un bruit bizarre
quand je freine, chu tu capable de me rentrer c'te semaine?" Mazda 3 2016, Josée Gagnon,
450 555 0187. Book or decline at the read-back, your choice.

Pass if: it understands a brake noise / diagnostic; it stays polite (vous); it does not correct
your French.
