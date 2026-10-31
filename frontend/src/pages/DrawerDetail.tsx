import { FormEvent, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ErrorNote, Loading } from "../components/Feedback";
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
  const [confirm, setConfirm] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const loaded = slot.data;

  async function save(event: FormEvent) {
    event.preventDefault();
    if (!loaded) return;
    setError(null);
    const body: Record<string, unknown> = {
      label: label || loaded.label,
      location: location || loaded.location,
      description: description || loaded.description,
    };
    if (number.trim()) body.slot_number = Number(number);
    try {
      const updated = await api<SlotDetail>(`/api/v1/slots/${loaded.slot_number}`, {
        method: "PATCH",
        body: JSON.stringify(body),
      });
      if (updated.slot_number !== loaded.slot_number) {
        navigate(`/drawers/${updated.slot_number}`, { replace: true });
      } else {
        slot.reload();
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not update the drawer.");
    }
  }

  async function archive() {
    if (!loaded) return;
    setError(null);
    try {
      await api(`/api/v1/slots/${loaded.slot_number}/archive`, {
        method: "POST",
        body: JSON.stringify({ confirm_remove_stock: confirm, reason: "Archived from the website" }),
      });
      slot.reload();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Archive failed.");
    }
  }

  async function remove() {
    if (!loaded) return;
    setError(null);
    try {
      await api(`/api/v1/slots/${loaded.slot_number}`, {
        method: "DELETE",
        body: JSON.stringify({ confirm_remove_stock: confirm, reason: "Deleted from the website" }),
      });
      navigate("/drawers");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Delete failed. Move or explicitly remove the stock first.");
    }
  }

  if (slot.loading && !loaded) return <Loading />;
  if (!loaded) return <ErrorNote message={slot.error || "Drawer not found."} />;

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
          onDone={slot.reload}
        />
      </section>
      <form className="card stack" onSubmit={save}>
        <h2>Rename and details</h2>
        <p className="muted">Changing the number keeps the same drawer and its stock. History stores the old number.</p>
        <div className="row">
          <label className="field">
            New number
            <input aria-label="New drawer number" inputMode="numeric" value={number} onChange={(event) => setNumber(event.target.value)} placeholder={String(loaded.slot_number)} />
          </label>
          <label className="field">
            Label
            <input aria-label="Edit label" value={label} placeholder={loaded.label || ""} onChange={(event) => setLabel(event.target.value)} />
          </label>
          <label className="field">
            Location
            <input aria-label="Edit location" value={location} placeholder={loaded.location || ""} onChange={(event) => setLocation(event.target.value)} />
          </label>
          <label className="field">
            Description
            <input aria-label="Edit description" value={description} placeholder={loaded.description || ""} onChange={(event) => setDescription(event.target.value)} />
          </label>
        </div>
        <button type="submit">Save drawer</button>
      </form>
      <section className="card stack">
        <h2>Archive or delete</h2>
        <p className="note">
          A drawer that still holds parts is not removed quietly. Check the box only when you want those quantities
          removed and written to the transaction log.
        </p>
        <label className="field">
          <span>
            <input type="checkbox" checked={confirm} onChange={(event) => setConfirm(event.target.checked)} /> Record
            removal of remaining stock
          </span>
        </label>
        <div className="actions">
          <button type="button" onClick={() => void archive()}>
            Archive
          </button>
          <button type="button" className="btn-danger" onClick={() => void remove()}>
            Delete drawer
          </button>
        </div>
      </section>
    </div>
  );
}
