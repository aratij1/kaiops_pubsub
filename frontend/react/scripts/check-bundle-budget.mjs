import { gzipSync } from "node:zlib";
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

const assetsDirectory = new URL("../dist/assets/", import.meta.url);
const limits = { maxChunkGzipBytes: 150 * 1024, maxCssGzipBytes: 32 * 1024 };
const assets = readdirSync(assetsDirectory).filter((name) => /\.(js|css)$/.test(name));
const failures = [];

for (const name of assets) {
  const gzipBytes = gzipSync(readFileSync(join(assetsDirectory.pathname, name))).byteLength;
  const limit = name.endsWith(".css") ? limits.maxCssGzipBytes : limits.maxChunkGzipBytes;
  console.log(`${name}: ${(gzipBytes / 1024).toFixed(2)} KiB gzip`);
  if (gzipBytes > limit) failures.push(`${name} exceeds ${(limit / 1024).toFixed(0)} KiB gzip`);
}

if (failures.length) {
  failures.forEach((failure) => console.error(`ERROR: ${failure}`));
  process.exit(1);
}
