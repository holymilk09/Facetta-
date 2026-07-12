// Client-side auth flow for the mobile app.
//
// Provider SDK/token exchange is not connected yet. Local provider helpers
// return profile-only sessions and MUST NOT authorize API requests. A real
// server-issued credential enters only through attachServerCredential:
//   - signInWithApple  → expo-apple-authentication
//   - signInWithGoogle → expo-auth-session (Google provider)

export type AuthProvider = 'apple' | 'google' | 'email';

export interface Session {
  provider: AuthProvider;
  email: string;
  name: string;
  designerId: string;
  /** Server-issued first-party credential. Never derive this from designerId. */
  accessToken?: string;
  accessTokenExpiresAt?: string;
}

export interface SessionCredential {
  accessToken: string;
  expiresAt: string;
}

export function sessionAccessToken(
  session: Session | null,
  now: number = Date.now(),
): string | null {
  if (session === null || typeof session.accessToken !== 'string'
    || typeof session.accessTokenExpiresAt !== 'string'
    || session.accessToken.trim().length === 0) return null;
  const expiresAt = Date.parse(session.accessTokenExpiresAt);
  return Number.isFinite(expiresAt) && expiresAt > now ? session.accessToken : null;
}

/** Provider/server integration seam. Credentials must come from Facetta's auth service. */
export function attachServerCredential(
  session: Session,
  credential: SessionCredential,
): Session {
  if (credential.accessToken.trim().length === 0
    || !Number.isFinite(Date.parse(credential.expiresAt))) {
    throw new Error('The server returned an invalid sign-in credential.');
  }
  return {
    ...session,
    accessToken: credential.accessToken,
    accessTokenExpiresAt: credential.expiresAt,
  };
}

/** usr_ana-style designer id derived from the account email. */
export function designerIdFromEmail(email: string): string {
  const local = email.split('@')[0] ?? 'designer';
  const slug = local.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '');
  return `usr_${slug || 'designer'}`;
}

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export function validateEmail(email: string): string | null {
  if (!email.trim()) return 'Enter your email address.';
  if (!EMAIL_RE.test(email.trim())) return 'That does not look like an email address.';
  return null;
}

export function validatePassword(password: string): string | null {
  if (!password) return 'Enter your password.';
  if (password.length < 8) return 'Password must be at least 8 characters.';
  return null;
}

function nameFromEmail(email: string): string {
  const local = email.split('@')[0] ?? 'Designer';
  return local
    .split(/[._-]+/)
    .filter(Boolean)
    .map((w) => w[0].toUpperCase() + w.slice(1))
    .join(' ') || 'Designer';
}

function makeSession(provider: AuthProvider, email: string, name?: string): Session {
  const clean = email.trim().toLowerCase();
  return {
    provider,
    email: clean,
    name: name?.trim() || nameFromEmail(clean),
    designerId: designerIdFromEmail(clean),
  };
}

const wait = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

/** Integration point for expo-apple-authentication. Resolves a local session for now. */
export async function signInWithApple(): Promise<Session> {
  await wait(700);
  return makeSession('apple', 'designer@icloud.com', 'Facetta Designer');
}

/** Integration point for expo-auth-session (Google). Resolves a local session for now. */
export async function signInWithGoogle(): Promise<Session> {
  await wait(700);
  return makeSession('google', 'designer@gmail.com', 'Facetta Designer');
}

export async function signInWithEmail(email: string, password: string): Promise<Session> {
  const emailErr = validateEmail(email);
  if (emailErr) throw new Error(emailErr);
  const passErr = validatePassword(password);
  if (passErr) throw new Error(passErr);
  await wait(500);
  return makeSession('email', email);
}

export async function signUpWithEmail(name: string, email: string, password: string): Promise<Session> {
  if (!name.trim()) throw new Error('Enter your name.');
  const emailErr = validateEmail(email);
  if (emailErr) throw new Error(emailErr);
  const passErr = validatePassword(password);
  if (passErr) throw new Error(passErr);
  await wait(500);
  return makeSession('email', email, name);
}

/** Local reset placeholder — it never claims an authenticated API session. */
export async function requestPasswordReset(email: string): Promise<void> {
  const emailErr = validateEmail(email);
  if (emailErr) throw new Error(emailErr);
  await wait(600);
}

// ---------------------------------------------------------------------------
// Tiny persistence layer: localStorage on web, in-memory fallback on native
// (swap for AsyncStorage when it lands in package.json).
// ---------------------------------------------------------------------------

const memory: Record<string, string> = {};

function getItem(key: string): string | null {
  try {
    if (typeof localStorage !== 'undefined') return localStorage.getItem(key);
  } catch {
    // storage unavailable (private mode etc.) — fall through to memory
  }
  return memory[key] ?? null;
}

function setItem(key: string, value: string) {
  try {
    if (typeof localStorage !== 'undefined') {
      localStorage.setItem(key, value);
      return;
    }
  } catch {
    // fall through to memory
  }
  memory[key] = value;
}

function removeItem(key: string) {
  try {
    if (typeof localStorage !== 'undefined') localStorage.removeItem(key);
  } catch {
    // fall through
  }
  delete memory[key];
}

const ONBOARDED_KEY = 'facetta.onboarded';
const SESSION_KEY = 'facetta.session';
let runtimeCredential: SessionCredential | null = null;

export const hasOnboarded = () => getItem(ONBOARDED_KEY) === '1';
export const markOnboarded = () => setItem(ONBOARDED_KEY, '1');

export function loadSession(): Session | null {
  const raw = getItem(SESSION_KEY);
  if (!raw) return null;
  try {
    const s = JSON.parse(raw);
    if (s && typeof s.email === 'string' && typeof s.designerId === 'string') {
      return runtimeCredential === null ? s as Session : {
        ...s,
        accessToken: runtimeCredential.accessToken,
        accessTokenExpiresAt: runtimeCredential.expiresAt,
      } as Session;
    }
  } catch {
    // corrupt — discard
  }
  return null;
}

export function loadAuthenticatedSession(): Session | null {
  const session = loadSession();
  return sessionAccessToken(session) === null ? null : session;
}

export const saveSession = (s: Session) => {
  runtimeCredential = sessionAccessToken(s) === null ? null : {
    accessToken: s.accessToken!, expiresAt: s.accessTokenExpiresAt!,
  };
  const { accessToken: _token, accessTokenExpiresAt: _expires, ...publicSession } = s;
  setItem(SESSION_KEY, JSON.stringify(publicSession));
};
export const clearSession = () => {
  runtimeCredential = null;
  removeItem(SESSION_KEY);
};
