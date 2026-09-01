import React from "react";
import ReactDOM from "react-dom/client";

import { App } from "./app/App";
import "./design-system";
// The semantic KaiMS system supersedes the removed Datamatics compatibility
// themes; retaining them created three competing token and surface cascades.
import "./styles.css";
import { initializeKaiTheme } from "./design-system/themes";

initializeKaiTheme();

const root = document.getElementById("root");

if (!root) {
  throw new Error("KaiMS root element was not found");
}

ReactDOM.createRoot(root).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
