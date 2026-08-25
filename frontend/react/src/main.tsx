import React from "react";
import ReactDOM from "react-dom/client";

import { App } from "./app/App";
import "./styles/tokens.css";
import "./datamatics-base.css";
import "./datamatics-light.css";
import "./datamatics-dark.css";
// KaiMS product styles load last so legacy compatibility themes cannot
// unpredictably override the branded component system.
import "./styles.css";

const root = document.getElementById("root");

if (!root) {
  throw new Error("KaiMS root element was not found");
}

ReactDOM.createRoot(root).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
