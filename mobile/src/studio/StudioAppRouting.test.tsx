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
    getStudioCapabilities: async () => ({
      data: {
        factory_review: { enabled: true, scope: 'principal' },
        workspace_entitlements_available: false,
      },
      error: null,
      status: 200,
    }),
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
        confirmable_pre_spec: true,
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
  const { Pressable, Text, View } = require('react-native');
  return {
    StudioRefineWorkspace: ({ initialAdvancedFactsOpen, lineage, onReviewStartingDesign }: {
      initialAdvancedFactsOpen?: boolean;
      lineage?: { sourceDesignVersion?: number } | null;
      onReviewStartingDesign?: () => void;
    }) => ReactLocal.createElement(
      View,
      null,
      ReactLocal.createElement(
        Text, null,
        initialAdvancedFactsOpen ? 'Advanced specifications route reached' : 'Refine route reached',
      ),
      lineage !== null && lineage?.sourceDesignVersion === undefined
        && onReviewStartingDesign !== undefined
        ? ReactLocal.createElement(
          Pressable,
          { accessibilityRole: 'button', onPress: onReviewStartingDesign },
          ReactLocal.createElement(Text, null, 'Review starting design'),
        )
        : null,
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

jest.mock('./StudioCollectionsWorkspace', () => {
  const ReactLocal = require('react');
  const { Pressable, Text, View } = require('react-native');
  return {
    StudioCollectionsWorkspace: ({ project, onVaryCurrent, onContinueRefining }: any) => ReactLocal.createElement(
      View,
      null,
      ReactLocal.createElement(
        Pressable,
        { accessibilityRole: 'button', onPress: onVaryCurrent },
        ReactLocal.createElement(Text, null, `Vary exact ${project?.root_id ?? 'none'}`),
      ),
      ReactLocal.createElement(
        Pressable,
        { accessibilityRole: 'button', onPress: onContinueRefining },
        ReactLocal.createElement(Text, null, 'Continue refining exact revision'),
      ),
    ),
  };
});

jest.mock('./StudioVaryWorkspace', () => {
  const ReactLocal = require('react');
  const { Text } = require('react-native');
  return {
    StudioVaryWorkspace: ({ lineage }: any) => ReactLocal.createElement(
      Text,
      null,
      `Vary route reached for ${lineage?.projectId ?? 'none'} via ${lineage?.sourceAssetId ?? 'none'}`,
    ),
  };
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

const nonConfirmablePreSpecProject = {
  ...hydratedProject,
  design_id: null,
  spec: null,
  active_design_version: null,
  selected_candidate_asset_id: null,
  active_revision: {
    ...hydratedProject.active_revision,
    capability: 'SOURCE_REFERENCE',
    provenance: 'designer_supplied_photograph',
    design_id: null,
    design_version: null,
  },
  revisions: [{
    ...hydratedProject.revisions[0],
    asset: {
      ...hydratedProject.revisions[0].asset,
      capability: 'SOURCE_REFERENCE',
      provenance: 'designer_supplied_photograph',
      design_id: null,
      design_version: null,
    },
    spec_version: null,
  }],
  assets: [{
    ...hydratedProject.active_revision,
    capability: 'SOURCE_REFERENCE',
    provenance: 'designer_supplied_photograph',
    design_id: null,
    design_version: null,
  }],
  factory_ready: false,
};

const refinedPreSpecProject = {
  ...nonConfirmablePreSpecProject,
  confirmable_pre_spec: true,
  selected_candidate_asset_id: 'asset_original_direction',
  active_asset_id: 'asset_refined_direction',
  active_revision: {
    ...nonConfirmablePreSpecProject.active_revision,
    asset_id: 'asset_refined_direction',
    parent_asset_id: 'asset_original_direction',
    capability: 'LOCALIZED_EDIT',
    provenance: 'studio_preview_applied',
  },
  revisions: [{
    ...nonConfirmablePreSpecProject.revisions[0],
    asset: {
      ...nonConfirmablePreSpecProject.revisions[0].asset,
      asset_id: 'asset_refined_direction',
      parent_asset_id: 'asset_original_direction',
      capability: 'LOCALIZED_EDIT',
      provenance: 'studio_preview_applied',
    },
  }],
  assets: [
    {
      ...nonConfirmablePreSpecProject.assets[0],
      asset_id: 'asset_original_direction',
      capability: 'CREATIVE_RENDER',
      provenance: 'pre_spec_creative_candidate',
    },
    {
      ...nonConfirmablePreSpecProject.assets[0],
      asset_id: 'asset_refined_direction',
      parent_asset_id: 'asset_original_direction',
      capability: 'LOCALIZED_EDIT',
      provenance: 'studio_preview_applied',
    },
  ],
};

const authenticate = () => {
  markOnboarded();
  saveSession({
    provider: 'email', email: 'designer@example.com', name: 'Designer',
    designerId: 'usr_designer', accessToken: 'server-issued-test-token',
    accessTokenExpiresAt: '2099-01-01T00:00:00Z',
  });
};

test('global navigation is exactly four named destinations and each opens its routed workspace', async () => {
  authenticate();
  const view = await render(<App />);

  await waitFor(() => expect(view.getByText('Start from an idea or reference')).toBeTruthy());
  expect(view.getAllByRole('tab').map((item) => item.props.accessibilityLabel)).toEqual([
    'Studio', 'Collections', 'Activity', 'Learn',
  ]);
  expect(view.getByRole('tab', { name: 'Studio' }).props.accessibilityState).toEqual({ selected: true });

  fireEvent.press(view.getByRole('tab', { name: 'Collections' }));
  expect(await view.findByText('Vary exact none')).toBeTruthy();
  expect(view.getByRole('tab', { name: 'Collections' }).props.accessibilityState).toEqual({ selected: true });

  fireEvent.press(view.getByRole('tab', { name: 'Activity' }));
  expect(await view.findByText('Review create')).toBeTruthy();
  expect(view.getByRole('tab', { name: 'Activity' }).props.accessibilityState).toEqual({ selected: true });

  fireEvent.press(view.getByRole('tab', { name: 'Learn' }));
  expect(await view.findByText('Learn the workflow, when you need it.')).toBeTruthy();
  expect(view.getByRole('tab', { name: 'Learn' }).props.accessibilityState).toEqual({ selected: true });

  fireEvent.press(view.getByRole('tab', { name: 'Studio' }));
  expect(await view.findByText('Start from an idea or reference')).toBeTruthy();
  expect(view.getByRole('tab', { name: 'Studio' }).props.accessibilityState).toEqual({ selected: true });
  expect(view.queryByText(/Builder|Share design|Factory/i)).toBeNull();
});

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

  fireEvent.press(view.getByLabelText('Back to Studio'));
  const cover = await view.findByLabelText('Current design cover');
  expect(cover.props.source.headers).toEqual({
    Authorization: 'Bearer server-issued-test-token',
  });
});

test('active design actions keep the exact saved revision visible and link to History', async () => {
  authenticate();
  const view = await render(<App />);

  await waitFor(() => expect(view.getByText('Start from an idea or reference')).toBeTruthy());
  fireEvent.press(view.getByText('Start from an idea or reference'));
  expect(view.queryByTestId('active-design-context')).toBeNull();

  fireEvent.press(await view.findByText('Save mocked direction'));
  expect(await view.findByTestId('active-design-context')).toBeTruthy();
  expect(view.getByText('Saved direction')).toBeTruthy();
  expect(view.getByText('Current saved revision · Revision 1')).toBeTruthy();
  expect(view.getByLabelText('Saved direction revision thumbnail').props.source.headers).toEqual({
    Authorization: 'Bearer server-issued-test-token',
  });

  for (const action of ['Save as a variation', 'Present this design', 'Refine this design']) {
    fireEvent.press(view.getByLabelText(action));
    expect(await view.findByTestId('active-design-context')).toBeTruthy();
    expect(view.getByText('Current saved revision · Revision 1')).toBeTruthy();
  }

  fireEvent.press(await view.findByText('Review starting design'));
  fireEvent.press(await view.findByText('Confirm mocked design'));
  expect(await view.findByText('Confirmed direction')).toBeTruthy();
  expect(view.getByText('Current saved revision · Revision 2')).toBeTruthy();

  fireEvent.press(view.getByLabelText('Generate technical views'));
  expect(await view.findByTestId('active-design-context')).toBeTruthy();
  expect(view.getByText('Current saved revision · Revision 2')).toBeTruthy();

  fireEvent.press(view.getByLabelText('Open revision history'));
  expect(await view.findByText('Vary exact project_1')).toBeTruthy();
});

test('Studio home opens Collections through the saved-work continuation', async () => {
  authenticate();
  const view = await render(<App />);

  const continuation = await view.findByLabelText('Continue saved work');
  fireEvent.press(continuation);
  expect(await view.findByText('Vary exact none')).toBeTruthy();
});

test('Collections delegates variation creation to Studio Vary with the exact active project', async () => {
  authenticate();
  const view = await render(<App />);

  await waitFor(() => expect(view.getByText('Start from an idea or reference')).toBeTruthy());
  fireEvent.press(view.getByText('Start from an idea or reference'));
  fireEvent.press(await view.findByText('Save mocked direction'));
  expect(await view.findByText('Refine route reached')).toBeTruthy();

  fireEvent.press(view.getAllByText('Collections').at(-1)!);
  fireEvent.press(await view.findByText('Vary exact project_1'));
  expect(await view.findByText('Vary route reached for project_1 via asset_1')).toBeTruthy();
});

test('Collections returns the selected exact revision to Refine', async () => {
  authenticate();
  const view = await render(<App />);

  await waitFor(() => expect(view.getByText('Start from an idea or reference')).toBeTruthy());
  fireEvent.press(view.getByText('Start from an idea or reference'));
  fireEvent.press(await view.findByText('Save mocked direction'));
  expect(await view.findByText('Refine route reached')).toBeTruthy();

  fireEvent.press(view.getAllByText('Collections').at(-1)!);
  fireEvent.press(await view.findByText('Continue refining exact revision'));
  expect(await view.findByText('Refine route reached')).toBeTruthy();
});

test('Refine links directly to starting design review and returns after confirmation', async () => {
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
  expect(view.queryByLabelText('More actions')).toBeNull();
  expect(view.queryByText('Starting design facts')).toBeNull();
  expect(view.queryByLabelText('Generate technical views')).toBeNull();

  fireEvent.press(await view.findByText('Review starting design'));
  fireEvent.press(await view.findByText('Confirm mocked design'));

  expect(await view.findByText('Refine route reached')).toBeTruthy();
  expect(view.queryByText('Confirm mocked design')).toBeNull();
  expect(view.queryByText('Your design families')).toBeNull();
  expect(view.queryByText(/Factory/i)).toBeNull();
  expect(view.getByLabelText('Generate technical views')).toBeTruthy();
  fireEvent.press(view.getByLabelText('Generate technical views'));
  expect(await view.findByText('Views route reached')).toBeTruthy();
  fireEvent.press(view.getByLabelText('Refine this design'));
  expect(await view.findByText('Refine route reached')).toBeTruthy();
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

test('Activity Refine does not offer design-fact review for a non-confirmable pre-spec source', async () => {
  authenticate();
  mockGetProject.mockResolvedValue({
    data: nonConfirmablePreSpecProject, error: null, status: 200,
  });
  const view = await render(<App />);
  await waitFor(() => expect(view.getByText('Start from an idea or reference')).toBeTruthy());
  fireEvent.press(view.getAllByText('Activity').at(-1)!);
  const review = await view.findByText('Review refine');
  await act(async () => { fireEvent.press(review); });

  expect(await view.findByText('Refine route reached')).toBeTruthy();
  expect(view.queryByText('Review starting design')).toBeNull();
});

test('Activity Refine keeps design-fact review on the current refined pre-spec child', async () => {
  authenticate();
  mockGetStudioJob.mockResolvedValueOnce({
    data: {
      job_id: 'job_refine', owner: 'usr_designer', action_id: 'refine',
      lane: 'trusted_structural', status: 'reviewing', progress: 0.9,
      active_design_id: 'project_hydrated', source_revision_id: 'asset_refined_direction',
      error_code: null, created_at: '2026-07-12T00:00:00Z',
      updated_at: '2026-07-12T00:00:01Z',
      billing: { requested_outputs: 1, credits_per_output: 20, estimated_credits: 20,
        completed_outputs: 0, charged_outputs: 0, charged_credits: 0, policy: 'test' },
    },
    error: null,
    status: 200,
  });
  mockGetProject.mockResolvedValue({
    data: refinedPreSpecProject, error: null, status: 200,
  });
  const view = await render(<App />);
  await waitFor(() => expect(view.getByText('Start from an idea or reference')).toBeTruthy());
  fireEvent.press(view.getAllByText('Activity').at(-1)!);
  const review = await view.findByText('Review refine');
  await act(async () => { fireEvent.press(review); });

  expect(await view.findByText('Refine route reached')).toBeTruthy();
  expect(view.getByText('Review starting design')).toBeTruthy();
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
