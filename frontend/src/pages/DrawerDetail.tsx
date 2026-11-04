import { FormEvent, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ErrorNote, FieldError, Loading, Notice } from "../components/Feedback";
import { StockForm } from "../components/StockForm";
import { useLoad } from "../hooks/useLoad";
import { api, ApiError } from "../services/api";
import type { SlotDetail } from "../types";

export function DrawerDetailPage() {
  const { slotNumber = "" } = useParams();
  const navigate = useNavigate();
  const slot = useLoad(() => api<SlotDetail>(`/api/v1/slots/${slotNumber}`), [slotNumber]);
  const [number, setNumber] = useState("");
  const [label, setLabel] = useState("");
  const [location, setLocation] = useState("");
  const [description, setDescription] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [numberError, setNumberError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const loaded = slot.data;

  useEffect(() => {
    if (!loaded) return;
    setNumber(String(loaded.slot_number));
    setLabel(loaded.label ?? "");
    setLocation(loaded.location ?? "");
    setDescription(loaded.description ?? "");
  }, [loaded]);

  function cancelEdits() {
    if (!loaded) return;
    setNumber(String(loaded.slot_number));
    setLabel(loaded.label ?? "");
    setLocation(loaded.location ?? "");
    setDescription(loaded.description ?? "");
    setError(null);
    setNumberError(null);
  }

  async function save(event: FormEvent) {
    event.preventDefault();
    if (!loaded) return;
    setError(null);
    setNumberError(null);
    setNotice(null);
    const drawerNumber = Number(number);
    if (!Number.isInteger(drawerNumber) || drawerNumber <= 0) {
      setNumberError("Enter a whole number greater than zero.");
      return;
    }
    try {
      const updated = await api<SlotDetail>(`/api/v1/slots/${loaded.slot_number}`, {
        method: "PATCH",
        body: JSON.stringify({
          slot_number: drawerNumber,
          label: label.trim() || null,
          location: location.trim() || null,
          description: description.trim() || null,
        }),
      });
      setNotice(`Drawer ${updated.slot_number} saved.`);
      if (updated.slot_number !== loaded.slot_number) {
        navigate(`/drawers/${updated.slot_number}`, { replace: true });
      } else {
        slot.reload();
      }
    } catch (err) {
      const message = err instanceof ApiError ? err.message : "Could not update the drawer.";
      if (err instanceof ApiError && err.field === "slot_number") setNumberError(message);
      else setError(message);
    }
  }

  async function archive() {
    if (!loaded) return;
    setError(null);
    setNotice(null);
    try {
      await api(`/api/v1/slots/${loaded.slot_number}/archive`, {
        method: "POST",
        body: JSON.stringify({ confirm_remove_stock: false, reason: "Archived from the website" }),
      });
      setNotice(`Drawer ${loaded.slot_number} archived.`);
      slot.reload();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Archive failed.");
    }
  }

  async function remove() {
    if (!loaded) return;
    if (loaded.total_units > 0) {
      setError(`Drawer ${loaded.slot_number} still contains parts. Transfer or remove them before deleting it.`);
      setConfirmDelete(false);
      return;
    }
    setError(null);
    try {
      await api(`/api/v1/slots/${loaded.slot_number}`, {
        method: "DELETE",
        body: JSON.stringify({ confirm_remove_stock: false, reason: "Deleted from the website" }),
      });
      navigate("/drawers");
    } catch (err) {
      setConfirmDelete(false);
      setError(err instanceof ApiError ? err.message : "Delete failed.");
    }
  }

  if (slot.loading && !loaded) return <Loading />;
  if (!loaded) return <ErrorNote message={slot.error || "Drawer not found."} />;
  const dirty =
    number !== String(loaded.slot_number) ||
    label !== (loaded.label ?? "") ||
    location !== (loaded.location ?? "") ||
    description !== (loaded.description ?? "");

  return (
    <div className="stack">
      <p>
        <Link to="/drawers">Drawers</Link>
      </p>
      <h1>Drawer {loaded.slot_number}</h1>
      <p className="muted">
        {loaded.label || "No label"} · {loaded.location || "No location"} · {loaded.total_units} units
        {loaded.archived_at ? " · archived" : ""}
      </p>
      <Notice message={notice} />
      <ErrorNote message={error || slot.error} />
      <div className="table-wrap">
        <table className="responsive">
          <thead>
            <tr>
              <th>Part</th>
              <th>SKU</th>
              <th>Quantity</th>
            </tr>
          </thead>
          <tbody>
            {loaded.items.map((item) => (
              <tr key={item.part_id}>
                <td data-label="Part">
                  <Link to={`/inventory/${item.part_id}`}>{item.name}</Link>
                </td>
                <td data-label="SKU">{item.sku || "—"}</td>
                <td className="num" data-label="Quantity">
                  {item.quantity} {item.unit}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {loaded.items.length === 0 ? <p className="muted">This drawer is empty.</p> : null}
      <section className="card stack">
        <h2>Stock in this drawer</h2>
        <StockForm
          presetSlot={loaded.slot_number}
          presetPartId={loaded.items.length === 1 ? loaded.items[0].part_id : undefined}
          onDone={() => {
            setNotice("Stock updated.");
            slot.reload();
          }}
        />
      </section>
      <form className="card stack" onSubmit={save}>
        <h2>Edit drawer</h2>
        <p className="muted">Changing the number keeps the same drawer and its stock. History stores the old number.</p>
        <div className="row">
          <label className="field">
            Number
            <input aria-label="New drawer number" inputMode="numeric" value={number} onChange={(event) => setNumber(event.target.value)} />
            <FieldError message={numberError} />
          </label>
          <label className="field">
            Label
            <input aria-label="Edit label" value={label} onChange={(event) => setLabel(event.target.value)} />
          </label>
          <label className="field">
            Location
            <input aria-label="Edit location" value={location} onChange={(event) => setLocation(event.target.value)} />
          </label>
          <label className="field">
            Description
            <input aria-label="Edit description" value={description} onChange={(event) => setDescription(event.target.value)} />
          </label>
        </div>
        <div className="actions">
          <button type="button" onClick={cancelEdits} disabled={!dirty}>
            Cancel
          </button>
          <button className="btn-primary" type="submit" disabled={!dirty || !number.trim()}>
            Save drawer
          </button>
        </div>
      </form>
      <section className="card stack">
        <h2>Archive or delete</h2>
        <p className="note">Transfer or remove the parts in this drawer before deleting it. Those changes are written to the transaction log.</p>
        <div className="actions">
          <button type="button" onClick={() => void archive()} disabled={Boolean(loaded.archived_at)}>
            Archive
          </button>
          <button type="button" className="btn-danger" onClick={() => setConfirmDelete(true)}>
            Delete
          </button>
        </div>
      </section>
      {confirmDelete ? (
        <div className="modal-backdrop">
          <div className="modal stack" role="dialog" aria-modal="true" aria-labelledby="detail-delete-title">
            <h2 id="detail-delete-title">Delete drawer {loaded.slot_number}?</h2>
            <p>
              {loaded.total_units > 0
                ? `Drawer ${loaded.slot_number} still contains parts. Transfer or remove them before deleting it.`
                : "This removes the empty drawer. Transaction history stays."}
            </p>
            <div className="actions">
              <button type="button" onClick={() => setConfirmDelete(false)}>
                Cancel
              </button>
              <button type="button" className="btn-danger" onClick={() => void remove()} disabled={loaded.total_units > 0}>
                Confirm delete
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
