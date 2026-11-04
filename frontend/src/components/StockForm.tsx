import { useEffect, useRef, useState, type FormEvent } from "react";
import { api, ApiError, itemsQuery, loadDrawers } from "../services/api";
import type { Page, Part, SlotSummary } from "../types";
import { DrawerSelect } from "./DrawerSelect";
import { FieldError } from "./Feedback";

type Action = "ADD" | "REMOVE" | "TRANSFER" | "ADJUST" | "RESTOCK" | "INITIAL_STOCK";

interface Props {
  presetSlot?: number;
  presetPartId?: string;
  presetAction?: Action;
  onDone: () => void;
}

function wholeNumber(value: string, allowZero: boolean): number | null {
  if (!/^\d+$/.test(value.trim())) return null;
  const amount = Number(value);
  if (!Number.isInteger(amount)) return null;
  if (amount < 0 || (!allowZero && amount === 0)) return null;
  return amount;
}

export function StockForm({ presetSlot, presetPartId, presetAction = "REMOVE", onDone }: Props) {
  const lock = useRef(false);
  const [action, setAction] = useState<Action>(presetAction);
  const [slot, setSlot] = useState(presetSlot ? String(presetSlot) : "");
  const [destination, setDestination] = useState("");
  const [partId, setPartId] = useState(presetPartId ?? "");
  const [partQuery, setPartQuery] = useState("");
  const [matches, setMatches] = useState<Part[]>([]);
  const [selected, setSelected] = useState<Part | null>(null);
  const [drawers, setDrawers] = useState<SlotSummary[]>([]);
  const [quantity, setQuantity] = useState("");
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [fieldError, setFieldError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

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

  useEffect(() => {
    if (!partId) {
      setSelected(null);
      return;
    }
    const known = matches.find((part) => part.id === partId);
    if (known) {
      setSelected(known);
      return;
    }
    let live = true;
    api<Part>(`/api/v1/items/${partId}`)
      .then((part) => {
        if (live) setSelected(part);
      })
      .catch(() => {
        if (live) setSelected(null);
      });
    return () => {
      live = false;
    };
  }, [partId, matches]);

  const available = selected?.slots?.find((item) => String(item.slot_number) === slot)?.quantity ?? (selected && slot ? 0 : null);
  const allowZero = action === "ADJUST";
  const amount = wholeNumber(quantity, allowZero);
  const overAvailable = available !== null && amount !== null && (action === "REMOVE" || action === "TRANSFER") && amount > available;
  const ready =
    Boolean(slot) &&
    Boolean(partId) &&
    amount !== null &&
    !overAvailable &&
    (action !== "TRANSFER" || (Boolean(destination) && destination !== slot));

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
    if (lock.current || !ready || amount === null) return;
    lock.current = true;
    setPending(true);
    setError(null);
    setFieldError(null);
    try {
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
      const message = err instanceof ApiError ? err.message : "The stock change was not saved.";
      if (err instanceof ApiError && err.field) setFieldError(message);
      setError(message);
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
        <DrawerSelect label="Drawer number" value={slot} onChange={setSlot} slots={drawers} error={fieldError} />
        {action === "TRANSFER" ? (
          <DrawerSelect label="Destination drawer" value={destination} onChange={setDestination} slots={drawers} exclude={slot ? [slot] : []} />
        ) : null}
        <label className="field">
          Part
          <input aria-label="Part id" value={partId} onChange={(event) => setPartId(event.target.value)} required placeholder="Part id or pick below" />
        </label>
        <label className="field">
          {action === "ADJUST" ? "New quantity" : "Quantity"}
          <input aria-label="Quantity" inputMode="numeric" value={quantity} onChange={(event) => setQuantity(event.target.value)} required />
          <FieldError
            message={
              quantity.trim() && amount === null
                ? allowZero
                  ? "Enter a whole number of zero or more."
                  : "Enter a whole number greater than zero."
                : null
            }
          />
          {overAvailable ? <FieldError message={`Only ${available} are available.`} /> : null}
        </label>
      </div>
      {available !== null ? <p className="note">Available in this drawer: {available}</p> : null}
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
                <button key={part.id} type="button" onClick={() => setPartId(part.id)} aria-pressed={partId === part.id}>
                  {part.sku ? `${part.sku} — ` : ""}
                  {part.name} ({part.current_quantity} on hand)
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
      <button className="btn-primary" type="submit" disabled={pending || !ready}>
        {pending ? "Saving…" : "Confirm stock change"}
      </button>
    </form>
  );
}
