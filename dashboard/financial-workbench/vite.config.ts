import { defineConfig } from "vite";
import { fileURLToPath } from "node:url";
export default defineConfig({
  root: fileURLToPath(new URL(".", import.meta.url)),
  base: "/financial-workbench/",
  build: {
    outDir: "../../src/octop/dashboard/financial-workbench",
    emptyOutDir: true,
    sourcemap: false,
  },
});
