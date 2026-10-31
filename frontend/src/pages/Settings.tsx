import { FormEvent, useEffect, useState } from "react";
import { ErrorNote } from "../components/Feedback";
import { api, ApiError } from "../services/api";
import type { Palette, Settings } from "../types";
import { PALETTE_KEYS } from "../types";
import { applyPalette, paletteProblems, THEME_OVERRIDE_KEY } from "../utils/color";

const LABELS: Record<keyof Palette, string> = {
  bg: "Background",
  surface: "Surface",
  text: "Text",
  muted: "Muted text",
  border: "Border",
  accent: "Primary accent",
  accent_2: "Secondary accent",
  danger: "Out of stock",
  warning: "Low stock",
  ok: "In stock",
  info: "Info",
};

export function SettingsPage({ onTitle }: { onTitle: (title: string) => void }) {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [presets, setPresets] = useState<Record<string, Palette>>({});
  const [palette, setPalette] = useState<Palette | null>(null);
  const [theme, setTheme] = useState("dark");
  const [name, setName] = useState("");
  const [percent, setPercent] = useState("10");
  const [landing, setLanding] = useState("dashboard");
  const [url, setUrl] = useState("");
  const [pageSize, setPageSize] = useState("25");
  const [density, setDensity] = useState("comfortable");
  const [showSku, setShowSku] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    Promise.all([api<Settings>("/api/v1/settings"), api<{ presets: Record<string, Palette> }>("/api/v1/themes")])
      .then(([current, themes]) => {
        if (!live) return;
        setSettings(current);
        setPresets(themes.presets);
        setPalette(current.color_palette);
        setTheme(current.theme_preference);
        setName(current.application_name);
        setPercent(String(current.default_low_stock_percent));
        setLanding(current.preferred_landing_page);
        setUrl(current.preferred_public_url || "");
        setPageSize(String(current.display_preferences.page_size));
        setDensity(current.display_preferences.density);
        setShowSku(current.display_preferences.show_sku);
      })
      .catch((err: unknown) => setError(err instanceof ApiError ? err.message : "Could not load settings."));
    return () => {
      live = false;
    };
  }, []);

  function preview(next: Palette, nextDensity = density) {
    setPalette(next);
    const problems = paletteProblems(next);
    setError(problems.length ? problems[0] : null);
    if (!problems.length) applyPalette(next, nextDensity);
  }

  function choosePreset(key: string) {
    const next = presets[key];
    if (!next) return;
    setTheme(key);
    preview(next);
  }

  async function save(target: "everyone" | "browser") {
    if (!palette) return;
    const problems = paletteProblems(palette);
    if (problems.length) {
      setError(problems.join(" "));
      return;
    }
    setSaved(null);
    try {
      if (target === "browser") {
        localStorage.setItem(THEME_OVERRIDE_KEY, JSON.stringify({ palette, density }));
        applyPalette(palette, density);
        setSaved("Saved for this browser only.");
        return;
      }
      const body: Record<string, unknown> = {
        application_name: name.trim(),
        default_low_stock_percent: Number(percent),
        preferred_landing_page: landing,
        preferred_public_url: url.trim() || null,
        display_preferences: {
          page_size: Number(pageSize),
          density,
          show_sku: showSku,
        },
      };
      if (theme !== "custom" && presets[theme]) {
        body.theme_preference = theme;
      } else {
        body.color_palette = palette;
      }
      const updated = await api<Settings>("/api/v1/settings", { method: "PATCH", body: JSON.stringify(body) });
      localStorage.removeItem(THEME_OVERRIDE_KEY);
      setSettings(updated);
      setPalette(updated.color_palette);
      setTheme(updated.theme_preference);
      applyPalette(updated.color_palette, updated.display_preferences.density);
      onTitle(updated.application_name);
      document.title = updated.application_name;
      setSaved("Saved for every browser that does not have its own override.");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not save settings.");
    }
  }

  function reset() {
    const dark = presets.dark;
    if (!dark) return;
    setTheme("dark");
    preview(dark);
    setSaved(null);
  }

  if (!settings || !palette) return <p className="muted">Loading settings…</p>;

  return (
    <form
      className="stack"
      onSubmit={(event: FormEvent) => {
        event.preventDefault();
        void save("everyone");
      }}
    >
      <h1>Settings</h1>
      <ErrorNote message={error} />
      {saved ? <p className="note">{saved}</p> : null}
      <section className="card stack">
        <h2>Application</h2>
        <div className="row">
          <label className="field">
            Name
            <input aria-label="Application name" value={name} onChange={(event) => setName(event.target.value)} />
          </label>
          <label className="field">
            Default low-stock percent
            <input aria-label="Default low-stock percent" inputMode="numeric" value={percent} onChange={(event) => setPercent(event.target.value)} />
          </label>
          <label className="field">
            Landing page
            <select aria-label="Landing page" value={landing} onChange={(event) => setLanding(event.target.value)}>
              <option value="dashboard">Dashboard</option>
              <option value="inventory">Parts</option>
              <option value="drawers">Drawers</option>
              <option value="alerts">Alerts</option>
              <option value="transactions">History</option>
            </select>
          </label>
          <label className="field">
            Preferred public URL
            <input aria-label="Preferred public URL" value={url} onChange={(event) => setUrl(event.target.value)} placeholder="http://100.x.x.x:8765" />
          </label>
        </div>
        <p className="muted">The default percent applies to new parts. Existing parts keep the percent they were created with.</p>
      </section>
      <section className="card stack">
        <h2>Theme</h2>
        <div className="actions">
          {Object.keys(presets).map((key) => (
            <button key={key} type="button" aria-pressed={theme === key} onClick={() => choosePreset(key)}>
              {key}
            </button>
          ))}
          <button type="button" onClick={reset}>
            Reset to Dark
          </button>
        </div>
        <div className="swatches">
          {PALETTE_KEYS.map((key) => (
            <label className="field" key={key}>
              {LABELS[key]}
              <input
                aria-label={LABELS[key]}
                value={palette[key]}
                onChange={(event) => {
                  setTheme("custom");
                  preview({ ...palette, [key]: event.target.value });
                }}
              />
            </label>
          ))}
        </div>
        <div className="preview-card" data-testid="theme-preview">
          <strong>Preview</strong>
          <p className="muted">Text, muted text, and status colors must stay readable on the background and surface.</p>
          <p>
            <span className="badge badge-IN_STOCK">In stock</span> <span className="badge badge-LOW_STOCK">Low stock</span>{" "}
            <span className="badge badge-OUT_OF_STOCK">Out of stock</span>
          </p>
        </div>
        <div className="row">
          <label className="field">
            Page size
            <input aria-label="Page size" inputMode="numeric" value={pageSize} onChange={(event) => setPageSize(event.target.value)} />
          </label>
          <label className="field">
            Density
            <select
              aria-label="Density"
              value={density}
              onChange={(event) => {
                setDensity(event.target.value);
                applyPalette(palette, event.target.value);
              }}
            >
              <option value="comfortable">Comfortable</option>
              <option value="compact">Compact</option>
            </select>
          </label>
          <label className="field">
            <span>
              <input type="checkbox" checked={showSku} onChange={(event) => setShowSku(event.target.checked)} /> Show SKU
            </span>
          </label>
        </div>
      </section>
      <div className="actions">
        <button className="btn-primary" type="submit">
          Save for everyone
        </button>
        <button type="button" onClick={() => void save("browser")}>
          Save colors for this browser
        </button>
      </div>
    </form>
  );
}
