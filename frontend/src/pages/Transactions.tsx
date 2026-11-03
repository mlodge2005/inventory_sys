import { useState } from "react";
import { Link } from "react-router-dom";
import { ErrorNote, Loading, formatWhen } from "../components/Feedback";
import { useLoad } from "../hooks/useLoad";
import { api } from "../services/api";
import type { Page, Transaction } from "../types";

const TYPES = ["", "INITIAL_STOCK", "ADD", "REMOVE", "TRANSFER", "ADJUST", "RESTOCK"];

export function TransactionsPage() {
  const [type, setType] = useState("");
  const [slot, setSlot] = useState("");
  const [source, setSource] = useState("");
  const [offset, setOffset] = useState(0);
  const limit = 50;
  const page = useLoad(() => {
    const query = new URLSearchParams({ limit: String(limit), offset: String(offset) });
    if (type) query.set("transaction_type", type);
    if (slot) query.set("slot", slot);
    if (source) query.set("source", source);
    return api<Page<Transaction>>(`/api/v1/transactions?${query.toString()}`);
  }, [type, slot, source, offset]);

  return (
    <div className="stack">
      <h1>Transaction history</h1>
      <p className="muted">History is append-only. Corrections are new ADJUST rows, not edits of older rows.</p>
      <div className="row">
        <label className="field">
          Type
          <select
            aria-label="Transaction type"
            value={type}
            onChange={(event) => {
              setType(event.target.value);
              setOffset(0);
            }}
          >
            {TYPES.map((item) => (
              <option key={item || "all"} value={item}>
                {item || "All"}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          Drawer
          <input
            aria-label="History drawer"
            inputMode="numeric"
            value={slot}
            onChange={(event) => {
              setSlot(event.target.value);
              setOffset(0);
            }}
          />
        </label>
        <label className="field">
          Source
          <select
            aria-label="Source"
            value={source}
            onChange={(event) => {
              setSource(event.target.value);
              setOffset(0);
            }}
          >
            <option value="">All</option>
            <option value="web">web</option>
            <option value="cli">cli</option>
            <option value="api">api</option>
            <option value="import">import</option>
            <option value="migration">migration</option>
          </select>
        </label>
      </div>
      <ErrorNote message={page.error} />
      {page.loading ? <Loading /> : null}
      <div className="table-wrap">
        <table className="responsive">
          <thead>
            <tr>
              <th>When</th>
              <th>Part</th>
              <th>Type</th>
              <th>From</th>
              <th>To</th>
              <th>Before</th>
              <th>After</th>
              <th>Source</th>
            </tr>
          </thead>
          <tbody>
            {(page.data?.items ?? []).map((row) => (
              <tr key={row.id}>
                <td data-label="When">{formatWhen(row.created_at)}</td>
                <td data-label="Part">
                  <Link to={`/inventory/${row.part_id}`}>{row.part_name}</Link>
                </td>
                <td data-label="Type">{row.transaction_type}</td>
                <td data-label="From">{row.from_slot_number ?? "—"}</td>
                <td data-label="To">{row.to_slot_number ?? "—"}</td>
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
      <div className="actions">
        <button type="button" disabled={offset <= 0} onClick={() => setOffset(Math.max(0, offset - limit))}>
          Previous
        </button>
        <span className="muted">{page.data ? `${page.data.total} rows` : ""}</span>
        <button type="button" disabled={!page.data || offset + limit >= page.data.total} onClick={() => setOffset(offset + limit)}>
          Next
        </button>
      </div>
    </div>
  );
}
