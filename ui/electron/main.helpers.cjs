const fs = require("node:fs");
const path = require("node:path");

function buildRunPipelineArgs(input) {
  return [
    "run",
    "--input",
    input.inputPath,
    "--out",
    input.outDir,
    ...(input.skipReview ? ["--skip-review"] : []),
    ...(input.chunkChars ? ["--chunk-chars", String(input.chunkChars)] : []),
    ...arrayArgs("--kb", input.kbPaths),
    ...(input.domainPackDir ? ["--domain-pack", input.domainPackDir] : []),
  ];
}

function resolvePythonScriptPath(filename, options = {}) {
  const dirname = options.dirname || __dirname;
  const resourcesPath = options.resourcesPath || process.resourcesPath || "";
  const existsSync = options.existsSync || fs.existsSync;
  const candidates = [
    path.resolve(dirname, "../..", filename),
    path.resolve(dirname, "../../..", filename),
    path.resolve(resourcesPath, filename),
    path.resolve(resourcesPath, "app.asar.unpacked", filename),
  ];
  return candidates.find((candidate) => existsSync(candidate)) || candidates[0];
}

function arrayArgs(flag, values) {
  return (values || []).flatMap((value) => [flag, value]);
}

module.exports = {
  buildRunPipelineArgs,
  resolvePythonScriptPath,
};
