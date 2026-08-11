import { JSDOM } from "jsdom";
import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const src = resolve(__dirname, "../src");
const logPath = resolve(__dirname, "../../../.cursor/debug-fe716a.log");

const css = [
  "styles/tokens.css",
  "datamatics-base.css",
  "datamatics-light.css",
  "datamatics-dark.css",
  "styles.css",
  "routes/incidents/IncidentsRoute.css",
]
  .map((rel) => readFileSync(resolve(src, rel), "utf8"))
  .join("\n");

const html = `<!doctype html><html><head><style>${css.replace(/<\//g, "<\\/")}</style></head>
<body>
<section class="grid single-col operations-center">
  <article class="panel incident-list-panel">
    <div class="contained-table"><table><tbody>
      <tr>
        <td><code>abc-123</code></td>
        <td><strong>kaiops-platform</strong></td>
        <td>high</td>
        <td>human-approval</td>
        <td><span class="pill status-awaiting_approval">awaiting_approval</span></td>
      </tr>
    </tbody></table></div>
  </article>
</section>
</body></html>`;

function apply(document, theme) {
  const root = document.documentElement;
  root.classList.remove("dm-theme-light", "dm-theme-dark");
  const resolved = theme === "auto" ? "dark" : theme;
  if (resolved === "light") root.classList.add("dm-theme-light");
  if (resolved === "dark") root.classList.add("dm-theme-dark");
  root.setAttribute("data-ui-theme", theme);
}

function luminance(rgb) {
  const m = String(rgb).match(/rgba?\((\d+),\s*(\d+),\s*(\d+)/i);
  if (!m) return null;
  const [r, g, b] = [m[1], m[2], m[3]].map((v) => {
    const c = Number(v) / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function contrast(fg, bg) {
  const L1 = luminance(fg);
  const L2 = luminance(bg);
  if (L1 == null || L2 == null) return null;
  const [a, b] = L1 > L2 ? [L1, L2] : [L2, L1];
  return Number(((a + 0.05) / (b + 0.05)).toFixed(2));
}

const lines = [];
for (const theme of ["light", "dark", "auto"]) {
  const dom = new JSDOM(html, { pretendToBeVisual: true });
  apply(dom.window.document, theme);
  const { document } = dom.window;
  const td = document.querySelector("td:nth-child(3)");
  const strong = document.querySelector("strong");
  const code = document.querySelector("code");
  const pill = document.querySelector(".pill");
  const table = document.querySelector(".contained-table");
  const panel = document.querySelector(".incident-list-panel");
  const pick = (el) => {
    const cs = dom.window.getComputedStyle(el);
    return { color: cs.color, background: cs.backgroundColor };
  };
  // jsdom often won't resolve stylesheet colors; also extract matched rules
  const incidentTd = /\.operations-center \.contained-table td \{[\s\S]*?color:\s*([^;]+);/.exec(css);
  const darkIncidentTable = /:root\.dm-theme-dark \.operations-center \.contained-table,[\s\S]*?background:\s*([^;]+);/.exec(css);
  const darkIncidentTd = /:root\.dm-theme-dark \.operations-center \.contained-table td,[\s\S]*?color:\s*([^;]+);/.exec(css);
  const lightPill = /\.operations-center \.contained-table \.pill\.status-awaiting_approval,[\s\S]*?color:\s*([^;]+);/.exec(css);
  const data = {
    theme,
    hasDark: document.documentElement.classList.contains("dm-theme-dark"),
    incidentTdColor: incidentTd?.[1]?.trim() || null,
    darkIncidentTableBg: darkIncidentTable?.[1]?.trim() || null,
    darkIncidentTdColor: darkIncidentTd?.[1]?.trim() || null,
    awaitingPillColor: lightPill?.[1]?.trim() || null,
    readableOnLightSurface: incidentTd?.[1]?.trim() === "#243b53",
    darkSurfacesAligned:
      darkIncidentTable?.[1]?.trim() === "#101317" &&
      darkIncidentTd?.[1]?.trim() === "#e9edf1",
    pillReadableOnLight: lightPill?.[1]?.trim() === "#3346a8",
    jsdom: {
      td: pick(td),
      strong: pick(strong),
      code: pick(code),
      pill: pick(pill),
      table: pick(table),
      panel: pick(panel),
    },
  };
  lines.push(
    JSON.stringify({
      sessionId: "fe716a",
      runId: "contrast-post",
      hypothesisId: "A",
      location: "scripts/debug-incidents-contrast.mjs",
      message: `Incidents contrast cascade for ${theme}`,
      data,
      timestamp: Date.now(),
    }),
  );
}

mkdirSync(dirname(logPath), { recursive: true });
writeFileSync(logPath, `${lines.join("\n")}\n`);
console.log(lines.map((l) => JSON.parse(l).data).map((d) => ({
  theme: d.theme,
  readableOnLightSurface: d.readableOnLightSurface,
  darkSurfacesAligned: d.darkSurfacesAligned,
  pillReadableOnLight: d.pillReadableOnLight,
  incidentTdColor: d.incidentTdColor,
  darkIncidentTableBg: d.darkIncidentTableBg,
})));
