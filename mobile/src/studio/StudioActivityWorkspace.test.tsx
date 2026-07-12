/// <reference types="jest" />

import React from 'react';
import { act, fireEvent, render, waitFor } from '@testing-library/react-native';

import type { StudioJobRecord } from '../trusted/types';
import {
  StudioActivityWorkspace,
  type StudioActivityApi,
} from './StudioActivityWorkspace';

const running: StudioJobRecord = {
  job_id: 'job_create', owner: 'usr_designer', action_id: 'create',
  lane: 'fast_visual', status: 'running', progress: 0.4,
  active_design_id: 'design_ring', source_revision_id: null, error_code: null,
  created_at: '2026-07-12T01:00:00Z', updated_at: '2026-07-12T01:01:00Z',
  billing: {
    requested_outputs: 4, credits_per_output: 7, estimated_credits: 28,
    completed_outputs: 0, charged_outputs: 0, charged_credits: 0,
    policy: 'Only requested outputs that complete successfully are charged. Internal retries are included.',
  },
};

function api(overrides: Partial<StudioActivityApi> = {}): StudioActivityApi {
  return {
    listStudioJobs: jest.fn(async () => ({
      data: { jobs: [running] }, error: null, status: 200,
    })),
    cancelStudioJob: jest.fn(async () => ({
      data: { ...running, status: 'canceled' as const }, error: null, status: 200,
    })),
    ...overrides,
  } as StudioActivityApi;
}

describe('StudioActivityWorkspace', () => {
  test('loads only the current owner and explains requested-output billing', async () => {
    const client = api();
    const view = await render(<StudioActivityWorkspace api={client} owner="usr_designer" />);

    expect(await view.findByText('Create directions')).toBeTruthy();
    expect(view.getByText('4 outputs requested · up to 28 credits')).toBeTruthy();
    expect(view.getByText('You pay only for usable requested outputs. Unsuccessful results cost 0 credits.')).toBeTruthy();
    expect(view.queryByText(/Internal retries/i)).toBeNull();
    expect(client.listStudioJobs).toHaveBeenCalledWith('usr_designer');
    expect(view.queryByText(/provider/i)).toBeNull();
    expect(view.queryByText(/model/i)).toBeNull();
  });

  test('cancels a running request without inventing a charge', async () => {
    const client = api();
    const view = await render(<StudioActivityWorkspace api={client} owner="usr_designer" />);
    await act(async () => {
      fireEvent.press(await view.findByText('Cancel request'));
    });

    await waitFor(() => expect(client.cancelStudioJob).toHaveBeenCalledWith(
      'job_create', 'usr_designer',
    ));
    expect(await view.findByText('Canceled')).toBeTruthy();
    expect(view.getByText('0 credits charged · 4 outputs requested')).toBeTruthy();
  });

  test('keeps a failed job honest and leaves saved work unchanged', async () => {
    const failed: StudioJobRecord = {
      ...running, status: 'failed', progress: 0.6,
      error_code: 'generation_unavailable',
    };
    const client = api({
      listStudioJobs: jest.fn(async () => ({
        data: { jobs: [failed] }, error: null, status: 200,
      })),
    });
    const view = await render(<StudioActivityWorkspace api={client} owner="usr_designer" />);

    expect(await view.findByText('Did not finish')).toBeTruthy();
    expect(view.getByText(/saved design is unchanged/i)).toBeTruthy();
    expect(view.queryByText('generation_unavailable')).toBeNull();
  });

  test('does not misreport an empty history when Activity is unavailable', async () => {
    const client = api({
      listStudioJobs: jest.fn(async () => ({
        data: null,
        error: {
          code: 'NETWORK_ERROR', message: 'Activity is temporarily unavailable.',
          category: 'network' as const, status: 0, retryable: true,
        },
        status: 0,
      })),
    });
    const view = await render(<StudioActivityWorkspace api={client} owner="usr_designer" />);

    expect(await view.findByText('Facetta could not connect. Check your connection and try again.')).toBeTruthy();
    expect(view.queryByText('Nothing is running yet')).toBeNull();
  });
});
