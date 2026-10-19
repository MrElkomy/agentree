import nextCoreWebVitals from "eslint-config-next/core-web-vitals";
import nextTypescript from "eslint-config-next/typescript";

const config = [
  ...nextCoreWebVitals,
  ...nextTypescript,
  {
    ignores: [
      "node_modules/**",
      ".next/**",
      "out/**",
      "next-env.d.ts",
      "playwright-report/**",
      "test-results/**",
      "src/lib/api-types.ts",
    ],
  },
  {
    rules: {
      // API data is untrusted: never render raw HTML.
      "react/no-danger": "error",
    },
  },
];

export default config;
