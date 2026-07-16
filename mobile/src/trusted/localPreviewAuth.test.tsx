/// <reference types="jest" />

import React from 'react';
import { act, fireEvent, render } from '@testing-library/react-native';

import {
  clearSession, localPreviewClientAllowed, requestLocalPreviewSession,
  saveSession, type LocalPreviewClientEnvironment, type Session,
} from '../auth';
import { LoginScreen } from '../LoginScreen';


const now = Date.parse('2026-07-17T03:00:00.000Z');
const environment: LocalPreviewClientEnvironment = {
  development: true,
  publicOptIn: true,
  apiUrl: 'http://127.0.0.1:8012',
  webHostname: 'localhost',
};
const runtimeToken = 'local-preview-runtime-token-1234567890';
const localSession: Session = {
  provider: 'local-preview',
  email: 'preview@facetta.local',
  name: 'Local Preview',
  designerId: 'localpreview00000000000000000000',
  accessToken: runtimeToken,
  accessTokenExpiresAt: '2026-07-17T05:00:00.000Z',
};

afterEach(() => clearSession());

test('allows the control only with explicit dev opt-in and loopback page/API', () => {
  expect(localPreviewClientAllowed(environment)).toBe(true);
  expect(localPreviewClientAllowed({ ...environment, development: false })).toBe(false);
  expect(localPreviewClientAllowed({ ...environment, publicOptIn: false })).toBe(false);
  expect(localPreviewClientAllowed({
    ...environment, apiUrl: 'https://api.facetta.example',
  })).toBe(false);
  expect(localPreviewClientAllowed({
    ...environment, webHostname: 'preview.facetta.example',
  })).toBe(false);
  expect(localPreviewClientAllowed({
    ...environment, apiUrl: 'http://user:password@127.0.0.1:8012',
  })).toBe(false);
});

test('exchanges an empty POST for a validated runtime-only session', async () => {
  const fetcher = jest.fn(async (_input: string, _init: unknown) => ({
    ok: true,
    status: 201,
    json: async () => ({
      access_token: runtimeToken,
      expires_at: '2026-07-17T05:00:00.000Z',
      token_type: 'bearer',
      designer_id: 'localpreview00000000000000000000',
    }),
  }));
  const session = await requestLocalPreviewSession({
    environment, fetcher, now,
  });

  expect(fetcher).toHaveBeenCalledWith(
    'http://127.0.0.1:8012/auth/local-preview-session',
    { method: 'POST', headers: { Accept: 'application/json' } },
  );
  expect(JSON.stringify(fetcher.mock.calls[0][1])).not.toMatch(/authorization|password/i);
  expect(session).toEqual(localSession);
});

test('rejects non-loopback calls and malformed or overlong sessions before adoption', async () => {
  await expect(requestLocalPreviewSession({
    environment: { ...environment, apiUrl: 'https://api.facetta.example' },
    fetcher: jest.fn() as any,
    now,
  })).rejects.toThrow(/outside localhost development/i);

  await expect(requestLocalPreviewSession({
    environment,
    fetcher: jest.fn(async () => ({
      ok: true,
      status: 201,
      json: async () => ({
        access_token: runtimeToken,
        expires_at: '2026-07-17T05:02:00.000Z',
        token_type: 'bearer',
        designer_id: 'localpreview00000000000000000000',
      }),
    })),
    now,
  })).rejects.toThrow(/invalid session/i);
});

test('shows one local action instead of unusable email fields and adopts its session', async () => {
  const onSignIn = jest.fn();
  const localPreviewSignIn = jest.fn(async () => localSession);
  const view = await render(
    <LoginScreen
      onSignIn={onSignIn}
      localPreviewSignIn={localPreviewSignIn}
      configurationError="Email sign-in is not configured for this build."
    />,
  );

  expect(view.getByText('Open local Studio')).toBeTruthy();
  expect(view.queryByPlaceholderText('you@studio.com')).toBeNull();
  expect(view.queryByText(/Email sign-in is not configured/)).toBeNull();
  await act(async () => {
    fireEvent.press(view.getByTestId('local-preview-sign-in'));
  });
  expect(localPreviewSignIn).toHaveBeenCalledTimes(1);
  expect(onSignIn).toHaveBeenCalledWith(localSession);
  view.unmount();
});

test('never writes the preview bearer into localStorage', () => {
  const values = new Map<string, string>();
  const previousStorage = (globalThis as any).localStorage;
  Object.defineProperty(globalThis, 'localStorage', {
    configurable: true,
    value: {
      getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, value: string) => values.set(key, value),
      removeItem: (key: string) => values.delete(key),
    },
  });
  try {
    saveSession(localSession);
    expect([...values.values()].join(' ')).not.toContain(runtimeToken);
    expect([...values.values()].join(' ')).not.toContain('accessToken');
  } finally {
    clearSession();
    Object.defineProperty(globalThis, 'localStorage', {
      configurable: true,
      value: previousStorage,
    });
  }
});
