// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { act, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { clearStoredSession, storeSessionTokens } from "../services/sessionBootstrap";
import { SessionProvider, useSession } from "./SessionContext";

function Probe() {
  const session = useSession();
  return <output>{session.accessToken ? `${session.username}:${session.accessToken}` : "anonymous"}</output>;
}

describe("route-owned session provider", () => {
  beforeEach(() => clearStoredSession());

  it("hydrates and synchronizes tokens written by the compatibility login shell", () => {
    const view = render(<SessionProvider><Probe /></SessionProvider>);
    expect(screen.getByText("anonymous")).toBeInTheDocument();
    act(() => storeSessionTokens({ accessToken: "verified-token", refreshToken: "refresh", user: { username: "reviewer.one" } }));
    expect(screen.getByText("reviewer.one:verified-token")).toBeInTheDocument();
    view.unmount();
  });
});
