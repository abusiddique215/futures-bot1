import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

// EquityCurve uses lightweight-charts which doesn't work well in jsdom
// (no real canvas/layout). Stub it to a placeholder div for tests.
vi.mock("@/components/EquityCurve", () => ({
  EquityCurve: () => <div data-testid="equity-curve-stub" />,
}));

import { BotDetailPage } from "@/pages/BotDetail";
import { mockBotDetail } from "@/lib/mock";

/**
 * Smoke test: BotDetailPage mounts against a fetch stub, hits
 * /api/bots/<name>, and renders the bot's name + symbol without
 * crashing. We deliberately avoid asserting on the equity chart
 * (lightweight-charts needs a real layout engine; jsdom is enough to
 * mount it but the API is opaque).
 */
describe("BotDetailPage", () => {
  const originalFetch = globalThis.fetch;

  beforeEach(() => {
    const fixture = mockBotDetail.surgebot_nq;
    globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.includes("/api/bots/surgebot_nq")) {
        return new Response(JSON.stringify(fixture), {
          status: 200,
          headers: { "content-type": "application/json" },
        });
      }
      return new Response("not found", { status: 404 });
    }) as typeof fetch;
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it("renders bot name + symbol from the API response", async () => {
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={["/bots/surgebot_nq"]}>
          <Routes>
            <Route path="/bots/:name" element={<BotDetailPage />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );
    await waitFor(() => {
      expect(screen.getAllByText(/surgebot_nq/).length).toBeGreaterThan(0);
    });
    expect(screen.getAllByText("MNQ").length).toBeGreaterThan(0);
  });
});
