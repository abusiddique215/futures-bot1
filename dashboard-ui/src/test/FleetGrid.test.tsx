import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { FleetGrid } from "@/components/FleetGrid";
import { mockBots } from "@/lib/mock";

describe("FleetGrid", () => {
  it("renders one card per bot in the fixture", () => {
    render(
      <MemoryRouter>
        <FleetGrid bots={mockBots} />
      </MemoryRouter>,
    );
    for (const bot of mockBots) {
      expect(screen.getByText(bot.name)).toBeInTheDocument();
    }
  });

  it("shows the strategy_id label", () => {
    render(
      <MemoryRouter>
        <FleetGrid bots={mockBots} />
      </MemoryRouter>,
    );
    expect(screen.getAllByText(/orb_5m/).length).toBeGreaterThan(0);
  });

  it("falls back to Disabled when bot.enabled is false", () => {
    render(
      <MemoryRouter>
        <FleetGrid bots={mockBots.filter((b) => !b.enabled)} />
      </MemoryRouter>,
    );
    expect(screen.getAllByText(/Disabled/).length).toBeGreaterThan(0);
  });

  it("renders empty state when no bots", () => {
    render(
      <MemoryRouter>
        <FleetGrid bots={[]} />
      </MemoryRouter>,
    );
    expect(screen.getByText(/No bots configured/i)).toBeInTheDocument();
  });
});
