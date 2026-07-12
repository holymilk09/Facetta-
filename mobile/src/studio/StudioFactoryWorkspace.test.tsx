import React from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react-native';

import { StudioFactoryWorkspace } from './StudioFactoryWorkspace';

const lineage = {
  projectId: 'project_1', sourceAssetId: 'asset_7', sourceDesignVersion: 4,
};

const manifest = {
  project_id: 'project_1', design_id: 'design_1', design_version: 4,
  pinned_asset_id: 'asset_7', approver: 'designer', approved_at: '2026-07-13T00:00:00Z',
  checklist_id: 'check_1', qa: null, dimensions: { has_estimates: false, estimated_fields: [], disclaimer: null },
  factory_sheet_fact_plan: {
    schema_version: 'facetta.factory-sheet-plan.v1' as const, jewelry_type: 'ring', template: 'ring',
    materials: [], stones: [], settings: [], recorded_facts: [], dimensions: [],
    confirmed_fact_count: 12, estimated_fact_count: 0, pending_confirmation_count: 1,
    has_estimates: false, estimate_disclaimer: null,
  },
  artifacts: [{ name: 'review-sheet.svg', media_type: 'image/svg+xml', sha256: 'a'.repeat(64), url: 'https://test/pack', authoritative: false }],
  bundle_url: 'https://test/pack', manifest_sha256: 'b'.repeat(64),
};

const job = (status: string) => ({
  job_id: 'job_1', owner: 'designer', action_id: 'factory' as const,
  lane: 'trusted_structural' as const, status, progress: status === 'succeeded' ? 1 : 0.05,
  active_design_id: 'project_1', source_revision_id: 'asset_7', error_code: null,
  created_at: '2026-07-13T00:00:00Z', updated_at: '2026-07-13T00:00:00Z',
  billing: { requested_outputs: 1, credits_per_output: 28, estimated_credits: 28,
    completed_outputs: status === 'succeeded' ? 1 : 0, charged_outputs: status === 'succeeded' ? 1 : 0,
    charged_credits: status === 'succeeded' ? 28 : 0, policy: 'accepted outputs only' },
});

describe('StudioFactoryWorkspace', () => {
  test('prepares an exact review pack through a transparently billed Factory job', async () => {
    const createStudioJob = jest.fn(async () => ({ data: job('queued'), error: null, status: 201 }));
    const transitionStudioJob = jest.fn(async (_id, request) => ({ data: job(request.status), error: null, status: 200 }));
    const getFactoryPack = jest.fn(async () => ({ data: manifest, error: null, status: 200 }));
    await render(<StudioFactoryWorkspace api={{ createStudioJob, transitionStudioJob, getFactoryPack } as any}
      lineage={lineage} createdBy="designer" />);

    expect(screen.getByText('1 requested output × 28 credits = estimated 28 credits')).toBeTruthy();
    await act(async () => { fireEvent.press(screen.getByText('Prepare production-review material')); });
    await waitFor(() => expect(screen.getByText('Review material prepared')).toBeTruthy());
    expect(createStudioJob).toHaveBeenCalledWith(expect.objectContaining({
      active_design_id: 'project_1', source_revision_id: 'asset_7', credits_per_output: 28,
    }));
    expect(transitionStudioJob).toHaveBeenLastCalledWith('job_1', expect.objectContaining({
      status: 'succeeded', completed_outputs: 1,
    }));
    expect(screen.getByText('review-sheet.svg')).toBeTruthy();
    expect(screen.queryByText(/provider|QA/i)).toBeNull();
  });

  test('fails closed and records zero-output failure when pack lineage mismatches', async () => {
    const transitionStudioJob = jest.fn(async (_id, request) => ({ data: job(request.status), error: null, status: 200 }));
    await render(<StudioFactoryWorkspace api={{
      createStudioJob: jest.fn(async () => ({ data: job('queued'), error: null, status: 201 })),
      transitionStudioJob,
      getFactoryPack: jest.fn(async () => ({ data: { ...manifest, pinned_asset_id: 'asset_other' }, error: null, status: 200 })),
    } as any} lineage={lineage} createdBy="designer" />);
    await act(async () => { fireEvent.press(screen.getByText('Prepare production-review material')); });
    expect(await screen.findByText(/did not match the selected revision/i)).toBeTruthy();
    expect(transitionStudioJob).toHaveBeenLastCalledWith('job_1', expect.objectContaining({ status: 'failed' }));
    expect(screen.queryByText('Review material prepared')).toBeNull();
  });
});
