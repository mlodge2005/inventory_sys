export class ApiError extends Error {
  status: number;
  code: string;

  constructor(message: string, status: number, code: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers);
  headers.set("X-Cyberdeck-Request", "1");
  headers.set("X-Cyberdeck-Client", "web");
  if (options.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetch(path, { ...options, headers });
  const text = await response.text();
  const data = text ? JSON.parse(text) : null;
  if (!response.ok) {
    throw new ApiError(
      data?.error?.message || response.statusText || "Request failed",
      response.status,
      data?.error?.code || "http_error",
    );
  }
  return data as T;
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
