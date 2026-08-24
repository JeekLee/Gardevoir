import fsd from "@feature-sliced/steiger-plugin";
import { defineConfig } from "steiger";

export default defineConfig([
  ...fsd.configs.recommended,
  {
    rules: {
      "fsd/insignificant-slice": "off",
    },
  },
  {
    files: ["./src/_app/**"],
    rules: {
      "fsd/no-segmentless-slices": "off",
      "fsd/no-segments-on-sliced-layers": "off",
      "fsd/no-ui-in-app": "off",
      "fsd/typo-in-layer-name": "off",
    },
  },
  {
    files: ["./src/_pages/**"],
    rules: {
      "fsd/typo-in-layer-name": "off",
    },
  },
]);
