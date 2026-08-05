import React from "react";
import ReactDOM from "react-dom/client";

import { App } from "./app/App";
import "./styles/tokens.css";
import "./styles.css";
import "./datamatics-base.css";
import "./datamatics-light.css";
import "./datamatics-dark.css";

const root = document.getElementById("root");

if (!root) {
  throw new Error("KaiOps root element was not found");
}

ReactDOM.createRoot(root).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
