export interface WorkspaceSecretDraft {
  name: string;
  value: string;
}

export interface WorkspaceMcpDraft {
  mcp_servers_json?: string;
  mcp_stdio_json?: string;
  mcp_http_url?: string;
  mcp_http_namespace?: string;
  mcp_http_headers_json?: string;
}

export const DEFAULT_WORKSPACE_SECRET_NAMES = [
  'CONTEXT7_API_KEY',
  'NEON_API_KEY',
  'SUPABASE_ACCESS_TOKEN',
];

export const WORKSPACE_SECRET_NAME_RE = /^[A-Z_][A-Z0-9_]{0,127}$/;

const INLINE_SECRET_NAME_RE = /(^|_)(API_KEY|ACCESS_TOKEN|TOKEN|SECRET|PASSWORD|PRIVATE_KEY|ACCESS_KEY)$/;
const SECRET_PLACEHOLDER_RE = /^\$\{[A-Z_][A-Z0-9_]{0,127}\}$/;

export function normalizeWorkspaceSecretName(name: string): string {
  return String(name || '').trim().toUpperCase();
}

export function normalizeWorkspaceSecretStatus(
  status: Record<string, boolean> = {}
): Record<string, boolean> {
  const next: Record<string, boolean> = {};
  for (const [name, configured] of Object.entries(status || {})) {
    const normalized = normalizeWorkspaceSecretName(name);
    if (normalized) next[normalized] = Boolean(configured) || Boolean(next[normalized]);
  }
  return next;
}

export function workspaceSecretRowsFromStatus(
  status: Record<string, boolean>,
  currentRows: WorkspaceSecretDraft[] = []
): WorkspaceSecretDraft[] {
  const names = new Set(DEFAULT_WORKSPACE_SECRET_NAMES);
  for (const name of Object.keys(status || {})) names.add(normalizeWorkspaceSecretName(name));
  for (const row of currentRows) {
    const name = normalizeWorkspaceSecretName(row.name);
    if (name || row.value.trim()) names.add(name);
  }

  return Array.from(names)
    .filter(Boolean)
    .map((name) => {
      const existing = currentRows.find((row) => normalizeWorkspaceSecretName(row.name) === name);
      return { name, value: existing?.value || '' };
    });
}

export function hasWorkspaceSecretDraftValues(rows: WorkspaceSecretDraft[]): boolean {
  return rows.some((row) => row.value.trim());
}

export function referencedWorkspaceSecretNames(mcp: WorkspaceMcpDraft): string[] {
  const names = new Set<string>();
  const values = [
    mcp.mcp_servers_json,
    mcp.mcp_stdio_json,
    mcp.mcp_http_url,
    mcp.mcp_http_namespace,
    mcp.mcp_http_headers_json,
  ];
  const pattern = /\$\{([A-Za-z_][A-Za-z0-9_]*)\}/g;

  for (const value of values) {
    let match: RegExpExecArray | null;
    pattern.lastIndex = 0;
    while ((match = pattern.exec(String(value || '')))) {
      names.add(normalizeWorkspaceSecretName(match[1] || ''));
    }
  }

  return Array.from(names).filter(Boolean);
}

function shouldExtractInlineSecret(name: string, value: string): boolean {
  const normalized = normalizeWorkspaceSecretName(name);
  const trimmed = value.trim();
  return (
    Boolean(trimmed) &&
    WORKSPACE_SECRET_NAME_RE.test(normalized) &&
    INLINE_SECRET_NAME_RE.test(normalized) &&
    !SECRET_PLACEHOLDER_RE.test(trimmed)
  );
}

function extractInlineSecretsFromJson(
  jsonValue: string | undefined,
  values: Record<string, string>
): string | undefined {
  const original = String(jsonValue || '');
  const trimmed = original.trim();
  if (!trimmed) return jsonValue;

  let parsed: unknown;
  try {
    parsed = JSON.parse(trimmed);
  } catch {
    return jsonValue;
  }

  let changed = false;
  const visit = (node: unknown): unknown => {
    if (Array.isArray(node)) {
      const next = node.map((item) => visit(item));
      if (next.some((item, index) => item !== node[index])) {
        changed = true;
        return next;
      }
      return node;
    }

    if (!node || typeof node !== 'object') return node;

    const next: Record<string, unknown> = {};
    let nodeChanged = false;
    for (const [key, rawValue] of Object.entries(node)) {
      if (typeof rawValue === 'string' && shouldExtractInlineSecret(key, rawValue)) {
        const secretName = normalizeWorkspaceSecretName(key);
        values[secretName] = rawValue.trim();
        next[key] = `\${${secretName}}`;
        nodeChanged = true;
        continue;
      }

      const nested = visit(rawValue);
      next[key] = nested;
      if (nested !== rawValue) nodeChanged = true;
    }

    if (nodeChanged) {
      changed = true;
      return next;
    }
    return node;
  };

  const sanitized = visit(parsed);
  return changed ? JSON.stringify(sanitized, null, 2) : jsonValue;
}

export function extractInlineWorkspaceSecretsFromMcp<T extends WorkspaceMcpDraft>(
  mcp: T
): { mcp: T; values: Record<string, string>; names: string[] } {
  const values: Record<string, string> = {};
  const next: WorkspaceMcpDraft = { ...mcp };
  const jsonFields: Array<keyof WorkspaceMcpDraft> = [
    'mcp_servers_json',
    'mcp_stdio_json',
    'mcp_http_headers_json',
  ];

  for (const field of jsonFields) {
    const sanitized = extractInlineSecretsFromJson(next[field], values);
    if (sanitized !== next[field]) {
      next[field] = sanitized;
    }
  }

  return {
    mcp: next as T,
    values,
    names: Object.keys(values),
  };
}
