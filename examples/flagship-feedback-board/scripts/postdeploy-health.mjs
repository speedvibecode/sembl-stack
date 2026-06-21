const args = process.argv.slice(2);
const options = parseArgs(args);
const deploymentUrl = options.url ?? process.env.VERCEL_URL;

if (!deploymentUrl) {
  console.error("Usage: npm run postdeploy -- <deployment-url>");
  process.exit(1);
}

const healthUrl = new URL(options.path, normalizeBaseUrl(deploymentUrl));
const controller = new AbortController();
const timeout = setTimeout(() => controller.abort(), options.timeoutMs);

try {
  const response = await fetch(healthUrl, { signal: controller.signal });
  const bodyText = await response.text();
  let body = null;

  try {
    body = JSON.parse(bodyText);
  } catch {
    body = { raw: bodyText.slice(0, 200) };
  }

  const okStatus = response.status >= 200 && response.status < 400;
  const okPayload = body?.ok === true && body?.app === "flagship-feedback-board";
  const supabaseReady = body?.supabaseConfigured === true;
  const passed =
    okStatus && okPayload && (supabaseReady || options.allowUnconfigured);

  console.log(
    JSON.stringify(
      {
        url: healthUrl.toString(),
        status: response.status,
        okPayload,
        supabaseConfigured: Boolean(body?.supabaseConfigured),
        passed,
      },
      null,
      2,
    ),
  );

  if (!passed) {
    process.exit(1);
  }
} catch (error) {
  console.error(
    JSON.stringify(
      {
        url: healthUrl.toString(),
        passed: false,
        error: error instanceof Error ? error.message : String(error),
      },
      null,
      2,
    ),
  );
  process.exit(1);
} finally {
  clearTimeout(timeout);
}

function parseArgs(values) {
  const out = {
    url: null,
    path: "/api/health",
    timeoutMs: 10_000,
    allowUnconfigured: false,
  };

  for (let i = 0; i < values.length; i += 1) {
    const value = values[i];
    if (value === "--path") {
      out.path = values[++i] ?? out.path;
    } else if (value === "--timeout-ms") {
      out.timeoutMs = Number(values[++i] ?? out.timeoutMs);
    } else if (value === "--allow-unconfigured") {
      out.allowUnconfigured = true;
    } else if (!out.url) {
      out.url = value;
    }
  }

  return out;
}

function normalizeBaseUrl(value) {
  const withProtocol = /^https?:\/\//i.test(value) ? value : `https://${value}`;
  return withProtocol.endsWith("/") ? withProtocol : `${withProtocol}/`;
}
