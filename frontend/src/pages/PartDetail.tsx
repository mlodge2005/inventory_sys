import { FormEvent, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ErrorNote, Loading, drawerList, formatWhen } from "../components/Feedback";
import { StatusBadge } from "../components/StatusBadge";
import { StockForm } from "../components/StockForm";
import { useLoad } from "../hooks/useLoad";
import { api, ApiError } from "../services/api";
import type { AuditEvent, Page, Part, Transaction } from "../types";

export function PartDetailPage() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const part = useLoad(() => api<Part>(`/api/v1/items/${id}`), [id]);
  const history = useLoad(
    () => api<Page<Transaction>>(`/api/v1/items/${id}/transactions?limit=50`),
    [id],
  );
  const audit = useLoad(() => api<AuditEvent[]>(`/api/v1/items/${id}/audit`), [id]);
  const [error, setError] = useState<string | null>(null);

  async function patch(body: Record<string, unknown>) {
    setError(null);
    try {
      await api(`/api/v1/items/${id}`, { method: "PATCH", body: JSON.stringify(body) });
      part.reload();
      audit.reload();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Update failed.");
    }
  }

  async function archive(confirm: boolean) {
    setError(null);
    try {
      await api(`/api/v1/items/${id}/archive`, {
        method: "POST",
        body: JSON.stringify({ confirm_remove_stock: confirm, reason: "Archived from the website" }),
      });
      part.reload();
      history.reload();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Archive failed.");
    }
  }

  if (part.loading && !part.data) return <Loading />;
  if (!part.data) return <ErrorNote message={part.error || "Part not found."} />;
  const item = part.data;

  return (
    <div className="stack">
      <p>
        <Link to="/inventory">Parts</Link>
      </p>
      <h1>{item.name}</h1>
      <ErrorNote message={error || part.error} />
      <div className="stat-grid">
        <div className="stat-card">
          <strong>{item.current_quantity}</strong>
          <span>On hand ({item.unit})</span>
        </div>
        <div className="stat-card">
          <strong>{item.initial_quantity}</strong>
          <span>Fixed baseline</span>
        </div>
        <div className="stat-card">
          <strong>{item.threshold_configured ? item.threshold : "—"}</strong>
          <span>{item.baseline_state === "BASELINE_NOT_SET" ? "Baseline not set" : "Alert at or below"}</span>
        </div>
        <div className="stat-card">
          <StatusBadge status={item.status} />
          <span>{item.sku || "No SKU"}</span>
        </div>
      </div>
      <p className="note">
        Physical stock is the sum of drawer allocations ({drawerList(item.slots)}). Adding pieces never rewrites the
        baseline. Threshold uses the override when set, otherwise the ceiling of baseline × {item.low_stock_percent}%.
      </p>
      <section className="card stack">
        <h2>Details</h2>
        <p>{item.description || "No description."}</p>
        <p className="muted">
          {item.category?.name || "Uncategorized"}
          {item.manufacturer ? ` · ${item.manufacturer}` : ""}
          {item.manufacturer_part_number ? ` · ${item.manufacturer_part_number}` : ""}
        </p>
        {Object.keys(item.specifications || {}).length ? (
          <pre>{JSON.stringify(item.specifications, null, 2)}</pre>
        ) : (
          <p className="muted">No technical specifications.</p>
        )}
        {item.notes ? <p>{item.notes}</p> : null}
      </section>
      <section className="card stack">
        <h2>Drawers</h2>
        {item.slots.length === 0 ? <p className="muted">Not allocated to a drawer yet.</p> : null}
        <ul>
          {item.slots.map((slot) => (
            <li key={slot.slot_id}>
              <Link to={`/drawers/${slot.slot_number}`}>Drawer {slot.slot_number}</Link> — {slot.quantity} {item.unit}
              {slot.label ? ` (${slot.label})` : ""}
            </li>
          ))}
        </ul>
      </section>
      <section className="card stack">
        <h2>Change stock</h2>
        <StockForm
          presetPartId={item.id}
          presetSlot={item.slots[0]?.slot_number}
          onDone={() => {
            part.reload();
            history.reload();
          }}
        />
      </section>
      <BaselineForm item={item} onSave={patch} />
      <section className="stack">
        <h2>Stock history</h2>
        <ErrorNote message={history.error} />
        <TransactionTable rows={history.data?.items ?? []} />
      </section>
      <section className="stack">
        <h2>Baseline audit</h2>
        {(audit.data ?? []).length === 0 ? <p className="muted">No baseline edits yet.</p> : null}
        <ul>
          {(audit.data ?? []).map((event) => (
            <li key={event.id}>
              {formatWhen(event.created_at)} — {event.action} ({event.source})
            </li>
          ))}
        </ul>
      </section>
      <div className="actions">
        {item.archived_at ? (
          <button type="button" onClick={() => void api(`/api/v1/items/${id}/unarchive`, { method: "POST" }).then(() => part.reload())}>
            Unarchive
          </button>
        ) : (
          <>
            <button type="button" onClick={() => void archive(false)}>
              Archive if empty
            </button>
            <button type="button" className="btn-danger" onClick={() => void archive(true)}>
              Remove stock and archive
            </button>
          </>
        )}
        <button
          type="button"
          className="btn-danger"
          onClick={() => {
            if (!window.confirm("Delete this part? Parts with history must be archived instead.")) return;
            api(`/api/v1/items/${id}`, { method: "DELETE" })
              .then(() => navigate("/inventory"))
              .catch((err: unknown) => setError(err instanceof ApiError ? err.message : "Delete failed."));
          }}
        >
          Delete
        </button>
      </div>
    </div>
  );
}

function BaselineForm({
  item,
  onSave,
}: {
  item: Part;
  onSave: (body: Record<string, unknown>) => Promise<void>;
}) {
  const [initial, setInitial] = useState(String(item.initial_quantity));
  const [percent, setPercent] = useState(String(item.low_stock_percent));
  const [override, setOverride] = useState(item.low_stock_override === null ? "" : String(item.low_stock_override));

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    const body: Record<string, unknown> = {
      initial_quantity: Number(initial),
      low_stock_percent: Number(percent),
      low_stock_override: override.trim() === "" ? null : Number(override),
    };
    void onSave(body);
  }

  return (
    <form className="card stack" onSubmit={onSubmit}>
      <h2>Alert settings</h2>
      <p className="muted">These edits are audited. They do not move physical stock.</p>
      <div className="row">
        <label className="field">
          Baseline
          <input aria-label="Edit baseline" inputMode="numeric" value={initial} onChange={(event) => setInitial(event.target.value)} />
        </label>
        <label className="field">
          Low-stock percent
          <input aria-label="Low-stock percent" inputMode="numeric" value={percent} onChange={(event) => setPercent(event.target.value)} />
        </label>
        <label className="field">
          Absolute override
          <input aria-label="Threshold override" inputMode="numeric" value={override} onChange={(event) => setOverride(event.target.value)} placeholder="Blank uses percent" />
        </label>
      </div>
      <button type="submit">Save alert settings</button>
    </form>
  );
}

function TransactionTable({ rows }: { rows: Transaction[] }) {
  if (!rows.length) return <p className="muted">No stock movements yet.</p>;
  return (
    <div className="table-wrap">
      <table className="responsive">
        <thead>
          <tr>
            <th>When</th>
            <th>Type</th>
            <th>Drawer before</th>
            <th>Drawer after</th>
            <th>Source</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.id}>
              <td data-label="When">{formatWhen(row.created_at)}</td>
              <td data-label="Type">{row.transaction_type}</td>
              <td className="num" data-label="Before">
                {row.quantity_before}
              </td>
              <td className="num" data-label="After">
                {row.quantity_after}
              </td>
              <td data-label="Source">{row.source}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
