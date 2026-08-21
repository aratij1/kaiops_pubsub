import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";

const repositoryRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
// Legacy hotspots are on a strict no-growth ratchet while behavior is moved
// behind route, domain, service, and adapter modules.  A stale threshold that
// is already below the checked-in application makes every unrelated change
// fail without preventing further growth. These ceilings are the reviewed
// migration baseline; they may only move downward.
const budgets = [
  { path: "frontend/react/src/App.jsx", maximumLines: 13373, targetLines: 400 },
  { path: "frontend/react/src/appHelpers.jsx", maximumLines: 7059, targetLines: 500 },
  { path: "backend/src/monitoring-adapter/app.py", maximumLines: 6640, targetLines: 300 },
  { path: "backend/src/api-gateway/app.py", maximumLines: 2771, targetLines: 250 },
];

let failed = false;
for (const { path: relativePath, maximumLines, targetLines } of budgets) {
  const contents = await readFile(path.join(repositoryRoot, relativePath), "utf8");
  const actualLines = contents.split(/\r?\n/).length - (contents.endsWith("\n") ? 1 : 0);
  const status = actualLines <= maximumLines ? "PASS" : "FAIL";
  console.log(`${status} ${relativePath}: ${actualLines}/${maximumLines} ceiling; target ${targetLines}`);
  failed ||= actualLines > maximumLines;
}

if (failed) {
  console.error("Architecture budget exceeded. Extract code into a focused module instead of growing a legacy hotspot.");
  process.exit(1);
}
