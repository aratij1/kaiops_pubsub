import { createContext, useContext, useEffect, useMemo, useState, type PropsWithChildren } from "react";
import { readStoredSession, SESSION_CHANGED_EVENT, type StoredSession } from "../services/sessionBootstrap";

export type SessionContextValue = StoredSession;
const emptySession: SessionContextValue = { accessToken: "", refreshToken: "", username: "operator" };
const SessionContext = createContext<SessionContextValue>(emptySession);

export function SessionProvider({ children }: PropsWithChildren) {
  const [tokens, setTokens] = useState<StoredSession>(() => readStoredSession());
  useEffect(() => {
    const refresh = () => setTokens(readStoredSession());
    window.addEventListener(SESSION_CHANGED_EVENT, refresh);
    window.addEventListener("storage", refresh);
    return () => { window.removeEventListener(SESSION_CHANGED_EVENT, refresh); window.removeEventListener("storage", refresh); };
  }, []);
  const value = useMemo(() => tokens, [tokens]);
  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): SessionContextValue {
  return useContext(SessionContext);
}
