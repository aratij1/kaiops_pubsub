import { gzipSync } from "node:zlib";
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

const assetsDirectory = new URL("../dist/assets/", import.meta.url);
// The shared stylesheet includes the signed-out login theme as well as the
// authenticated shell. Keep a narrow ceiling above the measured 49.28 KiB
// bundle so future growth still fails the build.
const limits = { maxChunkGzipBytes: 150 * 1024, maxCssGzipBytes: 50 * 1024 };
const assets = readdirSync(assetsDirectory).filter((name) => /\.(js|css)$/.test(name));
const failures = [];
const moduleGraph = new Map();

for (const name of assets) {
  const content = readFileSync(join(assetsDirectory.pathname, name));
  const gzipBytes = gzipSync(content).byteLength;
  const limit = name.endsWith(".css") ? limits.maxCssGzipBytes : limits.maxChunkGzipBytes;
  console.log(`${name}: ${(gzipBytes / 1024).toFixed(2)} KiB gzip`);
  if (gzipBytes > limit) failures.push(`${name} exceeds ${(limit / 1024).toFixed(0)} KiB gzip`);
  if (name.endsWith(".js")) {
    const source = content.toString("utf8");
    const imports = [...source.matchAll(/(?:from\s*|import\s*)["']\.\/(.+?\.js)["']/g)]
      .map((match) => match[1]);
    moduleGraph.set(name, imports.filter((dependency) => assets.includes(dependency)));
  }
}

function findCycle(node, path = [], visiting = new Set()) {
  if (visiting.has(node)) return [...path, node];
  const nextVisiting = new Set(visiting).add(node);
  for (const dependency of moduleGraph.get(node) || []) {
    const cycle = findCycle(dependency, [...path, node], nextVisiting);
    if (cycle) return cycle;
  }
  return null;
}

for (const name of moduleGraph.keys()) {
  const cycle = findCycle(name);
  if (cycle) {
    failures.push(`circular production chunks: ${cycle.join(" -> ")}`);
    break;
  }
}

if (failures.length) {
  failures.forEach((failure) => console.error(`ERROR: ${failure}`));
  process.exit(1);
}
