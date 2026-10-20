import { defineWorkersConfig } from "@cloudflare/vitest-pool-workers/config";

export default defineWorkersConfig({
  test: {
    setupFiles: ["./test/setup.ts"],
    poolOptions: {
      workers: {
        main: "./src/index.ts",
        singleWorker: true,
        miniflare: {
          compatibilityDate: "2025-10-11",
          d1Databases: { DB: "allo-test" },
          bindings: { TOOLS_SECRET: "test-secret" },
        },
      },
    },
  },
});
