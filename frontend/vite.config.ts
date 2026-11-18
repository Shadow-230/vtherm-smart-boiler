// The Boiler page's build (docs/en/development/plans/plan-0.2-i10.md): one ES module the plugin
// serves, written beside the plugin's code with the licenses of the packages bundled into it.
import { existsSync, readFileSync } from "node:fs";
import { dirname, join, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import type { Plugin } from "vite";
import { defineConfig } from "vitest/config";

const here = dirname(fileURLToPath(import.meta.url));
const outDir = resolve(here, "../custom_components/vtherm_smart_boiler/frontend");
const LICENSE_FILES = ["LICENSE", "LICENSE.md", "LICENSE.txt", "license"];

/** Writes THIRD_PARTY_LICENSES.txt: each npm package bundled into the output, with its license. */
function thirdPartyLicenses(): Plugin {
  return {
    name: "third-party-licenses",
    generateBundle(_options, bundle) {
      const marker = `${sep}node_modules${sep}`;
      const packages = new Map<string, string>();
      for (const output of Object.values(bundle)) {
        if (output.type !== "chunk") continue;
        for (const id of Object.keys(output.modules)) {
          const at = id.lastIndexOf(marker);
          if (at < 0) continue;
          const parts = id.slice(at + marker.length).split(sep);
          const name = parts[0].startsWith("@") ? `${parts[0]}/${parts[1]}` : parts[0];
          packages.set(name, id.slice(0, at + marker.length) + name.split("/").join(sep));
        }
      }
      const sections = [...packages.keys()].sort().map((name) => {
        const dir = packages.get(name) as string;
        const meta = JSON.parse(readFileSync(join(dir, "package.json"), "utf8"));
        const file = LICENSE_FILES.map((f) => join(dir, f)).find((f) => existsSync(f));
        const text = file ? readFileSync(file, "utf8").trim() : `License: ${meta.license}`;
        return `${name} ${meta.version} (${meta.license})\n\n${text}\n`;
      });
      this.emitFile({
        type: "asset",
        fileName: "THIRD_PARTY_LICENSES.txt",
        source: `The Boiler page bundles these packages.\n\n${sections.join(`\n${"-".repeat(72)}\n\n`)}`,
      });
    },
  };
}

export default defineConfig({
  plugins: [thirdPartyLicenses()],
  build: {
    outDir,
    emptyOutDir: false, // the translations live there too
    target: "es2022",
    minify: true,
    sourcemap: false,
    lib: {
      entry: resolve(here, "src/panel.ts"),
      formats: ["es"],
      fileName: () => "vtherm-smart-boiler-panel.js",
    },
  },
  test: {
    include: ["src/**/*.test.ts"],
  },
});
