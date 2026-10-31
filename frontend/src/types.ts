export type StockStatus = "OUT_OF_STOCK" | "LOW_STOCK" | "IN_STOCK";

export interface Category {
  id: string;
  name: string;
  description: string | null;
  color: string | null;
}

export interface SlotBrief {
  slot_id: string;
  slot_number: number;
  label: string | null;
  location: string | null;
  quantity: number;
}

export interface Part {
  id: string;
  sku: string | null;
  name: string;
  description: string | null;
  category: Category | null;
  manufacturer: string | null;
  manufacturer_part_number: string | null;
  specifications: Record<string, unknown>;
  unit: string;
  initial_quantity: number;
  low_stock_percent: number;
  low_stock_override: number | null;
  notes: string | null;
  current_quantity: number;
  threshold: number | null;
  threshold_configured: boolean;
  baseline_state: "OK" | "BASELINE_NOT_SET";
  status: StockStatus;
  slots: SlotBrief[];
  created_at: string;
  updated_at: string;
  archived_at: string | null;
}

export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export interface SlotItem {
  part_id: string;
  name: string;
  sku: string | null;
  unit: string;
  quantity: number;
}

export interface SlotDetail {
  id: string;
  slot_number: number;
  label: string | null;
  description: string | null;
  location: string | null;
  archived_at: string | null;
  items: SlotItem[];
  total_units: number;
}

export interface SlotSummary {
  id: string;
  slot_number: number;
  label: string | null;
  location: string | null;
  total_units: number;
  part_count: number;
  archived_at: string | null;
}

export interface Transaction {
  id: string;
  part_id: string;
  part_name: string;
  part_sku: string | null;
  from_slot_number: number | null;
  to_slot_number: number | null;
  transaction_type: string;
  quantity: number;
  quantity_delta: number;
  quantity_before: number;
  quantity_after: number;
  source: string;
  reason: string | null;
  created_at: string;
}

export interface AuditEvent {
  id: string;
  action: string;
  changes: Record<string, { old: unknown; new: unknown }>;
  source: string;
  created_at: string;
}

export interface Stats {
  active_part_types: number;
  occupied_slots: number;
  total_units: number;
  low_stock_part_types: number;
  out_of_stock_part_types: number;
  drawer_count: number;
}

export interface Palette {
  bg: string;
  surface: string;
  text: string;
  muted: string;
  border: string;
  accent: string;
  accent_2: string;
  danger: string;
  warning: string;
  ok: string;
  info: string;
}

export interface Settings {
  application_name: string;
  theme_preference: string;
  color_palette: Palette;
  default_low_stock_percent: number;
  preferred_landing_page: string;
  display_preferences: { page_size: number; density: string; show_sku: boolean };
  preferred_public_url: string | null;
}

export const PALETTE_KEYS: (keyof Palette)[] = [
  "bg",
  "surface",
  "text",
  "muted",
  "border",
  "accent",
  "accent_2",
  "danger",
  "warning",
  "ok",
  "info",
];
