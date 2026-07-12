/// <reference types="jest" />

const mockUnsubscribe = jest.fn();
const mockAuth = {
  signInWithPassword: jest.fn(),
  signUp: jest.fn(),
  resetPasswordForEmail: jest.fn(),
  updateUser: jest.fn(),
  getSession: jest.fn(),
  onAuthStateChange: jest.fn(),
  signOut: jest.fn(),
};

jest.mock('../supabase', () => ({
  getSupabaseClient: () => ({ auth: mockAuth }),
  passwordResetRedirectUrl: () => 'facetta://auth/reset-password',
  supabaseConfigurationError: null,
}));

import {
  requestPasswordReset,
  safeAuthMessage,
  signInWithEmail,
  signOutAuthenticatedSession,
  signUpWithEmail,
  subscribeToAuthStateChange,
} from '../auth';

const supabaseSession = {
  access_token: 'signed-access-token',
  refresh_token: 'private-refresh-token',
  expires_at: 4_070_908_800,
  expires_in: 3600,
  token_type: 'bearer',
  user: {
    id: '123e4567-e89b-12d3-a456-426614174000',
    email: 'designer@example.com',
    user_metadata: { full_name: 'Studio Designer' },
    app_metadata: {}, aud: 'authenticated', created_at: '2026-07-13T00:00:00Z',
  },
};

beforeEach(() => {
  jest.clearAllMocks();
  mockAuth.onAuthStateChange.mockReturnValue({
    data: { subscription: { unsubscribe: mockUnsubscribe } },
  });
  mockAuth.signOut.mockResolvedValue({ error: null });
});

test('email sign-in uses Supabase and returns only the canonical Facetta session', async () => {
  mockAuth.signInWithPassword.mockResolvedValue({
    data: { session: supabaseSession }, error: null,
  });
  const session = await signInWithEmail('Designer@Example.com', 'password-123');
  expect(mockAuth.signInWithPassword).toHaveBeenCalledWith({
    email: 'designer@example.com', password: 'password-123',
  });
  expect(session.designerId).toBe('123e4567e89b12d3a456426614174000');
  expect(session.accessToken).toBe('signed-access-token');
  expect(JSON.stringify(session)).not.toContain('private-refresh-token');
});

test('confirmation-required signup never invents an authenticated session', async () => {
  mockAuth.signUp.mockResolvedValue({
    data: { session: null, user: supabaseSession.user }, error: null,
  });
  await expect(signUpWithEmail(
    'Ana Moreau', 'ANA@example.com', 'password-123',
  )).resolves.toEqual({
    kind: 'confirmation_required', email: 'ana@example.com',
  });
  expect(mockAuth.signUp).toHaveBeenCalledWith({
    email: 'ana@example.com',
    password: 'password-123',
    options: { data: { full_name: 'Ana Moreau' } },
  });
});

test('password reset uses the registered recovery route and hides provider detail', async () => {
  mockAuth.resetPasswordForEmail.mockResolvedValue({ error: null });
  await requestPasswordReset('designer@example.com');
  expect(mockAuth.resetPasswordForEmail).toHaveBeenCalledWith(
    'designer@example.com',
    { redirectTo: 'facetta://auth/reset-password' },
  );
  expect(safeAuthMessage('raw-provider-secret')).toBe(
    'Facetta could not complete that sign-in request. Try again.',
  );
});

test('auth-state refresh maps the next token and unsubscribe remains explicit', () => {
  const listener = jest.fn();
  const unsubscribe = subscribeToAuthStateChange(listener);
  const callback = mockAuth.onAuthStateChange.mock.calls[0][0];
  callback('TOKEN_REFRESHED', supabaseSession);
  expect(listener).toHaveBeenCalledWith(
    'TOKEN_REFRESHED',
    expect.objectContaining({ accessToken: 'signed-access-token' }),
  );
  unsubscribe();
  expect(mockUnsubscribe).toHaveBeenCalled();
});

test('signout falls back to local session removal when remote revocation fails', async () => {
  mockAuth.signOut
    .mockResolvedValueOnce({ error: { message: 'network unavailable' } })
    .mockResolvedValueOnce({ error: null });
  await signOutAuthenticatedSession();
  expect(mockAuth.signOut).toHaveBeenNthCalledWith(1);
  expect(mockAuth.signOut).toHaveBeenNthCalledWith(2, { scope: 'local' });
});
