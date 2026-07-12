/// <reference types="jest" />

import { createTrustedApiClient } from './client';

const response = (status: number, body: unknown) => ({
  ok: status >= 200 && status < 300,
  status,
  text: async () => JSON.stringify(body),
}) as unknown as Response;

test('required principal boundary fails locally when the session token is missing', async () => {
  const fetcher = jest.fn();
  const client = createTrustedApiClient({
    baseUrl: 'https://facetta.test', fetcher,
    getAccessToken: () => null, requireAccessToken: true,
  });
  const result = await client.getProject('project_1');
  expect(result.error).toMatchObject({
    code: 'AUTHENTICATION_REQUIRED', category: 'authentication', status: 401,
  });
  expect(fetcher).not.toHaveBeenCalled();
});

test('a server-issued token is sent as the bearer principal', async () => {
  const fetcher = jest.fn(async (_input, init) => {
    expect((init?.headers as Record<string, string>).Authorization).toBe('Bearer first-party-token');
    return response(401, { detail: { code: 'invalid_authentication_token', message: 'Invalid token.' } });
  });
  const client = createTrustedApiClient({
    baseUrl: 'https://facetta.test', fetcher,
    getAccessToken: () => 'first-party-token', requireAccessToken: true,
  });
  const result = await client.getProject('project_1');
  expect(fetcher).toHaveBeenCalledTimes(1);
  expect(result.error).toMatchObject({ category: 'authentication', status: 401 });
});

test('cross-user actor and project denials remain authorization failures', async () => {
  const fetcher = jest.fn(async () => response(403, {
    detail: { code: 'principal_actor_mismatch', message: 'Actor does not match principal.' },
  }));
  const client = createTrustedApiClient({
    baseUrl: 'https://facetta.test', fetcher,
    getAccessToken: () => 'principal-a-token', requireAccessToken: true,
  });
  const result = await client.getProject('owned-by-principal-b');
  expect(result.error).toMatchObject({
    code: 'principal_actor_mismatch', category: 'authorization', status: 403,
  });
  expect(result.error?.retryable).toBe(false);
});
