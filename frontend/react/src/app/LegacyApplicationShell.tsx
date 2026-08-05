import { Suspense, useCallback, useEffect, useLayoutEffect, useRef } from "react";
import { Outlet, useLocation, useNavigate } from "react-router-dom";

import { LEGACY_REDIRECTS, navigationItemForPath, PATH_BY_TAB, tabForPath, type LegacyTabId } from "./navigation";
import { resilientLazy } from "./resilientLazy";

const LegacyApplication = resilientLazy(() => import("../App.jsx"));

export function LegacyApplicationShell() {
  const location = useLocation();
  const navigate = useNavigate();
  const selectedTab = tabForPath(location.pathname);
  const navigationItem = navigationItemForPath(location.pathname);
  // Dashboard and Admin still contain workflows that have not been fully
  // decomposed (incident cockpit and guided setup). Render those legacy
  // workspaces alone. Every other navigation target has a complete extracted
  // route and must not be rendered alongside the legacy report surface.
  const useLegacyWorkspace = selectedTab === "home" || selectedTab === "admin";
  const scrollPositions = useRef(new Map<string, number>());
  const previousPath = useRef(location.pathname);

  useEffect(() => {
    const previous = window.history.scrollRestoration;
    window.history.scrollRestoration = "manual";
    return () => { window.history.scrollRestoration = previous; };
  }, []);

  useLayoutEffect(() => {
    const redirect = LEGACY_REDIRECTS.find((candidate) => candidate.from === location.pathname);
    if (redirect) navigate(redirect.to, { replace: true });
  }, [location.pathname, navigate]);

  useEffect(() => {
    document.title = `${navigationItem.pageTitle} | KaiOps`;
  }, [navigationItem.pageTitle]);

  useEffect(() => {
    const oldPath = previousPath.current;
    if (oldPath !== location.pathname) {
      previousPath.current = location.pathname;
      const target = scrollPositions.current.get(location.pathname) ?? 0;
      let secondFrame = 0;
      const retries: number[] = [];
      let restoreInterval = 0;
      const restore = () => window.scrollTo({ top: target });
      const firstFrame = target > 0 ? window.requestAnimationFrame(() => {
        secondFrame = window.requestAnimationFrame(restore);
      }) : 0;
      // Lazy route chunks and async panels can increase the document height
      // after the first frames. Retry only a non-zero saved position; forcing
      // zero would override a user's first scroll on a newly opened page.
      if (target > 0) {
        [100, 300, 750, 1500, 3000, 4500].forEach((delay) => retries.push(window.setTimeout(restore, delay)));
        restoreInterval = window.setInterval(restore, 250);
        retries.push(window.setTimeout(() => window.clearInterval(restoreInterval), 5000));
      }
      return () => {
        window.cancelAnimationFrame(firstFrame);
        if (secondFrame) window.cancelAnimationFrame(secondFrame);
        retries.forEach((timer) => window.clearTimeout(timer));
        if (restoreInterval) window.clearInterval(restoreInterval);
      };
    }
    return undefined;
  }, [location.pathname]);

  const handleTabChange = useCallback(
    (tabId: string) => {
      if (tabForPath(location.pathname) === tabId) return;
      const path = PATH_BY_TAB[tabId as LegacyTabId];
      if (path && path !== location.pathname) {
        scrollPositions.current.set(location.pathname, window.scrollY);
        navigate(path);
      }
    },
    [location.pathname, navigate],
  );

  const handleNavigatePath = useCallback((path: string) => {
    if (path !== location.pathname) {
      scrollPositions.current.set(location.pathname, window.scrollY);
      navigate(path);
    }
  }, [location.pathname, navigate]);

  return (
    <>
      <Suspense fallback={<main className="app-route-loading" aria-busy="true">Loading KaiOps…</main>}>
        <LegacyApplication
          initialTab={selectedTab}
          currentPath={location.pathname}
          currentSearch={location.search}
          onActiveTabChange={handleTabChange}
          onNavigatePath={handleNavigatePath}
          routeOutlet={useLegacyWorkspace ? null : <Outlet />}
        />
      </Suspense>
    </>
  );
}
