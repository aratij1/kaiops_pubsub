export const KAI_BRAND = Object.freeze({
  productName: "KaiMS",
  category: "Autonomous Operations Intelligence",
  positioning: "Understand. Decide. Resolve.",
  proposition: "AI-native operations that turn signals into evidence, decisions and safe autonomous action.",
  endorsement: "by Datamatics",
  documentTitle: (page?: string) => page ? `${page} | KaiMS` : "KaiMS | Autonomous Operations Intelligence",
  themeStorageKey: "kaims.ui.theme",
} as const);

export type KaiTheme = "light" | "dark" | "auto";

export function applyKaiTheme(theme: KaiTheme, root: HTMLElement = document.documentElement) {
  root.dataset.uiTheme = theme;
  root.dataset.kaiBrand = "kaims";
}
