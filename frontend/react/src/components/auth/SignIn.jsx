import { useState } from "react";
import { KaiMSBrand } from "../brand/KaiMSBrand";

/**
 * Sign-in gate — split layout: form left, brand story right.
 */
export function SignIn({
  uiDensity = "comfortable",
  applicationToMonitor,
  onApplicationChange,
  monitorApplications = [],
  authConfig,
  adminSession,
  adminAuthForm,
  onAdminAuthFormChange,
  onLocalLogin,
  onOidcLogin,
}) {
  const [showPassword, setShowPassword] = useState(false);
  const [rememberMe, setRememberMe] = useState(true);
  const isOidc = authConfig?.mode === "oidc";

  return (
    <main className={`app-shell auth-shell density-${uiDensity}`}>
      <section className="auth-stage">
        <article className="auth-card">
          <header className="auth-card-top">
            <KaiMSBrand compact />
            <p className="auth-card-aside">
              Secure Managed Service workspace
            </p>
          </header>

          <div className="auth-card-body">
            <h1 className="auth-title">Sign in</h1>

            <label className="auth-application-select">
              Application workspace
              <select
                aria-label="Application workspace"
                value={applicationToMonitor}
                onChange={(event) => onApplicationChange(event.target.value)}
              >
                {monitorApplications.map((name) => (
                  <option key={name} value={name}>
                    {name}
                  </option>
                ))}
              </select>
              <small>The workspace opens already scoped to this managed application.</small>
            </label>

            {isOidc ? (
              <div className="auth-form">
                <p className="auth-form-note">
                  Enterprise single sign-on is required. Your identity-provider role controls KaiMS access.
                </p>
                <button
                  className="auth-submit"
                  type="button"
                  onClick={onOidcLogin}
                  disabled={adminSession.loading || authConfig.loading}
                >
                  {adminSession.loading ? "Redirecting..." : "Continue with SSO"}
                </button>
              </div>
            ) : (
              <form className="auth-form" onSubmit={onLocalLogin}>
                <label className="auth-field">
                  Username
                  <input
                    autoComplete="username"
                    value={adminAuthForm.username}
                    onChange={(event) => onAdminAuthFormChange({ username: event.target.value })}
                  />
                </label>
                <label className="auth-field">
                  Password
                  <span className="auth-password-wrap">
                    <input
                      type={showPassword ? "text" : "password"}
                      autoComplete="current-password"
                      value={adminAuthForm.password}
                      onChange={(event) => onAdminAuthFormChange({ password: event.target.value })}
                    />
                    <button
                      type="button"
                      className="auth-password-toggle"
                      aria-label={showPassword ? "Hide password" : "Show password"}
                      onClick={() => setShowPassword((value) => !value)}
                    >
                      {showPassword ? "Hide" : "Show"}
                    </button>
                  </span>
                </label>
                <label className="auth-remember">
                  <input
                    type="checkbox"
                    checked={rememberMe}
                    onChange={(event) => setRememberMe(event.target.checked)}
                  />
                  Remember me
                </label>
                <button className="auth-submit" type="submit" disabled={adminSession.loading}>
                  {adminSession.loading ? "Signing in..." : "Sign in"}
                </button>
              </form>
            )}

            {adminSession.error ? <p className="error auth-error">{adminSession.error}</p> : null}
            {authConfig.error ? <p className="error auth-error">{authConfig.error}</p> : null}

            <p className="auth-footnote">
              {authConfig.mode === "local"
                ? "Local password authentication is for local/demo/test only."
                : "Tokens remain in memory and are not written to local storage."}
            </p>
          </div>
        </article>

        <aside className="auth-brand-story">
          <div className="auth-feature-orb" aria-hidden="true">
            <strong>Incident Intelligence</strong>
            <span>Evidence → Decision → Safe action</span>
          </div>
          <div className="auth-story-copy">
            <h2>Always-on incident intelligence. Human-controlled outcomes.</h2>
            <p>
              Connect evidence, operational reasoning, human judgment, and safe automation in one
              trusted Managed Service workspace.
            </p>
            <ul className="auth-proof-list" aria-label="KaiMS platform capabilities">
              <li>
                <strong>Evidence-first</strong>
                <span>Every conclusion is traceable</span>
              </li>
              <li>
                <strong>Human-governed</strong>
                <span>Control stays with operators</span>
              </li>
              <li>
                <strong>Closed-loop</strong>
                <span>Every outcome improves the next</span>
              </li>
            </ul>
          </div>
        </aside>
      </section>
    </main>
  );
}

export default SignIn;
