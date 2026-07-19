/** Runtime configuration shared by the authenticated Studio surfaces. */
export const DEFAULT_API_URL =
  process.env.EXPO_PUBLIC_API_URL ?? 'http://localhost:8000';

const LOCAL_API_RE = /^https?:\/\/(?:localhost|127\.0\.0\.1)(?::\d+)?(?:\/|$)/;

export const LOCAL_PREVIEW_AUTH_ENABLED =
  process.env.EXPO_PUBLIC_FACETTA_LOCAL_PREVIEW_AUTH === 'true'
  || (process.env.NODE_ENV !== 'production' && LOCAL_API_RE.test(DEFAULT_API_URL));

export const PREVIEW_AUTH_BYPASS =
  (process.env.EXPO_PUBLIC_FACETTA_PREVIEW_BYPASS ?? '').trim().toLowerCase() === 'true';
