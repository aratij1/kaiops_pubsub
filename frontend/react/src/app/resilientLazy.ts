import { lazy, type ComponentType, type LazyExoticComponent } from "react";

const RECOVERY_KEY = "kaiops:chunk-recovery";

function isChunkLoadFailure(error: unknown): boolean {
  const message = error instanceof Error ? error.message : String(error || "");
  return /dynamically imported module|failed to fetch|loading chunk|importing a module script/i.test(message);
}

export function resilientLazy<T extends ComponentType<any>>(
  importer: () => Promise<{ default: T }>,
): LazyExoticComponent<T> {
  return lazy(async () => {
    try {
      const module = await importer();
      window.sessionStorage.removeItem(RECOVERY_KEY);
      return module;
    } catch (error) {
      if (isChunkLoadFailure(error) && !window.sessionStorage.getItem(RECOVERY_KEY)) {
        window.sessionStorage.setItem(RECOVERY_KEY, window.location.href);
        window.location.reload();
        return await new Promise<never>(() => undefined);
      }
      throw error;
    }
  });
}
