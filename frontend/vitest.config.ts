import { defineConfig } from 'vitest/config';

// Headless, Node-based unit tests for framework-agnostic logic (services,
// pure functions). Runs without a browser — unlike `ng test` (Karma), which
// needs ChromeHeadless. Legacy decorators (@Injectable) are enabled via the
// repo's tsconfig.json (experimentalDecorators: true), which the transformer reads.
export default defineConfig({
  test: {
    environment: 'jsdom',
    include: ['src/**/*.spec.ts'],
  },
});
