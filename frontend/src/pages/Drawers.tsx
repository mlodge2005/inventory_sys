import { FormEvent, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { ErrorNote, Loading } from "../components/Feedback";
import { useLoad } from "../hooks/useLoad";
import { api, ApiError } from "../services/api";
import type { Page, SlotSummary } from "../types";

export function DrawersPage() {
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const search = params.get("search") ?? "";
  const [draft, setDraft] = useState(search);
  const [number, setNumber] = useState("");
  const [label, setLabel] = useState("");
  const [location, setLocation] = useState("");
  const [error, setError] = useState<string | null>(null);
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
    try {
      const created = await api<{ slot_number: number }>("/api/v1/slots", {
        method: "POST",
        body: JSON.stringify({
          slot_number: Number(number),
          label: label.trim() || null,
          location: location.trim() || null,
        }),
      });
      setNumber("");
      setLabel("");
      page.reload();
      navigate(`/drawers/${created.slot_number}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not create the drawer.");
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
      <ErrorNote message={page.error} />
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
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <form className="card stack" onSubmit={create}>
        <h2>New drawer</h2>
        <ErrorNote message={error} />
        <div className="row">
          <label className="field">
            Number
            <input aria-label="New drawer number" inputMode="numeric" value={number} onChange={(event) => setNumber(event.target.value)} required />
          </label>
          <label className="field">
            Label
            <input aria-label="Drawer label" value={label} onChange={(event) => setLabel(event.target.value)} />
          </label>
          <label className="field">
            Location
            <input aria-label="Drawer location" value={location} onChange={(event) => setLocation(event.target.value)} />
          </label>
        </div>
        <button className="btn-primary" type="submit">
          Create drawer
        </button>
      </form>
    </div>
  );
}
