/// <reference types="jest" />

import {
  attachServerCredential, clearSession, loadAuthenticatedSession,
  saveSession, sessionAccessToken,
} from '../auth';

afterEach(() => clearSession());

const profile = {
  provider: 'email' as const,
  email: 'designer@example.com',
  name: 'Designer',
  designerId: 'usr_designer',
};

test('identity labels never become an API credential', () => {
  expect(sessionAccessToken(profile)).toBeNull();
  saveSession(profile);
  expect(loadAuthenticatedSession()).toBeNull();
});

test('only a non-expired server-issued credential authenticates a session', () => {
  const session = attachServerCredential(profile, {
    accessToken: 'server-issued-token', expiresAt: '2099-01-01T00:00:00Z',
  });
  saveSession(session);
  expect(sessionAccessToken(loadAuthenticatedSession())).toBe('server-issued-token');
  expect(sessionAccessToken(session, Date.parse('2100-01-01T00:00:00Z'))).toBeNull();
});

test('expired credentials are not restored as authenticated sessions', () => {
  const session = attachServerCredential(profile, {
    accessToken: 'expired-server-token', expiresAt: '2020-01-01T00:00:00Z',
  });
  saveSession(session);
  expect(loadAuthenticatedSession()).toBeNull();
});
