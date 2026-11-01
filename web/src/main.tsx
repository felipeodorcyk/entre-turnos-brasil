import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import Explorer from "./Explorer";
import "./explorer.css";
import "./styles.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    {new URLSearchParams(window.location.search).get("view") === "legacy" ? <App /> : <Explorer />}
  </StrictMode>,
);

