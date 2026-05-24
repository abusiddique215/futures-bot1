import { describe, expect, it } from "vitest";
import {
  contracts,
  dollars,
  percent,
  pnlClass,
  price,
  rMultiple,
  timeAgo,
  timeUntil,
} from "@/lib/format";

describe("format", () => {
  it("dollars: signed and unsigned", () => {
    expect(dollars(1234.5)).toBe("$1,234.50");
    expect(dollars(-1234.5)).toBe("-$1,234.50");
    expect(dollars(1234.5, { sign: true })).toBe("+$1,234.50");
    expect(dollars(0, { sign: true })).toBe("$0.00");
  });

  it("rMultiple: trader format", () => {
    expect(rMultiple(1.234)).toBe("+1.23R");
    expect(rMultiple(-0.5)).toBe("-0.50R");
    expect(rMultiple(0)).toBe("0.00R");
  });

  it("price: tick-aware decimals", () => {
    expect(price(18042.5, 0.25)).toBe("18042.50");
    expect(price(2398.3, 0.1)).toBe("2398.3");
    expect(price(50_000, 1)).toBe("50000");
  });

  it("percent: signed", () => {
    expect(percent(0.0125, { sign: true })).toBe("+1.25%");
    expect(percent(-0.0125, { sign: true })).toBe("-1.25%");
  });

  it("contracts: trader language", () => {
    expect(contracts(2, "long")).toBe("Long 2 contracts");
    expect(contracts(1, "short")).toBe("Short 1 contract");
    expect(contracts(0, null)).toBe("Flat");
  });

  it("timeAgo: relative formatting", () => {
    const now = 1_716_000_000_000;
    expect(timeAgo(now - 3_000, now)).toBe("just now");
    expect(timeAgo(now - 30_000, now)).toMatch(/30 seconds/);
    expect(timeAgo(now - 120_000, now)).toMatch(/2 minutes/);
  });

  it("timeUntil: compact countdown", () => {
    const now = 1_716_000_000_000;
    expect(timeUntil(now + 90_000, now)).toBe("1m");
    expect(timeUntil(now + 2 * 3600_000 + 14 * 60_000, now)).toBe("2h 14m");
    expect(timeUntil(now + 26 * 3600_000, now)).toBe("1d 2h");
  });

  it("pnlClass: maps sign to Tailwind class", () => {
    expect(pnlClass(1)).toBe("text-profit");
    expect(pnlClass(-1)).toBe("text-loss");
    expect(pnlClass(0)).toBe("text-flat");
  });
});
