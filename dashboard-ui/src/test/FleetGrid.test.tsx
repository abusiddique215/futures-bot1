import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { FleetGrid } from "@/components/FleetGrid";
import { mockBots, mockFleet } from "@/lib/mock";

describe("FleetGrid", () => {
  it("renders one card per bot in the fixture", () => {
    render(
      <MemoryRouter>
        <FleetGrid bots={mockBots} now={mockFleet.server_time} />
      </MemoryRouter>,
    );
    for (const bot of mockBots) {
      expect(screen.getByText(bot.display_name)).toBeInTheDocument();
    }
  });

  it("shows the day-trader state labels", () => {
    render(
      <MemoryRouter>
        <FleetGrid bots={mockBots} now={mockFleet.server_time} />
      </MemoryRouter>,
    );
    // SurgeBot is IN_TRADE +1.2R, Lux Bot ARMED_WAITING, ES Scalper DISABLED
    expect(screen.getAllByText(/In Trade · \+1\.20R/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Armed — Watching/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Disabled/).length).toBeGreaterThan(0);
  });

  it("renders next-window countdown when schedule is closed", () => {
    render(
      <MemoryRouter>
        <FleetGrid bots={mockBots} now={mockFleet.server_time} />
      </MemoryRouter>,
    );
    expect(screen.getAllByText(/in /).length).toBeGreaterThan(0);
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
