import coreWebVitals from "eslint-config-next/core-web-vitals";
import typescript from "eslint-config-next/typescript";

const eslintConfig = [
  ...coreWebVitals,
  ...typescript,
  {
    rules: {
      // Data-dense research tables benefit from compact JSX.
      "react/no-unescaped-entities": "off",
    },
  },
];

export default eslintConfig;
