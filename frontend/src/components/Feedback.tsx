export function ErrorNote({ message }: { message: string | null }) {
  if (!message) return null;
  return (
    <p className="error-banner" role="alert">
      {message}
    </p>
  );
}

export function Notice({ message }: { message: string | null }) {
  if (!message) return null;
  return (
    <p className="success-banner" role="status">
      {message}
    </p>
  );
}

export function FieldError({ message }: { message?: string | null }) {
  if (!message) return null;
  return <span className="field-error">{message}</span>;
}

export function Loading({ label = "Loading…" }: { label?: string }) {
  return <p className="muted">{label}</p>;
}

export function formatWhen(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

export function drawerList(slots: { slot_number: number; quantity: number }[]): string {
  if (!slots.length) return "—";
  return slots.map((slot) => `${slot.slot_number} × ${slot.quantity}`).join(", ");
}
