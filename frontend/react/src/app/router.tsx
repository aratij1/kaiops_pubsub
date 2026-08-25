import { Suspense, type ComponentType } from "react";
import { createBrowserRouter, Navigate } from "react-router-dom";

import { LegacyApplicationShell } from "./LegacyApplicationShell";
import { LEGACY_REDIRECTS, NAVIGATION_ITEMS, type NavigationId } from "./navigation";
import { resilientLazy } from "./resilientLazy";

const DashboardRoute = resilientLazy(() => import("../routes/dashboard/DashboardRoute"));
const AlertsRoute = resilientLazy(() => import("../routes/alerts/AlertsRoute"));
const IncidentsRoute = resilientLazy(() => import("../routes/incidents/IncidentsRoute"));
const IncidentCommandRoute = resilientLazy(() => import("../features/incidents/IncidentCommand"));
const ApprovalsRoute = resilientLazy(() => import("../routes/approvals/ApprovalsRoute"));
const CopilotRoute = resilientLazy(() => import("../routes/copilot/CopilotRoute"));
const AgentFlowRoute = resilientLazy(() => import("../routes/agent-flow/AgentFlowRoute"));
const KnowledgeRoute = resilientLazy(() => import("../routes/knowledge/KnowledgeRoute"));
const GatewaySafetyRoute = resilientLazy(() => import("../routes/gateway-safety/GatewaySafetyRoute"));
const ClosedIncidentsRoute = resilientLazy(() => import("../routes/closed-incidents/ClosedIncidentsRoute"));
const ExecutiveRoute = resilientLazy(() => import("../routes/executive/ExecutiveRoute"));
const AdminRoute = resilientLazy(() => import("../routes/admin/AdminRoute"));
const AuditRoute = resilientLazy(() => import("../routes/audit/AuditRoute"));
const ApplicationsRoute = resilientLazy(() => import("../routes/applications/ApplicationsRoute"));
const IntegrationsRoute = resilientLazy(() => import("../routes/integrations/IntegrationsRoute"));
const PlatformSettingsRoute = resilientLazy(() => import("../features/administration/PlatformSettings"));

function routeElement(RouteComponent: ComponentType) {
  return (
    <Suspense fallback={<section className="app-route-pending" aria-busy="true" aria-label="Loading workspace"><div className="app-route-pending-mark">K</div><div><strong>Preparing workspace</strong><span>Loading the requested KaiMS module…</span></div></section>}>
      <RouteComponent />
    </Suspense>
  );
}

const ROUTE_COMPONENTS: Readonly<Record<NavigationId, ComponentType>> = {
  dashboard: DashboardRoute,
  alerts: AlertsRoute,
  incidents: IncidentsRoute,
  approvals: ApprovalsRoute,
  copilot: CopilotRoute,
  agentFlow: AgentFlowRoute,
  knowledge: KnowledgeRoute,
  safety: GatewaySafetyRoute,
  audit: AuditRoute,
  closed: ClosedIncidentsRoute,
  applications: ApplicationsRoute,
  integrations: IntegrationsRoute,
  admin: AdminRoute,
  settings: PlatformSettingsRoute,
  executive: ExecutiveRoute,
};

export const router = createBrowserRouter([
  {
    element: <LegacyApplicationShell />,
    children: [
      { path: "/incidents/:incidentId", element: routeElement(IncidentCommandRoute) },
      { path: "/applications/:applicationId", element: routeElement(ApplicationsRoute) },
      ...NAVIGATION_ITEMS.map((item) => ({ path: item.path, element: routeElement(ROUTE_COMPONENTS[item.id]) })),
      ...LEGACY_REDIRECTS.map((redirect) => ({ path: redirect.from, element: <Navigate to={redirect.to} replace /> })),
      { path: "*", element: <Navigate to="/" replace /> },
    ],
  },
]);
