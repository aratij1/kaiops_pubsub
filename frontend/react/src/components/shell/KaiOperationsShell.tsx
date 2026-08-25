import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import {
  Activity,
  Bell,
  BookOpen,
  Bot,
  Boxes,
  CheckCircle2,
  ChevronDown,
  CircleAlert,
  CircleUserRound,
  Command,
  FileCheck2,
  Gauge,
  LayoutDashboard,
  Menu,
  PlugZap,
  Search,
  Settings,
  ShieldCheck,
  Siren,
  SlidersHorizontal,
  Users,
  X,
  Zap,
} from "lucide-react";

import { searchNavigation, type NavigationIcon, type NavigationItem } from "../../app/navigation";
import "./KaiOperationsShell.css";

type NavigationGroupView = { id: string; label: string; items: readonly NavigationItem[] };
type OperationalItem = { kind?: string; label?: string | number; meta?: string; row?: unknown };
type KaiStateItem = { label: string; value: number; tone?: "attention" | "active" | "calm" };

const ICONS: Record<NavigationIcon, typeof Activity> = {
  dashboard: LayoutDashboard,
  alerts: Activity,
  incidents: Siren,
  approvals: FileCheck2,
  copilot: Bot,
  agentFlow: Zap,
  knowledge: BookOpen,
  safety: ShieldCheck,
  audit: Gauge,
  closed: CheckCircle2,
  applications: Boxes,
  integrations: PlugZap,
  admin: Users,
  settings: Settings,
  executive: Gauge,
};

export interface KaiOperationsShellProps {
  children: ReactNode;
  navigationGroups: readonly NavigationGroupView[];
  currentItem: NavigationItem;
  currentPath: string;
  role: string;
  onNavigate: (item: NavigationItem) => void;
  projects: readonly string[];
  project: string;
  onProjectChange: (project: string) => void;
  environment: string;
  health: { ok?: boolean; loading?: boolean; message?: string };
  aiCapability?: { degraded?: boolean; loading?: boolean; message?: string };
  autonomyMode?: string;
  approvalCount: number;
  notificationCount: number;
  operationalQuery: string;
  onOperationalQueryChange: (query: string) => void;
  operationalResults: readonly OperationalItem[];
  notifications: readonly OperationalItem[];
  onOpenOperationalItem: (item: OperationalItem) => void;
  onOpenNotifications: () => void;
  onAskKai: () => void;
  user?: { username?: string; role_name?: string } | null;
  density: string;
  theme: string;
  onDensityChange: (density: string) => void;
  onThemeChange: (theme: string) => void;
  onLogout: () => void;
  kaiStates?: readonly KaiStateItem[];
  restrictedDestination?: string;
}

function humanize(value: string | undefined, fallback: string) {
  const text = String(value || "").trim();
  return text && text !== "-" ? text.replaceAll("_", " ").replaceAll("-", " ") : fallback;
}

export function KaiOperationsShell({
  children,
  navigationGroups,
  currentItem,
  currentPath,
  role,
  onNavigate,
  projects,
  project,
  onProjectChange,
  environment,
  health,
  aiCapability,
  autonomyMode,
  approvalCount,
  notificationCount,
  operationalQuery,
  onOperationalQueryChange,
  operationalResults,
  notifications,
  onOpenOperationalItem,
  onOpenNotifications,
  onAskKai,
  user,
  density,
  theme,
  onDensityChange,
  onThemeChange,
  onLogout,
  kaiStates = [],
  restrictedDestination,
}: KaiOperationsShellProps) {
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [paletteView, setPaletteView] = useState<"search" | "notifications">("search");
  const [mobileNavigationOpen, setMobileNavigationOpen] = useState(false);
  const searchRef = useRef<HTMLInputElement>(null);
  const navigationMatches = useMemo(() => searchNavigation(operationalQuery, role).slice(0, 6), [operationalQuery, role]);
  const hasQuery = Boolean(operationalQuery.trim());

  useEffect(() => {
    const handleShortcut = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setPaletteView("search");
        setPaletteOpen((open) => !open);
      }
      if (event.key === "Escape") setPaletteOpen(false);
    };
    window.addEventListener("keydown", handleShortcut);
    return () => window.removeEventListener("keydown", handleShortcut);
  }, []);

  useEffect(() => {
    if (!paletteOpen) return;
    const frame = window.requestAnimationFrame(() => searchRef.current?.focus());
    return () => window.cancelAnimationFrame(frame);
  }, [paletteOpen]);

  const selectNavigation = (item: NavigationItem) => {
    onNavigate(item);
    setPaletteOpen(false);
    setMobileNavigationOpen(false);
    onOperationalQueryChange("");
  };

  return (
    <div className="kai-shell">
      <aside className={`kai-navigation ${mobileNavigationOpen ? "is-open" : ""}`} aria-label="Primary navigation">
        <div className="kai-brand-lockup">
          <button type="button" onClick={() => selectNavigation(navigationGroups[0]?.items[0] ?? currentItem)} aria-label="KaiMS operations overview">
            <span className="kai-brand-mark" aria-hidden="true">K</span>
            <span><strong>KaiMS</strong><small>AI Operations Command Center</small></span>
          </button>
          <button className="kai-mobile-close" type="button" aria-label="Close navigation" onClick={() => setMobileNavigationOpen(false)}><X /></button>
        </div>

        <nav className="kai-navigation-groups" aria-label="Primary navigation">
          {navigationGroups.map((group) => (
            <section key={group.id} aria-labelledby={`kai-nav-${group.id}`}>
              <h2 id={`kai-nav-${group.id}`}>{group.label}</h2>
              {group.items.map((item) => {
                const Icon = ICONS[item.icon];
                const active = item.path === "/" ? currentPath === "/" : currentPath === item.path || currentPath.startsWith(`${item.path}/`);
                return (
                  <button key={item.id} type="button" className={active ? "is-active" : ""} aria-current={active ? "page" : undefined} onClick={() => selectNavigation(item)}>
                    <Icon aria-hidden="true" /><span>{item.label}</span>
                    {item.id === "approvals" && approvalCount > 0 ? <em>{approvalCount}</em> : null}
                  </button>
                );
              })}
            </section>
          ))}
        </nav>

        <section className="kai-brain-status" aria-label="Kai operations brain">
          <header><span><Bot aria-hidden="true" />Kai Operations Brain</span><i>Live</i></header>
          <div>
            {kaiStates.length ? kaiStates.map((state) => (
              <span key={state.label} className={state.tone ? `is-${state.tone}` : ""}><small>{state.label}</small><strong>{state.value}</strong></span>
            )) : <p>Kai activity will appear as operational records arrive.</p>}
          </div>
          <button type="button" onClick={onAskKai}><Bot aria-hidden="true" /> Ask Kai</button>
        </section>
      </aside>

      <div className="kai-workspace-frame">
        <header className="kai-operations-bar">
          <button className="kai-mobile-menu" type="button" aria-label="Open navigation" onClick={() => setMobileNavigationOpen(true)}><Menu /></button>
          <div className="kai-context-selectors">
            <label><span>Project</span><select value={project} onChange={(event) => onProjectChange(event.target.value)}>{projects.map((name) => <option value={name} key={name}>{name}</option>)}</select><ChevronDown aria-hidden="true" /></label>
            <span className={`kai-environment ${["prod", "production"].includes(environment.toLowerCase()) ? "is-production" : ""}`}><small>Environment</small><strong>{humanize(environment, "Unknown")}</strong></span>
          </div>

          <button className="kai-search-trigger" type="button" onClick={() => { setPaletteView("search"); setPaletteOpen(true); }}>
            <Search aria-hidden="true" /><span>{operationalQuery || "Search or ask Kai..."}</span><kbd><Command aria-hidden="true" /> K</kbd>
          </button>

          <div className="kai-global-actions">
            <span className={`kai-health ${health.ok ? "is-healthy" : "is-degraded"}`} title={health.message || "Platform health unavailable"}><i aria-hidden="true" /><span>Platform</span><strong>{health.loading ? "Checking" : health.ok ? "Healthy" : "Attention"}</strong></span>
            <span className="kai-autonomy"><ShieldCheck aria-hidden="true" /><span>Autonomy</span><strong>{humanize(autonomyMode, "Policy managed")}</strong></span>
            <button type="button" className="kai-count-action" onClick={() => {
              const item = navigationGroups.flatMap((group) => group.items).find((candidate) => candidate.id === "approvals");
              if (item) selectNavigation(item);
            }}><FileCheck2 aria-hidden="true" /><span>Approvals</span>{approvalCount > 0 ? <em>{approvalCount}</em> : null}</button>
            <button type="button" className="kai-icon-action" aria-label={`${notificationCount} operational notifications`} onClick={() => { onOpenNotifications(); setPaletteView("notifications"); setPaletteOpen(true); }}><Bell aria-hidden="true" />{notificationCount > 0 ? <em>{notificationCount}</em> : null}</button>
            <details className="kai-user-menu">
              <summary aria-label="User and display preferences"><CircleUserRound aria-hidden="true" /><span>{user?.username || "User"}</span><ChevronDown aria-hidden="true" /></summary>
              <div>
                <header><strong>{user?.username || "Signed-in user"}</strong><span>{humanize(user?.role_name, "Role unavailable")}</span></header>
                <fieldset><legend>Density</legend>{["comfortable", "compact"].map((value) => <button key={value} type="button" className={density === value ? "is-active" : ""} onClick={() => onDensityChange(value)}>{humanize(value, value)}</button>)}</fieldset>
                <fieldset><legend>Theme</legend>{["auto", "light", "dark"].map((value) => <button key={value} type="button" className={theme === value ? "is-active" : ""} onClick={() => onThemeChange(value)}>{humanize(value, value)}</button>)}</fieldset>
                <button className="kai-logout" type="button" onClick={onLogout}>Sign out</button>
              </div>
            </details>
          </div>
        </header>

        <main className="kai-route-content" id="workspace-content" tabIndex={-1}>
          {aiCapability?.degraded ? <div className="kai-ai-degraded" role="status"><Bot aria-hidden="true" /><span><strong>AI capability degraded.</strong> {aiCapability.message || "AI investigation may be delayed; deterministic monitoring remains active and execution stays governed by backend policy."}</span></div> : null}
          <header className="kai-route-context">
            <div><span>{navigationGroups.find((group) => group.items.some((item) => item.id === currentItem.id))?.label || "KaiMS"}</span><h1>{currentItem.pageTitle}</h1></div>
            <p>{currentItem.keywords.slice(0, 4).join(" · ")}</p>
          </header>
          {restrictedDestination ? <div className="kai-permission-notice" role="status"><CircleAlert aria-hidden="true" /><span><strong>Access is restricted.</strong> {restrictedDestination} is not available to your role.</span></div> : null}
          {children}
        </main>
      </div>

      {paletteOpen ? (
        <div className="kai-command-overlay" role="presentation" onMouseDown={(event) => { if (event.currentTarget === event.target) setPaletteOpen(false); }}>
          <section className="kai-command-palette" role="dialog" aria-modal="true" aria-label="Search, navigate, or ask Kai">
            <label>{paletteView === "notifications" ? <Bell aria-hidden="true" /> : <Search aria-hidden="true" />}<input ref={searchRef} value={operationalQuery} onChange={(event) => { setPaletteView("search"); onOperationalQueryChange(event.target.value); }} placeholder={paletteView === "notifications" ? "Filter notifications or start a new search..." : "Search incidents, services, commands, or ask Kai..."} /><kbd>ESC</kbd></label>
            <div className="kai-command-results">
              {paletteView === "notifications" ? <section><h2><Bell aria-hidden="true" /> Meaningful operational changes</h2>{notifications.length ? notifications.map((item, index) => <button type="button" key={`${item.kind}-${item.label}-${index}`} onClick={() => { onOpenOperationalItem(item); setPaletteOpen(false); }}><CircleAlert aria-hidden="true" /><span><strong>{item.kind}: {item.label}</strong><small>{item.meta || "Operational state changed"}</small></span><kbd>Open</kbd></button>) : <p>No approval, critical-alert, recovery, or reopening notifications are present.</p>}</section> : <><section><h2><SlidersHorizontal aria-hidden="true" /> Destinations</h2>{navigationMatches.length ? navigationMatches.map((item) => {
                const Icon = ICONS[item.icon];
                return <button type="button" key={item.id} onClick={() => selectNavigation(item)}><Icon aria-hidden="true" /><span><strong>{item.label}</strong><small>{item.pageTitle}</small></span><kbd>Open</kbd></button>;
              }) : <p>No permitted destination matches.</p>}</section>
              {hasQuery ? <section><h2><Activity aria-hidden="true" /> Operational records</h2>{operationalResults.length ? operationalResults.map((item, index) => <button type="button" key={`${item.kind}-${item.label}-${index}`} onClick={() => { onOpenOperationalItem(item); setPaletteOpen(false); }}><Siren aria-hidden="true" /><span><strong>{item.kind}: {item.label}</strong><small>{item.meta || "Loaded operational record"}</small></span><kbd>Open</kbd></button>) : <p>No matching loaded, role-authorized records.</p>}</section> : null}
              </>}
            </div>
            <footer><span><kbd>↑</kbd><kbd>↓</kbd> browse</span><span><kbd>Enter</kbd> open</span><button type="button" onClick={() => { setPaletteOpen(false); onAskKai(); }}><Bot aria-hidden="true" /> Ask Kai with context</button></footer>
          </section>
        </div>
      ) : null}
      {mobileNavigationOpen ? <button type="button" className="kai-mobile-scrim" aria-label="Close navigation" onClick={() => setMobileNavigationOpen(false)} /> : null}
    </div>
  );
}
