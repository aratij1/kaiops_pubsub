import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";

const repositoryRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const budgets = [
  ["frontend/react/src/App.jsx", 12521],
  ["frontend/react/src/appHelpers.jsx", 7063],
  ["backend/src/monitoring-adapter/app.py", 6434],
  ["backend/src/api-gateway/app.py", 2833],
];

let failed = false;
for (const [relativePath, maximumLines] of budgets) {
  const contents = await readFile(path.join(repositoryRoot, relativePath), "utf8");
  const actualLines = contents.split(/\r?\n/).length - (contents.endsWith("\n") ? 1 : 0);
  const status = actualLines <= maximumLines ? "PASS" : "FAIL";
  console.log(`${status} ${relativePath}: ${actualLines}/${maximumLines} lines`);
  failed ||= actualLines > maximumLines;
}

if (failed) {
  console.error("Architecture budget exceeded. Extract code into a focused module instead of growing a legacy hotspot.");
  process.exit(1);
}
