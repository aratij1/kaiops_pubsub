const SESSION_KEY = "kaims.auth.session.v1";

export type StoredSession = { accessToken: string; refreshToken: string };

export function readStoredSession(): StoredSession {
  try {
    const value = JSON.parse(window.sessionStorage.getItem(SESSION_KEY) || "{}");
    return { accessToken: String(value.accessToken || ""), refreshToken: String(value.refreshToken || "") };
  } catch {
    return { accessToken: "", refreshToken: "" };
  }
}

export function storeSessionTokens(session: Partial<StoredSession>) {
  window.sessionStorage.setItem(SESSION_KEY, JSON.stringify({ accessToken: String(session.accessToken || ""), refreshToken: String(session.refreshToken || "") }));
}

export function clearStoredSession() {
  window.sessionStorage.removeItem(SESSION_KEY);
}
