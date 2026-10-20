-- allo-tools D1 schema. Apply with:
--   wrangler d1 execute allo --file=worker/schema.sql --remote

DROP TABLE IF EXISTS slots;
DROP TABLE IF EXISTS appointments;
DROP TABLE IF EXISTS pending_bookings;
DROP TABLE IF EXISTS tool_calls;
DROP TABLE IF EXISTS calls;

CREATE TABLE slots (
  id            TEXT PRIMARY KEY,
  start_ts      TEXT NOT NULL,          -- ISO-8601 UTC instant, e.g. 2026-10-16T11:30:00.000Z
  bay           INTEGER NOT NULL,
  service_types TEXT NOT NULL,          -- JSON array of service codes
  taken         INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_slots_start ON slots (start_ts);
CREATE INDEX idx_slots_free  ON slots (taken, start_ts);

CREATE TABLE appointments (
  booking_ref        TEXT PRIMARY KEY,
  slot_id            TEXT NOT NULL,
  customer_name      TEXT NOT NULL,
  phone              TEXT NOT NULL,
  vin_or_vehicle     TEXT,
  service_type       TEXT,
  additional_services TEXT,                        -- JSON array of extra service codes
  language           TEXT,
  created_ts         TEXT NOT NULL,
  status             TEXT NOT NULL DEFAULT 'booked'   -- booked | moved | cancelled
);
CREATE INDEX idx_appt_phone ON appointments (phone);

-- Two-step booking: prepare_booking writes one pending row and returns a token;
-- book_appointment / move_appointment consume it. Single-use, 10-minute TTL, and
-- every field the caller agreed to is bound to the token.
CREATE TABLE pending_bookings (
  token               TEXT PRIMARY KEY,
  kind                TEXT NOT NULL,               -- 'book' | 'move'
  slot_id             TEXT NOT NULL,
  customer_name       TEXT,
  phone               TEXT NOT NULL,
  vin_or_vehicle      TEXT,
  service_type        TEXT,
  additional_services TEXT,                        -- JSON array, or NULL
  language            TEXT NOT NULL,
  booking_ref         TEXT,                        -- the appointment being moved, for kind='move'
  readback_fr         TEXT NOT NULL,
  readback_en         TEXT NOT NULL,
  created_ms          INTEGER NOT NULL,
  used                INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_pending_created ON pending_bookings (created_ms);

CREATE TABLE tool_calls (
  id              TEXT PRIMARY KEY,
  ts              TEXT NOT NULL,
  tool            TEXT NOT NULL,
  args_json       TEXT,
  result_json     TEXT,
  conversation_id TEXT
);

CREATE TABLE calls (
  conversation_id     TEXT PRIMARY KEY,
  agent_id            TEXT,
  status              TEXT,
  duration_secs       REAL,
  call_successful     TEXT,
  transcript_summary  TEXT,
  data_collection_json TEXT,
  raw_json            TEXT,
  received_ts         TEXT NOT NULL
);
