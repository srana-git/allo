import { env } from "cloudflare:test";
import schema from "../schema.sql?raw";

// Fresh schema for every test run. D1's exec() wants one statement per line and
// chokes on leading SQL comments, so strip comments and split on ";" instead.
const statements = schema
  .split("\n")
  .filter((line) => !line.trim().startsWith("--"))
  .join("\n")
  .split(";")
  .map((s) => s.trim())
  .filter((s) => s.length > 0);

await env.DB.batch(statements.map((s) => env.DB.prepare(s)));
