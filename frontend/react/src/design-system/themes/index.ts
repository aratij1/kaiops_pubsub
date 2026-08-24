import { applyKaiTheme, type KaiTheme } from "../../config/brand";

export function setKaiTheme(theme: KaiTheme) {
  applyKaiTheme(theme);
  window.localStorage.setItem("kaims.ui.theme", theme);
}

export function initializeKaiTheme(): KaiTheme {
  const stored = window.localStorage.getItem("kaims.ui.theme");
  const theme: KaiTheme = stored === "light" || stored === "auto" ? stored : "dark";
  applyKaiTheme(theme);
  return theme;
}
