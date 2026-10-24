import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

vi.mock("@tanstack/react-router", () => ({ useNavigate: () => vi.fn() }));
vi.mock("@/api/client", () => ({
  api: {
    login: vi.fn(async (_identifier: string, password: string) => {
      if (password !== "ok") throw new Error("Invalid credentials");
      return { access_token: "a", refresh_token: "r", token_type: "Bearer", expires_in: 900 };
    }),
    post: vi.fn(async () => ({})),
    verifyOtp: vi.fn(),
    orgId: null,
  },
  tokenStore: { hasSession: false },
  onSignedOut: () => () => undefined,
}));

import { SessionProvider } from "@/auth/session";

import { LoginPage } from "./LoginPage";

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <SessionProvider>
        <LoginPage />
      </SessionProvider>
    </QueryClientProvider>,
  );
}

describe("LoginPage", () => {
  it("shows the server error on a failed password login", async () => {
    renderPage();
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Email or phone number"), "ama@example.org");
    await user.type(screen.getByLabelText("Password"), "wrong");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Invalid credentials");
  });

  it("switches to the one-time code flow", async () => {
    renderPage();
    const user = userEvent.setup();
    await user.click(screen.getByText("Send me a one-time code instead"));
    expect(screen.getByRole("button", { name: "Send code" })).toBeInTheDocument();
  });
});
