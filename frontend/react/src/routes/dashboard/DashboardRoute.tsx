import { Navigate, useLocation } from "react-router-dom";

export default function DashboardRoute() {
  const location = useLocation();
  return location.search.includes("workspace=alert") ? null : <Navigate to="/incidents" replace />;
}
