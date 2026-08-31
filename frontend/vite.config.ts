/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    // Phase 17A: the responsive contract suite reads index.css with ?raw,
    // which vitest stubs to an empty string while css is false. Processing
    // CSS costs a little setup time and buys a real regression guard on the
    // rules the browser measurements established.
    css: true,
  },
});
