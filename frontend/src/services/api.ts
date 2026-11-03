import type { Page, SlotSummary } from "../types";

export const OFFLINE_MESSAGE =
  "Cannot connect to Cyberdeck Inventory. Check that the Raspberry Pi service is running.";

export class ApiError extends Error {
  status: number;
  code: string;
  field: string | null;
  guidance: string | null;

  constructor(
    message: string,
    status: number,
    code: string,
    field: string | null = null,
    guidance: string | null = null,
  ) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.field = field;
    this.guidance = guidance;
  }
}

function readableMessage(value: unknown, fallback: string): string {
  if (typeof value !== "string" || !value.trim()) return fallback;
  if (/traceback|sqlalchemy|sqlite3|http\s*\d{3}/i.test(value)) return fallback;
  return value;
}

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers);
  headers.set("X-Cyberdeck-Request", "1");
  headers.set("X-Cyberdeck-Client", "web");
  if (options.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  let response: Response;
  try {
    response = await fetch(path, { ...options, headers });
  } catch {
    throw new ApiError(OFFLINE_MESSAGE, 0, "network_error", null, "Check that the Raspberry Pi service is running.");
  }
  const text = await response.text();
  type ErrorBody = { error?: { message?: unknown; code?: unknown; field?: unknown; guidance?: unknown } };
  let data: ErrorBody | null = null;
  if (text) {
    try {
      data = JSON.parse(text) as ErrorBody;
    } catch {
      throw new ApiError(
        response.ok ? "The response could not be read." : OFFLINE_MESSAGE,
        response.status,
        "invalid_response",
      );
    }
  }
  if (!response.ok) {
    const error = data?.error;
    const fallback =
      response.status >= 500
        ? "Cyberdeck Inventory could not complete that action. Try again in a moment."
        : "The request could not be completed.";
    throw new ApiError(
      readableMessage(error?.message, fallback),
      response.status,
      typeof error?.code === "string" ? error.code : "http_error",
      typeof error?.field === "string" ? error.field : null,
      typeof error?.guidance === "string" ? error.guidance : null,
    );
  }
  return data as T;
}

export function formatDrawer(slot: { slot_number: number; label?: string | null }): string {
  return slot.label ? `${slot.slot_number} — ${slot.label}` : String(slot.slot_number);
}

export async function loadDrawers(): Promise<SlotSummary[]> {
  const collected: SlotSummary[] = [];
  let offset = 0;
  for (let pageIndex = 0; pageIndex < 20; pageIndex += 1) {
    const page = await api<Page<SlotSummary>>(`/api/v1/slots?limit=100&offset=${offset}`);
    collected.push(...page.items.filter((slot) => !slot.archived_at));
    offset += page.items.length;
    if (page.items.length === 0 || offset >= page.total) break;
  }
  return collected.sort((left, right) => left.slot_number - right.slot_number);
}

export function itemsQuery(params: {
  search?: string;
  category?: string;
  status?: string;
  slot?: string;
  sort?: string;
  order?: string;
  limit?: number;
  offset?: number;
}): string {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && String(value) !== "") {
      query.set(key, String(value));
    }
  }
  const text = query.toString();
  return text ? `/api/v1/items?${text}` : "/api/v1/items";
}
