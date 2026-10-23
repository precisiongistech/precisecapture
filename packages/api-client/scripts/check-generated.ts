/** Fails when src/schema.ts is stale relative to contract/openapi.json (CI). */
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const current = readFileSync(join(root, "src", "schema.ts"), "utf8");
const fresh = execFileSync(
  "pnpm",
  ["exec", "openapi-typescript", "../../contract/openapi.json", "--alphabetize", "--root-types"],
  { cwd: root, encoding: "utf8", stdio: ["ignore", "pipe", "inherit"] },
);
if (current.trim() !== fresh.trim()) {
  console.error("packages/api-client/src/schema.ts is stale: run `make contract`");
  process.exit(1);
}
console.log("src/schema.ts is up to date");
