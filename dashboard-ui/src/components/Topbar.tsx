import { NavLink } from "react-router-dom";
import { Activity } from "lucide-react";
import { useUiStore } from "@/store/ui";
import { HeartbeatIndicator } from "@/components/HeartbeatIndicator";
import { KillSwitch } from "@/components/KillSwitch";
import { cn } from "@/lib/utils";

const NAV = [
  { to: "/", label: "Overview", end: true },
  { to: "/profiles", label: "Profiles", end: false },
  { to: "/settings", label: "Settings", end: false },
];

export function Topbar() {
  const activeProfile = useUiStore((s) => s.activeProfile);
  const setActiveProfile = useUiStore((s) => s.setActiveProfile);

  return (
    <header className="sticky top-0 z-30 bg-bg-0/85 backdrop-blur border-b border-border">
      <div className="mx-auto max-w-screen-2xl px-4 h-12 flex items-center gap-6">
        {/* Brand */}
        <div className="flex items-center gap-2 mr-2">
          <Activity className="h-4 w-4 text-accent" aria-hidden />
          <span className="text-sm font-semibold tracking-tight">
            Futures Bot Console
          </span>
        </div>

        {/* Nav */}
        <nav className="flex items-center gap-1">
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                cn(
                  "px-2.5 py-1 rounded text-sm transition-colors",
                  isActive
                    ? "text-text-primary bg-bg-2"
                    : "text-text-secondary hover:text-text-primary hover:bg-bg-2/60",
                )
              }
            >
              {item.label}
            </NavLink>
          ))}
        </nav>

        <div className="flex-1" />

        {/* Profile switcher */}
        <label className="flex items-center gap-2 text-xs text-text-secondary">
          <span className="uppercase tracking-wide">Profile</span>
          <select
            value={activeProfile}
            onChange={(e) => setActiveProfile(e.target.value)}
            className="bg-bg-2 border border-border rounded px-2 py-1 text-sm text-text-primary font-mono focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40"
            aria-label="Active profile"
          >
            <option value="default">default</option>
          </select>
        </label>

        <HeartbeatIndicator />
        <KillSwitch />
      </div>
    </header>
  );
}
