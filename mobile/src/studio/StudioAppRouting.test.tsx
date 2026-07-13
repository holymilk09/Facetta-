/// <reference types="jest" />

import React from 'react';
import { act, fireEvent, render, waitFor } from '@testing-library/react-native';
import { clearSession, markOnboarded, saveSession } from '../auth';

const mockGetProject = jest.fn();
const mockGetStudioJob = jest.fn(async (jobId: string) => ({
  data: {
    job_id: jobId, owner: 'usr_designer', action_id: jobId.replace('job_', ''),
    lane: 'trusted_structural', status: 'reviewing', progress: 0.9,
    active_design_id: 'project_hydrated', source_revision_id: 'asset_hydrated',
    error_code: null, created_at: '2026-07-12T00:00:00Z', updated_at: '2026-07-12T00:00:01Z',
    billing: { requested_outputs: 1, credits_per_output: 20, estimated_credits: 20,
      completed_outputs: 0, charged_outputs: 0, charged_credits: 0, policy: 'test' },
  },
  error: null,
  status: 200,
}));

const deferred = <T,>() => {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((resolvePromise) => {
    resolve = resolvePromise;
  });
  return { promise, resolve };
};

jest.mock('../trusted/client', () => ({
  createTrustedApiClient: () => ({
    getProject: mockGetProject,
    getStudioJob: mockGetStudioJob,
  }),
}));

jest.mock('./StudioCreateWorkspace', () => {
  const ReactLocal = require('react');
  const { Pressable, Text } = require('react-native');
  const { DEFAULT_API_URL } = require('../config');
  return {
    StudioCreateWorkspace: ({ onSave, resumeProject, resumeStudioJobId }: {
      onSave: (selection: any) => void;
      resumeProject?: any;
      resumeStudioJobId?: string | null;
    }) => resumeProject ? ReactLocal.createElement(
      Text,
      null,
      `Create review reached for ${resumeProject.root_id} via ${resumeStudioJobId}`,
    ) : (
      ReactLocal.createElement(Pressable, { accessibilityRole: 'button', onPress: () => onSave({
      project: {
        id: 'project_1', root_id: 'project_1', title: 'Saved direction',
        collection: null, tags: [], owner: 'usr_designer', state: 'refining',
        design_id: null, spec: null, active_asset_id: 'asset_1',
        active_design_version: null, selected_candidate_asset_id: 'asset_1',
        active_revision: {
          asset_id: 'asset_1', root_id: 'project_1', parent_asset_id: null,
          capability: 'CREATIVE_RENDER', provenance: 'pre_spec_creative_candidate',
          revision: 1, design_id: null, design_version: null, region: null,
          instruction: 'Saved direction', drift: null, pinned: false,
          media_type: 'image/png',
          image_url: `${DEFAULT_API_URL.replace(/\/$/, '')}/assets/asset_1/image`,
          created_by: 'usr_designer', created_at: null, legacy_provenance: false,
        },
        pinned_revision: null, revisions: [], assets: [{
          asset_id: 'asset_1', root_id: 'project_1', parent_asset_id: null,
          capability: 'CREATIVE_RENDER', provenance: 'pre_spec_creative_candidate',
          revision: 1, design_id: null, design_version: null, region: null,
          instruction: 'Saved direction', drift: null, pinned: false,
          media_type: 'image/png',
          image_url: `${DEFAULT_API_URL.replace(/\/$/, '')}/assets/asset_1/image`,
          created_by: 'usr_designer', created_at: null, legacy_provenance: false,
        }], derived_assets: [],
        approval: null, factory_ready: false, factory_blockers: [],
        primary_revision_count: 1, has_factory_drawing: false,
        cover_asset_id: 'asset_1', created_at: null, updated_at: null,
      },
      selectedAssetId: 'asset_1', sentence: 'Saved direction', references: [],
      }) }, ReactLocal.createElement(Text, null, 'Save mocked direction'))
    ),
  };
});

jest.mock('./StudioRefineWorkspace', () => {
  const ReactLocal = require('react');
  const { Text } = require('react-native');
  return {
    StudioRefineWorkspace: ({ initialAdvancedFactsOpen }: { initialAdvancedFactsOpen?: boolean }) => (
      ReactLocal.createElement(
        Text, null,
        initialAdvancedFactsOpen ? 'Advanced specifications route reached' : 'Refine route reached',
      )
    ),
  };
});

jest.mock('./StudioViewsWorkspace', () => {
  const ReactLocal = require('react');
  const { Text } = require('react-native');
  return { StudioViewsWorkspace: () => ReactLocal.createElement(Text, null, 'Views route reached') };
});

jest.mock('./StudioPresentWorkspace', () => {
  const ReactLocal = require('react');
  const { Text } = require('react-native');
  return { StudioPresentWorkspace: () => ReactLocal.createElement(Text, null, 'Present route reached') };
});

jest.mock('./StudioActivityWorkspace', () => {
  const ReactLocal = require('react');
  const { Pressable, Text, View } = require('react-native');
  const review = (action_id: string, onOpenReview: (job: any) => void) => ReactLocal.createElement(
    Pressable,
    { onPress: () => onOpenReview({
      job_id: `job_${action_id}`,
      action_id, status: 'reviewing', active_design_id: 'project_hydrated',
      source_revision_id: action_id === 'create' ? null : 'asset_hydrated',
    }) },
    ReactLocal.createElement(Text, null, `Review ${action_id}`),
  );
  return {
    StudioActivityWorkspace: ({ onOpenReview, onOpenDesign }: any) => ReactLocal.createElement(
      View,
      null,
      review('create', onOpenReview),
      review('refine', onOpenReview),
      review('views', onOpenReview),
      review('present', onOpenReview),
      ReactLocal.createElement(Pressable, { onPress: () => onOpenDesign('project_hydrated') },
        ReactLocal.createElement(Text, null, 'Open hydrated design')),
    ),
  };
});

jest.mock('./StudioConfirmWorkspace', () => {
  const ReactLocal = require('react');
  const { Pressable, Text } = require('react-native');
  return {
    StudioConfirmWorkspace: ({ onSaved }: { onSaved: (receipt: any) => void }) => (
      ReactLocal.createElement(Pressable, { accessibilityRole: 'button', onPress: () => onSaved({
        project: {
          id: 'project_1', root_id: 'project_1', title: 'Confirmed direction',
          collection: null, tags: [], owner: 'usr_designer', state: 'refining',
          design_id: 'design_1', spec: { jewelry_type: 'ring' },
          active_asset_id: 'asset_exact_1', active_design_version: 1,
          selected_candidate_asset_id: 'asset_1',
          active_revision: {
            asset_id: 'asset_exact_1', root_id: 'project_1', parent_asset_id: 'asset_1',
            capability: 'SPEC_RENDER', provenance: 'confirmed_design', revision: 2,
            design_id: 'design_1', design_version: 1, region: null,
            instruction: 'Confirmed direction', drift: null, pinned: false,
            media_type: 'image/png', image_url: null, created_by: 'usr_designer',
            created_at: null, legacy_provenance: false,
          },
          pinned_revision: null, revisions: [], assets: [], derived_assets: [],
          approval: null, factory_ready: true, factory_blockers: [],
          primary_revision_count: 2, has_factory_drawing: false,
          cover_asset_id: 'asset_exact_1', created_at: null, updated_at: null,
        },
      }) }, ReactLocal.createElement(Text, null, 'Confirm mocked design'))
    ),
  };
});

jest.mock('./StudioFactoryWorkspace', () => {
  const ReactLocal = require('react');
  const { Text } = require('react-native');
  return {
    StudioFactoryWorkspace: ({ lineage }: { lineage: any }) => ReactLocal.createElement(
      Text, null, `Factory route reached for ${lineage?.sourceAssetId ?? 'none'}`,
    ),
  };
});

import App from '../../App';

afterEach(() => { clearSession(); mockGetProject.mockReset(); mockGetStudioJob.mockClear(); });

const hydratedProject = {
  id: 'project_hydrated', root_id: 'project_hydrated', title: 'Hydrated design',
  collection: null, tags: [], owner: 'usr_designer', state: 'refining',
  design_id: 'design_hydrated', spec: { jewelry_type: 'ring' },
  active_asset_id: 'asset_hydrated', active_design_version: 2,
  selected_candidate_asset_id: 'asset_hydrated',
  active_revision: {
    asset_id: 'asset_hydrated', root_id: 'project_hydrated', parent_asset_id: null,
    capability: 'SPEC_RENDER', provenance: 'confirmed_design', revision: 2,
    design_id: 'design_hydrated', design_version: 2, region: null,
    instruction: 'Hydrated design', drift: null, pinned: false,
    media_type: 'image/png', image_url: null, created_by: 'usr_designer',
    created_at: null, legacy_provenance: false,
  },
  pinned_revision: null, revisions: [{
    revision: 2,
    asset: {
      asset_id: 'asset_hydrated', root_id: 'project_hydrated', parent_asset_id: null,
      capability: 'SPEC_RENDER', provenance: 'confirmed_design', revision: 2,
      design_id: 'design_hydrated', design_version: 2, region: null,
      instruction: 'Hydrated design', drift: null, pinned: false,
      media_type: 'image/png', image_url: null, created_by: 'usr_designer',
      created_at: null, legacy_provenance: false,
    },
    spec_version: 2, spec_change: [], ignored_fields: [], qa: null, routing: null,
    created_at: null,
  }], assets: [], derived_assets: [], approval: null,
  factory_ready: false, factory_blockers: [], primary_revision_count: 2,
  has_factory_drawing: false, cover_asset_id: 'asset_hydrated', created_at: null, updated_at: null,
};

const authenticate = () => {
  markOnboarded();
  saveSession({
    provider: 'email', email: 'designer@example.com', name: 'Designer',
    designerId: 'usr_designer', accessToken: 'server-issued-test-token',
    accessTokenExpiresAt: '2099-01-01T00:00:00Z',
  });
};

test('saving a selected direction continues to Refine and authenticates its Studio cover', async () => {
  markOnboarded();
  saveSession({
    provider: 'email', email: 'designer@example.com', name: 'Designer',
    designerId: 'usr_designer', accessToken: 'server-issued-test-token',
    accessTokenExpiresAt: '2099-01-01T00:00:00Z',
  });
  const view = await render(<App />);

  await waitFor(() => expect(view.getByText('Start from an idea or reference')).toBeTruthy());
  fireEvent.press(view.getByText('Start from an idea or reference'));
  fireEvent.press(await view.findByText('Save mocked direction'));
  expect(await view.findByText('Refine route reached')).toBeTruthy();
  expect(view.queryByText('Your design families')).toBeNull();

  fireEvent.press(view.getByText('Close'));
  const cover = await view.findByLabelText('Current design cover');
  expect(cover.props.source.headers).toEqual({
    Authorization: 'Bearer server-issued-test-token',
  });
});

test('confirming Design v1 returns immediately to Refine without a Collections or Factory detour', async () => {
  markOnboarded();
  saveSession({
    provider: 'email', email: 'designer@example.com', name: 'Designer',
    designerId: 'usr_designer', accessToken: 'server-issued-test-token',
    accessTokenExpiresAt: '2099-01-01T00:00:00Z',
  });
  const view = await render(<App />);

  await waitFor(() => expect(view.getByText('Start from an idea or reference')).toBeTruthy());
  fireEvent.press(view.getByText('Start from an idea or reference'));
  fireEvent.press(await view.findByText('Save mocked direction'));
  expect(await view.findByText('Refine route reached')).toBeTruthy();

  fireEvent.press(view.getByLabelText('Confirm design details'));
  fireEvent.press(await view.findByText('Confirm mocked design'));

  expect(await view.findByText('Refine route reached')).toBeTruthy();
  expect(view.queryByText('Confirm mocked design')).toBeNull();
  expect(view.queryByText('Your design families')).toBeNull();
  expect(view.queryByText(/Factory/i)).toBeNull();
  expect(view.getByLabelText('More actions')).toBeTruthy();
  fireEvent.press(view.getByLabelText('More actions'));
  expect(await view.findByText('Specifications')).toBeTruthy();
  expect(await view.findByText('Factory')).toBeTruthy();
  fireEvent.press(view.getByText('Specifications'));
  expect(await view.findByText('Advanced specifications route reached')).toBeTruthy();
  fireEvent.press(view.getByLabelText('More actions'));
  fireEvent.press(await view.findByText('Factory'));
  expect(await view.findByText('Factory route reached for asset_exact_1')).toBeTruthy();
  expect(view.queryByText(/destination will use the exact active revision/i)).toBeNull();
});

test.each([
  ['network', { code: 'NETWORK_ERROR', category: 'network', status: 0, retryable: true }, /could not connect/i],
  ['auth', { code: 'AUTHENTICATION_REQUIRED', category: 'authentication', status: 401, retryable: false }, /session is missing or expired/i],
  ['not-found', { code: 'NOT_FOUND', category: 'not_found', status: 404, retryable: false }, /could not open that saved work/i],
] as const)('project hydration exposes recoverable %s errors and Retry', async (_kind, error, message) => {
  authenticate();
  const failedHydration = deferred<any>();
  const retryHydration = deferred<any>();
  mockGetProject
    .mockReturnValueOnce(failedHydration.promise)
    .mockReturnValueOnce(retryHydration.promise);
  const view = await render(<App />);
  await waitFor(() => expect(view.getByText('Start from an idea or reference')).toBeTruthy());
  fireEvent.press(view.getAllByText('Activity').at(-1)!);
  const review = await view.findByText('Review refine');
  await act(async () => {
    fireEvent.press(review);
    failedHydration.resolve({ data: null, error, status: error.status });
    await failedHydration.promise;
  });
  expect(await view.findByText(message)).toBeTruthy();
  const retry = view.getByText('Retry');
  await act(async () => {
    fireEvent.press(retry);
    retryHydration.resolve({ data: hydratedProject, error: null, status: 200 });
    await retryHydration.promise;
  });
  expect(await view.findByText('Refine route reached')).toBeTruthy();
  expect(mockGetProject).toHaveBeenCalledTimes(2);
});

test.each([
  ['refine', 'Refine route reached'],
  ['views', 'Views route reached'],
  ['present', 'Present route reached'],
] as const)('Activity reviewing %s hydrates exact lineage into the correct destination', async (action, expected) => {
  authenticate();
  const hydration = deferred<any>();
  mockGetProject.mockReturnValue(hydration.promise);
  const view = await render(<App />);
  await waitFor(() => expect(view.getByText('Start from an idea or reference')).toBeTruthy());
  fireEvent.press(view.getAllByText('Activity').at(-1)!);
  const review = await view.findByText(`Review ${action}`);
  await act(async () => {
    fireEvent.press(review);
    hydration.resolve({ data: hydratedProject, error: null, status: 200 });
    await hydration.promise;
  });
  expect(await view.findByText(expected)).toBeTruthy();
});

test('Activity reviewing Create rehydrates the saved candidate chooser and durable job id', async () => {
  authenticate();
  const hydration = deferred<any>();
  mockGetProject.mockReturnValue(hydration.promise);
  const view = await render(<App />);
  await waitFor(() => expect(view.getByText('Start from an idea or reference')).toBeTruthy());
  fireEvent.press(view.getAllByText('Activity').at(-1)!);
  const review = await view.findByText('Review create');
  await act(async () => {
    fireEvent.press(review);
    hydration.resolve({ data: hydratedProject, error: null, status: 200 });
    await hydration.promise;
  });
  expect(await view.findByText(
    'Create review reached for project_hydrated via job_create',
  )).toBeTruthy();
  expect(mockGetProject).toHaveBeenCalledWith('project_hydrated');
});
