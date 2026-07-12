/// <reference types="jest" />

import React from 'react';
import { fireEvent, render } from '@testing-library/react-native';

import { facettaSessionFromSupabase, safeAuthMessage } from '../auth';
import { LoginScreen } from '../LoginScreen';

const session = {
  provider: 'email' as const,
  email: 'designer@example.com',
  name: 'Studio Designer',
  designerId: '123e4567e89b12d3a456426614174000',
  accessToken: 'runtime-supabase-token',
  accessTokenExpiresAt: '2099-01-01T00:00:00.000Z',
};

const baseAuthService = {
  requestPasswordReset: jest.fn(async () => {}),
  signInWithEmail: jest.fn(async () => session),
  signUpWithEmail: jest.fn(async () => ({
    kind: 'confirmation_required' as const, email: 'ana@example.com',
  })),
};

test('maps only a real Supabase session into the existing runtime Bearer seam', () => {
  const mapped = facettaSessionFromSupabase({
    access_token: 'runtime-supabase-token',
    refresh_token: 'refresh-token-owned-by-supabase-storage',
    expires_at: 4_070_908_800,
    expires_in: 3600,
    token_type: 'bearer',
    user: {
      id: '123e4567-e89b-12d3-a456-426614174000',
      email: 'designer@example.com',
      user_metadata: { full_name: 'Studio Designer' },
      app_metadata: {}, aud: 'authenticated', created_at: '2026-07-13T00:00:00Z',
    },
  } as any);
  expect(mapped).toMatchObject(session);
  expect(JSON.stringify(mapped)).not.toContain('refresh-token-owned-by-supabase-storage');
});

test('confirmation-required signup stays on login and tells the user to check email', async () => {
  const onSignIn = jest.fn();
  const view = await render(
    <LoginScreen
      onSignIn={onSignIn}
      authService={baseAuthService}
      configurationError={null}
    />,
  );
  await fireEvent.press(view.getByText('Create an account'));
  await fireEvent.changeText(await view.findByPlaceholderText('Ana Moreau'), 'Ana Moreau');
  await fireEvent.changeText(view.getByPlaceholderText('you@studio.com'), 'ana@example.com');
  await fireEvent.changeText(view.getByPlaceholderText('At least 8 characters'), 'correct-password');
  const createButtons = view.getAllByText('Create account');
  await fireEvent.press(createButtons[createButtons.length - 1]);

  expect(await view.findByText(/Check ana@example.com to confirm your account/)).toBeTruthy();
  expect(onSignIn).not.toHaveBeenCalled();
  view.unmount();
});

test('unknown provider error codes map to a generic message without raw details', () => {
  expect(safeAuthMessage('unexpected_provider_failure')).toBe(
    'Facetta could not complete that sign-in request. Try again.',
  );
  expect(safeAuthMessage('unexpected_provider_failure')).not.toMatch(/token|provider_failure/i);
});
