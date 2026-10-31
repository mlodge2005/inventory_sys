import { useState } from "react";
import { ErrorNote } from "../components/Feedback";
import { api, ApiError } from "../services/api";

type Kind = "parts" | "categories" | "slots" | "allocations";

export function ImportExportPage() {
  const [parts, setParts] = useState("");
  const [categories, setCategories] = useState("");
  const [slots, setSlots] = useState("");
  const [allocations, setAllocations] = useState("");
  const [mode, setMode] = useState("create_only");
  const [allocationMode, setAllocationMode] = useState("add");
  const [preview, setPreview] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [ok, setOk] = useState(false);

  function bundle() {
    return {
      parts_csv: parts || null,
      categories_csv: categories || null,
      slots_csv: slots || null,
      allocations_csv: allocations || null,
      mode,
      allocation_mode: allocationMode,
    };
  }

  async function run(commit: boolean) {
    setError(null);
    setPreview(null);
    try {
      const result = await api<{ ok: boolean; errors: unknown[]; summary: unknown; rows: number }>(
        commit ? "/api/v1/import/commit" : "/api/v1/import/preview",
        { method: "POST", body: JSON.stringify(bundle()) },
      );
      setOk(result.ok);
      setPreview(JSON.stringify(result, null, 2));
    } catch (err) {
      setOk(false);
      setError(err instanceof ApiError ? err.message : "Import failed. Nothing was committed.");
    }
  }

  async function download(kind: Kind | "transactions") {
    const response = await fetch(`/api/v1/export/${kind}.csv`, {
      headers: { "X-Cyberdeck-Request": "1", "X-Cyberdeck-Client": "web" },
    });
    if (!response.ok) {
      setError("Export failed.");
      return;
    }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `${kind}.csv`;
    link.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div className="stack">
      <h1>Import and export</h1>
      <p className="note">
        Preview checks the whole file before anything is written. A failed import leaves inventory unchanged. Allocation
        rows add stock through the normal transaction log. They do not rewrite history.
      </p>
      <div className="actions">
        {(["parts", "categories", "slots", "allocations", "transactions"] as const).map((kind) => (
          <button key={kind} type="button" onClick={() => void download(kind)}>
            Export {kind}
          </button>
        ))}
      </div>
      <label className="field">
        Categories CSV
        <textarea aria-label="Categories CSV" rows={4} value={categories} onChange={(event) => setCategories(event.target.value)} />
      </label>
      <label className="field">
        Drawers CSV
        <textarea aria-label="Drawers CSV" rows={4} value={slots} onChange={(event) => setSlots(event.target.value)} />
      </label>
      <label className="field">
        Parts CSV
        <textarea aria-label="Parts CSV" rows={6} value={parts} onChange={(event) => setParts(event.target.value)} />
      </label>
      <label className="field">
        Allocations CSV
        <textarea aria-label="Allocations CSV" rows={4} value={allocations} onChange={(event) => setAllocations(event.target.value)} />
      </label>
      <div className="row">
        <label className="field">
          Part mode
          <select aria-label="Import mode" value={mode} onChange={(event) => setMode(event.target.value)}>
            <option value="create_only">Create only</option>
            <option value="update_metadata">Update metadata</option>
          </select>
        </label>
        <label className="field">
          Allocations
          <select aria-label="Allocation mode" value={allocationMode} onChange={(event) => setAllocationMode(event.target.value)}>
            <option value="add">Add quantity</option>
            <option value="skip_existing">Skip existing</option>
          </select>
        </label>
      </div>
      <ErrorNote message={error} />
      <div className="actions">
        <button type="button" onClick={() => void run(false)}>
          Preview
        </button>
        <button className="btn-primary" type="button" disabled={!ok} onClick={() => void run(true)}>
          Commit preview
        </button>
      </div>
      {preview ? <pre className="card">{preview}</pre> : null}
    </div>
  );
}
