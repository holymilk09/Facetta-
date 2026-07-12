const TRUE_VALUES = new Set(['1', 'true', 'yes', 'on']);

/** The trusted workspace stays dark until the internal acceptance flow passes. */
export const TRUSTED_WORKSPACE_ENABLED = TRUE_VALUES.has(
  (process.env.EXPO_PUBLIC_TRUSTED_WORKSPACE ?? '').trim().toLowerCase(),
);

const memory: Record<string, string> = {};
const ACTIVE_PROJECT_KEY = 'facetta.trusted.active-project';

function read(key: string): string | null {
  try {
    if (typeof localStorage !== 'undefined') return localStorage.getItem(key);
  } catch {
    // Private browsing and native runtimes fall back to process memory.
  }
  return memory[key] ?? null;
}

function write(key: string, value: string): void {
  try {
    if (typeof localStorage !== 'undefined') {
      localStorage.setItem(key, value);
      return;
    }
  } catch {
    // Fall through to the native/in-memory recovery seam.
  }
  memory[key] = value;
}

function remove(key: string): void {
  try {
    if (typeof localStorage !== 'undefined') localStorage.removeItem(key);
  } catch {
    // Keep cleanup best-effort when browser storage is unavailable.
  }
  delete memory[key];
}

export function loadTrustedProjectId(): string | null {
  return read(ACTIVE_PROJECT_KEY);
}

export function saveTrustedProjectId(projectId: string): void {
  write(ACTIVE_PROJECT_KEY, projectId);
}

export function clearTrustedProjectId(): void {
  remove(ACTIVE_PROJECT_KEY);
}
