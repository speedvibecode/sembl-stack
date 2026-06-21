import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { spawnSync } from "node:child_process";

const root = process.cwd();
const envPath = join(root, ".env.local");
const vercelProjectPath = join(root, ".vercel", "project.json");
const supabaseConfigPath = join(root, "supabase", "config.toml");
const migrationPath = join(
  root,
  "supabase",
  "migrations",
  "202606200001_feedback_board.sql",
);

const localEnv = existsSync(envPath) ? parseEnv(readFileSync(envPath, "utf8")) : {};
const mergedEnv = { ...process.env, ...localEnv };

const checks = [
  commandCheck("vercel", ["--version"], "Vercel CLI"),
  commandCheck("npx", ["supabase", "--version"], "Supabase CLI"),
  fileCheck(vercelProjectPath, "Vercel project link"),
  fileCheck(supabaseConfigPath, "Supabase CLI config"),
  fileCheck(migrationPath, "Feedback migration"),
  envCheck("NEXT_PUBLIC_SUPABASE_URL", mergedEnv),
  envEitherCheck(
    ["NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY", "NEXT_PUBLIC_SUPABASE_ANON_KEY"],
    mergedEnv,
  ),
  serviceRoleCheck(localEnv),
];

let blocked = false;
for (const check of checks) {
  const marker = check.ok ? "OK" : "BLOCK";
  console.log(`${marker} ${check.label}${check.detail ? ` - ${check.detail}` : ""}`);
  blocked ||= !check.ok;
}

if (blocked) {
  console.error("");
  console.error("Deploy readiness is blocked. Fix the BLOCK rows, then rerun.");
  console.error("Useful commands:");
  console.error("  vercel link --yes --project <project-name> --scope <team>");
  console.error("  npm run supabase:link");
  console.error("  npm run supabase:push");
  process.exit(1);
}

console.log("");
console.log("Deploy readiness is green.");

function parseEnv(text) {
  const out = {};
  for (const rawLine of text.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line || line.startsWith("#")) {
      continue;
    }
    const idx = line.indexOf("=");
    if (idx <= 0) {
      continue;
    }
    const key = line.slice(0, idx).trim();
    const value = stripQuotes(line.slice(idx + 1).trim());
    out[key] = value;
  }
  return out;
}

function stripQuotes(value) {
  if (
    (value.startsWith('"') && value.endsWith('"')) ||
    (value.startsWith("'") && value.endsWith("'"))
  ) {
    return value.slice(1, -1);
  }
  return value;
}

function commandCheck(command, args, label) {
  const result = spawnSync(command, args, {
    cwd: root,
    shell: process.platform === "win32",
    encoding: "utf8",
  });

  if (result.status === 0) {
    const firstLine = `${result.stdout}${result.stderr}`.trim().split(/\r?\n/)[0];
    return { ok: true, label, detail: firstLine };
  }

  return { ok: false, label, detail: "not available" };
}

function fileCheck(path, label) {
  return existsSync(path)
    ? { ok: true, label, detail: "present" }
    : { ok: false, label, detail: "missing" };
}

function envCheck(name, env) {
  return env[name]
    ? { ok: true, label: name, detail: "present" }
    : { ok: false, label: name, detail: "missing" };
}

function envEitherCheck(names, env) {
  const present = names.find((name) => env[name]);
  return present
    ? { ok: true, label: names.join(" or "), detail: `${present} present` }
    : { ok: false, label: names.join(" or "), detail: "missing" };
}

function serviceRoleCheck(env) {
  const forbidden = Object.keys(env).filter((key) =>
    /SERVICE_ROLE|SECRET_KEY|SUPABASE_SERVICE/i.test(key),
  );

  return forbidden.length === 0
    ? { ok: true, label: "No service-role key in .env.local", detail: "clean" }
    : {
        ok: false,
        label: "No service-role key in .env.local",
        detail: `${forbidden.join(", ")} should not be used by this app`,
      };
}
