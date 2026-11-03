import type { StockStatus } from "../types";

const LABELS: Record<StockStatus, string> = {
  OUT_OF_STOCK: "Out of stock",
  LOW_STOCK: "Low stock",
  IN_STOCK: "In stock",
};

export function StatusBadge({ status }: { status: StockStatus }) {
  return <span className={`badge badge-${status}`}>{LABELS[status]}</span>;
}
