import { Suspense, useCallback, useEffect, useLayoutEffect, useRef, type ComponentType, type ReactNode } from "react";
import { Outlet, useLocation, useNavigate } from "react-router-dom";

import { LEGACY_REDIRECTS, navigationItemForPath, PATH_BY_TAB, tabForPath, type LegacyTabId } from "./navigation";
import { resilientLazy } from "./resilientLazy";

type LegacyApplicationProps = {
  initialTab?: string;
  currentPath?: string;
  currentSearch?: string;
  onActiveTabChange?: (tabId: string) => void;
  onNavigatePath?: (path: string) => void;
  routeOutlet?: ReactNode;
};

const LegacyApplication = resilientLazy(() => import("../App.jsx")) as ComponentType<LegacyApplicationProps>;

export function LegacyApplicationShell() {
  const location = useLocation();
  const navigate = useNavigate();
  const selectedTab = tabForPath(location.pathname);
  const navigationItem = navigationItemForPath(location.pathname);
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
    document.title = `${navigationItem.pageTitle} | KaiMS`;
  }, [navigationItem.pageTitle]);

  useEffect(() => {
    const oldPath = previousPath.current;
    if (oldPath !== location.pathname) {
      previousPath.current = location.pathname;
      const target = scrollPositions.current.get(location.pathname) ?? 0;
      const restore = () => window.scrollTo({ top: target });
      const firstFrame = target > 0 ? window.requestAnimationFrame(() => {
        window.requestAnimationFrame(restore);
      }) : 0;
      return () => {
        window.cancelAnimationFrame(firstFrame);
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
      <Suspense fallback={<main className="app-route-loading" aria-busy="true">Loading KaiMS…</main>}>
        <LegacyApplication
          initialTab={selectedTab}
          currentPath={location.pathname}
          currentSearch={location.search}
          onActiveTabChange={handleTabChange}
          onNavigatePath={handleNavigatePath}
          routeOutlet={<Outlet />}
        />
      </Suspense>
    </>
  );
}
