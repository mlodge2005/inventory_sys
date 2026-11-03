import { useMemo, useState } from "react";
import { formatDrawer } from "../services/api";
import type { SlotSummary } from "../types";
import { FieldError } from "./Feedback";

interface Props {
  label: string;
  value: string;
  onChange: (slotNumber: string) => void;
  slots: SlotSummary[];
  exclude?: string[];
  required?: boolean;
  error?: string | null;
  onCreate?: () => void;
  announceEmpty?: boolean;
}

export function DrawerSelect({
  label,
  value,
  onChange,
  slots,
  exclude = [],
  required,
  error,
  onCreate,
  announceEmpty = true,
}: Props) {
  const [query, setQuery] = useState("");
  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return slots.filter((slot) => {
      const number = String(slot.slot_number);
      if (exclude.includes(number) && number !== value) return false;
      if (!needle) return true;
      return `${slot.slot_number} ${slot.label ?? ""} ${slot.location ?? ""}`.toLowerCase().includes(needle);
    });
  }, [exclude, query, slots, value]);
  const hiddenSelection = value && !filtered.some((slot) => String(slot.slot_number) === value)
    ? slots.find((slot) => String(slot.slot_number) === value)
    : undefined;

  return (
    <div className="field">
      <span>{label}</span>
      {slots.length === 0 && announceEmpty ? (
        <p className="muted">No drawers exist yet. Create a drawer to assign this part.</p>
      ) : slots.length > 0 ? (
        <input
          aria-label={`${label} search`}
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search number or label"
        />
      ) : null}
      <select aria-label={label} value={value} required={required} onChange={(event) => onChange(event.target.value)}>
        <option value="">{slots.length ? "Select a drawer" : "No drawers yet"}</option>
        {hiddenSelection ? <option value={hiddenSelection.slot_number}>{formatDrawer(hiddenSelection)}</option> : null}
        {filtered.map((slot) => (
          <option key={slot.id} value={slot.slot_number}>
            {formatDrawer(slot)}
          </option>
        ))}
      </select>
      <FieldError message={error} />
      {onCreate ? (
        <button type="button" onClick={onCreate}>
          Create Drawer
        </button>
      ) : null}
    </div>
  );
}
