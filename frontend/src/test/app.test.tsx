import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { readFileSync } from "node:fs";
import { Layout } from "../components/Layout";
import { StockForm } from "../components/StockForm";
import { AlertsPage } from "../pages/Alerts";
import { DashboardPage } from "../pages/Dashboard";
import { DrawersPage } from "../pages/Drawers";
import { InventoryPage } from "../pages/Inventory";
import { SettingsPage } from "../pages/Settings";
import type { Page, Part, Settings } from "../types";
import { contrastRatio, paletteProblems } from "../utils/color";

const part: Part = {
  id: "part-1",
  sku: "M3-SCREW",
  name: "M3 screw",
  description: null,
  category: { id: "cat-1", name: "Fasteners", description: null, color: "#888888" },
  manufacturer: null,
  manufacturer_part_number: null,
  specifications: {},
  unit: "pcs",
  initial_quantity: 100,
  low_stock_percent: 10,
  low_stock_override: null,
  notes: null,
  current_quantity: 5,
  threshold: 10,
  threshold_configured: true,
  baseline_state: "OK",
  status: "LOW_STOCK",
  slots: [{ slot_id: "slot-1", slot_number: 110, label: null, location: null, quantity: 5 }],
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  archived_at: null,
};

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("color contrast", () => {
  it("rejects unreadable palettes and accepts the dark default", () => {
    expect(contrastRatio("#ffffff", "#ffffff")).toBeLessThan(2);
    const bad = paletteProblems({
      bg: "#ffffff",
      surface: "#ffffff",
      text: "#ffffff",
      muted: "#ffffff",
      border: "#cccccc",
      accent: "#ffffff",
      accent_2: "#ffffff",
      danger: "#ffffff",
      warning: "#ffffff",
      ok: "#ffffff",
      info: "#ffffff",
    });
    expect(bad.length).toBeGreaterThan(0);
    expect(
      paletteProblems({
        bg: "#0e1116",
        surface: "#171c24",
        text: "#e7ecf3",
        muted: "#9aabbf",
        border: "#2c3646",
        accent: "#3ddc97",
        accent_2: "#7aa2ff",
        danger: "#ff5d6c",
        warning: "#f5c16c",
        ok: "#3ddc97",
        info: "#7aa2ff",
      }),
    ).toEqual([]);
  });
});

describe("inventory page", () => {
  it("loads parts and applies a search", async () => {
    const user = userEvent.setup();
    const calls: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        calls.push(url);
        if (url.includes("/categories")) return jsonResponse([{ id: "cat-1", name: "Fasteners", description: null, color: null }]);
        if (url.includes("/slots")) {
          return jsonResponse({
            items: [{ id: "slot-1", slot_number: 110, label: "M3 Fasteners", location: null, total_units: 5, part_count: 1, archived_at: null }],
            total: 1,
            limit: 100,
            offset: 0,
          });
        }
        const page: Page<Part> = { items: url.includes("search=M3") ? [part] : [part], total: 1, limit: 25, offset: 0 };
        return jsonResponse(page);
      }),
    );
    render(
      <MemoryRouter initialEntries={["/inventory"]}>
        <InventoryPage />
      </MemoryRouter>,
    );
    expect(await screen.findByText("M3 screw")).toBeInTheDocument();
    expect(screen.getByText("110 × 5")).toBeInTheDocument();
    await user.clear(screen.getByLabelText("Filter parts"));
    await user.type(screen.getByLabelText("Filter parts"), "M3");
    await user.click(screen.getByRole("button", { name: "Apply" }));
    expect(calls.some((url) => url.includes("search=M3"))).toBe(true);
    vi.unstubAllGlobals();
  });

  it("shows an API error", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes("/categories")) return jsonResponse([]);
        if (url.includes("/slots")) return jsonResponse({ items: [], total: 0, limit: 100, offset: 0 });
        return jsonResponse({ error: { code: "internal_error", message: "Database busy" } }, 500);
      }),
    );
    render(
      <MemoryRouter>
        <InventoryPage />
      </MemoryRouter>,
    );
    expect(await screen.findByRole("alert")).toHaveTextContent("Database busy");
    vi.unstubAllGlobals();
  });
});

describe("stock form", () => {
  it("submits a removal once", async () => {
    const user = userEvent.setup();
    let calls = 0;
    let release: (value: Response) => void = () => undefined;
    const pending = new Promise<Response>((resolve) => {
      release = resolve;
    });
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.includes("/slots")) {
          return jsonResponse({
            items: [{ id: "slot-1", slot_number: 110, label: "M3 Fasteners", location: null, total_units: 5, part_count: 1, archived_at: null }],
            total: 1,
            limit: 100,
            offset: 0,
          });
        }
        if (url.includes("/items/part-1")) return jsonResponse(part);
        if (url.includes("/items")) {
          return jsonResponse({ items: [part], total: 1, limit: 8, offset: 0 });
        }
        calls += 1;
        expect(url).toContain("/api/v1/stock/remove");
        expect(init?.method).toBe("POST");
        expect(String(init?.body)).toContain('"quantity":5');
        return pending;
      }),
    );
    const onDone = vi.fn();
    render(<StockForm presetPartId="part-1" presetSlot={110} onDone={onDone} />);
    await user.type(screen.getByLabelText("Quantity"), "5");
    const form = screen.getByRole("button", { name: "Confirm stock change" }).closest("form");
    if (!form) throw new Error("missing form");
    fireEvent.submit(form);
    fireEvent.submit(form);
    expect(calls).toBe(1);
    release(jsonResponse({ id: "txn" }));
    await waitFor(() => expect(onDone).toHaveBeenCalledTimes(1));
    vi.unstubAllGlobals();
  });

  it("keeps the quantity when removal is rejected", async () => {
    const user = userEvent.setup();
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.includes("/slots")) {
          return jsonResponse({
            items: [{ id: "slot-1", slot_number: 110, label: "M3 Fasteners", location: null, total_units: 5, part_count: 1, archived_at: null }],
            total: 1,
            limit: 100,
            offset: 0,
          });
        }
        if (url.includes("/items/part-1")) return jsonResponse(part);
        if (init?.method === "POST") {
          return jsonResponse(
            {
              error: {
                code: "negative_stock",
                message: "Cannot remove 15 M3 screw from drawer 110. Only 8 are available.",
                field: "quantity",
              },
            },
            409,
          );
        }
        return jsonResponse({ items: [], total: 0, limit: 8, offset: 0 });
      }),
    );
    render(<StockForm presetPartId="part-1" presetSlot={110} onDone={vi.fn()} />);
    await user.type(screen.getByLabelText("Quantity"), "5");
    expect(await screen.findByText("Available in this drawer: 5")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Confirm stock change" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Cannot remove 15 M3 screw from drawer 110. Only 8 are available.");
    expect(screen.getByLabelText("Quantity")).toHaveValue("5");
    vi.unstubAllGlobals();
  });
});

describe("drawers", () => {
  it("lists drawers and creates one", async () => {
    const user = userEvent.setup();
    const posted: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
        if (init?.method === "POST") {
          posted.push(String(init.body));
          return jsonResponse({ slot_number: 110, id: "s", items: [], total_units: 0 });
        }
        return jsonResponse({
          items: [{ id: "s", slot_number: 111, label: "Screws", location: "Cabinet", total_units: 4, part_count: 2, archived_at: null }],
          total: 1,
          limit: 100,
          offset: 0,
        });
      }),
    );
    render(
      <MemoryRouter>
        <DrawersPage />
      </MemoryRouter>,
    );
    expect(await screen.findByText("111")).toBeInTheDocument();
    await user.type(screen.getByLabelText("New drawer number"), "110");
    await user.click(screen.getByRole("button", { name: "Create drawer" }));
    expect(posted[0]).toContain("110");
    vi.unstubAllGlobals();
  });
});

describe("drawer editing and part allocation", () => {
  const drawer = {
    id: "slot-1",
    slot_number: 110,
    label: "M3 Fasteners",
    description: "Left side",
    location: "Bench",
    archived_at: null,
    items: [{ part_id: "part-1", name: "M3 screw", sku: "M3-SCREW", unit: "pcs", quantity: 5 }],
    total_units: 5,
  };

  it("edits a drawer, refuses a occupied delete, and deletes an empty drawer", async () => {
    const user = userEvent.setup();
    const calls: { url: string; method?: string; body?: string }[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        calls.push({ url, method: init?.method, body: init?.body ? String(init.body) : undefined });
        if (init?.method === "PATCH") {
          return jsonResponse({ ...drawer, slot_number: 210, label: "Renamed", id: "slot-1" });
        }
        if (init?.method === "DELETE") return jsonResponse({ deleted: true });
        if (url.endsWith("/slots/110")) return jsonResponse(drawer);
        return jsonResponse({
          items: [{ id: "slot-1", slot_number: 110, label: "M3 Fasteners", location: "Bench", total_units: 5, part_count: 1, archived_at: null }],
          total: 1,
          limit: 100,
          offset: 0,
        });
      }),
    );
    render(
      <MemoryRouter>
        <DrawersPage />
      </MemoryRouter>,
    );
    expect(await screen.findByRole("button", { name: "Edit" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "View Contents" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Delete" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Drawer 110 still contains parts");
    expect(calls.some((call) => call.method === "DELETE")).toBe(false);
    await user.click(screen.getByRole("button", { name: "Edit" }));
    const number = await screen.findByLabelText("Edit drawer number");
    expect(number).toHaveValue("110");
    await user.clear(number);
    await user.type(number, "210");
    await user.clear(screen.getByLabelText("Edit label"));
    await user.type(screen.getByLabelText("Edit label"), "Renamed");
    await user.click(screen.getByRole("button", { name: "Save drawer" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Drawer 210 saved.");
    expect(calls.some((call) => call.method === "PATCH" && call.body?.includes("210"))).toBe(true);
    vi.unstubAllGlobals();
  });

  it("confirms deletion of an empty drawer", async () => {
    const user = userEvent.setup();
    const methods: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
        methods.push(init?.method ?? "GET");
        if (init?.method === "DELETE") return jsonResponse({ deleted: true });
        return jsonResponse({
          items: [{ id: "slot-9", slot_number: 9, label: null, location: null, total_units: 0, part_count: 0, archived_at: null }],
          total: 1,
          limit: 100,
          offset: 0,
        });
      }),
    );
    render(
      <MemoryRouter>
        <DrawersPage />
      </MemoryRouter>,
    );
    await user.click(await screen.findByRole("button", { name: "Delete" }));
    await user.click(screen.getByRole("button", { name: "Confirm delete" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Drawer deleted successfully.");
    expect(methods).toContain("DELETE");
    vi.unstubAllGlobals();
  });

  it("fills drawer choices, keeps the part form, and submits several drawers", async () => {
    const user = userEvent.setup();
    const posted: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.includes("/categories")) return jsonResponse([{ id: "cat-1", name: "Fasteners", description: null, color: null }]);
        if (init?.method === "POST" && url.endsWith("/slots")) {
          return jsonResponse({
            id: "slot-new",
            slot_number: 210,
            label: "Spare",
            description: null,
            location: null,
            archived_at: null,
            items: [],
            total_units: 0,
          });
        }
        if (init?.method === "POST" && url.endsWith("/items")) {
          posted.push(String(init.body));
          return jsonResponse({ error: { code: "conflict", message: "SKU M3 is already in use.", field: "sku" } }, 409);
        }
        if (url.includes("/slots")) {
          return jsonResponse({
            items: [{ id: "slot-1", slot_number: 110, label: "M3 Fasteners", location: null, total_units: 0, part_count: 0, archived_at: null }],
            total: 1,
            limit: 100,
            offset: 0,
          });
        }
        return jsonResponse({ items: [], total: 0, limit: 25, offset: 0 });
      }),
    );
    render(
      <MemoryRouter>
        <InventoryPage />
      </MemoryRouter>,
    );
    await user.type(screen.getByLabelText("New part name"), "Kept screw");
    await user.click(screen.getByRole("button", { name: "Add drawer" }));
    expect(await screen.findByRole("option", { name: "110 — M3 Fasteners" })).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText("Allocate to drawer 1"), "110");
    await user.type(screen.getByLabelText("Allocation quantity 1"), "4");
    await user.click(screen.getByRole("button", { name: "Add drawer" }));
    const second = screen.getByLabelText("Allocate to drawer 2") as HTMLSelectElement;
    expect([...second.options].map((option) => option.value)).not.toContain("110");
    await user.click(screen.getByRole("button", { name: "Create Drawer" }));
    await user.type(screen.getByLabelText("Inline drawer number"), "210");
    await user.type(screen.getByLabelText("Inline drawer label"), "Spare");
    await user.click(screen.getByRole("button", { name: "Create drawer" }));
    expect(await screen.findByRole("option", { name: "210 — Spare" })).toBeInTheDocument();
    expect(screen.getByLabelText("New part name")).toHaveValue("Kept screw");
    expect(screen.getByLabelText("Allocate to drawer 2")).toHaveValue("210");
    await user.type(screen.getByLabelText("Allocation quantity 2"), "6");
    await user.click(screen.getByRole("button", { name: "Create part" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("SKU M3 is already in use.");
    expect(screen.getByLabelText("New part name")).toHaveValue("Kept screw");
    expect(screen.getByLabelText("Allocation quantity 1")).toHaveValue("4");
    expect(posted[0]).toContain('"slot_number":110');
    expect(posted[0]).toContain('"slot_number":210');
    expect(posted[0]).toContain('"initial_quantity":0');
    vi.unstubAllGlobals();
  });

  it("says when no drawers exist yet", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes("/categories")) return jsonResponse([]);
        if (url.includes("/slots")) return jsonResponse({ items: [], total: 0, limit: 100, offset: 0 });
        return jsonResponse({ items: [], total: 0, limit: 25, offset: 0 });
      }),
    );
    render(
      <MemoryRouter>
        <InventoryPage />
      </MemoryRouter>,
    );
    expect(await screen.findByText("No drawers exist yet. Create a drawer to assign this part.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Create part" })).toBeDisabled();
    vi.unstubAllGlobals();
  });
});

describe("alerts", () => {
  it("shows critical stock and restocks without touching the baseline", async () => {
    const user = userEvent.setup();
    const bodies: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
        if (init?.method === "POST") {
          bodies.push(String(init.body));
          return jsonResponse({ id: "txn" });
        }
        return jsonResponse({ items: [part], total: 1, limit: 200, offset: 0 });
      }),
    );
    render(
      <MemoryRouter>
        <AlertsPage />
      </MemoryRouter>,
    );
    expect(await screen.findByText("M3 screw")).toBeInTheDocument();
    expect(screen.getAllByText("Low stock").length).toBeGreaterThan(0);
    await user.click(screen.getByRole("button", { name: "Restock" }));
    expect(bodies[0]).toContain("RESTOCK");
    expect(bodies[0]).not.toContain("initial_quantity");
    vi.unstubAllGlobals();
  });
});

describe("dashboard", () => {
  it("renders clickable status counts", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes("/stats")) {
          return jsonResponse({
            active_part_types: 3,
            occupied_slots: 2,
            total_units: 40,
            low_stock_part_types: 1,
            out_of_stock_part_types: 1,
            drawer_count: 2,
          });
        }
        return jsonResponse({ items: [], total: 0, limit: 8, offset: 0 });
      }),
    );
    render(
      <MemoryRouter>
        <DashboardPage />
      </MemoryRouter>,
    );
    expect(await screen.findByText("Active part types")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Low stock/ })).toHaveAttribute("href", "/inventory?status=LOW_STOCK");
    vi.unstubAllGlobals();
  });
});

describe("settings theme", () => {
  const settings: Settings = {
    application_name: "Cyberdeck Inventory",
    theme_preference: "dark",
    color_palette: {
      bg: "#0e1116",
      surface: "#171c24",
      text: "#e7ecf3",
      muted: "#9aabbf",
      border: "#2c3646",
      accent: "#3ddc97",
      accent_2: "#7aa2ff",
      danger: "#ff5d6c",
      warning: "#f5c16c",
      ok: "#3ddc97",
      info: "#7aa2ff",
    },
    default_low_stock_percent: 10,
    preferred_landing_page: "dashboard",
    display_preferences: { page_size: 25, density: "comfortable", show_sku: true },
    preferred_public_url: null,
  };

  it("switches presets and refuses an unreadable custom color", async () => {
    const user = userEvent.setup();
    let calls = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        calls += 1;
        const url = String(input);
        if (url.includes("/themes")) {
          return jsonResponse({ presets: { dark: settings.color_palette, cyberpunk: { ...settings.color_palette, accent: "#e23ca8" } } });
        }
        return jsonResponse(settings);
      }),
    );
    render(<SettingsPage onTitle={() => undefined} />);
    expect(await screen.findByLabelText("Primary accent")).toHaveValue("#3ddc97");
    await user.click(screen.getByRole("button", { name: "cyberpunk" }));
    expect(screen.getByLabelText("Primary accent")).toHaveValue("#e23ca8");
    await user.clear(screen.getByLabelText("Text"));
    await user.type(screen.getByLabelText("Text"), "#ffffff");
    await user.clear(screen.getByLabelText("Background"));
    await user.type(screen.getByLabelText("Background"), "#ffffff");
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(calls).toBeGreaterThan(0);
    vi.unstubAllGlobals();
  });
});

describe("layout", () => {
  it("exposes the mobile navigation and touch-sized controls", () => {
    render(
      <MemoryRouter>
        <Layout title="Cyberdeck Inventory">
          <p>Body</p>
        </Layout>
      </MemoryRouter>,
    );
    expect(screen.getByRole("navigation", { name: "Mobile" })).toBeInTheDocument();
    const css = readFileSync("src/styles/app.css", "utf8");
    expect(css).toContain("max-width: 720px");
    expect(css).toContain("min-height: 44px");
    expect(css).toContain(".bottom-nav");
  });
});
