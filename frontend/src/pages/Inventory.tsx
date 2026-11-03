import { FormEvent, useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { DrawerSelect } from "../components/DrawerSelect";
import { ErrorNote, FieldError, Loading, Notice, drawerList } from "../components/Feedback";
import { StatusBadge } from "../components/StatusBadge";
import { useLoad } from "../hooks/useLoad";
import { api, ApiError, itemsQuery, loadDrawers } from "../services/api";
import type { Category, Page, Part, SlotDetail, SlotSummary } from "../types";

export function InventoryPage() {
  const [params, setParams] = useSearchParams();
  const search = params.get("search") ?? "";
  const category = params.get("category") ?? "";
  const status = params.get("status") ?? "";
  const slot = params.get("slot") ?? "";
  const sort = params.get("sort") ?? "name";
  const offset = Number(params.get("offset") ?? "0") || 0;
  const limit = 25;
  const [draft, setDraft] = useState(search);
  const categories = useLoad(() => api<Category[]>("/api/v1/categories"), []);
  const page = useLoad(
    () =>
      api<Page<Part>>(
        itemsQuery({
          search,
          category,
          status,
          slot,
          sort,
          order: sort === "name" ? "asc" : "desc",
          limit,
          offset,
        }),
      ),
    [search, category, status, slot, sort, offset],
  );

  function update(next: Record<string, string>) {
    const merged = new URLSearchParams(params);
    for (const [key, value] of Object.entries(next)) {
      if (value) merged.set(key, value);
      else merged.delete(key);
    }
    if (!("offset" in next)) merged.delete("offset");
    setParams(merged);
  }

  function onSearch(event: FormEvent) {
    event.preventDefault();
    update({ search: draft.trim() });
  }

  return (
    <div className="stack">
      <h1>Parts</h1>
      <p className="note">
        The baseline is the fixed reference used for low-stock alerts. Creating a part does not put pieces in a drawer
        until you allocate stock.
      </p>
      <form className="row" onSubmit={onSearch}>
        <label className="field">
          Search
          <input aria-label="Filter parts" value={draft} onChange={(event) => setDraft(event.target.value)} />
        </label>
        <label className="field">
          Category
          <select aria-label="Category" value={category} onChange={(event) => update({ category: event.target.value })}>
            <option value="">All</option>
            {(categories.data ?? []).map((item) => (
              <option key={item.id} value={item.name}>
                {item.name}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          Status
          <select aria-label="Stock status" value={status} onChange={(event) => update({ status: event.target.value })}>
            <option value="">All</option>
            <option value="IN_STOCK">In stock</option>
            <option value="LOW_STOCK">Low stock</option>
            <option value="OUT_OF_STOCK">Out of stock</option>
          </select>
        </label>
        <label className="field">
          Drawer
          <input aria-label="Drawer filter" inputMode="numeric" value={slot} onChange={(event) => update({ slot: event.target.value })} />
        </label>
        <label className="field">
          Sort
          <select aria-label="Sort" value={sort} onChange={(event) => update({ sort: event.target.value })}>
            <option value="name">Name</option>
            <option value="quantity">Quantity</option>
            <option value="updated_at">Updated</option>
            <option value="status">Status</option>
          </select>
        </label>
        <button type="submit">Apply</button>
      </form>
      <ErrorNote message={page.error || categories.error} />
      {page.loading ? <Loading /> : null}
      <div className="table-wrap">
        <table className="responsive">
          <thead>
            <tr>
              <th>Part</th>
              <th>SKU</th>
              <th>Category</th>
              <th>On hand</th>
              <th>Baseline</th>
              <th>Threshold</th>
              <th>Status</th>
              <th>Drawers</th>
            </tr>
          </thead>
          <tbody>
            {(page.data?.items ?? []).map((part) => (
              <tr key={part.id}>
                <td data-label="Part">
                  <Link to={`/inventory/${part.id}`}>{part.name}</Link>
                </td>
                <td data-label="SKU">{part.sku || "—"}</td>
                <td data-label="Category">{part.category?.name || "—"}</td>
                <td className="num" data-label="On hand">
                  {part.current_quantity}
                </td>
                <td className="num" data-label="Baseline">
                  {part.initial_quantity}
                </td>
                <td data-label="Threshold">
                  {part.threshold_configured ? part.threshold : "Baseline not set"}
                </td>
                <td data-label="Status">
                  <StatusBadge status={part.status} />
                </td>
                <td data-label="Drawers">{drawerList(part.slots)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {page.data && page.data.items.length === 0 ? <p className="muted">No parts match these filters.</p> : null}
      <div className="actions">
        <button type="button" disabled={offset <= 0} onClick={() => update({ offset: String(Math.max(0, offset - limit)) })}>
          Previous
        </button>
        <span className="muted">
          {page.data ? `${Math.min(offset + 1, page.data.total)}–${Math.min(offset + (page.data.items.length || 0), page.data.total)} of ${page.data.total}` : ""}
        </span>
        <button
          type="button"
          disabled={!page.data || offset + limit >= page.data.total}
          onClick={() => update({ offset: String(offset + limit) })}
        >
          Next
        </button>
      </div>
      <CreatePart onCreated={page.reload} categories={categories.data ?? []} />
    </div>
  );
}

function CreatePart({ onCreated, categories }: { onCreated: () => void; categories: Category[] }) {
  const [error, setError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [notice, setNotice] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [sku, setSku] = useState("");
  const [baseline, setBaseline] = useState("0");
  const [categoryId, setCategoryId] = useState("");
  const [rows, setRows] = useState<{ slot: string; quantity: string }[]>([]);
  const [drawers, setDrawers] = useState<SlotSummary[]>([]);
  const [creatingDrawer, setCreatingDrawer] = useState(false);
  const [newNumber, setNewNumber] = useState("");
  const [newLabel, setNewLabel] = useState("");
  const [drawerError, setDrawerError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    loadDrawers()
      .then((items) => {
        if (live) setDrawers(items);
      })
      .catch((err: unknown) => {
        if (live) setError(err instanceof ApiError ? err.message : "Could not load drawers.");
      });
    return () => {
      live = false;
    };
  }, []);

  function chosenNumbers(exceptIndex?: number): string[] {
    return rows.flatMap((row, index) => (index !== exceptIndex && row.slot ? [row.slot] : []));
  }

  const allocationProblems = rows.map((row) => {
    if (!row.slot && !row.quantity.trim()) return null;
    if (!row.slot) return "Select an existing drawer or create a new one.";
    if (!/^\d+$/.test(row.quantity.trim()) || Number(row.quantity) <= 0) return "Enter a whole number greater than zero.";
    return null;
  });
  const allocationsReady = allocationProblems.every((problem) => problem === null);
  const baselineOk = /^\d+$/.test(baseline.trim());

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setFieldErrors({});
    setNotice(null);
    if (!name.trim() || !baselineOk || !allocationsReady) return;
    const initial = Number(baseline);
    const body: Record<string, unknown> = {
      name: name.trim(),
      sku: sku.trim() || null,
      initial_quantity: initial,
      category_id: categoryId || null,
    };
    const allocations = rows
      .filter((row) => row.slot && Number(row.quantity) > 0)
      .map((row) => ({ slot_number: Number(row.slot), quantity: Number(row.quantity) }));
    if (allocations.length) body.allocations = allocations;
    try {
      await api("/api/v1/items", { method: "POST", body: JSON.stringify(body) });
      setName("");
      setSku("");
      setBaseline("0");
      setRows([]);
      setNotice("Part created. The baseline was stored separately from drawer quantities.");
      onCreated();
    } catch (err) {
      const message = err instanceof ApiError ? err.message : "Could not create the part.";
      if (err instanceof ApiError && err.field) setFieldErrors({ [err.field]: message });
      setError(message);
    }
  }

  async function createDrawer() {
    setDrawerError(null);
    const drawerNumber = Number(newNumber);
    if (!Number.isInteger(drawerNumber) || drawerNumber <= 0) {
      setDrawerError("Enter a whole number greater than zero.");
      return;
    }
    try {
      const created = await api<SlotDetail>("/api/v1/slots", {
        method: "POST",
        body: JSON.stringify({ slot_number: drawerNumber, label: newLabel.trim() || null }),
      });
      const summary: SlotSummary = {
        id: created.id,
        slot_number: created.slot_number,
        label: created.label,
        location: created.location,
        total_units: created.total_units,
        part_count: created.items.length,
        archived_at: created.archived_at,
      };
      setDrawers((current) => [...current, summary].sort((left, right) => left.slot_number - right.slot_number));
      setRows((current) => {
        const next = [...current];
        const target = next.findIndex((row) => !row.slot);
        if (target === -1) {
          next.push({ slot: String(created.slot_number), quantity: "" });
          return next;
        }
        next[target] = { ...next[target], slot: String(created.slot_number) };
        return next;
      });
      setNewNumber("");
      setNewLabel("");
      setCreatingDrawer(false);
      setNotice(`Drawer ${created.slot_number} created. The part form was kept.`);
    } catch (err) {
      setDrawerError(err instanceof ApiError ? err.message : "Could not create the drawer.");
    }
  }

  return (
    <form className="card stack" onSubmit={onSubmit}>
      <h2>New part</h2>
      <p className="muted">The baseline is the alert reference. Drawer quantities are the physical stock and do not change the baseline.</p>
      <Notice message={notice} />
      <ErrorNote message={error} />
      <div className="row">
        <label className="field">
          Name
          <input aria-label="New part name" value={name} onChange={(event) => setName(event.target.value)} required />
        </label>
        <label className="field">
          SKU
          <input aria-label="New part SKU" value={sku} onChange={(event) => setSku(event.target.value)} />
          <FieldError message={fieldErrors.sku} />
        </label>
        <label className="field">
          Baseline
          <input aria-label="Baseline quantity" inputMode="numeric" value={baseline} onChange={(event) => setBaseline(event.target.value)} />
          <FieldError message={baseline.trim() && !baselineOk ? "Enter a whole number of zero or more." : null} />
        </label>
        <label className="field">
          Category
          <select aria-label="New part category" value={categoryId} onChange={(event) => setCategoryId(event.target.value)}>
            <option value="">None</option>
            {categories.map((item) => (
              <option key={item.id} value={item.id}>
                {item.name}
              </option>
            ))}
          </select>
        </label>
      </div>
      <div className="stack">
        <h3>Drawers</h3>
        {rows.length === 0 ? <p className="muted">Leave this empty to create the part without stock.</p> : null}
        {drawers.length === 0 ? <p>No drawers exist yet. Create a drawer to assign this part.</p> : null}
        {rows.map((row, index) => (
          <div className="row" key={`allocation-${index}`}>
            <DrawerSelect
              label={`Allocate to drawer ${index + 1}`}
              value={row.slot}
              slots={drawers}
              exclude={chosenNumbers(index)}
              announceEmpty={false}
              error={allocationProblems[index] && row.slot ? null : allocationProblems[index]}
              onChange={(slot) =>
                setRows((current) => current.map((item, itemIndex) => (itemIndex === index ? { ...item, slot } : item)))
              }
            />
            <label className="field">
              Allocate quantity
              <input
                aria-label={`Allocation quantity ${index + 1}`}
                inputMode="numeric"
                value={row.quantity}
                onChange={(event) =>
                  setRows((current) => current.map((item, itemIndex) => (itemIndex === index ? { ...item, quantity: event.target.value } : item)))
                }
              />
              <FieldError message={row.slot ? allocationProblems[index] : null} />
            </label>
            <button
              type="button"
              onClick={() => setRows((current) => current.filter((_, itemIndex) => itemIndex !== index))}
            >
              Remove drawer
            </button>
          </div>
        ))}
        <div className="actions">
          <button type="button" onClick={() => setRows((current) => [...current, { slot: "", quantity: "" }])}>
            Add drawer
          </button>
          <button type="button" onClick={() => setCreatingDrawer(true)}>
            Create Drawer
          </button>
        </div>
      </div>
      {creatingDrawer ? (
        <div className="modal-backdrop">
          <div className="modal stack" role="dialog" aria-modal="true" aria-labelledby="inline-drawer-title">
            <h2 id="inline-drawer-title">Create Drawer</h2>
            <p className="muted">The part name and other fields stay as you entered them.</p>
            <ErrorNote message={drawerError} />
            <label className="field">
              Number
              <input aria-label="Inline drawer number" inputMode="numeric" value={newNumber} onChange={(event) => setNewNumber(event.target.value)} />
            </label>
            <label className="field">
              Label
              <input aria-label="Inline drawer label" value={newLabel} onChange={(event) => setNewLabel(event.target.value)} />
            </label>
            <div className="actions">
              <button type="button" onClick={() => setCreatingDrawer(false)}>
                Cancel
              </button>
              <button type="button" className="btn-primary" disabled={!newNumber.trim()} onClick={() => void createDrawer()}>
                Create drawer
              </button>
            </div>
          </div>
        </div>
      ) : null}
      <button className="btn-primary" type="submit" disabled={!name.trim() || !baselineOk || !allocationsReady}>
        Create part
      </button>
    </form>
  );
}
