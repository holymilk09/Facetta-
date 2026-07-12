/// <reference types="jest" />

import React from 'react';
import { render } from '@testing-library/react-native';

import App from '../../App';
import { clearSession, markOnboarded, saveSession } from '../auth';

afterEach(() => clearSession());

test('signed-in Studio home offers one start decision without a duplicate feature menu', async () => {
  saveSession({
    provider: 'email', email: 'designer@example.com', name: 'Designer',
    designerId: 'usr_designer',
    accessToken: 'server-issued-test-token',
    accessTokenExpiresAt: '2099-01-01T00:00:00Z',
  });
  const view = await render(<App />);

  expect(view.getByText('Start from an idea or reference')).toBeTruthy();
  expect(view.queryByText('Creative studios')).toBeNull();
  expect(view.queryByText('Preserve a new direction')).toBeNull();
  expect(view.queryByText('Prepare presentation imagery')).toBeNull();
  expect(view.queryByText(/Builder|Share design|Factory/i)).toBeNull();
  expect(view.queryByText(/Developer connection|API URL|designer id/i)).toBeNull();
  expect(view.queryByLabelText('Create')).toBeNull();
  view.unmount();
});

test('a persisted profile without a server credential remains at login', async () => {
  markOnboarded();
  saveSession({
    provider: 'email', email: 'profile@example.com', name: 'Profile',
    designerId: 'usr_profile',
  });
  const view = await render(<App />);
  expect(view.getByText('Continue to Facetta')).toBeTruthy();
  expect(view.queryByText('Start from an idea or reference')).toBeNull();
  view.unmount();
});

test('an expired server credential remains at login', async () => {
  markOnboarded();
  saveSession({
    provider: 'email', email: 'expired@example.com', name: 'Expired',
    designerId: 'usr_expired', accessToken: 'expired-server-token',
    accessTokenExpiresAt: '2020-01-01T00:00:00Z',
  });
  const view = await render(<App />);
  expect(view.getByText('Continue to Facetta')).toBeTruthy();
  expect(view.queryByText('Start from an idea or reference')).toBeNull();
  view.unmount();
});
