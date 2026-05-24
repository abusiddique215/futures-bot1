import { Route, Routes } from "react-router-dom";
import { Topbar } from "@/components/Topbar";
import { OverviewPage } from "@/pages/Overview";
import { BotDetailPage } from "@/pages/BotDetail";
import { ProfilesPage } from "@/pages/Profiles";
import { SettingsPage } from "@/pages/Settings";

export default function App() {
  return (
    <div className="min-h-screen flex flex-col bg-bg-0 text-text-primary">
      <Topbar />
      <main className="flex-1 mx-auto w-full max-w-screen-2xl px-4">
        <Routes>
          <Route path="/" element={<OverviewPage />} />
          <Route path="/bots/:name" element={<BotDetailPage />} />
          <Route path="/profiles" element={<ProfilesPage />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route
            path="*"
            element={
              <div className="py-8 text-text-secondary text-sm">Not found.</div>
            }
          />
        </Routes>
      </main>
    </div>
  );
}
