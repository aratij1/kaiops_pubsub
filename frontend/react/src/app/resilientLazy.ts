import { lazy, type ComponentType, type LazyExoticComponent } from "react";

function isChunkLoadFailure(error: unknown): boolean {
  const message = error instanceof Error ? error.message : String(error || "");
  return /dynamically imported module|failed to fetch|loading chunk|importing a module script/i.test(message);
}

export function resilientLazy<T extends ComponentType<any>>(
  importer: () => Promise<{ default: T }>,
): LazyExoticComponent<T> {
  return lazy(async () => {
    try {
      return await importer();
    } catch (error) {
      // A full-page reload here used to tear down the authenticated shell and
      // appeared as a flash (or a return to sign-in) whenever a route chunk was
      // briefly unavailable. Keep the mounted workspace intact and retry once.
      if (isChunkLoadFailure(error)) {
        await new Promise((resolve) => window.setTimeout(resolve, 250));
        return await importer();
      }
      throw error;
    }
  });
}
