import path from "node:path";
import { fileURLToPath } from "node:url";

import type { NextConfig } from "next";

const consoleRoot = path.dirname(fileURLToPath(import.meta.url));

const nextConfig: NextConfig = {
  output: "standalone",
  outputFileTracingRoot: path.join(consoleRoot, "../.."),
};

export default nextConfig;
