import { useEffect, useState } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import { AlertsPage } from "./pages/Alerts";
import { DashboardPage } from "./pages/Dashboard";
import { DrawerDetailPage } from "./pages/DrawerDetail";
import { DrawersPage } from "./pages/Drawers";
import { ImportExportPage } from "./pages/ImportExport";
import { InventoryPage } from "./pages/Inventory";
import { PartDetailPage } from "./pages/PartDetail";
import { SettingsPage } from "./pages/Settings";
import { TransactionsPage } from "./pages/Transactions";
import { api } from "./services/api";
import type { Palette, Settings } from "./types";
import { applyPalette, THEME_OVERRIDE_KEY } from "./utils/color";

function applySavedTheme(settings: Settings) {
  const stored = localStorage.getItem(THEME_OVERRIDE_KEY);
  if (stored) {
    try {
      const parsed = JSON.parse(stored) as { palette?: Palette; density?: string };
      if (parsed.palette) {
        applyPalette(parsed.palette, parsed.density || settings.display_preferences.density);
        return;
      }
    } catch {
      localStorage.removeItem(THEME_OVERRIDE_KEY);
    }
  }
  applyPalette(settings.color_palette, settings.display_preferences.density);
}

export function App() {
  const [title, setTitle] = useState("Cyberdeck Inventory");

  useEffect(() => {
    let live = true;
    api<Settings>("/api/v1/settings")
      .then((settings) => {
        if (!live) return;
        setTitle(settings.application_name || "Cyberdeck Inventory");
        document.title = settings.application_name || "Cyberdeck Inventory";
        applySavedTheme(settings);
      })
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, []);

  return (
    <Layout title={title}>
      <Routes>
        <Route path="/" element={<LandingRedirect />} />
        <Route path="/dashboard" element={<DashboardPage />} />
        <Route path="/inventory" element={<InventoryPage />} />
        <Route path="/inventory/:id" element={<PartDetailPage />} />
        <Route path="/drawers" element={<DrawersPage />} />
        <Route path="/drawers/:slotNumber" element={<DrawerDetailPage />} />
        <Route path="/transactions" element={<TransactionsPage />} />
        <Route path="/alerts" element={<AlertsPage />} />
        <Route path="/settings" element={<SettingsPage onTitle={setTitle} />} />
        <Route path="/import" element={<ImportExportPage />} />
        <Route path="*" element={<Navigate to="/dashboard" replace />} />
      </Routes>
    </Layout>
  );
}

function LandingRedirect() {
  const [target, setTarget] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    api<Settings>("/api/v1/settings")
      .then((settings) => {
        if (!live) return;
        const page = settings.preferred_landing_page || "dashboard";
        setTarget(page === "dashboard" ? "/dashboard" : `/${page}`);
      })
      .catch(() => {
        if (live) setTarget("/dashboard");
      });
    return () => {
      live = false;
    };
  }, []);
  if (!target) return <p className="muted">Loading…</p>;
  return <Navigate to={target} replace />;
}
