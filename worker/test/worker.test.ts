import { env, SELF, fetchMock } from "cloudflare:test";
import { beforeAll, afterEach, describe, expect, it } from "vitest";

const SECRET = "test-secret";

async function post(
  path: string,
  body: unknown,
  secret: string | null = SECRET,
): Promise<{ status: number; json: any }> {
  const headers: Record<string, string> = { "content-type": "application/json" };
  if (secret !== null) headers["X-Allo-Secret"] = secret;
  const res = await SELF.fetch(`https://allo.test${path}`, {
    method: "POST",
    headers,
    body: JSON.stringify(body),
  });
  return { status: res.status, json: await res.json() };
}

/** prepare_booking, so a token exists for the write tests. */
async function prepare(body: Record<string, unknown>) {
  return post("/tools/prepare_booking", body);
}

/** Insert a free slot 3 days out so tests never collide with each other. */
async function insertSlot(id: string, dayOffset: number, bay = 1): Promise<string> {
  const start = new Date(Date.now() + dayOffset * 86400_000).toISOString();
  await env.DB.prepare(
    `INSERT INTO slots (id, start_ts, bay, service_types, taken) VALUES (?, ?, ?, ?, 0)`,
  )
    .bind(id, start, bay, JSON.stringify(["oil_change", "tires", "recall_repair", "diagnostic", "maintenance"]))
    .run();
  return start;
}

beforeAll(() => {
  fetchMock.activate();
  fetchMock.disableNetConnect();
});

afterEach(() => {
  fetchMock.assertNoPendingInterceptors();
});

describe("health", () => {
  it("returns ok without auth", async () => {
    const res = await SELF.fetch("https://allo.test/health");
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({ ok: true });
  });
});

describe("auth", () => {
  it("rejects a call with no secret", async () => {
    const { status, json } = await post("/tools/find_slots", { date_from: "2026-10-16" }, null);
    expect(status).toBe(401);
    expect(json).toEqual({ ok: false, error: "unauthorized" });
  });

  it("rejects a call with the wrong secret", async () => {
    const { status, json } = await post("/tools/find_slots", { date_from: "2026-10-16" }, "nope");
    expect(status).toBe(401);
    expect(json).toEqual({ ok: false, error: "unauthorized" });
  });

  it("logs rejected calls to tool_calls", async () => {
    await post("/tools/find_slots", { date_from: "2026-10-16" }, "bad");
    const row = await env.DB.prepare(
      `SELECT * FROM tool_calls WHERE result_json LIKE '%unauthorized%' ORDER BY ts DESC LIMIT 1`,
    ).first<any>();
    expect(row).toBeTruthy();
    expect(row.tool).toBe("/tools/find_slots");
  });
});

describe("decode_vin", () => {
  it("rejects a VIN that is not 17 characters", async () => {
    const { json } = await post("/tools/decode_vin", { vin: "2HGFC2F59JH00000" });
    expect(json).toEqual({ ok: false, error: "invalid_vin" });
  });

  it("rejects a VIN containing I, O or Q", async () => {
    const { json } = await post("/tools/decode_vin", { vin: "2HGFC2F59JHI0000O" });
    expect(json).toEqual({ ok: false, error: "invalid_vin" });
  });

  it("strips spaces and dashes and upper-cases the VIN before validating", async () => {
    fetchMock
      .get("https://vpic.nhtsa.dot.gov")
      .intercept({ path: /DecodeVinValues\/2HGFC2F59JH000000/, method: "GET" })
      .reply(200, {
        Results: [{ Make: "HONDA", Model: "Civic", ModelYear: "2018", PlantCountry: "CANADA" }],
      });

    const { json } = await post("/tools/decode_vin", { vin: " 2hgf-c2f59 jh000000 " });
    expect(json.ok).toBe(true);
    expect(json.vin).toBe("2HGFC2F59JH000000");
    expect(json.make).toBe("HONDA");
  });

  it("still rejects a VIN that is 16 characters once the separators are stripped", async () => {
    // 17 characters as typed, 16 real characters — normalization must not rescue it.
    const { json } = await post("/tools/decode_vin", { vin: "2HGF C2F59 JH00000" });
    expect(json).toEqual({ ok: false, error: "invalid_vin" });
  });

  it("decodes a valid VIN through NHTSA vPIC", async () => {
    fetchMock
      .get("https://vpic.nhtsa.dot.gov")
      .intercept({ path: /DecodeVinValues\/2HGFC2F59JH000000/, method: "GET" })
      .reply(200, {
        Results: [{ Make: "HONDA", Model: "Civic", ModelYear: "2018", PlantCountry: "CANADA" }],
      });

    const { json } = await post("/tools/decode_vin", { vin: "2hgfC2F59JH000000" });
    expect(json).toEqual({
      ok: true,
      vin: "2HGFC2F59JH000000",
      make: "HONDA",
      model: "Civic",
      year: "2018",
      plant_country: "CANADA",
    });
  });
});

describe("check_recalls", () => {
  it("returns French text when lang=fr and English when lang=en", async () => {
    const listRow = (n: string, date: string) => [
      { Name: "Recall number", Value: { Literal: n } },
      { Name: "Recall date", Value: { Literal: date } },
    ];
    const detailRow = (n: string) => [
      [
        { Name: "RECALL_NUMBER_NUM", Value: { Literal: n } },
        { Name: "SYSTEM_TYPE_ETXT", Value: { Literal: "Steering" } },
        { Name: "SYSTEM_TYPE_FTXT", Value: { Literal: "Direction" } },
        { Name: "COMMENT_ETXT", Value: { Literal: "English summary text." } },
        { Name: "COMMENT_FTXT", Value: { Literal: "Résumé français du rappel." } },
        { Name: "RECALL_DATE_DTE", Value: { Literal: "9/27/2018 12:00:00 AM" } },
      ],
    ];

    fetchMock
      .get("https://data.tc.gc.ca")
      .intercept({ path: /recall\/make-name\/HONDA/, method: "GET" })
      .reply(200, { ResultSet: [listRow("2018536", "9/27/2018 12:00:00 AM")] })
      .times(2);
    fetchMock
      .get("https://data.tc.gc.ca")
      .intercept({ path: /recall-summary\/recall-number\/2018536/, method: "GET" })
      .reply(200, { ResultSet: detailRow("2018536") })
      .times(2);

    const fr = await post("/tools/check_recalls", {
      make: "honda", model: "civic", year: "2018", lang: "fr",
    });
    expect(fr.json.ok).toBe(true);
    expect(fr.json.count_total).toBe(1);
    expect(fr.json.recalls[0].component).toBe("Direction");
    expect(fr.json.recalls[0].summary).toBe("Résumé français du rappel.");

    const en = await post("/tools/check_recalls", {
      make: "honda", model: "civic", year: "2018", lang: "en",
    });
    expect(en.json.recalls[0].component).toBe("Steering");
    expect(en.json.recalls[0].summary).toBe("English summary text.");
  });
});

describe("find_slots", () => {
  it("returns free slots with ISO+offset and a human string in both languages", async () => {
    await insertSlot("t-find-1", 3);
    const { json } = await post("/tools/find_slots", {
      date_from: new Date(Date.now() - 86400_000).toISOString().slice(0, 10),
    });
    expect(json.ok).toBe(true);
    expect(json.slots.length).toBeGreaterThan(0);
    const slot = json.slots.find((s: any) => s.slot_id === "t-find-1");
    expect(slot).toBeTruthy();
    expect(slot.start_ts).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}$/);
    expect(slot.start_local_fr).toMatch(/^(lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche) \d+ \S+ à \d+ h \d\d$/);
    expect(slot.start_local_en).toMatch(/^\w+, \w+ \d+ at \d+:\d\d [AP]M$/);
  });

  it("rejects a bad date", async () => {
    const { json } = await post("/tools/find_slots", { date_from: "16-10-2026" });
    expect(json).toEqual({ ok: false, error: "invalid_date_from" });
  });
});

describe("prepare_booking", () => {
  it("returns a token and one speakable sentence in both languages", async () => {
    await insertSlot("t-prep-1", 4);
    const { json } = await prepare({
      slot_id: "t-prep-1",
      customer_name: "Marie Tremblay",
      phone: "(514) 555-0143",
      vin_or_vehicle: "2018 Honda Civic",
      service_type: "oil_change",
      additional_services: ["tires"],
      language: "fr",
    });
    expect(json.ok).toBe(true);
    expect(json.token).toMatch(/^[0-9a-f]{32}$/);
    expect(json.kind).toBe("book");
    expect(json.expires_in_secs).toBe(600);

    // One sentence, one item order: service, vehicle, name, grouped phone, when.
    expect(json.readback_fr).toBe(json.readback_fr.trim());
    expect(json.readback_fr.match(/[.!?]$/)).toBeTruthy();
    expect(json.readback_fr).toContain("un changement d'huile et un service de pneus");
    expect(json.readback_fr).toContain("2018 Honda Civic");
    expect(json.readback_fr).toContain("au nom de Marie Tremblay");
    expect(json.readback_fr).toContain("cinq-un-quatre, cinq-cinq-cinq, zéro-un-quatre-trois");
    expect(json.readback_fr).toContain("c'est bien ça?");

    expect(json.readback_en).toContain("an oil change and a tire service");
    expect(json.readback_en).toContain("five-one-four, five-five-five, zero-one-four-three");
    expect(json.readback_en).toContain("is that right?");

    // Preparing reserves nothing.
    const slot = await env.DB.prepare(`SELECT taken FROM slots WHERE id = ?`)
      .bind("t-prep-1")
      .first<{ taken: number }>();
    expect(slot?.taken).toBe(0);
  });

  it("refuses a slot that is already taken", async () => {
    await insertSlot("t-prep-taken", 5);
    await env.DB.prepare(`UPDATE slots SET taken = 1 WHERE id = 't-prep-taken'`).run();
    const { json } = await prepare({
      slot_id: "t-prep-taken",
      customer_name: "Marie Tremblay",
      phone: "5145550143",
      service_type: "oil_change",
    });
    expect(json).toEqual({ ok: false, error: "slot_taken" });
  });

  it("requires a name and a usable phone number", async () => {
    await insertSlot("t-prep-bad", 6);
    const noName = await prepare({
      slot_id: "t-prep-bad", phone: "5145550143", service_type: "tires",
    });
    expect(noName.json).toEqual({ ok: false, error: "missing_customer_name" });

    const badPhone = await prepare({
      slot_id: "t-prep-bad", customer_name: "A", phone: "514555", service_type: "tires",
    });
    expect(badPhone.json).toEqual({ ok: false, error: "invalid_phone" });
  });

  it("checks the booking ref and the phone when the token is for a move", async () => {
    await insertSlot("t-prep-mv1", 7);
    await insertSlot("t-prep-mv2", 8);
    const booked = await prepare({
      slot_id: "t-prep-mv1", customer_name: "Jean Roy", phone: "5145550144",
      service_type: "maintenance",
    });
    const book = await post("/tools/book_appointment",
      { token: booked.json.token, confirmed: true });
    const ref = book.json.booking_ref;

    const badPhone = await prepare({
      slot_id: "t-prep-mv2", booking_ref_to_move: ref, phone: "5145550000",
    });
    expect(badPhone.json).toEqual({ ok: false, error: "phone_mismatch" });

    const unknownRef = await prepare({
      slot_id: "t-prep-mv2", booking_ref_to_move: "GAL-NOPE1", phone: "5145550144",
    });
    expect(unknownRef.json).toEqual({ ok: false, error: "booking_not_found" });

    const good = await prepare({
      slot_id: "t-prep-mv2", booking_ref_to_move: ref, phone: "514 555 0144",
    });
    expect(good.json.ok).toBe(true);
    expect(good.json.kind).toBe("move");
    expect(good.json.readback_fr).toContain("Votre nouveau rendez-vous");
    expect(good.json.readback_fr).toContain("au nom de Jean Roy");
  });
});

describe("book_appointment", () => {
  it("refuses to book without confirmed=true", async () => {
    await insertSlot("t-book-unconfirmed", 4);
    const prep = await prepare({
      slot_id: "t-book-unconfirmed",
      customer_name: "Marie Tremblay",
      phone: "514-555-0143",
      service_type: "oil_change",
      language: "fr",
    });
    const { json } = await post("/tools/book_appointment", {
      token: prep.json.token,
      confirmed: false,
    });
    expect(json).toEqual({ ok: false, error: "not_confirmed" });
    const slot = await env.DB.prepare(`SELECT taken FROM slots WHERE id = ?`)
      .bind("t-book-unconfirmed")
      .first<{ taken: number }>();
    expect(slot?.taken).toBe(0);
  });

  it("requires a token", async () => {
    await insertSlot("t-book-notoken", 4);
    const { json } = await post("/tools/book_appointment", { confirmed: true });
    expect(json).toEqual({ ok: false, error: "needs_prepare" });
  });

  it("books, marks the slot taken, and returns a GAL- booking ref", async () => {
    await insertSlot("t-book-ok", 5);
    const prep = await prepare({
      slot_id: "t-book-ok",
      customer_name: "Marie Tremblay",
      phone: "(514) 555-0143",
      vin_or_vehicle: "2018 Honda Civic",
      service_type: "oil_change",
      language: "fr",
    });
    const { json } = await post("/tools/book_appointment", {
      token: prep.json.token,
      confirmed: true,
      conversation_id: "conv-test-1",
    });
    expect(json.ok).toBe(true);
    expect(json.booking_ref).toMatch(/^GAL-[A-Z2-9]{5}$/);

    const slot = await env.DB.prepare(`SELECT taken FROM slots WHERE id = ?`)
      .bind("t-book-ok")
      .first<{ taken: number }>();
    expect(slot?.taken).toBe(1);

    const appt = await env.DB.prepare(`SELECT * FROM appointments WHERE booking_ref = ?`)
      .bind(json.booking_ref)
      .first<any>();
    expect(appt.slot_id).toBe("t-book-ok");
    expect(appt.phone).toBe("5145550143");
  });

  it("stores additional services on the appointment", async () => {
    await insertSlot("t-book-add", 5);
    const prep = await prepare({
      slot_id: "t-book-add",
      customer_name: "Marie Tremblay",
      phone: "5145550143",
      vin_or_vehicle: "2018 Honda Civic",
      service_type: "oil_change",
      additional_services: ["tires", "maintenance"],
      language: "fr",
    });
    const { json } = await post("/tools/book_appointment", {
      token: prep.json.token, confirmed: true,
    });
    expect(json.ok).toBe(true);
    expect(json.additional_services).toEqual(["tires", "maintenance"]);

    const appt = await env.DB.prepare(`SELECT * FROM appointments WHERE booking_ref = ?`)
      .bind(json.booking_ref)
      .first<any>();
    expect(JSON.parse(appt.additional_services)).toEqual(["tires", "maintenance"]);
  });

  it("accepts a token only once", async () => {
    await insertSlot("t-book-once", 5);
    const prep = await prepare({
      slot_id: "t-book-once", customer_name: "Marie Tremblay",
      phone: "5145550143", service_type: "oil_change",
    });
    const first = await post("/tools/book_appointment",
      { token: prep.json.token, confirmed: true });
    expect(first.json.ok).toBe(true);

    const second = await post("/tools/book_appointment",
      { token: prep.json.token, confirmed: true });
    expect(second.json).toEqual({ ok: false, error: "needs_prepare" });
  });

  it("rejects a token older than ten minutes", async () => {
    await insertSlot("t-book-exp", 5);
    const prep = await prepare({
      slot_id: "t-book-exp", customer_name: "Marie Tremblay",
      phone: "5145550143", service_type: "oil_change",
    });
    await env.DB.prepare(`UPDATE pending_bookings SET created_ms = ? WHERE token = ?`)
      .bind(Date.now() - 11 * 60_000, prep.json.token)
      .run();

    const { json } = await post("/tools/book_appointment",
      { token: prep.json.token, confirmed: true });
    expect(json).toEqual({ ok: false, error: "token_expired" });
  });

  it("ignores raw details and writes only what the token froze", async () => {
    await insertSlot("t-book-freeze-a", 5);
    await insertSlot("t-book-freeze-b", 6);
    const prep = await prepare({
      slot_id: "t-book-freeze-a", customer_name: "Marie Tremblay",
      phone: "5145550143", service_type: "oil_change", language: "fr",
    });
    // A caller who changes their mind mid-read-back cannot smuggle the change
    // through the write: the token's own slot and name are what get stored.
    const { json } = await post("/tools/book_appointment", {
      token: prep.json.token,
      confirmed: true,
      slot_id: "t-book-freeze-b",
      customer_name: "Someone Else",
      phone: "5145559999",
      service_type: "tires",
      language: "en",
    });
    expect(json.ok).toBe(true);
    expect(json.slot_id).toBe("t-book-freeze-a");
    expect(json.customer_name).toBe("Marie Tremblay");
    expect(json.phone).toBe("5145550143");

    const a = await env.DB.prepare(`SELECT taken FROM slots WHERE id = 't-book-freeze-a'`)
      .first<{ taken: number }>();
    const b = await env.DB.prepare(`SELECT taken FROM slots WHERE id = 't-book-freeze-b'`)
      .first<{ taken: number }>();
    expect(a?.taken).toBe(1);
    expect(b?.taken).toBe(0);
  });

  it("cannot double-book the same slot", async () => {
    await insertSlot("t-book-dup", 6);
    const a = await prepare({
      slot_id: "t-book-dup", customer_name: "A", phone: "5145550001", service_type: "tires",
    });
    const first = await post("/tools/book_appointment",
      { token: a.json.token, confirmed: true });
    expect(first.json.ok).toBe(true);

    const b = await prepare({
      slot_id: "t-book-dup", customer_name: "B", phone: "5145550002", service_type: "tires",
    });
    expect(b.json).toEqual({ ok: false, error: "slot_taken" });
  });

  it("returns slot_not_found for an unknown slot", async () => {
    const { json } = await prepare({
      slot_id: "does-not-exist",
      customer_name: "A",
      phone: "5145550003",
      service_type: "tires",
    });
    expect(json).toEqual({ ok: false, error: "slot_not_found" });
  });
});

describe("phone matching on lookup and move", () => {
  it("refuses lookup when the phone does not match", async () => {
    await insertSlot("t-phone-1", 7);
    const prep = await prepare({
      slot_id: "t-phone-1",
      customer_name: "Marie Tremblay",
      phone: "5145550143",
      service_type: "diagnostic",
      language: "fr",
    });
    const booked = await post("/tools/book_appointment",
      { token: prep.json.token, confirmed: true });
    const ref = booked.json.booking_ref;

    const bad = await post("/tools/lookup_appointment", { booking_ref: ref, phone: "5145559999" });
    expect(bad.json).toEqual({ ok: false, error: "phone_mismatch" });

    const good = await post("/tools/lookup_appointment", { booking_ref: ref, phone: "514 555 0143" });
    expect(good.json.ok).toBe(true);
    expect(good.json.booking.booking_ref).toBe(ref);
  });

  it("refuses move when the phone does not match, and moves when it does", async () => {
    await insertSlot("t-phone-2", 8);
    await insertSlot("t-phone-3", 9);
    const booked = await prepare({
      slot_id: "t-phone-2",
      customer_name: "Jean Roy",
      phone: "5145550144",
      service_type: "maintenance",
    });
    const book = await post("/tools/book_appointment",
      { token: booked.json.token, confirmed: true });
    const ref = book.json.booking_ref;

    // The phone is checked when the token is minted, so a wrong number never
    // reaches a read-back at all.
    const bad = await prepare({
      slot_id: "t-phone-3", booking_ref_to_move: ref, phone: "5145550000",
    });
    expect(bad.json).toEqual({ ok: false, error: "phone_mismatch" });

    const movePrep = await prepare({
      slot_id: "t-phone-3", booking_ref_to_move: ref, phone: "514 555 0144",
    });
    expect(movePrep.json.ok).toBe(true);

    const unconfirmed = await post("/tools/move_appointment", {
      token: movePrep.json.token, confirmed: false,
    });
    expect(unconfirmed.json).toEqual({ ok: false, error: "not_confirmed" });

    const good = await post("/tools/move_appointment", {
      token: movePrep.json.token, confirmed: true,
    });
    expect(good.json.ok).toBe(true);
    expect(good.json.slot_id).toBe("t-phone-3");

    const oldSlot = await env.DB.prepare(`SELECT taken FROM slots WHERE id = ?`)
      .bind("t-phone-2").first<{ taken: number }>();
    const newSlot = await env.DB.prepare(`SELECT taken FROM slots WHERE id = ?`)
      .bind("t-phone-3").first<{ taken: number }>();
    expect(oldSlot?.taken).toBe(0);
    expect(newSlot?.taken).toBe(1);

    // A move token is single-use too.
    const replay = await post("/tools/move_appointment", {
      token: movePrep.json.token, confirmed: true,
    });
    expect(replay.json).toEqual({ ok: false, error: "needs_prepare" });
  });

  it("refuses a book token on move_appointment", async () => {
    await insertSlot("t-phone-4", 10);
    const prep = await prepare({
      slot_id: "t-phone-4", customer_name: "Jean Roy",
      phone: "5145550144", service_type: "maintenance",
    });
    const { json } = await post("/tools/move_appointment",
      { token: prep.json.token, confirmed: true });
    expect(json).toEqual({ ok: false, error: "needs_prepare" });
  });

  it("still works with the seeded fixture booking", async () => {
    // reset_fixture needs a free slot on the next Monday at 09:00 to seed onto.
    const types = JSON.stringify(["oil_change", "tires", "recall_repair", "diagnostic", "maintenance"]);
    await env.DB.prepare(
      `INSERT INTO slots (id, start_ts, bay, service_types, taken) VALUES (?, ?, 1, ?, 0)`,
    ).bind("fx-monday", new Date(nextMondayNineUtc()).toISOString(), types).run();
    const seeded = await post("/admin/reset_fixture", {});
    expect(seeded.json.ok).toBe(true);

    await insertSlot("t-phone-5", 11);
    const prep = await prepare({
      slot_id: "t-phone-5",
      booking_ref_to_move: "GAL-TEST1",
      phone: "514 555 0199",
      language: "fr",
    });
    expect(prep.json.ok).toBe(true);
    const moved = await post("/tools/move_appointment",
      { token: prep.json.token, confirmed: true });
    expect(moved.json.ok).toBe(true);
    expect(moved.json.booking_ref).toBe("GAL-TEST1");
    expect(moved.json.slot_id).toBe("t-phone-5");
  });
});

describe("post_call webhook", () => {
  it("stores the payload when the shared secret is present", async () => {
    const { json } = await post("/webhooks/post_call", {
      type: "post_call_transcription",
      data: {
        conversation_id: "conv-webhook-1",
        status: "done",
        agent_id: "agent_123",
        metadata: { call_duration_secs: 143 },
        analysis: {
          call_successful: "success",
          transcript_summary: "Caller booked an oil change.",
          data_collection: { intent: "booking" },
        },
      },
    });
    expect(json.ok).toBe(true);

    const row = await env.DB.prepare(`SELECT * FROM calls WHERE conversation_id = ?`)
      .bind("conv-webhook-1").first<any>();
    expect(row.agent_id).toBe("agent_123");
    expect(row.duration_secs).toBe(143);
    expect(row.call_successful).toBe("success");
    expect(JSON.parse(row.data_collection_json).intent).toBe("booking");
  });

  it("rejects the webhook without a secret or signature", async () => {
    const { status, json } = await post("/webhooks/post_call", { data: { conversation_id: "x" } }, null);
    expect(status).toBe(401);
    expect(json).toEqual({ ok: false, error: "unauthorized" });
  });
});

/* ---- admin/reset_fixture ------------------------------------------------ */

/** Toronto wall-clock parts of an instant (workerd ships full ICU). */
function torontoParts(utcMs: number) {
  const fmt = new Intl.DateTimeFormat("en-US", {
    timeZone: "America/Toronto",
    hourCycle: "h23",
    year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", second: "2-digit",
  });
  const p: Record<string, string> = {};
  for (const part of fmt.formatToParts(new Date(utcMs))) p[part.type] = part.value;
  return { y: +p.year, mo: +p.month, d: +p.day, h: +p.hour, mi: +p.minute, s: +p.second };
}

/** UTC instant of the next Monday 09:00 Toronto time, strictly after today. */
function nextMondayNineUtc(): number {
  const now = torontoParts(Date.now());
  const dow = new Date(Date.UTC(now.y, now.mo - 1, now.d)).getUTCDay() || 7; // 1=Mon..7=Sun
  const daysAhead = (8 - dow) % 7 || 7;
  const monday = new Date(Date.UTC(now.y, now.mo - 1, now.d) + daysAhead * 86400_000);
  const y = monday.getUTCFullYear();
  const mo = monday.getUTCMonth() + 1;
  const d = monday.getUTCDate();
  // 09:00 Toronto is 13:00Z under EDT and 14:00Z under EST.
  const thirteen = Date.UTC(y, mo - 1, d, 13, 0);
  return torontoParts(thirteen).h === 9 ? thirteen : Date.UTC(y, mo - 1, d, 14, 0);
}

describe("admin/reset_fixture", () => {
  it("rejects a call with no secret", async () => {
    const { status, json } = await post("/admin/reset_fixture", {}, null);
    expect(status).toBe(401);
    expect(json).toEqual({ ok: false, error: "unauthorized" });
  });

  it("seeds GAL-TEST1 on the next Monday at 09:00 and can be re-run", async () => {
    const nine = nextMondayNineUtc();
    const types = JSON.stringify(["oil_change", "tires", "recall_repair", "diagnostic", "maintenance"]);
    await env.DB.prepare(
      `INSERT INTO slots (id, start_ts, bay, service_types, taken) VALUES (?, ?, 1, ?, 0)`,
    ).bind("fixture-a", new Date(nine).toISOString(), types).run();
    await env.DB.prepare(
      `INSERT INTO slots (id, start_ts, bay, service_types, taken) VALUES (?, ?, 1, ?, 0)`,
    ).bind("fixture-b", new Date(nine + 90 * 60_000).toISOString(), types).run();

    const one = await post("/admin/reset_fixture", {});
    expect(one.status).toBe(200);
    expect(one.json.ok).toBe(true);
    expect(one.json.booking_ref).toBe("GAL-TEST1");
    expect(one.json.customer_name).toBe("Test Client");
    expect(one.json.phone).toBe("5145550199");
    expect(one.json.service_type).toBe("oil_change");
    expect(one.json.slot_id).toBe("fixture-a");

    const takenA = await env.DB.prepare(`SELECT taken FROM slots WHERE id = 'fixture-a'`)
      .first<{ taken: number }>();
    expect(takenA?.taken).toBe(1);

    // The seeded booking is usable by the move scenarios: it looks up with its phone.
    const lookup = await post("/tools/lookup_appointment", {
      booking_ref: "GAL-TEST1", phone: "514 555 0199",
    });
    expect(lookup.json.ok).toBe(true);
    expect(lookup.json.booking.slot_id).toBe("fixture-a");

    // Simulate a suite run that moved the seeded booking to another slot: the
    // reset must free that slot and put the booking back on the canonical one.
    await env.DB.prepare(`UPDATE slots SET taken = 0 WHERE id = 'fixture-a'`).run();
    await env.DB.prepare(`UPDATE slots SET taken = 1 WHERE id = 'fixture-b'`).run();
    await env.DB.prepare(`UPDATE appointments SET slot_id = 'fixture-b' WHERE booking_ref = 'GAL-TEST1'`).run();

    const two = await post("/admin/reset_fixture", {});
    expect(two.json.ok).toBe(true);
    expect(two.json.slot_id).toBe("fixture-a");

    const freedB = await env.DB.prepare(`SELECT taken FROM slots WHERE id = 'fixture-b'`)
      .first<{ taken: number }>();
    const retakenA = await env.DB.prepare(`SELECT taken FROM slots WHERE id = 'fixture-a'`)
      .first<{ taken: number }>();
    expect(freedB?.taken).toBe(0);
    expect(retakenA?.taken).toBe(1);

    const rows = await env.DB.prepare(
      `SELECT booking_ref FROM appointments WHERE booking_ref = 'GAL-TEST1'`,
    ).all();
    expect(rows.results?.length).toBe(1);
  });
});
