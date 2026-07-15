import React from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react-native';

import {
  buildStudioFactoryPolicy, deliverAuthenticatedProtectedFile, StudioFactoryWorkspace,
} from './StudioFactoryWorkspace';
import { getStudioAction } from './actions';
import { getStudioWorkspaceControls } from './workspaceControls';

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

const approvedChecklist = {
  checklist_id: 'check_1', asset_id: 'asset_7', design_id: 'design_1', design_version: 4,
  mode: 'auto_pin' as const,
  items: [{ key: 'identity', label: 'Design identity', fact: 'Halo ring', section: 'identity', ref: null, index: null, target_element_id: null }],
  answers: { identity: { item_key: 'identity', approved: true, note: null, understood_as: null, created_by: 'designer', created_at: '2026-07-13T00:00:00Z' } },
  outstanding: [], approved_count: 1, total: 1, completed: true, all_approved: true, pinned: true,
};

const readyProject = {
  root_id: 'project_1', active_asset_id: 'asset_7', active_design_version: 4,
  pinned_revision: { asset_id: 'asset_7', design_version: 4 },
  approval: approvedChecklist, factory_ready: true, factory_blockers: [],
};

const withReadiness = (api: Record<string, unknown>, project: any = readyProject) => ({
  getProject: jest.fn(async () => ({ data: project, error: null, status: 200 })),
  createChecklist: jest.fn(async () => ({ data: approvedChecklist, error: null, status: 201 })),
  respondChecklist: jest.fn(async () => ({ data: approvedChecklist, error: null, status: 201 })),
  ...api,
});

const job = (status: string) => ({
  job_id: 'job_1', owner: 'designer', action_id: 'factory' as const,
  lane: 'trusted_structural' as const, status, progress: status === 'succeeded' ? 1 : 0.05,
  active_design_id: 'project_1', source_revision_id: 'asset_7',
  accepted_output_sha256: status === 'succeeded' ? 'a'.repeat(64) : null,
  error_code: null,
  created_at: '2026-07-13T00:00:00Z', updated_at: '2026-07-13T00:00:00Z',
  billing: { requested_outputs: 1, credits_per_output: 28, estimated_credits: 28,
    completed_outputs: status === 'succeeded' ? 1 : 0, charged_outputs: status === 'succeeded' ? 1 : 0,
    charged_credits: status === 'succeeded' ? 28 : 0, policy: 'accepted outputs only' },
});

describe('StudioFactoryWorkspace', () => {
  test('derives optional Factory billing and routing only from the canonical manifest', () => {
    const action = getStudioAction('factory');
    const controls = getStudioWorkspaceControls('factory');
    expect(buildStudioFactoryPolicy(action, controls)).toEqual({
      lane: 'trusted_structural',
      requestedOutputs: 1,
      creditsPerOutput: 28,
      estimatedCredits: 28,
    });
    expect(buildStudioFactoryPolicy({ ...action, lane: null }, controls)).toBeNull();
    expect(buildStudioFactoryPolicy({ ...action, lane: 'fast_visual' }, controls)).toBeNull();
    expect(buildStudioFactoryPolicy({
      ...action, executionMode: 'candidate_job', reviewAuthority: 'candidate_decision',
    }, controls)).toBeNull();
    expect(buildStudioFactoryPolicy({
      ...action, authority: 'visual_preview',
    }, controls)).toBeNull();
    expect(buildStudioFactoryPolicy(
      action,
      { ...controls, requestedOutputChoices: [2] },
    )).toBeNull();
  });

  test('prepares an exact review pack through a transparently billed Factory job', async () => {
    const createStudioJob = jest.fn(async () => ({ data: job('queued'), error: null, status: 201 }));
    const prepareFactoryPack = jest.fn(async () => ({ data: manifest, error: null, status: 200 }));
    const deliverProtectedFile = jest.fn(async () => {});
    const readinessApi = withReadiness({ createStudioJob, prepareFactoryPack });
    await render(<StudioFactoryWorkspace api={readinessApi as any}
      lineage={lineage} createdBy="designer" deliverProtectedFile={deliverProtectedFile} />);

    expect(screen.getByText('The exact saved revision is selected for this readiness review.')).toBeTruthy();
    expect(screen.queryByText(/(?:Version|Design v)\s*4/i)).toBeNull();
    await waitFor(() => expect(readinessApi.getProject).toHaveBeenCalledWith('project_1'));
    expect(screen.getByText('1 requested output × 28 credits = estimated 28 credits')).toBeTruthy();
    expect(screen.getByText('You pay only for a usable requested output. Unsuccessful results cost 0 credits.')).toBeTruthy();
    expect(screen.queryByText(/internal retries/i)).toBeNull();
    await act(async () => { fireEvent.press(screen.getByText('Prepare factory review material')); });
    await waitFor(() => expect(screen.getByText('Review material prepared')).toBeTruthy());
    expect(createStudioJob).toHaveBeenCalledWith(expect.objectContaining({
      action_id: 'factory', lane: 'trusted_structural',
      active_design_id: 'project_1', source_revision_id: 'asset_7',
      requested_outputs: 1, credits_per_output: 28,
    }));
    expect(prepareFactoryPack).toHaveBeenCalledWith('project_1', {
      studio_job_id: 'job_1', owner: 'designer',
    });
    expect(screen.getByText('review-sheet.svg')).toBeTruthy();
    await act(async () => { fireEvent.press(screen.getByText('Open review-sheet.svg')); });
    expect(deliverProtectedFile).toHaveBeenCalledWith({
      url: 'https://test/pack', name: 'review-sheet.svg', mediaType: 'image/svg+xml',
    });
    await act(async () => { fireEvent.press(screen.getByText('Download complete review pack')); });
    expect(deliverProtectedFile).toHaveBeenCalledWith({
      url: 'https://test/pack', name: 'facetta-factory-review.zip', mediaType: 'application/zip',
    });
    expect(screen.queryByText(/provider|QA/i)).toBeNull();
  });

  test('fails closed when a malformed pack response mismatches exact lineage', async () => {
    await render(<StudioFactoryWorkspace api={withReadiness({
      createStudioJob: jest.fn(async () => ({ data: job('queued'), error: null, status: 201 })),
      prepareFactoryPack: jest.fn(async () => ({ data: { ...manifest, pinned_asset_id: 'asset_other' }, error: null, status: 200 })),
    }) as any} lineage={lineage} createdBy="designer" deliverProtectedFile={jest.fn()} />);
    await act(async () => { fireEvent.press(screen.getByText('Prepare factory review material')); });
    expect(await screen.findByText(/did not match the selected revision/i)).toBeTruthy();
    expect(screen.queryByText('Review material prepared')).toBeNull();
  });

  test('file delivery failure is retryable without a new job, history mutation, or charge', async () => {
    const createStudioJob = jest.fn(async () => ({ data: job('queued'), error: null, status: 201 }));
    const deliverProtectedFile = jest.fn()
      .mockRejectedValueOnce(new Error('network'))
      .mockResolvedValueOnce(undefined);
    await render(<StudioFactoryWorkspace api={withReadiness({
      createStudioJob,
      prepareFactoryPack: jest.fn(async () => ({ data: manifest, error: null, status: 200 })),
    }) as any} lineage={lineage} createdBy="designer" deliverProtectedFile={deliverProtectedFile} />);

    await waitFor(() => expect(screen.getByText('Prepare factory review material')).toBeTruthy());

    await act(async () => { fireEvent.press(screen.getByText('Prepare factory review material')); });
    await act(async () => { fireEvent.press(screen.getByText('Open review-sheet.svg')); });
    expect(await screen.findByText(/credit record are unchanged/i)).toBeTruthy();
    expect(createStudioJob).toHaveBeenCalledTimes(1);

    await act(async () => { fireEvent.press(screen.getByText('Retry protected file')); });
    expect(deliverProtectedFile).toHaveBeenCalledTimes(2);
    expect(createStudioJob).toHaveBeenCalledTimes(1);
    expect(screen.queryByText(/credit record are unchanged/i)).toBeNull();
  });

  test('moves an unready exact ring through checklist, pinning, and pack preparation', async () => {
    const pendingChecklist = {
      ...approvedChecklist,
      answers: {}, outstanding: ['identity'], approved_count: 0,
      completed: false, all_approved: false, pinned: false,
    };
    const blockedProject = {
      ...readyProject,
      pinned_revision: null,
      approval: null,
      factory_ready: false,
      factory_blockers: [],
    };
    const reviewingProject = { ...blockedProject, approval: pendingChecklist };
    const getProject = jest.fn()
      .mockResolvedValueOnce({ data: blockedProject, error: null, status: 200 })
      .mockResolvedValueOnce({ data: reviewingProject, error: null, status: 200 })
      .mockResolvedValueOnce({ data: readyProject, error: null, status: 200 });
    const createChecklist = jest.fn(async () => ({ data: pendingChecklist, error: null, status: 201 }));
    const respondChecklist = jest.fn(async () => ({ data: approvedChecklist, error: null, status: 201 }));
    const createStudioJob = jest.fn(async () => ({
      data: job('queued'), error: null, status: 201,
    }));
    const prepareFactoryPack = jest.fn(async () => ({
      data: manifest, error: null, status: 200,
    }));
    const onProjectUpdated = jest.fn();
    await render(<StudioFactoryWorkspace api={{
      getProject, createChecklist, respondChecklist,
      createStudioJob, prepareFactoryPack,
    } as any} lineage={lineage} createdBy="designer" deliverProtectedFile={jest.fn()}
    onProjectUpdated={onProjectUpdated} />);

    expect(await screen.findByText('Start exact-fact checklist')).toBeTruthy();
    expect(screen.queryByText('Prepare factory review material')).toBeNull();
    expect(createStudioJob).not.toHaveBeenCalled();
    expect(prepareFactoryPack).not.toHaveBeenCalled();

    await act(async () => { fireEvent.press(screen.getByText('Start exact-fact checklist')); });
    expect(await screen.findByText('Confirm fact')).toBeTruthy();
    expect(createChecklist).toHaveBeenCalledWith('asset_7', {
      created_by: 'designer', mode: 'auto_pin',
    });
    expect(createStudioJob).not.toHaveBeenCalled();
    expect(prepareFactoryPack).not.toHaveBeenCalled();

    await act(async () => { fireEvent.press(screen.getByText('Confirm fact')); });
    expect(await screen.findByText('Ready for optional Factory preparation')).toBeTruthy();
    expect(screen.getByText('Prepare factory review material')).toBeTruthy();
    expect(respondChecklist).toHaveBeenCalledWith('asset_7', expect.objectContaining({
      item_key: 'identity', approved: true, interpret: false,
    }));
    expect(onProjectUpdated).toHaveBeenLastCalledWith(readyProject);
    expect(createStudioJob).not.toHaveBeenCalled();
    expect(prepareFactoryPack).not.toHaveBeenCalled();

    await act(async () => {
      fireEvent.press(screen.getByText('Prepare factory review material'));
    });
    expect(await screen.findByText('Review material prepared')).toBeTruthy();
    expect(createStudioJob).toHaveBeenCalledWith(expect.objectContaining({
      active_design_id: 'project_1', source_revision_id: 'asset_7',
      requested_outputs: 1,
    }));
    expect(prepareFactoryPack).toHaveBeenCalledWith('project_1', {
      studio_job_id: 'job_1', owner: 'designer',
    });
  });

  test('authenticated delivery fetches same-origin bytes before web or native delivery', async () => {
    const fetcher = jest.fn(async () => ({
      ok: true,
      arrayBuffer: async () => new Uint8Array([1, 2, 3]).buffer,
    }));
    const webDownload = jest.fn();
    await deliverAuthenticatedProtectedFile({
      url: '/projects/project_1/factory-pack.zip',
      name: 'review.zip',
      mediaType: 'application/zip',
    }, {
      apiUrl: 'https://api.facetta.test', accessToken: 'secret-session-token',
      fetcher: fetcher as any, platform: 'web', webDownload,
    });
    expect(fetcher).toHaveBeenCalledWith(
      'https://api.facetta.test/projects/project_1/factory-pack.zip',
      {
        redirect: 'error',
        headers: { Authorization: 'Bearer secret-session-token', Accept: 'application/zip' },
      },
    );
    expect(webDownload).toHaveBeenCalledTimes(1);

    const nativeShare = jest.fn(async () => {});
    await deliverAuthenticatedProtectedFile({
      url: 'https://api.facetta.test/artifact.svg',
      name: 'artifact.svg',
      mediaType: 'image/svg+xml',
    }, {
      apiUrl: 'https://api.facetta.test', accessToken: 'secret-session-token',
      fetcher: fetcher as any, platform: 'ios', nativeShare,
    });
    expect(nativeShare).toHaveBeenCalledTimes(1);
  });

  test('protected delivery rejects missing auth and off-origin URLs before fetch', async () => {
    const fetcher = jest.fn();
    await expect(deliverAuthenticatedProtectedFile({
      url: '/pack.zip', name: 'pack.zip', mediaType: 'application/zip',
    }, {
      apiUrl: 'https://api.facetta.test', accessToken: null, fetcher: fetcher as any,
    })).rejects.toThrow(/sign in again/i);
    await expect(deliverAuthenticatedProtectedFile({
      url: 'https://attacker.test/pack.zip', name: 'pack.zip', mediaType: 'application/zip',
    }, {
      apiUrl: 'https://api.facetta.test', accessToken: 'token', fetcher: fetcher as any,
    })).rejects.toThrow(/does not belong/i);
    expect(fetcher).not.toHaveBeenCalled();
  });
});
