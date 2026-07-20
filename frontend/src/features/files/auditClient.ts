// Low-level client for the read-only audit API (/api/v1/audit), mounted on the
// Chainlit backend. Same-origin in production; VITE_CHAINLIT_URL points at the
// backend in dev. Auth rides the Chainlit session cookie (credentials: include).

const backendOrigin = (import.meta.env.VITE_CHAINLIT_URL ?? "").replace(/\/$/, "");
const AUDIT_BASE = `${backendOrigin}/api/v1/audit`;

export class AuditApiError extends Error {
  constructor(
    public readonly code: string,
    public readonly status: number,
    message?: string,
  ) {
    super(message ?? code);
    this.name = "AuditApiError";
  }
}

type QueryValue = string | string[] | number | undefined;

export async function auditGet<T>(
  path: string,
  params?: Record<string, QueryValue>,
): Promise<T> {
  // Absolute AUDIT_BASE ignores the origin arg; a relative one resolves against it.
  const url = new URL(AUDIT_BASE + path, window.location.origin);
  if (params) {
    for (const [key, value] of Object.entries(params)) {
      if (value === undefined) continue;
      if (Array.isArray(value)) value.forEach((v) => url.searchParams.append(key, v));
      else url.searchParams.set(key, String(value));
    }
  }

  const response = await fetch(url.toString(), {
    credentials: "include",
    headers: { Accept: "application/json" },
  });

  if (!response.ok) {
    let code = "read_failed";
    try {
      code = ((await response.json()) as { code?: string }).code ?? code;
    } catch {
      // non-JSON error body — keep the default code
    }
    throw new AuditApiError(code, response.status);
  }

  return (await response.json()) as T;
}
