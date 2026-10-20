/**
 * allo-tools — the Cloudflare Worker that backs the "allo" ElevenLabs agent.
 *
 * Every tool endpoint is POST + JSON, requires the shared header
 * `X-Allo-Secret`, returns JSON, and never throws a raw error:
 * failures come back as {ok:false, error:"<code>"} with an HTTP status.
 *
 * Every authenticated call (tool or webhook) is appended to D1 `tool_calls`.
 */

export interface Env {
  DB: D1Database;
  /** Shared secret the agent sends in `X-Allo-Secret`. */
  TOOLS_SECRET?: string;
  /** ElevenLabs HMAC signing secret for the post-call webhook, once configured. */
  ELEVENLABS_WEBHOOK_SECRET?: string;
}

const TZ = "America/Toronto";

const SERVICE_TYPES = [
  "oil_change",
  "tires",
  "recall_repair",
  "diagnostic",
  "maintenance",
] as const;

const TC_BASE = "https://data.tc.gc.ca/v1.3/api/eng/vehicle-recall-database";
const NHTSA_BASE = "https://vpic.nhtsa.dot.gov/api/vehicles/DecodeVinValues";

/** How long a prepare_booking token stays valid. */
const TOKEN_TTL_MS = 10 * 60 * 1000;

/** Spoken service names, so a read-back is speakable verbatim in either language. */
const SERVICE_LABELS: Record<string, { fr: string; en: string }> = {
  oil_change: { fr: "un changement d'huile", en: "an oil change" },
  tires: { fr: "un service de pneus", en: "a tire service" },
  recall_repair: { fr: "une réparation de rappel", en: "a recall repair" },
  diagnostic: { fr: "un diagnostic", en: "a diagnostic" },
  maintenance: { fr: "un entretien", en: "a maintenance service" },
};

const FR_DIGITS = ["zéro", "un", "deux", "trois", "quatre", "cinq", "six", "sept", "huit", "neuf"];
const EN_DIGITS = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"];

/* ------------------------------------------------------------------ *
 * small helpers
 * ------------------------------------------------------------------ */

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json; charset=utf-8" },
  });
}

function ok(body: Record<string, unknown>): Response {
  return json({ ok: true, ...body });
}

function fail(error: string, status = 200): Response {
  return json({ ok: false, error }, status);
}

function pad2(n: number): string {
  return String(n).padStart(2, "0");
}

/** Current Toronto wall-clock parts for an instant. */
function tzParts(utcMs: number) {
  const fmt = new Intl.DateTimeFormat("en-US", {
    timeZone: TZ,
    hourCycle: "h23",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
  const p: Record<string, string> = {};
  for (const part of fmt.formatToParts(new Date(utcMs))) p[part.type] = part.value;
  return {
    y: Number(p.year),
    mo: Number(p.month),
    d: Number(p.day),
    h: Number(p.hour),
    mi: Number(p.minute),
    s: Number(p.second),
  };
}

/** Offset of Toronto from UTC, in ms, at a given instant (negative in the Americas). */
function torontoOffsetMs(utcMs: number): number {
  const p = tzParts(utcMs);
  const asIfUtc = Date.UTC(p.y, p.mo - 1, p.d, p.h, p.mi, p.s);
  return asIfUtc - Math.floor(utcMs / 1000) * 1000;
}

/** Toronto wall-clock date+time -> UTC instant (ms). Handles EDT/EST. */
function wallToUtc(
  y: number,
  mo: number,
  d: number,
  h: number,
  mi: number,
): number {
  const target = Date.UTC(y, mo - 1, d, h, mi, 0);
  let guess = target;
  for (let i = 0; i < 4; i++) {
    const next = target - torontoOffsetMs(guess);
    if (next === guess) break;
    guess = next;
  }
  return guess;
}

function isoWithOffset(utcMs: number): string {
  const p = tzParts(utcMs);
  const offMin = torontoOffsetMs(utcMs) / 60000;
  const sign = offMin >= 0 ? "+" : "-";
  const abs = Math.abs(offMin);
  return (
    `${p.y}-${pad2(p.mo)}-${pad2(p.d)}T${pad2(p.h)}:${pad2(p.mi)}:${pad2(p.s)}` +
    `${sign}${pad2(Math.floor(abs / 60))}:${pad2(abs % 60)}`
  );
}

const FR_WEEKDAYS = ["", "lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"];
const FR_MONTHS = [
  "", "janvier", "février", "mars", "avril", "mai", "juin",
  "juillet", "août", "septembre", "octobre", "novembre", "décembre",
];

/** "jeudi 16 octobre à 9 h 00" — Québec convention. */
function humanFr(utcMs: number): string {
  const p = tzParts(utcMs);
  const weekdayIdx = isoWeekdayIndex(utcMs);
  return `${FR_WEEKDAYS[weekdayIdx]} ${p.d} ${FR_MONTHS[p.mo]} à ${p.h} h ${pad2(p.mi)}`;
}

const EN_WEEKDAYS = ["", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
const EN_MONTHS = [
  "", "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

/** "Thursday, October 16 at 9:00 AM" */
function humanEn(utcMs: number): string {
  const p = tzParts(utcMs);
  const h12 = p.h % 12 === 0 ? 12 : p.h % 12;
  const ampm = p.h < 12 ? "AM" : "PM";
  return (
    `${EN_WEEKDAYS[isoWeekdayIndex(utcMs)]}, ${EN_MONTHS[p.mo]} ${p.d}` +
    ` at ${h12}:${pad2(p.mi)} ${ampm}`
  );
}

/** 1 = Monday .. 7 = Sunday, for the Toronto-local date of an instant. */
function isoWeekdayIndex(utcMs: number): number {
  const p = tzParts(utcMs);
  const dow = new Date(Date.UTC(p.y, p.mo - 1, p.d)).getUTCDay(); // 0=Sun
  return dow === 0 ? 7 : dow;
}

function slotTimes(utcMs: number, lang?: string) {
  const out: Record<string, string> = {
    start_ts: isoWithOffset(utcMs),
    start_local_fr: humanFr(utcMs),
    start_local_en: humanEn(utcMs),
  };
  if (lang === "fr") out.start_local = humanFr(utcMs);
  else if (lang === "en") out.start_local = humanEn(utcMs);
  return out;
}

function toE164ish(raw: unknown): string {
  return String(raw ?? "").replace(/[^\d+]/g, "");
}

/* ------------------------------------------------------------------ *
 * auth + audit
 * ------------------------------------------------------------------ */

function secretOk(req: Request, env: Env): boolean {
  const expected = env.TOOLS_SECRET;
  if (!expected) return false;
  const got = req.headers.get("X-Allo-Secret") ?? "";
  // constant-time-ish compare
  if (got.length !== expected.length) return false;
  let diff = 0;
  for (let i = 0; i < got.length; i++) diff |= got.charCodeAt(i) ^ expected.charCodeAt(i);
  return diff === 0;
}

async function audit(
  env: Env,
  tool: string,
  args: unknown,
  result: unknown,
  conversationId: string | null,
): Promise<void> {
  try {
    await env.DB.prepare(
      `INSERT INTO tool_calls (id, ts, tool, args_json, result_json, conversation_id)
       VALUES (?, ?, ?, ?, ?, ?)`,
    )
      .bind(
        crypto.randomUUID(),
        new Date().toISOString(),
        tool,
        JSON.stringify(args ?? null),
        JSON.stringify(result ?? null),
        conversationId,
      )
      .run();
  } catch {
    // Audit logging must never break a tool response.
  }
}

/* ------------------------------------------------------------------ *
 * HMAC verification for the ElevenLabs post-call webhook
 * ------------------------------------------------------------------ */

/**
 * ElevenLabs signs post-call webhooks as `ElevenLabs-Signature: t=<unix>,v0=<hex>`
 * where v0 = HMAC-SHA256(secret, `${t}.${rawBody}`). Returns:
 *   "valid" | "invalid" | "absent"
 */
async function verifyWebhookSignature(
  req: Request,
  rawBody: string,
  secret: string | undefined,
): Promise<"valid" | "invalid" | "absent"> {
  const header =
    req.headers.get("ElevenLabs-Signature") ?? req.headers.get("elevenlabs-signature");
  if (!header) return "absent";
  if (!secret) return "absent";

  const parts: Record<string, string> = {};
  for (const chunk of header.split(",")) {
    const idx = chunk.indexOf("=");
    if (idx > 0) parts[chunk.slice(0, idx).trim()] = chunk.slice(idx + 1).trim();
  }
  const t = parts["t"];
  const v0 = parts["v0"];
  if (!t || !v0) return "invalid";

  const key = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const mac = await crypto.subtle.sign(
    "HMAC",
    key,
    new TextEncoder().encode(`${t}.${rawBody}`),
  );
  const hex = [...new Uint8Array(mac)].map((b) => b.toString(16).padStart(2, "0")).join("");
  if (hex.length !== v0.length) return "invalid";
  let diff = 0;
  for (let i = 0; i < hex.length; i++) diff |= hex.charCodeAt(i) ^ v0.charCodeAt(i);
  return diff === 0 ? "valid" : "invalid";
}

/* ------------------------------------------------------------------ *
 * external API payload readers
 * ------------------------------------------------------------------ */

type TcRow = Array<{ Name: string; Value?: { Literal?: unknown } }>;

function tcField(row: TcRow, name: string): string | null {
  for (const f of row) {
    if (f.Name === name) {
      const lit = f.Value?.Literal;
      return lit === undefined || lit === null ? null : String(lit);
    }
  }
  return null;
}

function truncate(s: string, n: number): string {
  return s.length <= n ? s : s.slice(0, n - 1).trimEnd() + "…";
}

/* ------------------------------------------------------------------ *
 * handlers
 * ------------------------------------------------------------------ */

/**
 * Normalize a VIN to the form NHTSA expects: uppercase, no spaces, no dashes.
 * Normalizing is safe — case and separators carry no information. It never
 * repairs a wrong length, so a 16- or 18-character VIN still fails validation.
 */
function normalizeVin(raw: unknown): string {
  return String(raw ?? "")
    .replace(/[\s-]/g, "")
    .toUpperCase();
}

async function handleDecodeVin(env: Env, body: Record<string, unknown>) {
  const vin = normalizeVin(body.vin);
  if (!/^[A-HJ-NPR-Z0-9]{17}$/.test(vin)) {
    return fail("invalid_vin");
  }
  const res = await fetch(`${NHTSA_BASE}/${encodeURIComponent(vin)}?format=json`);
  if (!res.ok) return fail("upstream_error");
  const payload = (await res.json()) as any;
  const row = payload?.Results?.[0] ?? {};
  return ok({
    vin,
    make: (row.Make ?? "").trim(),
    model: (row.Model ?? "").trim(),
    year: (row.ModelYear ?? "").trim(),
    plant_country: (row.PlantCountry ?? "").trim(),
  });
}

async function handleCheckRecalls(env: Env, body: Record<string, unknown>) {
  const make = String(body.make ?? "").trim().toUpperCase();
  const model = String(body.model ?? "").trim().toUpperCase();
  const year = String(body.year ?? "").trim();
  const lang = body.lang === "fr" ? "fr" : "en";

  if (!make || !model || !/^\d{4}$/.test(year)) {
    return fail("invalid_args");
  }

  // Cache is per-request only (a fresh Map inside this handler).
  // data.tc.gc.ca answers 500 ("Runtime Error") to a request whose Accept header
  // is not application/json — Workers' fetch defaults to */*, so set it
  // explicitly. Verified live 2026-10-15.
  // data.tc.gc.ca also throws sporadic 500s (observed 2026-10-15), so a 5xx is
  // retried twice before it is reported upstream.
  const cache = new Map<string, any>();
  const getJson = async (url: string) => {
    if (cache.has(url)) return cache.get(url);
    let lastStatus = 0;
    for (let attempt = 0; attempt < 3; attempt++) {
      const r = await fetch(url, { headers: { Accept: "application/json" } });
      if (r.ok) {
        const j = await r.json();
        cache.set(url, j);
        return j;
      }
      lastStatus = r.status;
      if (r.status < 500) break;
    }
    throw new Error(`upstream ${lastStatus}`);
  };

  let listRows: TcRow[];
  try {
    const list = await getJson(
      `${TC_BASE}/recall/make-name/${encodeURIComponent(make)}` +
        `/model-name/${encodeURIComponent(model)}/year-range/${year}-${year}?format=json`,
    );
    listRows = Array.isArray(list?.ResultSet) ? list.ResultSet : [];
  } catch (e) {
    return json({ ok: false, error: "upstream_error", detail: String(e) });
  }

  // Newest first, then take 5.
  const listMeta = listRows.map((row) => ({
    recall_number: tcField(row, "Recall number") ?? "",
    recall_date: tcField(row, "Recall date") ?? "",
    sortKey: Date.parse(tcField(row, "Recall date") ?? "") || 0,
  }));
  listMeta.sort((a, b) => b.sortKey - a.sortKey);
  const top = listMeta.filter((r) => r.recall_number).slice(0, 5);

  const suffix = lang === "fr" ? "FTXT" : "ETXT";
  const recalls = [];
  for (const meta of top) {
    let row: TcRow | null = null;
    try {
      const detail = await getJson(
        `${TC_BASE}/recall-summary/recall-number/${encodeURIComponent(meta.recall_number)}?format=json`,
      );
      const set = Array.isArray(detail?.ResultSet) ? detail.ResultSet : [];
      row = Array.isArray(set[0]) ? (set[0] as TcRow) : null;
    } catch {
      row = null;
    }
    const component =
      (row && tcField(row, `SYSTEM_TYPE_${suffix}`)) ??
      (row && tcField(row, "SYSTEM_TYPE_ETXT")) ??
      "";
    const summaryRaw =
      (row && tcField(row, `COMMENT_${suffix}`)) ??
      (row && tcField(row, "COMMENT_ETXT")) ??
      "";
    recalls.push({
      recall_number: meta.recall_number,
      date: (row && tcField(row, "RECALL_DATE_DTE")) ?? meta.recall_date,
      component,
      summary: truncate(summaryRaw.replace(/\s+/g, " ").trim(), 400),
    });
  }

  return ok({ count_total: listRows.length, lang, recalls });
}

async function handleFindSlots(env: Env, body: Record<string, unknown>) {
  const dateFrom = String(body.date_from ?? "").trim();
  const serviceType = String(body.service_type ?? "").trim();
  const lang = body.lang === "en" ? "en" : body.lang === "fr" ? "fr" : undefined;

  if (!/^\d{4}-\d{2}-\d{2}$/.test(dateFrom)) return fail("invalid_date_from");
  if (serviceType && !(SERVICE_TYPES as readonly string[]).includes(serviceType)) {
    return fail("invalid_service_type");
  }

  // Local Toronto midnight for date_from -> UTC instant.
  const [y, mo, d] = dateFrom.split("-").map(Number);
  const fromUtc = new Date(wallToUtc(y, mo, d, 0, 0)).toISOString();

  const rows = await env.DB.prepare(
    `SELECT id, start_ts, bay, service_types
       FROM slots
      WHERE taken = 0 AND start_ts >= ?
      ORDER BY start_ts ASC
      LIMIT 40`,
  )
    .bind(fromUtc)
    .all<{ id: string; start_ts: string; bay: number; service_types: string }>();

  const out = [];
  for (const r of (rows.results ?? [])) {
    let types: string[] = [];
    try {
      types = JSON.parse(r.service_types ?? "[]");
    } catch {
      types = [];
    }
    if (serviceType && types.length && !types.includes(serviceType)) continue;
    out.push({
      slot_id: r.id,
      bay: r.bay,
      service_types: types,
      ...slotTimes(Date.parse(r.start_ts), lang),
    });
    if (out.length === 5) break;
  }

  return ok({ count: out.length, slots: out });
}

/* ------------------------------------------------------------------ *
 * the spoken read-back produced by prepare_booking
 * ------------------------------------------------------------------ */

/** A phone number in grouped spoken digits, 3-3-4 for a 10-digit number. */
function spokenPhone(raw: unknown, lang: "fr" | "en"): string {
  let digits = String(raw ?? "").replace(/\D/g, "");
  if (digits.length === 11 && digits.startsWith("1")) digits = digits.slice(1);
  if (!digits) return "";
  const words = lang === "fr" ? FR_DIGITS : EN_DIGITS;
  // A 10-digit number reads 3-3-4, the way it is written here; anything else
  // falls back to even groups of three.
  const ends: number[] = [];
  if (digits.length === 10) ends.push(3, 6, 10);
  else for (let i = 3; i < digits.length; i += 3) ends.push(i);
  if (ends[ends.length - 1] !== digits.length) ends.push(digits.length);

  const speak = (chunk: string) =>
    chunk.split("").map((d) => words[Number(d)]).join("-");
  const groups: string[] = [];
  let at = 0;
  for (const end of ends) {
    groups.push(speak(digits.slice(at, end)));
    at = end;
  }
  return groups.join(", ");
}

/** "un changement d'huile et un service de pneus" */
function spokenService(serviceType: string, additional: string[], lang: "fr" | "en"): string {
  const codes = [serviceType, ...additional].filter(Boolean);
  const names = codes.map((code) => SERVICE_LABELS[code]?.[lang] ?? code);
  if (names.length === 0) return lang === "fr" ? "un rendez-vous" : "an appointment";
  if (names.length === 1) return names[0];
  const last = names[names.length - 1];
  const head = names.slice(0, -1).join(", ");
  return `${head} ${lang === "fr" ? "et" : "and"} ${last}`;
}

function readbackFor(
  kind: "book" | "move",
  rec: {
    service_type: string | null;
    additional_services: string | null;
    vin_or_vehicle: string | null;
    customer_name: string | null;
    phone: string;
  },
  startUtcMs: number,
  lang: "fr" | "en",
): string {
  let additional: string[] = [];
  try {
    const parsed = JSON.parse(rec.additional_services ?? "[]");
    if (Array.isArray(parsed)) additional = parsed.map(String);
  } catch {
    additional = [];
  }
  const service = spokenService(String(rec.service_type ?? ""), additional, lang);
  const vehicle = String(rec.vin_or_vehicle ?? "").trim();
  const name = String(rec.customer_name ?? "").trim();
  const phone = spokenPhone(rec.phone, lang);

  if (lang === "fr") {
    const head = kind === "move" ? "Votre nouveau rendez-vous," : "Donc";
    const car = vehicle ? `pour votre ${vehicle}` : "pour votre véhicule";
    const who = name ? `, au nom de ${name}` : "";
    return `${head} ${service} ${car}${who}, au ${phone}, ${humanFr(startUtcMs)} — c'est bien ça?`;
  }
  const head = kind === "move" ? "Your new appointment," : "So that's";
  const car = vehicle ? `for your ${vehicle}` : "for your vehicle";
  const who = name ? `, under the name ${name}` : "";
  return `${head} ${service} ${car}${who}, at ${phone}, ${humanEn(startUtcMs)} — is that right?`;
}

/** 32 hex characters, cryptographically random. */
function makeToken(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  return [...bytes].map((b) => b.toString(16).padStart(2, "0")).join("");
}

function makeBookingRef(): string {
  // 5 chars, unambiguous alphabet, uniformly random.
  const alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789";
  const bytes = crypto.getRandomValues(new Uint8Array(5));
  let ref = "";
  for (const b of bytes) ref += alphabet[b % alphabet.length];
  return `GAL-${ref}`;
}

/** A JSON array of service codes, or null when the caller gave none. */
function normalizeServices(raw: unknown): string[] | null {
  if (!Array.isArray(raw)) return null;
  const out = raw.map((v) => String(v ?? "").trim()).filter((v) => v.length > 0);
  return out.length ? out : null;
}

function parseServices(raw: unknown): string[] | null {
  try {
    const parsed = JSON.parse(String(raw ?? ""));
    return Array.isArray(parsed) && parsed.length ? parsed.map(String) : null;
  } catch {
    return null;
  }
}

type PendingRow = {
  token: string;
  kind: string;
  slot_id: string;
  customer_name: string | null;
  phone: string;
  vin_or_vehicle: string | null;
  service_type: string | null;
  additional_services: string | null;
  language: string;
  booking_ref: string | null;
  readback_fr: string;
  readback_en: string;
  created_ms: number;
  used: number;
};

/**
 * Load a pending row and check it is still usable. Missing, already used and
 * wrong-kind tokens all mean the same thing to the agent: call prepare_booking
 * again. Only a genuine timeout gets its own code.
 */
async function loadPending(
  env: Env,
  token: string,
): Promise<{ rec: PendingRow } | { error: string }> {
  if (!token) return { error: "needs_prepare" };
  const rec = await env.DB.prepare(`SELECT * FROM pending_bookings WHERE token = ?`)
    .bind(token)
    .first<PendingRow>();
  if (!rec) return { error: "needs_prepare" };
  if (rec.used) return { error: "needs_prepare" };
  if (Date.now() - Number(rec.created_ms) > TOKEN_TTL_MS) return { error: "token_expired" };
  return { rec };
}

/** Burn the token. Returns false when another request got there first. */
async function consumePending(env: Env, token: string): Promise<boolean> {
  const res = await env.DB.prepare(
    `UPDATE pending_bookings SET used = 1 WHERE token = ? AND used = 0`,
  )
    .bind(token)
    .run();
  return Boolean(res.meta?.changes);
}

/**
 * Step one of a two-step write. Nothing is reserved here: the slot is only
 * checked, and every field the caller will hear is frozen into a pending row
 * plus a single-use token. The read-back strings are the exact sentence the
 * agent must speak, in both languages.
 */
async function handlePrepareBooking(env: Env, body: Record<string, unknown>) {
  const slotId = String(body.slot_id ?? "").trim();
  const phone = toE164ish(body.phone);
  const moveRef = String(body.booking_ref_to_move ?? "").trim().toUpperCase();
  const language = body.language === "en" ? "en" : "fr";

  if (!slotId) return fail("invalid_slot_id");

  const slot = await env.DB.prepare(
    `SELECT id, start_ts, bay, taken FROM slots WHERE id = ?`,
  )
    .bind(slotId)
    .first<{ id: string; start_ts: string; bay: number; taken: number }>();
  if (!slot) return fail("slot_not_found");
  if (slot.taken) return fail("slot_taken");

  const kind = moveRef ? "move" : "book";
  let name = String(body.customer_name ?? "").trim();
  let vehicle = String(body.vin_or_vehicle ?? "").trim();
  let serviceType = String(body.service_type ?? "").trim();
  let additional = normalizeServices(body.additional_services);
  let bookingRef: string | null = null;

  if (kind === "move") {
    const appt = await env.DB.prepare(`SELECT * FROM appointments WHERE booking_ref = ?`)
      .bind(moveRef)
      .first<any>();
    if (!appt) return fail("booking_not_found");
    if (toE164ish(appt.phone) !== phone) return fail("phone_mismatch");
    if (appt.status === "cancelled") return fail("booking_cancelled");
    bookingRef = appt.booking_ref;
    // Anything the agent did not re-state is taken from the booking being moved.
    name = name || String(appt.customer_name ?? "");
    vehicle = vehicle || String(appt.vin_or_vehicle ?? "");
    serviceType = serviceType || String(appt.service_type ?? "");
    if (additional === null) additional = parseServices(appt.additional_services);
  } else {
    if (!name) return fail("missing_customer_name");
    if (phone.replace(/\D/g, "").length < 10) return fail("invalid_phone");
  }

  if (serviceType && !(SERVICE_TYPES as readonly string[]).includes(serviceType)) {
    return fail("invalid_service_type");
  }

  const rec = {
    service_type: serviceType || null,
    additional_services: additional ? JSON.stringify(additional) : null,
    vin_or_vehicle: vehicle || null,
    customer_name: name || null,
    phone,
  };
  const token = makeToken();

  await env.DB.prepare(
    `INSERT INTO pending_bookings
       (token, kind, slot_id, customer_name, phone, vin_or_vehicle, service_type,
        additional_services, language, booking_ref, readback_fr, readback_en,
        created_ms, used)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)`,
  )
    .bind(
      token,
      kind,
      slotId,
      rec.customer_name,
      rec.phone,
      rec.vin_or_vehicle,
      rec.service_type,
      rec.additional_services,
      language,
      bookingRef,
      readbackFor(kind, rec, Date.parse(slot.start_ts), "fr"),
      readbackFor(kind, rec, Date.parse(slot.start_ts), "en"),
      Date.now(),
    )
    .run();

  return ok({
    token,
    kind,
    expires_in_secs: Math.floor(TOKEN_TTL_MS / 1000),
    readback_fr: readbackFor(kind, rec, Date.parse(slot.start_ts), "fr"),
    readback_en: readbackFor(kind, rec, Date.parse(slot.start_ts), "en"),
    slot_id: slotId,
    bay: slot.bay,
    ...slotTimes(Date.parse(slot.start_ts), language),
  });
}

/**
 * Step two. Takes a token, never raw details: the only way to change a detail
 * is a new prepare_booking call, which means a new read-back and a new yes.
 */
async function handleBookAppointment(env: Env, body: Record<string, unknown>) {
  if (body.confirmed !== true) return fail("not_confirmed");

  const token = String(body.token ?? "").trim();
  const loaded = await loadPending(env, token);
  if ("error" in loaded) return fail(loaded.error);
  const rec = loaded.rec;
  if (rec.kind !== "book") return fail("needs_prepare");

  if (!(await consumePending(env, token))) return fail("needs_prepare");

  const slotId = rec.slot_id;
  const slot = await env.DB.prepare(
    `SELECT id, start_ts, bay, taken FROM slots WHERE id = ?`,
  )
    .bind(slotId)
    .first<{ id: string; start_ts: string; bay: number; taken: number }>();
  if (!slot) return fail("slot_not_found");
  if (slot.taken) return fail("slot_taken");

  // Reserve the slot atomically; the WHERE clause makes double-booking impossible.
  const claim = await env.DB.prepare(
    `UPDATE slots SET taken = 1 WHERE id = ? AND taken = 0`,
  )
    .bind(slotId)
    .run();
  if (!claim.meta?.changes) return fail("slot_taken");

  let bookingRef = makeBookingRef();
  for (let attempt = 0; attempt < 5; attempt++) {
    const clash = await env.DB.prepare(
      `SELECT booking_ref FROM appointments WHERE booking_ref = ?`,
    )
      .bind(bookingRef)
      .first();
    if (!clash) break;
    bookingRef = makeBookingRef();
  }

  const language = rec.language === "en" ? "en" : "fr";

  await env.DB.prepare(
    `INSERT INTO appointments
       (booking_ref, slot_id, customer_name, phone, vin_or_vehicle, service_type,
        additional_services, language, created_ts, status)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'booked')`,
  )
    .bind(
      bookingRef,
      slotId,
      rec.customer_name ?? "",
      rec.phone,
      rec.vin_or_vehicle ?? "",
      rec.service_type ?? "",
      rec.additional_services,
      language,
      new Date().toISOString(),
    )
    .run();

  return ok({
    booking_ref: bookingRef,
    slot_id: slotId,
    bay: slot.bay,
    service_type: rec.service_type ?? "",
    additional_services: rec.additional_services ? JSON.parse(rec.additional_services) : [],
    customer_name: rec.customer_name ?? "",
    phone: rec.phone,
    ...slotTimes(Date.parse(slot.start_ts), language),
  });
}

async function handleLookupAppointment(env: Env, body: Record<string, unknown>) {
  const ref = String(body.booking_ref ?? "").trim().toUpperCase();
  const phone = toE164ish(body.phone);
  if (!ref) return fail("invalid_booking_ref");

  const appt = await env.DB.prepare(
    `SELECT * FROM appointments WHERE booking_ref = ?`,
  )
    .bind(ref)
    .first<any>();
  if (!appt) return fail("booking_not_found");
  if (toE164ish(appt.phone) !== phone) return fail("phone_mismatch");

  const slot = await env.DB.prepare(`SELECT start_ts, bay FROM slots WHERE id = ?`)
    .bind(appt.slot_id)
    .first<{ start_ts: string; bay: number }>();

  return ok({
    booking: {
      booking_ref: appt.booking_ref,
      slot_id: appt.slot_id,
      bay: slot?.bay ?? null,
      customer_name: appt.customer_name,
      phone: appt.phone,
      vin_or_vehicle: appt.vin_or_vehicle,
      service_type: appt.service_type,
      language: appt.language,
      status: appt.status,
      created_ts: appt.created_ts,
      ...(slot ? slotTimes(Date.parse(slot.start_ts), appt.language) : {}),
    },
  });
}

async function handleMoveAppointment(env: Env, body: Record<string, unknown>) {
  if (body.confirmed !== true) return fail("not_confirmed");

  const token = String(body.token ?? "").trim();
  const loaded = await loadPending(env, token);
  if ("error" in loaded) return fail(loaded.error);
  const rec = loaded.rec;
  if (rec.kind !== "move" || !rec.booking_ref) return fail("needs_prepare");

  if (!(await consumePending(env, token))) return fail("needs_prepare");

  const ref = rec.booking_ref;
  const appt = await env.DB.prepare(`SELECT * FROM appointments WHERE booking_ref = ?`)
    .bind(ref)
    .first<any>();
  if (!appt) return fail("booking_not_found");
  // The phone was checked at prepare time; check it again because the booking
  // may have changed between the read-back and the yes.
  if (toE164ish(appt.phone) !== rec.phone) return fail("phone_mismatch");
  if (appt.status === "cancelled") return fail("booking_cancelled");

  const newSlotId = rec.slot_id;
  const slot = await env.DB.prepare(`SELECT id, start_ts, bay, taken FROM slots WHERE id = ?`)
    .bind(newSlotId)
    .first<{ id: string; start_ts: string; bay: number; taken: number }>();
  if (!slot) return fail("slot_not_found");
  if (slot.taken) return fail("slot_taken");

  const claim = await env.DB.prepare(`UPDATE slots SET taken = 1 WHERE id = ? AND taken = 0`)
    .bind(newSlotId)
    .run();
  if (!claim.meta?.changes) return fail("slot_taken");

  await env.DB.prepare(`UPDATE slots SET taken = 0 WHERE id = ?`).bind(appt.slot_id).run();
  await env.DB.prepare(
    `UPDATE appointments
        SET slot_id = ?, status = 'moved',
            service_type = ?, additional_services = ?
      WHERE booking_ref = ?`,
  )
    .bind(
      newSlotId,
      rec.service_type ?? appt.service_type,
      rec.additional_services ?? appt.additional_services,
      ref,
    )
    .run();

  return ok({
    booking_ref: ref,
    previous_slot_id: appt.slot_id,
    slot_id: newSlotId,
    bay: slot.bay,
    ...slotTimes(Date.parse(slot.start_ts), appt.language),
  });
}

/* ------------------------------------------------------------------ *
 * test fixture — the seeded booking the move scenarios depend on
 * ------------------------------------------------------------------ */

const FIXTURE_REF = "GAL-TEST1";
const FIXTURE_PHONE = "5145550199";

/**
 * Recreate the seeded booking GAL-TEST1 so the move/phone-check scenarios are
 * repeatable: free whatever slot the previous fixture held, then put GAL-TEST1
 * on the first free slot of the next Monday at or after 09:00 Toronto time.
 * Returns the booking, in the same shape as book_appointment.
 */
async function handleResetFixture(env: Env) {
  const previous = await env.DB.prepare(
    `SELECT slot_id FROM appointments WHERE booking_ref = ?`,
  )
    .bind(FIXTURE_REF)
    .first<{ slot_id: string }>();

  if (previous?.slot_id) {
    // Only free the slot if no other appointment is sitting on it.
    const other = await env.DB.prepare(
      `SELECT booking_ref FROM appointments WHERE slot_id = ? AND booking_ref != ?`,
    )
      .bind(previous.slot_id, FIXTURE_REF)
      .first();
    if (!other) {
      await env.DB.prepare(`UPDATE slots SET taken = 0 WHERE id = ?`)
        .bind(previous.slot_id)
        .run();
    }
  }
  await env.DB.prepare(`DELETE FROM appointments WHERE booking_ref = ?`)
    .bind(FIXTURE_REF)
    .run();

  // Pending prepare_booking tokens from an earlier run must not survive: they
  // hold the fixture's phone and would let a stale read-back still write.
  await env.DB.prepare(`DELETE FROM pending_bookings`).run();

  // The next Monday, Toronto wall clock, strictly after today.
  const nowMs = Date.now();
  const dow = isoWeekdayIndex(nowMs); // 1 = Monday .. 7 = Sunday
  const daysAhead = (8 - dow) % 7 || 7; // next Monday, never today
  const nowParts = tzParts(nowMs);
  const monday = new Date(
    Date.UTC(nowParts.y, nowParts.mo - 1, nowParts.d) + daysAhead * 86400_000,
  );
  const my = monday.getUTCFullYear();
  const mmo = monday.getUTCMonth() + 1;
  const md = monday.getUTCDate();

  const fromUtc = new Date(wallToUtc(my, mmo, md, 9, 0)).toISOString();
  const toUtc = new Date(wallToUtc(my, mmo, md + 1, 0, 0)).toISOString();

  const slot = await env.DB.prepare(
    `SELECT id, start_ts, bay FROM slots
      WHERE taken = 0 AND start_ts >= ? AND start_ts < ?
      ORDER BY start_ts ASC
      LIMIT 1`,
  )
    .bind(fromUtc, toUtc)
    .first<{ id: string; start_ts: string; bay: number }>();

  if (!slot) return fail("no_free_slot", 409);

  const claim = await env.DB.prepare(
    `UPDATE slots SET taken = 1 WHERE id = ? AND taken = 0`,
  )
    .bind(slot.id)
    .run();
  if (!claim.meta?.changes) return fail("slot_taken", 409);

  await env.DB.prepare(
    `INSERT INTO appointments
       (booking_ref, slot_id, customer_name, phone, vin_or_vehicle, service_type, language, created_ts, status)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'booked')`,
  )
    .bind(
      FIXTURE_REF,
      slot.id,
      "Test Client",
      FIXTURE_PHONE,
      "",
      "oil_change",
      "fr",
      new Date().toISOString(),
    )
    .run();

  return ok({
    booking_ref: FIXTURE_REF,
    slot_id: slot.id,
    bay: slot.bay,
    service_type: "oil_change",
    customer_name: "Test Client",
    phone: FIXTURE_PHONE,
    ...slotTimes(Date.parse(slot.start_ts), "fr"),
  });
}

async function handlePostCall(env: Env, body: Record<string, unknown>) {
  const data = (body.data ?? body) as Record<string, any>;
  const analysis = data?.analysis ?? {};
  const metadata = data?.metadata ?? {};
  const conversationId =
    data?.conversation_id ?? metadata?.conversation_id ?? body.conversation_id ?? null;

  if (!conversationId) return fail("missing_conversation_id");

  const durationSecs = Number(
    metadata?.call_duration_secs ?? body.duration_secs ?? data?.duration_secs ?? 0,
  );

  await env.DB.prepare(
    `INSERT INTO calls
       (conversation_id, agent_id, status, duration_secs, call_successful,
        transcript_summary, data_collection_json, raw_json, received_ts)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
     ON CONFLICT(conversation_id) DO UPDATE SET
       status = excluded.status,
       duration_secs = excluded.duration_secs,
       call_successful = excluded.call_successful,
       transcript_summary = excluded.transcript_summary,
       data_collection_json = excluded.data_collection_json,
       raw_json = excluded.raw_json,
       received_ts = excluded.received_ts`,
  )
    .bind(
      String(conversationId),
      String(metadata?.agent_id ?? body.agent_id ?? data?.agent_id ?? ""),
      String(data?.status ?? body.status ?? metadata?.status ?? ""),
      Number.isFinite(durationSecs) ? durationSecs : 0,
      String(analysis?.call_successful ?? body.call_successful ?? ""),
      String(analysis?.transcript_summary ?? body.transcript_summary ?? ""),
      JSON.stringify(analysis?.data_collection ?? body.data_collection ?? {}),
      JSON.stringify(body).slice(0, 200000),
      new Date().toISOString(),
    )
    .run();

  return ok({ stored: true, conversation_id: String(conversationId) });
}

/* ------------------------------------------------------------------ *
 * router
 * ------------------------------------------------------------------ */

export default {
  async fetch(req: Request, env: Env): Promise<Response> {
    const url = new URL(req.url);
    const path = url.pathname.replace(/\/+$/, "") || "/";

    if (req.method === "GET" && path === "/health") {
      return json({ ok: true });
    }

    if (req.method !== "POST") {
      return fail("method_not_allowed", 405);
    }

    let raw = "";
    let body: Record<string, unknown> = {};
    try {
      raw = await req.text();
      body = raw ? JSON.parse(raw) : {};
    } catch {
      return fail("invalid_json", 400);
    }

    // Post-call webhook: accept a valid ElevenLabs signature when one is present
    // and a signing secret is configured; otherwise fall back to the shared header.
    if (path === "/webhooks/post_call") {
      const verdict = await verifyWebhookSignature(req, raw, env.ELEVENLABS_WEBHOOK_SECRET);
      if (verdict === "invalid") {
        await audit(env, "post_call", body, { ok: false, error: "bad_signature" }, null);
        return fail("bad_signature", 401);
      }
      if (verdict === "absent" && !secretOk(req, env)) {
        await audit(env, "post_call", body, { ok: false, error: "unauthorized" }, null);
        return fail("unauthorized", 401);
      }
      const result = await handlePostCall(env, body);
      await audit(env, "post_call", body, await result.clone().json(), null);
      return result;
    }

    if (!secretOk(req, env)) {
      await audit(env, path, body, { ok: false, error: "unauthorized" }, null);
      return fail("unauthorized", 401);
    }

    const conversationId =
      typeof body.conversation_id === "string" ? body.conversation_id : null;

    // Test fixture: same auth as the tools, no /tools/ prefix.
    if (path === "/admin/reset_fixture") {
      const result = await handleResetFixture(env);
      let fixture: unknown = null;
      try {
        fixture = await result.clone().json();
      } catch {
        fixture = null;
      }
      await audit(env, "reset_fixture", body, fixture, conversationId);
      return result;
    }

    if (!path.startsWith("/tools/")) return fail("not_found", 404);

    const tool = path.slice("/tools/".length);
    let result: Response;
    try {
      switch (tool) {
        case "decode_vin":
          result = await handleDecodeVin(env, body);
          break;
        case "check_recalls":
          result = await handleCheckRecalls(env, body);
          break;
        case "find_slots":
          result = await handleFindSlots(env, body);
          break;
        case "prepare_booking":
          result = await handlePrepareBooking(env, body);
          break;
        case "book_appointment":
          result = await handleBookAppointment(env, body);
          break;
        case "move_appointment":
          result = await handleMoveAppointment(env, body);
          break;
        case "lookup_appointment":
          result = await handleLookupAppointment(env, body);
          break;
        default:
          return fail("unknown_tool", 404);
      }
    } catch (e) {
      result = fail("internal_error", 500);
    }

    let parsed: unknown = null;
    try {
      parsed = await result.clone().json();
    } catch {
      parsed = null;
    }
    await audit(env, tool, body, parsed, conversationId);
    return result;
  },
};
