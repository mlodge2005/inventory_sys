import { FormEvent, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { ErrorNote, Loading, drawerList } from "../components/Feedback";
import { StatusBadge } from "../components/StatusBadge";
import { useLoad } from "../hooks/useLoad";
import { api, itemsQuery } from "../services/api";
import type { Category, Page, Part } from "../types";

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
  const [name, setName] = useState("");
  const [sku, setSku] = useState("");
  const [baseline, setBaseline] = useState("0");
  const [categoryId, setCategoryId] = useState("");
  const [slot, setSlot] = useState("");
  const [qty, setQty] = useState("");

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    const initial = Number(baseline);
    if (!Number.isInteger(initial) || initial < 0) {
      setError("Baseline must be a whole number.");
      return;
    }
    const body: Record<string, unknown> = {
      name: name.trim(),
      sku: sku.trim() || null,
      initial_quantity: initial,
      category_id: categoryId || null,
    };
    if (slot && qty) {
      const quantity = Number(qty);
      if (!Number.isInteger(quantity) || quantity <= 0) {
        setError("Allocation quantity must be a positive whole number.");
        return;
      }
      body.allocations = [{ slot_number: Number(slot), quantity }];
    }
    try {
      await api("/api/v1/items", { method: "POST", body: JSON.stringify(body) });
      setName("");
      setSku("");
      setSlot("");
      setQty("");
      onCreated();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create the part.");
    }
  }

  return (
    <form className="card stack" onSubmit={onSubmit}>
      <h2>New part</h2>
      <ErrorNote message={error} />
      <div className="row">
        <label className="field">
          Name
          <input aria-label="New part name" value={name} onChange={(event) => setName(event.target.value)} required />
        </label>
        <label className="field">
          SKU
          <input aria-label="New part SKU" value={sku} onChange={(event) => setSku(event.target.value)} />
        </label>
        <label className="field">
          Baseline
          <input aria-label="Baseline quantity" inputMode="numeric" value={baseline} onChange={(event) => setBaseline(event.target.value)} />
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
        <label className="field">
          Allocate to drawer
          <input aria-label="Allocation drawer" inputMode="numeric" value={slot} onChange={(event) => setSlot(event.target.value)} />
        </label>
        <label className="field">
          Allocate quantity
          <input aria-label="Allocation quantity" inputMode="numeric" value={qty} onChange={(event) => setQty(event.target.value)} />
        </label>
      </div>
      <button className="btn-primary" type="submit">
        Create part
      </button>
    </form>
  );
}
