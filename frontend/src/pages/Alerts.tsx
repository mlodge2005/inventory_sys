import { useState } from "react";
import { Link } from "react-router-dom";
import { ErrorNote, Loading, drawerList } from "../components/Feedback";
import { StatusBadge } from "../components/StatusBadge";
import { useLoad } from "../hooks/useLoad";
import { api, ApiError } from "../services/api";
import type { Page, Part } from "../types";

export function AlertsPage() {
  const page = useLoad(() => api<Page<Part>>("/api/v1/alerts/low-stock?limit=200"), []);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState<string | null>(null);

  async function restock(part: Part) {
    const slot = part.slots[0]?.slot_number;
    if (!slot) {
      setError(`${part.name} has no drawer. Open the part and allocate stock first.`);
      return;
    }
    const gap = Math.max(part.initial_quantity - part.current_quantity, 1);
    setPending(part.id);
    setError(null);
    setMessage(null);
    try {
      await api("/api/v1/stock/add", {
        method: "POST",
        body: JSON.stringify({
          part_id: part.id,
          slot_number: slot,
          quantity: gap,
          transaction_type: "RESTOCK",
          reason: "Restock from alerts",
        }),
      });
      setMessage(`Restocked ${part.name} by ${gap}. The baseline stayed ${part.initial_quantity}.`);
      page.reload();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Restock failed.");
    } finally {
      setPending(null);
    }
  }

  return (
    <div className="stack">
      <h1>Low stock</h1>
      <p className="muted">Out-of-stock parts are listed first, then low stock, then the smallest quantities.</p>
      <ErrorNote message={error || page.error} />
      {message ? <p className="note">{message}</p> : null}
      {page.loading ? <Loading /> : null}
      {(page.data?.items.length ?? 0) === 0 && !page.loading ? <p className="muted">Nothing is at or below its threshold.</p> : null}
      <div className="table-wrap">
        <table className="responsive">
          <thead>
            <tr>
              <th>Part</th>
              <th>Status</th>
              <th>On hand</th>
              <th>Baseline</th>
              <th>Threshold</th>
              <th>Drawers</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {(page.data?.items ?? []).map((part) => (
              <tr key={part.id}>
                <td data-label="Part">
                  <Link to={`/inventory/${part.id}`}>{part.name}</Link>
                </td>
                <td data-label="Status">
                  <StatusBadge status={part.status} />
                </td>
                <td className="num" data-label="On hand">
                  {part.current_quantity}
                </td>
                <td className="num" data-label="Baseline">
                  {part.initial_quantity}
                </td>
                <td data-label="Threshold">{part.threshold_configured ? part.threshold : "Baseline not set"}</td>
                <td data-label="Drawers">{drawerList(part.slots)}</td>
                <td data-label="Action">
                  <button type="button" disabled={pending === part.id} onClick={() => void restock(part)}>
                    Restock
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
