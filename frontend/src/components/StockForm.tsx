import { useRef, useState, type FormEvent } from "react";
import { api, ApiError, itemsQuery } from "../services/api";
import type { Page, Part } from "../types";

type Action = "ADD" | "REMOVE" | "TRANSFER" | "ADJUST" | "RESTOCK" | "INITIAL_STOCK";

interface Props {
  presetSlot?: number;
  presetPartId?: string;
  presetAction?: Action;
  onDone: () => void;
}

export function StockForm({ presetSlot, presetPartId, presetAction = "REMOVE", onDone }: Props) {
  const lock = useRef(false);
  const [action, setAction] = useState<Action>(presetAction);
  const [slot, setSlot] = useState(presetSlot ? String(presetSlot) : "");
  const [destination, setDestination] = useState("");
  const [partId, setPartId] = useState(presetPartId ?? "");
  const [partQuery, setPartQuery] = useState("");
  const [matches, setMatches] = useState<Part[]>([]);
  const [quantity, setQuantity] = useState("");
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function findParts() {
    setError(null);
    try {
      const page = await api<Page<Part>>(itemsQuery({ search: partQuery, limit: 8 }));
      setMatches(page.items);
      if (!page.items.length) setError("No parts matched that search.");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Part search failed.");
    }
  }

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (lock.current) return;
    lock.current = true;
    setPending(true);
    setError(null);
    try {
      const amount = Number(quantity);
      if (!Number.isInteger(amount) || amount < 0 || (action !== "ADJUST" && amount <= 0)) {
        throw new ApiError("Enter a whole number of pieces.", 422, "validation_error");
      }
      if (action === "TRANSFER") {
        await api("/api/v1/stock/transfer", {
          method: "POST",
          body: JSON.stringify({
            part_id: partId,
            from_slot: Number(slot),
            to_slot: Number(destination),
            quantity: amount,
            reason: reason || null,
          }),
        });
      } else if (action === "ADJUST") {
        await api("/api/v1/stock/adjust", {
          method: "POST",
          body: JSON.stringify({
            part_id: partId,
            slot_number: Number(slot),
            new_quantity: amount,
            reason: reason || null,
          }),
        });
      } else if (action === "REMOVE") {
        await api("/api/v1/stock/remove", {
          method: "POST",
          body: JSON.stringify({
            part_id: partId,
            slot_number: Number(slot),
            quantity: amount,
            reason: reason || null,
          }),
        });
      } else {
        await api("/api/v1/stock/add", {
          method: "POST",
          body: JSON.stringify({
            part_id: partId,
            slot_number: Number(slot),
            quantity: amount,
            transaction_type: action === "RESTOCK" || action === "INITIAL_STOCK" ? action : "ADD",
            reason: reason || null,
          }),
        });
      }
      setQuantity("");
      onDone();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "The stock change was not saved.");
    } finally {
      lock.current = false;
      setPending(false);
    }
  }

  return (
    <form className="stack" onSubmit={onSubmit}>
      {error ? (
        <p className="error-banner" role="alert">
          {error}
        </p>
      ) : null}
      <div className="row">
        <label className="field">
          Action
          <select aria-label="Stock action" value={action} onChange={(event) => setAction(event.target.value as Action)}>
            <option value="REMOVE">Remove</option>
            <option value="ADD">Add</option>
            <option value="RESTOCK">Restock</option>
            <option value="INITIAL_STOCK">Initial allocation</option>
            <option value="TRANSFER">Transfer</option>
            <option value="ADJUST">Set quantity</option>
          </select>
        </label>
        <label className="field">
          Drawer
          <input aria-label="Drawer number" inputMode="numeric" value={slot} onChange={(event) => setSlot(event.target.value)} required />
        </label>
        {action === "TRANSFER" ? (
          <label className="field">
            Destination
            <input aria-label="Destination drawer" inputMode="numeric" value={destination} onChange={(event) => setDestination(event.target.value)} required />
          </label>
        ) : null}
        <label className="field">
          Part
          <input aria-label="Part id" value={partId} onChange={(event) => setPartId(event.target.value)} required placeholder="Part id or pick below" />
        </label>
        <label className="field">
          {action === "ADJUST" ? "New quantity" : "Quantity"}
          <input aria-label="Quantity" inputMode="numeric" value={quantity} onChange={(event) => setQuantity(event.target.value)} required />
        </label>
      </div>
      {presetPartId ? null : (
        <div className="stack">
          <div className="row">
            <label className="field">
              Find part
              <input aria-label="Find part" value={partQuery} onChange={(event) => setPartQuery(event.target.value)} placeholder="Name or SKU" />
            </label>
            <button type="button" onClick={() => void findParts()}>
              Find
            </button>
          </div>
          {matches.length ? (
            <div className="actions" role="list">
              {matches.map((part) => (
                <button
                  key={part.id}
                  type="button"
                  onClick={() => setPartId(part.id)}
                  aria-pressed={partId === part.id}
                >
                  {part.sku ? `${part.sku} — ` : ""}
                  {part.name}
                </button>
              ))}
            </div>
          ) : null}
        </div>
      )}
      <label className="field">
        Reason (optional)
        <input aria-label="Reason" value={reason} onChange={(event) => setReason(event.target.value)} />
      </label>
      <button className="btn-primary" type="submit" disabled={pending}>
        {pending ? "Saving…" : "Confirm stock change"}
      </button>
    </form>
  );
}
