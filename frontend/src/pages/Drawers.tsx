import { FormEvent, useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { DrawerSelect } from "../components/DrawerSelect";
import { ErrorNote, FieldError, Loading, Notice } from "../components/Feedback";
import { useLoad } from "../hooks/useLoad";
import { api, ApiError, loadDrawers } from "../services/api";
import type { Page, SlotDetail, SlotSummary } from "../types";

export function DrawersPage() {
  const [params, setParams] = useSearchParams();
  const search = params.get("search") ?? "";
  const [draft, setDraft] = useState(search);
  const [number, setNumber] = useState("");
  const [label, setLabel] = useState("");
  const [location, setLocation] = useState("");
  const [description, setDescription] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [numberError, setNumberError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [editing, setEditing] = useState<SlotDetail | null>(null);
  const [contents, setContents] = useState<SlotDetail | null>(null);
  const [pendingDelete, setPendingDelete] = useState<SlotSummary | null>(null);
  const [busy, setBusy] = useState(false);
  const page = useLoad(
    () => api<Page<SlotSummary>>(`/api/v1/slots?limit=100${search ? `&search=${encodeURIComponent(search)}` : ""}`),
    [search],
  );

  function onSearch(event: FormEvent) {
    event.preventDefault();
    const next = new URLSearchParams();
    if (draft.trim()) next.set("search", draft.trim());
    setParams(next);
  }

  async function create(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setNumberError(null);
    setNotice(null);
    const drawerNumber = Number(number);
    if (!Number.isInteger(drawerNumber) || drawerNumber <= 0) {
      setNumberError("Enter a whole number greater than zero.");
      return;
    }
    try {
      const created = await api<SlotDetail>("/api/v1/slots", {
        method: "POST",
        body: JSON.stringify({
          slot_number: drawerNumber,
          label: label.trim() || null,
          location: location.trim() || null,
          description: description.trim() || null,
        }),
      });
      setNumber("");
      setLabel("");
      setLocation("");
      setDescription("");
      setNotice(`Drawer ${created.slot_number} created.`);
      page.reload();
    } catch (err) {
      const message = err instanceof ApiError ? err.message : "Could not create the drawer.";
      if (err instanceof ApiError && err.field === "slot_number") setNumberError(message);
      else setError(message);
    }
  }

  async function openEditor(slotNumber: number) {
    setError(null);
    setNotice(null);
    try {
      setEditing(await api<SlotDetail>(`/api/v1/slots/${slotNumber}`));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not open that drawer.");
    }
  }

  async function openContents(slotNumber: number) {
    setError(null);
    try {
      setContents(await api<SlotDetail>(`/api/v1/slots/${slotNumber}`));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not open that drawer.");
    }
  }

  function askDelete(slot: SlotSummary) {
    setNotice(null);
    if (slot.part_count > 0 || slot.total_units > 0) {
      setError(`Drawer ${slot.slot_number} still contains parts. Transfer or remove them before deleting it.`);
      return;
    }
    setError(null);
    setPendingDelete(slot);
  }

  async function confirmDelete() {
    if (!pendingDelete) return;
    setBusy(true);
    setError(null);
    try {
      await api(`/api/v1/slots/${pendingDelete.slot_number}`, { method: "DELETE", body: JSON.stringify({}) });
      setNotice("Drawer deleted successfully.");
      setPendingDelete(null);
      page.reload();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not delete the drawer.");
      setPendingDelete(null);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="stack">
      <h1>Drawers</h1>
      <form className="row" onSubmit={onSearch}>
        <label className="field">
          Drawer number
          <input aria-label="Search drawers" inputMode="numeric" value={draft} onChange={(event) => setDraft(event.target.value)} />
        </label>
        <button type="submit">Open</button>
      </form>
      <Notice message={notice} />
      <ErrorNote message={error || page.error} />
      {page.loading ? <Loading /> : null}
      <div className="table-wrap">
        <table className="responsive">
          <thead>
            <tr>
              <th>Drawer</th>
              <th>Label</th>
              <th>Location</th>
              <th>Parts</th>
              <th>Units</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {(page.data?.items ?? []).map((slot) => (
              <tr key={slot.id}>
                <td data-label="Drawer">
                  <Link to={`/drawers/${slot.slot_number}`}>{slot.slot_number}</Link>
                  {slot.archived_at ? " (archived)" : ""}
                </td>
                <td data-label="Label">{slot.label || "—"}</td>
                <td data-label="Location">{slot.location || "—"}</td>
                <td className="num" data-label="Parts">
                  {slot.part_count}
                </td>
                <td className="num" data-label="Units">
                  {slot.total_units}
                </td>
                <td data-label="Actions">
                  <div className="actions">
                    <button type="button" onClick={() => void openEditor(slot.slot_number)}>
                      Edit
                    </button>
                    <button type="button" onClick={() => void openContents(slot.slot_number)}>
                      View Contents
                    </button>
                    <button type="button" className="btn-danger" onClick={() => askDelete(slot)}>
                      Delete
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <form className="card stack" onSubmit={create}>
        <h2>New drawer</h2>
        <div className="row">
          <label className="field">
            Number
            <input aria-label="New drawer number" inputMode="numeric" value={number} onChange={(event) => setNumber(event.target.value)} required />
            <FieldError message={numberError} />
          </label>
          <label className="field">
            Label
            <input aria-label="Drawer label" value={label} onChange={(event) => setLabel(event.target.value)} />
          </label>
          <label className="field">
            Location
            <input aria-label="Drawer location" value={location} onChange={(event) => setLocation(event.target.value)} />
          </label>
          <label className="field">
            Description
            <input aria-label="Drawer description" value={description} onChange={(event) => setDescription(event.target.value)} />
          </label>
        </div>
        <button className="btn-primary" type="submit" disabled={!number.trim()}>
          Create drawer
        </button>
      </form>
      {editing ? (
        <EditDrawer
          slot={editing}
          onCancel={() => setEditing(null)}
          onSaved={(updated) => {
            setEditing(null);
            setNotice(`Drawer ${updated.slot_number} saved.`);
            page.reload();
          }}
        />
      ) : null}
      {contents ? (
        <ContentsDrawer
          slot={contents}
          onClose={() => setContents(null)}
          onChanged={async (message) => {
            setNotice(message);
            page.reload();
            setContents(await api<SlotDetail>(`/api/v1/slots/${contents.slot_number}`).catch(() => contents));
          }}
        />
      ) : null}
      {pendingDelete ? (
        <div className="modal-backdrop">
          <div className="modal stack" role="dialog" aria-modal="true" aria-labelledby="delete-drawer-title">
            <h2 id="delete-drawer-title">Delete drawer {pendingDelete.slot_number}?</h2>
            <p>This removes the empty drawer. Parts and transaction history stay.</p>
            <div className="actions">
              <button type="button" onClick={() => setPendingDelete(null)} disabled={busy}>
                Cancel
              </button>
              <button type="button" className="btn-danger" onClick={() => void confirmDelete()} disabled={busy}>
                {busy ? "Deleting…" : "Confirm delete"}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function EditDrawer({
  slot,
  onCancel,
  onSaved,
}: {
  slot: SlotDetail;
  onCancel: () => void;
  onSaved: (slot: SlotDetail) => void;
}) {
  const [number, setNumber] = useState(String(slot.slot_number));
  const [label, setLabel] = useState(slot.label ?? "");
  const [location, setLocation] = useState(slot.location ?? "");
  const [description, setDescription] = useState(slot.description ?? "");
  const [error, setError] = useState<string | null>(null);
  const [numberError, setNumberError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const unchanged =
    number === String(slot.slot_number) &&
    label === (slot.label ?? "") &&
    location === (slot.location ?? "") &&
    description === (slot.description ?? "");

  async function save(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setNumberError(null);
    const drawerNumber = Number(number);
    if (!Number.isInteger(drawerNumber) || drawerNumber <= 0) {
      setNumberError("Enter a whole number greater than zero.");
      return;
    }
    setBusy(true);
    try {
      const updated = await api<SlotDetail>(`/api/v1/slots/${slot.slot_number}`, {
        method: "PATCH",
        body: JSON.stringify({
          slot_number: drawerNumber,
          label: label.trim() || null,
          location: location.trim() || null,
          description: description.trim() || null,
        }),
      });
      onSaved(updated);
    } catch (err) {
      const message = err instanceof ApiError ? err.message : "Could not update the drawer.";
      if (err instanceof ApiError && err.field === "slot_number") setNumberError(message);
      else setError(message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="modal-backdrop">
      <form className="modal stack" role="dialog" aria-modal="true" aria-labelledby="edit-drawer-title" onSubmit={save}>
        <h2 id="edit-drawer-title">Edit drawer {slot.slot_number}</h2>
        <p className="muted">Changing the number keeps this drawer and its stock. History keeps the previous number.</p>
        <ErrorNote message={error} />
        <label className="field">
          Number
          <input aria-label="Edit drawer number" inputMode="numeric" value={number} onChange={(event) => setNumber(event.target.value)} required />
          <FieldError message={numberError} />
        </label>
        <label className="field">
          Label
          <input aria-label="Edit label" value={label} onChange={(event) => setLabel(event.target.value)} />
        </label>
        <label className="field">
          Description
          <input aria-label="Edit description" value={description} onChange={(event) => setDescription(event.target.value)} />
        </label>
        <label className="field">
          Location
          <input aria-label="Edit location" value={location} onChange={(event) => setLocation(event.target.value)} />
        </label>
        <div className="actions">
          <button type="button" onClick={onCancel} disabled={busy}>
            Cancel
          </button>
          <button className="btn-primary" type="submit" disabled={busy || unchanged || !number.trim()}>
            {busy ? "Saving…" : "Save drawer"}
          </button>
        </div>
      </form>
    </div>
  );
}

function ContentsDrawer({
  slot,
  onClose,
  onChanged,
}: {
  slot: SlotDetail;
  onClose: () => void;
  onChanged: (message: string) => Promise<void>;
}) {
  const [drawers, setDrawers] = useState<SlotSummary[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [moves, setMoves] = useState<Record<string, { destination: string; quantity: string }>>({});
  const [removals, setRemovals] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let live = true;
    loadDrawers()
      .then((rows) => {
        if (live) setDrawers(rows);
      })
      .catch((err: unknown) => {
        if (live) setError(err instanceof ApiError ? err.message : "Could not load drawers.");
      });
    return () => {
      live = false;
    };
  }, []);

  async function move(partId: string, available: number) {
    const draft = moves[partId] ?? { destination: "", quantity: "" };
    const quantity = Number(draft.quantity);
    if (!draft.destination) {
      setError("Select a destination drawer.");
      return;
    }
    if (!Number.isInteger(quantity) || quantity <= 0) {
      setError("Enter a whole number greater than zero.");
      return;
    }
    if (quantity > available) {
      setError(`Only ${available} are available.`);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await api("/api/v1/stock/transfer", {
        method: "POST",
        body: JSON.stringify({
          part_id: partId,
          from_slot: slot.slot_number,
          to_slot: Number(draft.destination),
          quantity,
          reason: "Moved from the drawers page",
        }),
      });
      await onChanged(`Moved ${quantity} from drawer ${slot.slot_number}.`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not move that part.");
    } finally {
      setBusy(false);
    }
  }

  async function remove(partId: string, available: number) {
    const quantity = Number(removals[partId] ?? "");
    if (!Number.isInteger(quantity) || quantity <= 0) {
      setError("Enter a whole number greater than zero.");
      return;
    }
    if (quantity > available) {
      setError(`Only ${available} are available.`);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await api("/api/v1/stock/remove", {
        method: "POST",
        body: JSON.stringify({
          part_id: partId,
          slot_number: slot.slot_number,
          quantity,
          reason: "Removed from the drawers page",
        }),
      });
      await onChanged(`Removed ${quantity} from drawer ${slot.slot_number}.`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not remove that part.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="modal-backdrop">
      <div className="modal stack" role="dialog" aria-modal="true" aria-labelledby="contents-title">
        <h2 id="contents-title">Drawer {slot.slot_number}</h2>
        <p className="muted">
          {slot.label || "No label"} · {slot.location || "No location"} · {slot.total_units} units
        </p>
        <ErrorNote message={error} />
        {slot.items.length === 0 ? <p className="muted">This drawer is empty.</p> : null}
        {slot.items.map((item) => {
          const moveDraft = moves[item.part_id] ?? { destination: "", quantity: "" };
          const removal = removals[item.part_id] ?? "";
          return (
            <section key={item.part_id} className="card stack">
              <p>
                <Link to={`/inventory/${item.part_id}`}>{item.name}</Link>
                {item.sku ? ` · ${item.sku}` : ""} · Available: {item.quantity} {item.unit}
              </p>
              <div className="row">
                <DrawerSelect
                  label="Move to"
                  value={moveDraft.destination}
                  slots={drawers}
                  exclude={[String(slot.slot_number)]}
                  onChange={(destination) =>
                    setMoves((current) => ({ ...current, [item.part_id]: { ...moveDraft, destination } }))
                  }
                />
                <label className="field">
                  Move quantity
                  <input
                    aria-label={`Move quantity for ${item.name}`}
                    inputMode="numeric"
                    value={moveDraft.quantity}
                    onChange={(event) =>
                      setMoves((current) => ({
                        ...current,
                        [item.part_id]: { ...moveDraft, quantity: event.target.value },
                      }))
                    }
                  />
                </label>
                <button type="button" disabled={busy || !moveDraft.destination || !moveDraft.quantity.trim()} onClick={() => void move(item.part_id, item.quantity)}>
                  Move
                </button>
              </div>
              <div className="row">
                <label className="field">
                  Remove quantity
                  <input
                    aria-label={`Remove quantity for ${item.name}`}
                    inputMode="numeric"
                    value={removal}
                    onChange={(event) => setRemovals((current) => ({ ...current, [item.part_id]: event.target.value }))}
                  />
                </label>
                <button type="button" className="btn-danger" disabled={busy || !removal.trim()} onClick={() => void remove(item.part_id, item.quantity)}>
                  Remove
                </button>
              </div>
            </section>
          );
        })}
        <div className="actions">
          <Link to={`/drawers/${slot.slot_number}`}>Open drawer page</Link>
          <button type="button" onClick={onClose}>
            Close
          </button>
        </div>
      </div>
    </div>
  );
}
