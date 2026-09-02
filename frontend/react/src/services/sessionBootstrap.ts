const SESSION_KEY = "kaims.auth.session.v1";
export const SESSION_CHANGED_EVENT = "kaims:session-changed";

export type StoredSession = { accessToken: string; refreshToken: string; username: string };

export function readStoredSession(): StoredSession {
  try {
    const value = JSON.parse(window.sessionStorage.getItem(SESSION_KEY) || "{}");
    return { accessToken: String(value.accessToken || ""), refreshToken: String(value.refreshToken || ""), username: String(value.username || "operator") };
  } catch {
    return { accessToken: "", refreshToken: "", username: "operator" };
  }
}

export function storeSessionTokens(session: Partial<StoredSession> & { user?: { username?: string } | null }) {
  window.sessionStorage.setItem(SESSION_KEY, JSON.stringify({ accessToken: String(session.accessToken || ""), refreshToken: String(session.refreshToken || ""), username: String(session.username || session.user?.username || "operator") }));
  window.dispatchEvent(new Event(SESSION_CHANGED_EVENT));
}

export function clearStoredSession() {
  window.sessionStorage.removeItem(SESSION_KEY);
  window.dispatchEvent(new Event(SESSION_CHANGED_EVENT));
}
