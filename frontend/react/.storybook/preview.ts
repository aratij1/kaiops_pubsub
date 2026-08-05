import type { Preview } from "@storybook/react-vite";

import "../src/styles/tokens.css";
import "../src/components/design-system/design-system.css";

const preview: Preview = {
  parameters: {
    a11y: { test: "error" },
    controls: {
      matchers: {
        color: /(background|color)$/i,
        date: /Date$/i,
      },
    },
    layout: "padded",
  },
};

export default preview;
