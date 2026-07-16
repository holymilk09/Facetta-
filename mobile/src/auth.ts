// Client-side auth flow for the mobile app.
//
// Supabase Auth owns credential persistence and refresh. Facetta persists only
// public profile fields; access tokens are copied into runtime state solely so
// the typed API and protected-image seams can attach the current Bearer token.

import type { AuthChangeEvent, Session as SupabaseSession } from '@supabase/supabase-js';
import {
  getSupabaseClient, passwordResetRedirectUrl, supabaseConfigurationError,
} from './supabase';

export type AuthProvider = 'apple' | 'google' | 'email' | 'local-preview';

export type SignUpResult =
  | { kind: 'signed_in'; session: Session }
  | { kind: 'confirmation_required'; email: string };

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

export interface LocalPreviewClientEnvironment {
  development: boolean;
  publicOptIn: boolean;
  apiUrl: string;
  /** Defined only on web, where both page and API must be loopback. */
  webHostname?: string;
}

interface LocalPreviewSessionPayload {
  access_token: string;
  expires_at: string;
  token_type: 'bearer';
  designer_id: string;
}

// The API issues a two-hour process-ephemeral credential. One minute of clock
// tolerance keeps validation fail-closed while allowing for request latency.
const LOCAL_PREVIEW_MAX_SESSION_MS = 121 * 60 * 1000;

type LocalPreviewFetch = (
  input: string,
  init: { method: 'POST'; headers: { Accept: 'application/json' } },
) => Promise<{ ok: boolean; status: number; json: () => Promise<unknown> }>;

export interface LocalPreviewSessionRequestOptions {
  environment: LocalPreviewClientEnvironment;
  fetcher?: LocalPreviewFetch;
  now?: number;
}

function isLoopbackHostname(value: string): boolean {
  const hostname = value.trim().toLowerCase().replace(/^\[|\]$/g, '');
  return hostname === 'localhost' || hostname === '127.0.0.1' || hostname === '::1';
}

export function localPreviewClientAllowed(
  environment: LocalPreviewClientEnvironment,
): boolean {
  if (!environment.development || !environment.publicOptIn) return false;
  try {
    const api = new URL(environment.apiUrl);
    if (api.protocol !== 'http:' && api.protocol !== 'https:') return false;
    if (api.username || api.password || !isLoopbackHostname(api.hostname)) return false;
  } catch {
    return false;
  }
  return environment.webHostname === undefined
    || isLoopbackHostname(environment.webHostname);
}

/**
 * Exchange an explicit local click for a process-ephemeral Bearer session.
 * No password is accepted and the returned credential remains runtime-only.
 */
export async function requestLocalPreviewSession(
  options: LocalPreviewSessionRequestOptions,
): Promise<Session> {
  if (!localPreviewClientAllowed(options.environment)) {
    throw new Error('Local preview sign-in is unavailable outside localhost development.');
  }
  const fetcher = options.fetcher ?? (globalThis.fetch as LocalPreviewFetch);
  let response: Awaited<ReturnType<LocalPreviewFetch>>;
  try {
    response = await fetcher(
      `${options.environment.apiUrl.replace(/\/$/, '')}/auth/local-preview-session`,
      { method: 'POST', headers: { Accept: 'application/json' } },
    );
  } catch {
    throw new Error('Facetta could not reach the local preview API.');
  }
  if (!response.ok) {
    throw new Error(response.status === 404
      ? 'Local preview sign-in is not enabled on this API.'
      : 'Facetta could not start a local preview session.');
  }
  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    throw new Error('The local preview API returned an invalid session.');
  }
  if (payload === null || typeof payload !== 'object') {
    throw new Error('The local preview API returned an invalid session.');
  }
  const value = payload as Partial<LocalPreviewSessionPayload>;
  const now = options.now ?? Date.now();
  const expiresAt = typeof value.expires_at === 'string'
    ? Date.parse(value.expires_at) : Number.NaN;
  const token = typeof value.access_token === 'string' ? value.access_token : '';
  if (
    value.token_type !== 'bearer'
    || !/^[a-z0-9_-]{1,32}$/.test(value.designer_id ?? '')
    || token.length < 32
    || token.length > 4096
    || /\s/.test(token)
    || !Number.isFinite(expiresAt)
    || expiresAt <= now + 30_000
    || expiresAt > now + LOCAL_PREVIEW_MAX_SESSION_MS
  ) {
    throw new Error('The local preview API returned an invalid session.');
  }
  return attachServerCredential(
    {
      provider: 'local-preview',
      email: 'preview@facetta.local',
      name: 'Local Preview',
      designerId: value.designer_id!,
    },
    {
      accessToken: token,
      expiresAt: new Date(expiresAt).toISOString(),
    },
  );
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

function makeSession(provider: AuthProvider, email: string, designerId: string, name?: string): Session {
  const clean = email.trim().toLowerCase();
  return {
    provider,
    email: clean,
    name: name?.trim() || nameFromEmail(clean),
    designerId,
  };
}

function requireClient() {
  const client = getSupabaseClient();
  if (client === null) throw new Error(supabaseConfigurationError ?? 'Email sign-in is unavailable.');
  return client;
}

export function safeAuthMessage(code?: string): string {
  if (code === 'invalid_credentials') return 'The email or password is incorrect.';
  if (code === 'email_not_confirmed') return 'Confirm your email before signing in.';
  if (code === 'user_already_exists' || code === 'email_exists') return 'An account already exists for this email.';
  if (code === 'weak_password') return 'Choose a stronger password with at least 8 characters.';
  if (code === 'over_request_rate_limit' || code === 'over_email_send_rate_limit') {
    return 'Too many attempts. Wait a moment and try again.';
  }
  return 'Facetta could not complete that sign-in request. Try again.';
}

function compactDesignerId(subject: string): string {
  const compact = subject.replace(/-/g, '').toLowerCase();
  if (!/^[a-f0-9]{32}$/.test(compact)) {
    throw new Error('Facetta could not verify this account.');
  }
  return compact;
}

export function facettaSessionFromSupabase(session: SupabaseSession): Session {
  const email = session.user.email?.trim().toLowerCase();
  if (!email || !session.access_token || typeof session.expires_at !== 'number') {
    throw new Error('Facetta could not verify this account.');
  }
  const fullName = typeof session.user.user_metadata?.full_name === 'string'
    ? session.user.user_metadata.full_name : undefined;
  return attachServerCredential(
    makeSession('email', email, compactDesignerId(session.user.id), fullName),
    {
      accessToken: session.access_token,
      expiresAt: new Date(session.expires_at * 1000).toISOString(),
    },
  );
}

export async function signInWithEmail(email: string, password: string): Promise<Session> {
  const emailErr = validateEmail(email);
  if (emailErr) throw new Error(emailErr);
  const passErr = validatePassword(password);
  if (passErr) throw new Error(passErr);
  const { data, error } = await requireClient().auth.signInWithPassword({
    email: email.trim().toLowerCase(), password,
  });
  if (error) throw new Error(safeAuthMessage(error.code));
  if (data.session === null) throw new Error('Confirm your email before signing in.');
  return facettaSessionFromSupabase(data.session);
}

export async function signUpWithEmail(name: string, email: string, password: string): Promise<SignUpResult> {
  if (!name.trim()) throw new Error('Enter your name.');
  const emailErr = validateEmail(email);
  if (emailErr) throw new Error(emailErr);
  const passErr = validatePassword(password);
  if (passErr) throw new Error(passErr);
  const cleanEmail = email.trim().toLowerCase();
  const { data, error } = await requireClient().auth.signUp({
    email: cleanEmail,
    password,
    options: { data: { full_name: name.trim() } },
  });
  if (error) throw new Error(safeAuthMessage(error.code));
  if (data.session === null) return { kind: 'confirmation_required', email: cleanEmail };
  return { kind: 'signed_in', session: facettaSessionFromSupabase(data.session) };
}

export async function requestPasswordReset(email: string): Promise<void> {
  const emailErr = validateEmail(email);
  if (emailErr) throw new Error(emailErr);
  const { error } = await requireClient().auth.resetPasswordForEmail(email.trim().toLowerCase(), {
    redirectTo: passwordResetRedirectUrl(),
  });
  if (error) throw new Error(safeAuthMessage(error.code));
}

export async function updatePassword(password: string): Promise<void> {
  const passErr = validatePassword(password);
  if (passErr) throw new Error(passErr);
  const { error } = await requireClient().auth.updateUser({ password });
  if (error) throw new Error(safeAuthMessage(error.code));
}

export async function restoreAuthenticatedSession(): Promise<Session | null> {
  const runtime = loadAuthenticatedSession();
  if (runtime !== null) return runtime;
  const client = getSupabaseClient();
  if (client === null) return null;
  const { data, error } = await client.auth.getSession();
  if (error || data.session === null) return null;
  try { return facettaSessionFromSupabase(data.session); } catch { return null; }
}

export function subscribeToAuthStateChange(
  listener: (event: AuthChangeEvent, session: Session | null) => void,
): () => void {
  const client = getSupabaseClient();
  if (client === null) return () => {};
  const { data } = client.auth.onAuthStateChange((event, next) => {
    let mapped: Session | null = null;
    if (next !== null) {
      try { mapped = facettaSessionFromSupabase(next); } catch { mapped = null; }
    }
    listener(event, mapped);
  });
  return () => data.subscription.unsubscribe();
}

export async function signOutAuthenticatedSession(): Promise<void> {
  const client = getSupabaseClient();
  try {
    if (client !== null) {
      const { error } = await client.auth.signOut();
      if (error) await client.auth.signOut({ scope: 'local' });
    }
  } finally {
    clearSession();
  }
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
