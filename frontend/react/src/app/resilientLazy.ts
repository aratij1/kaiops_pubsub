import { lazy, type ComponentType, type LazyExoticComponent } from "react";

function isChunkLoadFailure(error: unknown): boolean {
  const message = error instanceof Error ? error.message : String(error || "");
  return /dynamically imported module|failed to fetch|loading chunk|importing a module script/i.test(message);
}

export function resilientLazy<T extends ComponentType<any>>(
  importer: () => Promise<{ default: T }>,
): LazyExoticComponent<T> {
  return lazy(async () => {
    const reloadGuardKey = "kaims:chunk-reload-at";
    try {
      const loaded = await importer();
      window.sessionStorage.removeItem(reloadGuardKey);
      return loaded;
    } catch (error) {
      if (isChunkLoadFailure(error)) {
        // Retry once for a transient network failure. If the same hashed chunk
        // is still missing, a deployment replaced it while this page was open;
        // reload once so index.html can reference the current asset manifest.
        await new Promise((resolve) => window.setTimeout(resolve, 250));
        try {
          const loaded = await importer();
          window.sessionStorage.removeItem(reloadGuardKey);
          return loaded;
        } catch (retryError) {
          if (!isChunkLoadFailure(retryError)) throw retryError;
          const lastReloadAt = Number(window.sessionStorage.getItem(reloadGuardKey) || 0);
          if (!lastReloadAt || Date.now() - lastReloadAt > 60_000) {
            window.sessionStorage.setItem(reloadGuardKey, String(Date.now()));
            window.location.reload();
            return await new Promise<{ default: T }>(() => undefined);
          }
          throw retryError;
        }
      }
      throw error;
    }
  });
}
