/// <reference types="jest" />

import React from 'react';
import { render, waitFor } from '@testing-library/react-native';

import { clearSession, markOnboarded, saveSession } from '../auth';

const mockListDesignFamilies = jest.fn();

jest.mock('../trusted/client', () => ({
  createTrustedApiClient: () => ({
    listDesignFamilies: mockListDesignFamilies,
    getStudioCapabilities: async () => ({
      data: {
        factory_review: { enabled: false, scope: 'none' },
        workspace_entitlements_available: false,
      },
      error: null,
      status: 200,
    }),
  }),
}));

import App from '../../App';

beforeEach(() => {
  mockListDesignFamilies.mockResolvedValue({
    data: { families: [] }, error: null, status: 200,
  });
});

afterEach(() => {
  clearSession();
  mockListDesignFamilies.mockReset();
});

test('signed-in Studio home offers one start decision without a duplicate feature menu', async () => {
  markOnboarded();
  saveSession({
    provider: 'email', email: 'designer@example.com', name: 'Designer',
    designerId: 'usr_designer',
    accessToken: 'server-issued-test-token',
    accessTokenExpiresAt: '2099-01-01T00:00:00Z',
  });
  const view = await render(<App />);

  await waitFor(() => expect(view.getByText('Start from an idea or reference')).toBeTruthy());
  await waitFor(() => expect(mockListDesignFamilies).toHaveBeenCalledWith('usr_designer'));
  expect(view.queryByLabelText('Continue saved work')).toBeNull();
  expect(view.queryByText('Creative studios')).toBeNull();
  expect(view.queryByText('Preserve a new direction')).toBeNull();
  expect(view.queryByText('Prepare presentation imagery')).toBeNull();
  expect(view.queryByText(/Builder|Share design|Factory/i)).toBeNull();
  expect(view.queryByText(/Developer connection|API URL|designer id/i)).toBeNull();
  expect(view.queryByLabelText('Create')).toBeNull();
  view.unmount();
});

test('Studio home offers saved-work continuation only when the account has a saved family', async () => {
  mockListDesignFamilies.mockResolvedValue({
    data: { families: [{ family_id: 'family_saved' }] }, error: null, status: 200,
  });
  markOnboarded();
  saveSession({
    provider: 'email', email: 'designer@example.com', name: 'Designer',
    designerId: 'usr_designer',
    accessToken: 'server-issued-test-token',
    accessTokenExpiresAt: '2099-01-01T00:00:00Z',
  });
  const view = await render(<App />);

  expect(await view.findByLabelText('Continue saved work')).toBeTruthy();
  view.unmount();
});

test('Studio home makes no saved-work claim when family availability cannot be verified', async () => {
  mockListDesignFamilies.mockRejectedValue(new Error('network unavailable'));
  markOnboarded();
  saveSession({
    provider: 'email', email: 'designer@example.com', name: 'Designer',
    designerId: 'usr_designer',
    accessToken: 'server-issued-test-token',
    accessTokenExpiresAt: '2099-01-01T00:00:00Z',
  });
  const view = await render(<App />);

  await waitFor(() => expect(mockListDesignFamilies).toHaveBeenCalledWith('usr_designer'));
  expect(view.queryByLabelText('Continue saved work')).toBeNull();
  expect(view.getByText('Start from an idea or reference')).toBeTruthy();
  view.unmount();
});

test('a persisted profile without a server credential remains at login', async () => {
  markOnboarded();
  saveSession({
    provider: 'email', email: 'profile@example.com', name: 'Profile',
    designerId: 'usr_profile',
  });
  const view = await render(<App />);
  await waitFor(() => expect(view.getByText('Continue to Facetta')).toBeTruthy());
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
  await waitFor(() => expect(view.getByText('Continue to Facetta')).toBeTruthy());
  expect(view.queryByText('Start from an idea or reference')).toBeNull();
  view.unmount();
});
