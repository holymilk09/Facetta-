/// <reference types="jest" />

import React from 'react';
import {
  act, fireEvent, render, userEvent, waitFor,
} from '@testing-library/react-native';
import { StyleSheet } from 'react-native';
import { clearSession, markOnboarded, saveSession } from '../auth';
import { theme } from '../theme';

let mockAuthStateListener: ((event: any, session: any) => void) | null = null;
let mockRestoreAuthenticatedSession: (() => Promise<any>) | null = null;
jest.mock('../auth', () => {
  const actual = jest.requireActual('../auth');
  return {
    ...actual,
    subscribeToAuthStateChange: (listener: (event: any, session: any) => void) => {
      mockAuthStateListener = listener;
      return () => {
        if (mockAuthStateListener === listener) mockAuthStateListener = null;
      };
    },
    restoreAuthenticatedSession: () => (
      mockRestoreAuthenticatedSession?.() ?? actual.restoreAuthenticatedSession()
    ),
  };
});

const mockGetProject = jest.fn();
const mockGetCreativeDirectionReviewDraft: jest.Mock = jest.fn(async () => ({
  data: null,
  error: {
    code: 'NOT_FOUND', message: 'No saved Create review draft.', category: 'not_found',
    retryable: false,
  },
  status: 404,
}));
let mockFactoryReviewEnabled = true;
let mockConfirmedJewelryType = 'ring';
let mockConfirmedFactoryReady = false;
let mockSavedPreSpecCapability = 'CREATIVE_RENDER';
let mockFactoryProjectUpdate: any = null;
const mockGetStudioCapabilities = jest.fn(async () => ({
  data: {
    factory_review: { enabled: mockFactoryReviewEnabled, scope: 'principal' },
    workspace_entitlements_available: false,
  },
  error: null,
  status: 200,
}));
const mockListDesignFamilies = jest.fn(async () => ({
  data: { families: [{ family_id: 'family_saved' }] },
  error: null,
  status: 200,
}));
const mockGetStudioJob = jest.fn(async (jobId: string) => ({
  data: {
    job_id: jobId, owner: 'usr_designer', action_id: jobId.replace('job_', ''),
    lane: 'trusted_structural', status: 'reviewing', progress: 0.9,
    active_design_id: 'project_hydrated',
    source_revision_id: jobId === 'job_create' ? null : 'asset_hydrated',
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
    getCreativeDirectionReviewDraft: mockGetCreativeDirectionReviewDraft,
    listDesignFamilies: mockListDesignFamilies,
    getStudioJob: mockGetStudioJob,
    getStudioCapabilities: mockGetStudioCapabilities,
  }),
}));

jest.mock('./StudioCreateWorkspace', () => {
  const ReactLocal = require('react');
  const { Pressable, Text, TextInput, View } = require('react-native');
  const { DEFAULT_API_URL } = require('../config');
  return {
    StudioCreateWorkspace: ({
      onSave, resumeProject, resumeStudioJobId, resumeReviewDraft, draft, onDraftChange,
      onGenerationSucceeded, onReviewDraftStateChange,
    }: {
      onSave: (selection: any) => void;
      resumeProject?: any;
      resumeStudioJobId?: string | null;
      resumeReviewDraft?: any;
      draft?: any;
      onDraftChange?: (draft: any) => void;
      onGenerationSucceeded?: (success: any) => void;
      onReviewDraftStateChange?: (state: 'saved' | 'saving' | 'error') => void;
    }) => resumeProject ? ReactLocal.createElement(
      View,
      null,
      ReactLocal.createElement(
        Text,
        null,
        `Create review reached for ${resumeProject.root_id} via ${resumeStudioJobId}`,
      ),
      ReactLocal.createElement(
        Text,
        null,
        `Create review selection: ${resumeReviewDraft?.selected_candidate_id ?? 'default'}`,
      ),
    ) : (
      ReactLocal.createElement(
        View,
        null,
        ReactLocal.createElement(TextInput, {
          accessibilityLabel: 'Mock draft sentence',
          value: draft?.sentence ?? '',
          onChangeText: (sentence: string) => onDraftChange?.({ ...draft, sentence }),
        }),
        ReactLocal.createElement(
          Text,
          null,
          `Mock draft count: ${draft?.candidateCount ?? 2}`,
        ),
        ReactLocal.createElement(
          Text,
          null,
          `Mock master source: ${draft?.references?.find((reference: any) => (
            reference.role === 'master_geometry'
          ))?.sourceKind ?? 'none'}`,
        ),
        ReactLocal.createElement(
          Pressable,
          {
            accessibilityRole: 'button',
            onPress: () => onDraftChange?.({ ...draft, candidateCount: 4 }),
          },
          ReactLocal.createElement(Text, null, 'Mock four directions'),
        ),
        ReactLocal.createElement(
          Pressable,
          {
            accessibilityRole: 'button',
            onPress: () => onDraftChange?.({
              ...draft,
              references: [{
                id: 'mock_master', role: 'master_geometry', label: 'Sketch.png',
                imageBase64: 'bW9jaw==', mediaType: 'image/png', sourceKind: 'drawing',
              }],
            }),
          },
          ReactLocal.createElement(Text, null, 'Mock add drawing reference'),
        ),
        ReactLocal.createElement(
          Pressable,
          {
            accessibilityRole: 'button',
            onPress: () => onGenerationSucceeded?.({
              owner: 'usr_designer', projectId: 'project_1', submittedDraft: draft,
            }),
          },
          ReactLocal.createElement(Text, null, 'Mock generation succeeded'),
        ),
        ReactLocal.createElement(
          Pressable,
          {
            accessibilityRole: 'button',
            onPress: () => onReviewDraftStateChange?.('saving'),
          },
          ReactLocal.createElement(Text, null, 'Mock draft saving'),
        ),
        ReactLocal.createElement(
          Pressable,
          {
            accessibilityRole: 'button',
            onPress: () => onReviewDraftStateChange?.('saved'),
          },
          ReactLocal.createElement(Text, null, 'Mock draft saved'),
        ),
        ReactLocal.createElement(Pressable, { accessibilityRole: 'button', onPress: () => onSave({
          project: {
            id: 'project_1', root_id: 'project_1', title: 'Saved direction',
            collection: null, tags: [], owner: 'usr_designer', state: 'refining',
            design_id: null, spec: null, active_asset_id: 'asset_1',
            confirmable_pre_spec: true,
            active_design_version: null, selected_candidate_asset_id: 'asset_1',
            active_revision: {
              asset_id: 'asset_1', root_id: 'project_1', parent_asset_id: null,
              capability: mockSavedPreSpecCapability,
              provenance: 'pre_spec_creative_candidate',
              revision: 1, design_id: null, design_version: null, region: null,
              instruction: 'Saved direction', drift: null, pinned: false,
              media_type: 'image/png',
              sha256: '1'.repeat(64),
              image_url: `${DEFAULT_API_URL.replace(/\/$/, '')}/assets/asset_1/image`,
              created_by: 'usr_designer', created_at: null, legacy_provenance: false,
            },
            pinned_revision: null, revisions: [], assets: [{
              asset_id: 'asset_1', root_id: 'project_1', parent_asset_id: null,
              capability: mockSavedPreSpecCapability,
              provenance: 'pre_spec_creative_candidate',
              revision: 1, design_id: null, design_version: null, region: null,
              instruction: 'Saved direction', drift: null, pinned: false,
              media_type: 'image/png',
              sha256: '1'.repeat(64),
              image_url: `${DEFAULT_API_URL.replace(/\/$/, '')}/assets/asset_1/image`,
              created_by: 'usr_designer', created_at: null, legacy_provenance: false,
            }], derived_assets: [],
            approval: null, factory_ready: false, factory_blockers: [],
            primary_revision_count: 1, has_factory_drawing: false,
            cover_asset_id: 'asset_1', created_at: null, updated_at: null,
          },
          selectedAssetId: 'asset_1',
        }) }, ReactLocal.createElement(Text, null, 'Save mocked direction')),
      )
    ),
  };
});

jest.mock('./StudioRefineWorkspace', () => {
  const ReactLocal = require('react');
  const { Pressable, Text, View } = require('react-native');
  return {
    StudioRefineWorkspace: ({
      workspaceMode, lineage, onReviewStartingDesign, destinationContext,
      onSelectDestination, initialInstruction,
    }: {
      workspaceMode?: 'refine' | 'specifications';
      lineage?: { sourceDesignVersion?: number } | null;
      onReviewStartingDesign?: (pendingInstruction: string) => void;
      destinationContext?: { activeRevisionId?: string | null };
      onSelectDestination?: (destination: 'library' | 'client') => void;
      initialInstruction?: string;
    }) => ReactLocal.createElement(
      View,
      null,
      ReactLocal.createElement(
        Text, null,
        workspaceMode === 'specifications'
          ? 'Advanced specifications route reached' : 'Refine route reached',
      ),
      lineage !== null && lineage?.sourceDesignVersion === undefined
        && onReviewStartingDesign !== undefined
        ? ReactLocal.createElement(
          Pressable,
          {
            accessibilityRole: 'button',
            onPress: () => onReviewStartingDesign('Use rose gold'),
          },
          ReactLocal.createElement(Text, null, 'Review starting design'),
        )
        : null,
      initialInstruction
        ? ReactLocal.createElement(Text, null, `Pending instruction: ${initialInstruction}`)
        : null,
      !destinationContext?.activeRevisionId
        || onSelectDestination === undefined ? null : ReactLocal.createElement(
        Pressable,
        { accessibilityRole: 'button', onPress: () => onSelectDestination('library') },
        ReactLocal.createElement(Text, null, 'Refine handoff to Collections'),
      ),
      !destinationContext?.activeRevisionId
        || onSelectDestination === undefined ? null : ReactLocal.createElement(
        Pressable,
        { accessibilityRole: 'button', onPress: () => onSelectDestination('client') },
        ReactLocal.createElement(Text, null, 'Refine handoff to Present'),
      ),
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
  const { Text, View } = require('react-native');
  return {
    StudioPresentWorkspace: ({ lineage, initialDestination }: any) => ReactLocal.createElement(
      View,
      null,
      ReactLocal.createElement(
        Text, null, `Present route reached for ${lineage?.sourceAssetId ?? 'none'}`,
      ),
      ReactLocal.createElement(
        Text, null, `Present destination ${initialDestination ?? 'choose'}`,
      ),
    ),
  };
});

jest.mock('./StudioCollectionsWorkspace', () => {
  const ReactLocal = require('react');
  const { Pressable, Text, View } = require('react-native');
  return {
    StudioCollectionsWorkspace: ({
      project,
      onOpenProject,
      onStartDesign,
      onVaryCurrent,
      onVaryRevision,
      onContinueRefining,
      destinationContext,
      onSelectDestination,
    }: any) => ReactLocal.createElement(
      View,
      null,
      ReactLocal.createElement(
        Pressable,
        { accessibilityRole: 'button', onPress: () => onOpenProject('project_a') },
        ReactLocal.createElement(Text, null, 'Open project A'),
      ),
      ReactLocal.createElement(
        Pressable,
        { accessibilityRole: 'button', onPress: () => onOpenProject('project_b') },
        ReactLocal.createElement(Text, null, 'Open project B'),
      ),
      ReactLocal.createElement(
        Pressable,
        { accessibilityRole: 'button', onPress: onStartDesign },
        ReactLocal.createElement(Text, null, 'Start a design from Collections'),
      ),
      ReactLocal.createElement(
        Pressable,
        { accessibilityRole: 'button', onPress: onVaryCurrent },
        ReactLocal.createElement(Text, null, `Vary exact ${project?.root_id ?? 'none'}`),
      ),
      project === null ? null : ReactLocal.createElement(
        Pressable,
        {
          accessibilityRole: 'button',
          onPress: () => onVaryRevision({
            mode: 'saved_revision', projectId: project.root_id,
            sourceAssetId: 'asset_history_1', sourceDesignVersion: 1,
            sourceSha256: '1'.repeat(64), sourceRevision: 1,
            expectedActiveAssetId: project.active_asset_id,
            expectedActiveDesignVersion: project.active_design_version,
          }),
        },
        ReactLocal.createElement(Text, null, 'Vary from mocked Revision 1'),
      ),
      ReactLocal.createElement(
        Pressable,
        { accessibilityRole: 'button', onPress: onContinueRefining },
        ReactLocal.createElement(Text, null, 'Continue refining exact revision'),
      ),
      ReactLocal.createElement(
        Text,
        { accessibilityRole: 'button', onPress: () => onSelectDestination('client') },
        'Present exact current revision',
      ),
      ReactLocal.createElement(
        Text,
        { accessibilityRole: 'button', onPress: () => onSelectDestination('marketing') },
        'Market exact current revision',
      ),
      destinationContext?.activeProjectId
        && destinationContext?.activeRevisionId
        && destinationContext?.hasExactSpecification
        && destinationContext?.factoryEligible ? ReactLocal.createElement(
        Text,
        { accessibilityRole: 'button', onPress: () => onSelectDestination('factory') },
        'Review optional Factory readiness',
      ) : null,
    ),
  };
});

jest.mock('./StudioVaryWorkspace', () => {
  const ReactLocal = require('react');
  const { Text, View } = require('react-native');
  return {
    StudioVaryWorkspace: ({ lineage }: any) => ReactLocal.createElement(
      View,
      null,
      ReactLocal.createElement(
        Text,
        null,
        `Vary route reached for ${lineage?.projectId ?? 'none'} via ${lineage?.sourceAssetId ?? 'none'}`,
      ),
      ReactLocal.createElement(
        Text,
        null,
        lineage === null ? 'No Vary source' : `Starting Revision ${lineage.sourceRevision}`,
      ),
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
          design_id: 'design_1', spec: { jewelry_type: mockConfirmedJewelryType },
          active_asset_id: 'asset_exact_1', active_design_version: 1,
          selected_candidate_asset_id: 'asset_1',
          active_revision: {
            asset_id: 'asset_exact_1', root_id: 'project_1', parent_asset_id: 'asset_1',
            capability: 'SPEC_RENDER', provenance: 'confirmed_design', revision: 2,
            design_id: 'design_1', design_version: 1, region: null,
            instruction: 'Confirmed direction', drift: null, pinned: false,
            media_type: 'image/png', image_url: null, created_by: 'usr_designer',
            sha256: '2'.repeat(64),
            created_at: null, legacy_provenance: false,
          },
          pinned_revision: mockConfirmedFactoryReady ? {
            asset_id: 'asset_exact_1', root_id: 'project_1', parent_asset_id: 'asset_1',
            capability: 'SPEC_RENDER', provenance: 'confirmed_design', revision: 2,
            design_id: 'design_1', design_version: 1, region: null,
            instruction: 'Confirmed direction', drift: null, pinned: true,
            media_type: 'image/png', image_url: null, created_by: 'usr_designer',
            sha256: '2'.repeat(64),
            created_at: null, legacy_provenance: false,
          } : null, revisions: [], assets: [], derived_assets: [],
          approval: null, factory_ready: mockConfirmedFactoryReady, factory_blockers: [],
          primary_revision_count: 2, has_factory_drawing: false,
          cover_asset_id: 'asset_exact_1', created_at: null, updated_at: null,
        },
      }) }, ReactLocal.createElement(Text, null, 'Save starting facts'))
    ),
  };
});

jest.mock('./StudioFactoryWorkspace', () => {
  const ReactLocal = require('react');
  const { Pressable, Text, View } = require('react-native');
  return {
    StudioFactoryWorkspace: ({ lineage, onProjectUpdated }: {
      lineage: any;
      onProjectUpdated?: (project: any) => void;
    }) => ReactLocal.createElement(
      View,
      null,
      ReactLocal.createElement(
        Text, null, `Factory route reached for ${lineage?.sourceAssetId ?? 'none'}`,
      ),
      mockFactoryProjectUpdate === null ? null : ReactLocal.createElement(
        Pressable,
        {
          accessibilityRole: 'button',
          onPress: () => onProjectUpdated?.(mockFactoryProjectUpdate),
        },
        ReactLocal.createElement(Text, null, 'Refresh mocked Factory project'),
      ),
    ),
  };
});

import App from '../../App';

afterEach(() => {
  clearSession();
  mockAuthStateListener = null;
  mockRestoreAuthenticatedSession = null;
  mockFactoryReviewEnabled = true;
  mockConfirmedJewelryType = 'ring';
  mockConfirmedFactoryReady = false;
  mockSavedPreSpecCapability = 'CREATIVE_RENDER';
  mockFactoryProjectUpdate = null;
  mockGetProject.mockReset();
  mockGetCreativeDirectionReviewDraft.mockReset();
  mockGetCreativeDirectionReviewDraft.mockResolvedValue({
    data: null,
    error: {
      code: 'NOT_FOUND', message: 'No saved Create review draft.', category: 'not_found',
      retryable: false,
    },
    status: 404,
  });
  mockGetStudioCapabilities.mockClear();
  mockListDesignFamilies.mockClear();
  mockGetStudioJob.mockClear();
});

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
    sha256: 'a'.repeat(64),
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

const staleActivitySourceProject = {
  ...hydratedProject,
  revisions: [
    {
      ...hydratedProject.revisions[0],
      revision: 1,
      asset: {
        ...hydratedProject.revisions[0].asset,
        asset_id: 'asset_stale',
        revision: 1,
        design_version: 1,
        instruction: 'Earlier saved direction',
      },
      spec_version: 1,
    },
    hydratedProject.revisions[0],
  ],
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

const hydratedProjectFor = (projectId: string, assetId: string) => ({
  ...hydratedProject,
  id: projectId,
  root_id: projectId,
  title: `Hydrated ${projectId}`,
  active_asset_id: assetId,
  selected_candidate_asset_id: assetId,
  active_revision: {
    ...hydratedProject.active_revision,
    asset_id: assetId,
    root_id: projectId,
    instruction: `Hydrated ${projectId}`,
  },
  revisions: hydratedProject.revisions.map((revision) => ({
    ...revision,
    asset: {
      ...revision.asset,
      asset_id: assetId,
      root_id: projectId,
      instruction: `Hydrated ${projectId}`,
    },
  })),
  cover_asset_id: assetId,
});

const eligibleFactoryProject = () => {
  const project = hydratedProjectFor('project_1', 'asset_exact_1');
  const pinned = {
    ...project.active_revision,
    design_version: 1,
    pinned: true,
  };
  return {
    ...project,
    active_design_version: 1,
    active_revision: pinned,
    pinned_revision: pinned,
    factory_ready: true,
    factory_blockers: [],
  };
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

type AppRenderResult = Awaited<ReturnType<typeof render>>;

const openStudioMoreActions = async (view: AppRenderResult): Promise<void> => {
  const user = userEvent.setup();
  await user.press(view.getByTestId('studio-action-more'));
};

const pressStudioAction = async (
  view: AppRenderResult,
  accessibilityLabel: string,
): Promise<void> => {
  const user = userEvent.setup();
  await user.press(view.getByLabelText(accessibilityLabel));
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

test('Create keeps the review mounted until its latest Activity draft is durable', async () => {
  authenticate();
  const view = await render(<App />);

  fireEvent.press(await view.findByText('Start from an idea or reference'));
  fireEvent.press(await view.findByText('Mock draft saving'));

  await waitFor(() => {
    expect(view.getByLabelText('Back to Studio').props.accessibilityState).toEqual(
      expect.objectContaining({ disabled: true }),
    );
  });
  expect(view.queryByTestId('global-navigation')).toBeNull();
  expect(view.queryAllByRole('tab')).toHaveLength(0);
  fireEvent.press(view.getByLabelText('Back to Studio'));
  expect(view.getByText('Mock draft saving')).toBeTruthy();
  expect(view.queryByText('Learn the workflow, when you need it.')).toBeNull();

  fireEvent.press(view.getByText('Mock draft saved'));
  await waitFor(() => {
    expect(view.getByLabelText('Back to Studio').props.accessibilityState).toEqual({});
  });
  expect(view.queryByTestId('global-navigation')).toBeNull();
  fireEvent.press(view.getByLabelText('Back to Studio'));
  expect(await view.findByTestId('global-navigation')).toBeTruthy();
  fireEvent.press(view.getByRole('tab', { name: 'Learn' }));
  expect(await view.findByText('Learn the workflow, when you need it.')).toBeTruthy();
});

test('the account menu opens without replacing the active routed workspace', async () => {
  authenticate();
  const view = await render(<App />);

  await waitFor(() => expect(view.getByText('Start from an idea or reference')).toBeTruthy());
  fireEvent.press(view.getByRole('tab', { name: 'Activity' }));
  expect(await view.findByText('Review create')).toBeTruthy();

  await fireEvent.press(view.getByLabelText('Account menu'));

  expect(view.getByText('designer@example.com')).toBeTruthy();
  expect(view.getByText('Review create')).toBeTruthy();
  expect(view.getByRole('tab', { name: 'Activity' }).props.accessibilityState)
    .toEqual({ selected: true });
});

test('Create restores its full draft after leaving for every global destination', async () => {
  authenticate();
  const view = await render(<App />);

  await waitFor(() => expect(view.getByText('Start from an idea or reference')).toBeTruthy());
  await fireEvent.press(view.getByText('Start from an idea or reference'));
  await fireEvent.changeText(
    await view.findByLabelText('Mock draft sentence'),
    'An architectural sapphire ring.',
  );
  await fireEvent.press(view.getByText('Mock four directions'));
  await fireEvent.press(view.getByText('Mock add drawing reference'));

  const expectRestoredDraft = () => {
    expect(view.getByLabelText('Mock draft sentence').props.value)
      .toBe('An architectural sapphire ring.');
    expect(view.getByText('Mock draft count: 4')).toBeTruthy();
    expect(view.getByText('Mock master source: drawing')).toBeTruthy();
  };
  expectRestoredDraft();

  for (const destination of ['Studio', 'Collections', 'Activity', 'Learn'] as const) {
    await fireEvent.press(view.getByLabelText('Back to Studio'));
    if (destination !== 'Studio') {
      await fireEvent.press(view.getByRole('tab', { name: destination }));
      await fireEvent.press(view.getByRole('tab', { name: 'Studio' }));
    }
    await fireEvent.press(await view.findByText('Start from an idea or reference'));
    expectRestoredDraft();
  }
});

test('a successful Create generation clears the setup before the next Create session', async () => {
  authenticate();
  const view = await render(<App />);

  await waitFor(() => expect(view.getByText('Start from an idea or reference')).toBeTruthy());
  await fireEvent.press(view.getByText('Start from an idea or reference'));
  await fireEvent.changeText(view.getByLabelText('Mock draft sentence'), 'A quiet gold ring.');
  await fireEvent.press(view.getByText('Mock four directions'));
  await fireEvent.press(view.getByText('Mock add drawing reference'));
  await fireEvent.press(view.getByText('Mock generation succeeded'));

  expect(view.getByLabelText('Mock draft sentence').props.value).toBe('');
  expect(view.getByText('Mock draft count: 2')).toBeTruthy();
  expect(view.getByText('Mock master source: none')).toBeTruthy();

  await fireEvent.press(view.getByLabelText('Back to Studio'));
  await fireEvent.press(await view.findByText('Start from an idea or reference'));
  expect(view.getByLabelText('Mock draft sentence').props.value).toBe('');
  expect(view.getByText('Mock draft count: 2')).toBeTruthy();
  expect(view.getByText('Mock master source: none')).toBeTruthy();
});

test('a direct authenticated account switch clears the previous designer Create state', async () => {
  authenticate();
  const view = await render(<App />);

  await waitFor(() => expect(view.getByText('Start from an idea or reference')).toBeTruthy());
  await fireEvent.press(view.getByText('Start from an idea or reference'));
  await fireEvent.changeText(view.getByLabelText('Mock draft sentence'), 'Designer A private direction.');
  await fireEvent.press(view.getByText('Mock four directions'));
  await fireEvent.press(view.getByText('Mock add drawing reference'));

  await act(async () => {
    mockAuthStateListener?.('SIGNED_IN', {
      provider: 'email', email: 'designer-b@example.com', name: 'Designer B',
      designerId: 'usr_designer_b', accessToken: 'server-issued-b-token',
      accessTokenExpiresAt: '2099-01-01T00:00:00Z',
    });
  });

  expect(await view.findByText('Start from an idea or reference')).toBeTruthy();
  await fireEvent.press(view.getByText('Start from an idea or reference'));
  expect(view.getByLabelText('Mock draft sentence').props.value).toBe('');
  expect(view.getByText('Mock draft count: 2')).toBeTruthy();
  expect(view.getByText('Mock master source: none')).toBeTruthy();
  await fireEvent.press(view.getByLabelText('Account menu'));
  expect(view.getByText('designer-b@example.com')).toBeTruthy();
});

test('a stale bootstrap restore cannot overwrite a newer signed-in account', async () => {
  const pendingRestore = deferred<any>();
  const restoredAccount = {
    provider: 'email' as const, email: 'restored-a@example.com', name: 'Restored A',
    designerId: 'usr_restored_a', accessToken: 'restored-a-token',
    accessTokenExpiresAt: '2099-01-01T00:00:00Z',
  };
  const signedInAccount = {
    provider: 'email' as const, email: 'signed-in-b@example.com', name: 'Signed In B',
    designerId: 'usr_signed_in_b', accessToken: 'signed-in-b-token',
    accessTokenExpiresAt: '2099-01-01T00:00:00Z',
  };
  markOnboarded();
  saveSession(restoredAccount);
  mockRestoreAuthenticatedSession = () => pendingRestore.promise;
  const view = await render(<App />);

  await act(async () => {
    mockAuthStateListener?.('SIGNED_IN', signedInAccount);
  });
  expect(await view.findByText('Start from an idea or reference')).toBeTruthy();

  await act(async () => {
    pendingRestore.resolve(restoredAccount);
    await pendingRestore.promise;
  });

  await fireEvent.press(view.getByLabelText('Account menu'));
  expect(view.getByText('signed-in-b@example.com')).toBeTruthy();
  expect(view.queryByText('restored-a@example.com')).toBeNull();
});

test('authenticated shell fills short workspaces with the routed surface while Studio home stays dark', async () => {
  authenticate();
  const view = await render(<App />);

  await waitFor(() => expect(view.getByText('Start from an idea or reference')).toBeTruthy());
  expect(StyleSheet.flatten(view.getByTestId('authenticated-shell').props.style)).toEqual(
    expect.objectContaining({ flex: 1, minHeight: '100%', backgroundColor: '#15121c' }),
  );
  expect(StyleSheet.flatten(view.getByTestId('authenticated-workspace-surface').props.style)).toEqual(
    expect.objectContaining({ flex: 1, backgroundColor: '#15121c' }),
  );

  fireEvent.press(view.getByRole('tab', { name: 'Activity' }));
  expect(await view.findByText('Review create')).toBeTruthy();
  expect(StyleSheet.flatten(view.getByTestId('authenticated-shell').props.style)).toEqual(
    expect.objectContaining({ flex: 1, minHeight: '100%', backgroundColor: theme.paper }),
  );
  expect(StyleSheet.flatten(view.getByTestId('authenticated-workspace-surface').props.style)).toEqual(
    expect.objectContaining({ flex: 1, backgroundColor: theme.paper }),
  );

  fireEvent.press(view.getByRole('tab', { name: 'Studio' }));
  expect(await view.findByText('Start from an idea or reference')).toBeTruthy();
  expect(StyleSheet.flatten(view.getByTestId('authenticated-workspace-surface').props.style))
    .toEqual(expect.objectContaining({ flex: 1, backgroundColor: '#15121c' }));
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
  await fireEvent.press(view.getByText('Start from an idea or reference'));
  await fireEvent.press(await view.findByText('Save mocked direction'));
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
  expect(view.getByTestId('screen-title').props.children).toBe('Studio');
  expect(view.getByText('Saved direction')).toBeTruthy();
  expect(view.getByText('Current saved revision · Revision 1')).toBeTruthy();
  expect(view.getByLabelText('Saved direction revision thumbnail').props.source.headers).toEqual({
    Authorization: 'Bearer server-issued-test-token',
  });

  for (const action of ['Save as a variation', 'Present this design', 'Refine this design']) {
    await pressStudioAction(view, action);
    expect(await view.findByTestId('active-design-context')).toBeTruthy();
    if (action === 'Save as a variation') {
      expect(view.getAllByText('Starting Revision 1').length).toBeGreaterThanOrEqual(1);
    } else {
      expect(view.getByText('Current saved revision · Revision 1')).toBeTruthy();
    }
  }

  fireEvent.press(await view.findByText('Review starting design'));
  fireEvent.press(await view.findByText('Save starting facts'));
  expect(await view.findByText('Confirmed direction')).toBeTruthy();
  expect(view.getByText('Current saved revision · Revision 2')).toBeTruthy();

  await pressStudioAction(view, 'Generate technical views');
  expect(await view.findByTestId('active-design-context')).toBeTruthy();
  expect(view.getByText('Current saved revision · Revision 2')).toBeTruthy();

  fireEvent.press(view.getByLabelText('Open revision history'));
  expect(await view.findByText('Vary exact project_1')).toBeTruthy();
});

test('every visible contextual action reaches its named destination', async () => {
  authenticate();
  const view = await render(<App />);

  await waitFor(() => expect(view.getByText('Start from an idea or reference')).toBeTruthy());
  fireEvent.press(view.getByText('Start from an idea or reference'));
  fireEvent.press(await view.findByText('Save mocked direction'));
  expect(await view.findByText('Refine route reached')).toBeTruthy();

  for (const [label, destination] of [
    ['Save as a variation', 'Vary route reached for project_1 via asset_1'],
    ['Refine this design', 'Refine route reached'],
    ['Present this design', 'Present route reached for asset_1'],
  ] as const) {
    await pressStudioAction(view, label);
    expect(await view.findByText(destination)).toBeTruthy();
  }

  const user = userEvent.setup();
  await openStudioMoreActions(view);
  expect(await view.findByText('Starting design facts')).toBeTruthy();
  await user.press(view.getByLabelText('More actions'));
  await waitFor(() => expect(view.queryByText('Starting design facts')).toBeNull());

  await user.press(view.getByLabelText(
    'Generate technical views; Save starting facts first',
  ));
  expect(await view.findByText('Save starting facts')).toBeTruthy();
  expect(view.getAllByText('Studio').length).toBeGreaterThan(0);
  fireEvent.press(view.getByText('Save starting facts'));
  expect(await view.findByText('Views route reached')).toBeTruthy();

  await pressStudioAction(view, 'Create a design');
  expect(await view.findByText('Save mocked direction')).toBeTruthy();
  expect(view.queryByTestId('active-design-context')).toBeNull();
});

test('More opens Starting design facts in the confirmation workspace', async () => {
  authenticate();
  const view = await render(<App />);

  await waitFor(() => expect(view.getByText('Start from an idea or reference')).toBeTruthy());
  fireEvent.press(view.getByText('Start from an idea or reference'));
  fireEvent.press(await view.findByText('Save mocked direction'));
  expect(await view.findByText('Refine route reached')).toBeTruthy();

  const user = userEvent.setup();
  await openStudioMoreActions(view);
  await user.press(await view.findByText('Starting design facts'));

  expect(await view.findByText('Save starting facts')).toBeTruthy();
  expect(view.getAllByText('Studio').length).toBeGreaterThan(0);
  expect(view.queryByText('Refine route reached')).toBeNull();
});

test.each(['VARIATION_BRANCH', 'RESTORED_REVISION'])(
  '%s keeps Starting design facts available when the backend confirms its lineage',
  async (capability) => {
    mockSavedPreSpecCapability = capability;
    authenticate();
    const view = await render(<App />);

    await waitFor(() => expect(
      view.getByText('Start from an idea or reference'),
    ).toBeTruthy());
    fireEvent.press(view.getByText('Start from an idea or reference'));
    fireEvent.press(await view.findByText('Save mocked direction'));
    expect(await view.findByText('Refine route reached')).toBeTruthy();

    await openStudioMoreActions(view);
    expect(await view.findByText('Starting design facts')).toBeTruthy();
  },
);

test('starting-design review returns the designer to Refine with the pending sentence intact', async () => {
  authenticate();
  const view = await render(<App />);

  await waitFor(() => expect(view.getByText('Start from an idea or reference')).toBeTruthy());
  fireEvent.press(view.getByText('Start from an idea or reference'));
  fireEvent.press(await view.findByText('Save mocked direction'));
  expect(await view.findByText('Refine route reached')).toBeTruthy();

  fireEvent.press(await view.findByText('Review starting design'));
  fireEvent.press(await view.findByText('Save starting facts'));

  expect(await view.findByText('Refine route reached')).toBeTruthy();
  expect(view.getByText('Pending instruction: Use rose gold')).toBeTruthy();
});

test('Create hides the previous design controls without forgetting the saved design', async () => {
  authenticate();
  const view = await render(<App />);

  await fireEvent.press(await view.findByText('Start from an idea or reference'));
  await fireEvent.press(await view.findByText('Save mocked direction'));
  expect(await view.findByText('Refine route reached')).toBeTruthy();
  expect(view.getByTestId('active-design-context')).toBeTruthy();

  await pressStudioAction(view, 'Create a design');
  expect(await view.findByText('Save mocked direction')).toBeTruthy();
  for (const label of [
    'Save as a variation',
    'Refine this design',
    'Present this design',
    'More actions',
    'Open revision history',
  ]) {
    expect(view.queryByLabelText(label)).toBeNull();
  }
  expect(view.queryByTestId('active-design-context')).toBeNull();

  await fireEvent.press(view.getByLabelText('Back to Studio'));
  const savedCover = await view.findByLabelText('Current design cover');
  expect(view.getByText('Saved direction')).toBeTruthy();

  await fireEvent.press(savedCover);
  expect(await view.findByText('Refine route reached')).toBeTruthy();
  expect(view.getByText('Current saved revision · Revision 1')).toBeTruthy();
});

test('Studio home opens Collections through the saved-work continuation', async () => {
  authenticate();
  const view = await render(<App />);

  const continuation = await view.findByLabelText('Continue saved work');
  fireEvent.press(continuation);
  expect(await view.findByText('Vary exact none')).toBeTruthy();
});

test('Collections can return an empty account directly to Create', async () => {
  authenticate();
  const view = await render(<App />);

  fireEvent.press(await view.findByRole('tab', { name: 'Collections' }));
  fireEvent.press(await view.findByText('Start a design from Collections'));

  expect(await view.findByText('Save mocked direction')).toBeTruthy();
  expect(view.queryByTestId('global-navigation')).toBeNull();
  expect(view.getByLabelText('Back to Studio')).toBeTruthy();
});

test('the latest family selection wins when an older project request resolves last', async () => {
  authenticate();
  const older = deferred<any>();
  const latest = deferred<any>();
  mockGetProject.mockImplementation((projectId: string) => (
    projectId === 'project_a' ? older.promise : latest.promise
  ));
  const view = await render(<App />);

  fireEvent.press(await view.findByRole('tab', { name: 'Collections' }));
  const projectA = await view.findByText('Open project A');
  const projectB = view.getByText('Open project B');
  await act(async () => {
    fireEvent.press(projectA);
    await Promise.resolve();
  });
  await act(async () => {
    fireEvent.press(projectB);
    latest.resolve({ data: hydratedProjectFor('project_b', 'asset_b'), error: null, status: 200 });
    await latest.promise;
    await Promise.resolve();
  });
  expect(await view.findByText('Vary exact project_b')).toBeTruthy();

  await act(async () => {
    older.resolve({ data: hydratedProjectFor('project_a', 'asset_a'), error: null, status: 200 });
    await older.promise;
    await Promise.resolve();
  });
  await waitFor(() => {
    expect(view.getByText('Vary exact project_b')).toBeTruthy();
    expect(view.queryByText('Vary exact project_a')).toBeNull();
  });
});

test('a newer Collections action cannot be overridden by an older project hydration', async () => {
  authenticate();
  const hydration = deferred<any>();
  mockGetProject.mockReturnValue(hydration.promise);
  const view = await render(<App />);

  fireEvent.press(await view.findByRole('tab', { name: 'Collections' }));
  fireEvent.press(await view.findByText('Open project A'));
  await waitFor(() => expect(mockGetProject).toHaveBeenCalledWith('project_a'));
  fireEvent.press(view.getByText('Start a design from Collections'));
  expect(await view.findByText('Save mocked direction')).toBeTruthy();

  await act(async () => {
    hydration.resolve({
      data: hydratedProjectFor('project_a', 'asset_a'), error: null, status: 200,
    });
    await hydration.promise;
    await Promise.resolve();
  });

  expect(view.getByText('Save mocked direction')).toBeTruthy();
  expect(view.queryByText('Vary exact project_a')).toBeNull();
});

test('an older family request cannot surface a stale error over the latest selection', async () => {
  authenticate();
  const older = deferred<any>();
  const latest = deferred<any>();
  mockGetProject.mockImplementation((projectId: string) => (
    projectId === 'project_a' ? older.promise : latest.promise
  ));
  const view = await render(<App />);

  fireEvent.press(await view.findByRole('tab', { name: 'Collections' }));
  const projectA = await view.findByText('Open project A');
  const projectB = view.getByText('Open project B');
  await act(async () => {
    fireEvent.press(projectA);
    await Promise.resolve();
  });
  await act(async () => {
    fireEvent.press(projectB);
    latest.resolve({ data: hydratedProjectFor('project_b', 'asset_b'), error: null, status: 200 });
    await latest.promise;
    await Promise.resolve();
  });
  expect(await view.findByText('Vary exact project_b')).toBeTruthy();

  await act(async () => {
    older.resolve({
      data: null,
      error: {
        code: 'NETWORK_ERROR', category: 'network', status: 0,
        message: 'Older request failed.', retryable: true,
      },
      status: 0,
    });
    await older.promise;
    await Promise.resolve();
  });
  await waitFor(() => {
    expect(view.getByText('Vary exact project_b')).toBeTruthy();
    expect(view.queryByText(/could not connect/i)).toBeNull();
    expect(view.queryByText('Retry')).toBeNull();
  });
});

test('Collections delegates variation creation to Studio Vary with the exact active project', async () => {
  authenticate();
  const view = await render(<App />);

  await waitFor(() => expect(view.getByText('Start from an idea or reference')).toBeTruthy());
  fireEvent.press(view.getByText('Start from an idea or reference'));
  fireEvent.press(await view.findByText('Save mocked direction'));
  expect(await view.findByText('Refine route reached')).toBeTruthy();

  fireEvent.press(view.getByLabelText('Open revision history'));
  fireEvent.press(await view.findByText('Vary exact project_1'));
  expect(await view.findByText('Vary route reached for project_1 via asset_1')).toBeTruthy();
  expect((await view.findAllByText('Starting Revision 1')).length).toBeGreaterThanOrEqual(1);
});

test('Collections routes a historical revision to canonical Vary without restoring it first', async () => {
  authenticate();
  const view = await render(<App />);

  await fireEvent.press(await view.findByText('Start from an idea or reference'));
  await fireEvent.press(await view.findByText('Save mocked direction'));
  fireEvent.press(view.getByLabelText('Open revision history'));
  fireEvent.press(await view.findByText('Vary from mocked Revision 1'));

  expect(await view.findByText(
    'Vary route reached for project_1 via asset_history_1',
  )).toBeTruthy();
  expect(view.getAllByText('Starting Revision 1').length).toBeGreaterThanOrEqual(1);
});

test('Collections returns the selected exact revision to Refine', async () => {
  authenticate();
  const view = await render(<App />);

  await waitFor(() => expect(view.getByText('Start from an idea or reference')).toBeTruthy());
  fireEvent.press(view.getByText('Start from an idea or reference'));
  fireEvent.press(await view.findByText('Save mocked direction'));
  expect(await view.findByText('Refine route reached')).toBeTruthy();

  fireEvent.press(view.getByLabelText('Open revision history'));
  fireEvent.press(await view.findByText('Continue refining exact revision'));
  expect(await view.findByText('Refine route reached')).toBeTruthy();
});

test('accepted Refine handoff opens Collections and Present for the exact active revision', async () => {
  authenticate();
  const view = await render(<App />);

  await waitFor(() => expect(view.getByText('Start from an idea or reference')).toBeTruthy());
  fireEvent.press(view.getByText('Start from an idea or reference'));
  fireEvent.press(await view.findByText('Save mocked direction'));
  expect(await view.findByText('Refine route reached')).toBeTruthy();

  await fireEvent.press(view.getByText('Refine handoff to Collections'));
  expect(await view.findByText('Vary exact project_1')).toBeTruthy();
  await fireEvent.press(view.getByText('Continue refining exact revision'));
  expect(await view.findByText('Refine route reached')).toBeTruthy();
  await fireEvent.press(view.getByText('Refine handoff to Present'));
  expect(await view.findByText('Present route reached for asset_1')).toBeTruthy();
});

test('Collections sends the exact active revision to Present', async () => {
  authenticate();
  const view = await render(<App />);

  await waitFor(() => expect(view.getByText('Start from an idea or reference')).toBeTruthy());
  fireEvent.press(view.getByText('Start from an idea or reference'));
  fireEvent.press(await view.findByText('Save mocked direction'));
  expect(await view.findByText('Refine route reached')).toBeTruthy();
  fireEvent.press(view.getByLabelText('Open revision history'));

  expect(view.queryByText('Review optional Factory readiness')).toBeNull();
  fireEvent.press(await view.findByText('Present exact current revision'));
  expect(await view.findByText('Present route reached for asset_1')).toBeTruthy();
  expect(await view.findByText('Present destination client')).toBeTruthy();

  fireEvent.press(view.getByLabelText('Open revision history'));
  fireEvent.press(await view.findByText('Market exact current revision'));
  expect(await view.findByText('Present route reached for asset_1')).toBeTruthy();
  expect(await view.findByText('Present destination marketing')).toBeTruthy();
});

test('Collections keeps optional Factory out of the everyday exact-revision handoff', async () => {
  authenticate();
  const view = await render(<App />);

  await waitFor(() => expect(view.getByText('Start from an idea or reference')).toBeTruthy());
  fireEvent.press(view.getByText('Start from an idea or reference'));
  fireEvent.press(await view.findByText('Save mocked direction'));
  fireEvent.press(await view.findByText('Review starting design'));
  fireEvent.press(await view.findByText('Save starting facts'));
  expect(await view.findByText('Refine route reached')).toBeTruthy();

  fireEvent.press(view.getByLabelText('Open revision history'));
  expect(view.queryByText(/Factory/i)).toBeNull();
});

test('Collections also hides Factory when the exact ring is already pack-ready', async () => {
  mockConfirmedFactoryReady = true;
  mockGetProject.mockResolvedValue({ data: eligibleFactoryProject(), error: null, status: 200 });
  authenticate();
  const view = await render(<App />);

  await waitFor(() => expect(view.getByText('Start from an idea or reference')).toBeTruthy());
  fireEvent.press(view.getByText('Start from an idea or reference'));
  fireEvent.press(await view.findByText('Save mocked direction'));
  fireEvent.press(await view.findByText('Review starting design'));
  fireEvent.press(await view.findByText('Save starting facts'));
  expect(await view.findByText('Refine route reached')).toBeTruthy();

  fireEvent.press(view.getByLabelText('Open revision history'));
  expect(view.queryByText(/Factory/i)).toBeNull();
});

test('Collections hides Factory readiness for an exact non-ring revision', async () => {
  mockConfirmedJewelryType = 'necklace';
  authenticate();
  const view = await render(<App />);

  await waitFor(() => expect(view.getByText('Start from an idea or reference')).toBeTruthy());
  fireEvent.press(view.getByText('Start from an idea or reference'));
  fireEvent.press(await view.findByText('Save mocked direction'));
  fireEvent.press(await view.findByText('Review starting design'));
  fireEvent.press(await view.findByText('Save starting facts'));
  expect(await view.findByText('Refine route reached')).toBeTruthy();
  expect(mockGetStudioCapabilities).not.toHaveBeenCalled();

  fireEvent.press(view.getByLabelText('Open revision history'));
  expect(view.queryByText(/Factory/i)).toBeNull();
});

test('Collections hides Factory readiness when the account lacks entitlement', async () => {
  mockFactoryReviewEnabled = false;
  mockConfirmedFactoryReady = true;
  authenticate();
  const view = await render(<App />);

  await waitFor(() => expect(view.getByText('Start from an idea or reference')).toBeTruthy());
  fireEvent.press(view.getByText('Start from an idea or reference'));
  fireEvent.press(await view.findByText('Save mocked direction'));
  fireEvent.press(await view.findByText('Review starting design'));
  fireEvent.press(await view.findByText('Save starting facts'));
  expect(await view.findByText('Refine route reached')).toBeTruthy();
  await waitFor(() => expect(mockGetStudioCapabilities).toHaveBeenCalled());

  fireEvent.press(view.getByLabelText('Open revision history'));
  expect(view.queryByText(/Factory/i)).toBeNull();
});

test('Views resumes after starting facts and an open Factory fails closed after revocation', async () => {
  mockConfirmedFactoryReady = true;
  mockGetProject.mockResolvedValue({ data: eligibleFactoryProject(), error: null, status: 200 });
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
  const prerequisiteViews = view.getByLabelText(
    'Generate technical views; Save starting facts first',
  );
  expect(prerequisiteViews.props.accessibilityState).toEqual({
    disabled: false, selected: false,
  });
  expect(prerequisiteViews.props.accessibilityHint).toContain(
    'Opens Review starting design facts, then continues to Views.',
  );
  expect(view.queryByText('Views route reached')).toBeNull();
  await userEvent.setup().press(prerequisiteViews);
  expect(await view.findByText('Save starting facts')).toBeTruthy();
  expect(view.queryByText('Views route reached')).toBeNull();

  fireEvent.press(await view.findByText('Save starting facts'));

  expect(await view.findByText('Views route reached')).toBeTruthy();
  expect(view.queryByText('Save starting facts')).toBeNull();
  expect(view.queryByText('Your design families')).toBeNull();
  expect(view.queryByText(/Factory/i)).toBeNull();
  expect(view.getByLabelText('Generate technical views').props.accessibilityState).toEqual({
    disabled: false, selected: true,
  });
  await userEvent.setup().press(view.getByLabelText('Refine this design'));
  expect(await view.findByText('Refine route reached')).toBeTruthy();
  expect(view.getByLabelText('More actions')).toBeTruthy();
  await openStudioMoreActions(view);
  expect(await view.findByText('Specifications')).toBeTruthy();
  expect(await view.findByText('Factory')).toBeTruthy();
  await userEvent.setup().press(view.getByText('Specifications'));
  expect(await view.findByText('Advanced specifications route reached')).toBeTruthy();
  expect(view.queryByText('Refine route reached')).toBeNull();
  await openStudioMoreActions(view);
  mockFactoryProjectUpdate = {
    ...eligibleFactoryProject(),
    factory_ready: false,
    factory_blockers: [{
      code: 'source_component_unresolved',
      subject_kind: 'source_component',
      subject_id: 'setting.shoulder',
      element_id: 'setting.shoulder',
      component_id: 'setting.shoulder',
      role: 'shoulder',
      label: 'Shoulder',
      detail: 'The shoulder still needs an exact construction decision.',
      required_resolution: 'Resolve the shoulder before Factory review.',
    }],
  };
  await userEvent.setup().press(await view.findByText('Factory'));
  expect(await view.findByText('Factory route reached for asset_exact_1')).toBeTruthy();
  expect(view.queryByText(/destination will use the exact active revision/i)).toBeNull();

  const recheck = deferred<any>();
  mockGetStudioCapabilities.mockImplementationOnce(() => recheck.promise);
  const capabilityCallsBeforeRefresh = mockGetStudioCapabilities.mock.calls.length;
  await userEvent.setup().press(view.getByText('Refresh mocked Factory project'));
  await waitFor(() => expect(mockGetStudioCapabilities).toHaveBeenCalledTimes(
    capabilityCallsBeforeRefresh + 1,
  ));
  // The same exact revision remains mounted while its backend recheck is in
  // flight, avoiding a transient eligibility-null redirect or route flicker.
  expect(view.getByText('Factory route reached for asset_exact_1')).toBeTruthy();

  await act(async () => {
    recheck.resolve({
      data: {
        factory_review: { enabled: true, scope: 'principal' },
        workspace_entitlements_available: false,
      },
      error: null,
      status: 200,
    });
  });

  expect(await view.findByText('Refine route reached')).toBeTruthy();
  expect(view.queryByText('Factory route reached for asset_exact_1')).toBeNull();
  await openStudioMoreActions(view);
  expect(view.queryByText('Factory')).toBeNull();
});

test('Factory never renders a newly changed exact revision under the prior authorization', async () => {
  mockConfirmedFactoryReady = true;
  mockGetProject.mockResolvedValue({ data: eligibleFactoryProject(), error: null, status: 200 });
  authenticate();
  const view = await render(<App />);

  fireEvent.press(await view.findByText('Start from an idea or reference'));
  fireEvent.press(await view.findByText('Save mocked direction'));
  fireEvent.press(await view.findByText('Review starting design'));
  fireEvent.press(await view.findByText('Save starting facts'));
  expect(await view.findByText('Refine route reached')).toBeTruthy();
  await openStudioMoreActions(view);

  const prior = eligibleFactoryProject();
  const nextRevision = {
    ...prior.active_revision,
    asset_id: 'asset_exact_2',
    revision: 3,
    design_version: 2,
    sha256: '3'.repeat(64),
  };
  mockFactoryProjectUpdate = {
    ...prior,
    active_asset_id: 'asset_exact_2',
    active_design_version: 2,
    active_revision: nextRevision,
    pinned_revision: { ...nextRevision, pinned: true },
    cover_asset_id: 'asset_exact_2',
  };
  fireEvent.press(await view.findByText('Factory'));
  expect(await view.findByText('Factory route reached for asset_exact_1')).toBeTruthy();

  fireEvent.press(view.getByText('Refresh mocked Factory project'));

  await waitFor(() => {
    expect(view.queryByText('Factory route reached for asset_exact_1')).toBeNull();
    expect(view.queryByText('Factory route reached for asset_exact_2')).toBeNull();
    expect(view.getByText('Refine route reached')).toBeTruthy();
  });
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
  ['present', 'Present route reached for asset_hydrated'],
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

test('Activity historical review is read-only until the designer returns to the current revision', async () => {
  authenticate();
  mockGetStudioJob.mockResolvedValueOnce({
    data: {
      job_id: 'job_refine', owner: 'usr_designer', action_id: 'refine',
      lane: 'trusted_structural', status: 'reviewing', progress: 0.9,
      active_design_id: 'project_hydrated', source_revision_id: 'asset_stale',
      error_code: null, created_at: '2026-07-12T00:00:00Z',
      updated_at: '2026-07-12T00:00:01Z',
      billing: { requested_outputs: 1, credits_per_output: 20, estimated_credits: 20,
        completed_outputs: 0, charged_outputs: 0, charged_credits: 0, policy: 'test' },
    },
    error: null,
    status: 200,
  });
  mockGetProject.mockResolvedValue({
    data: staleActivitySourceProject, error: null, status: 200,
  });
  const view = await render(<App />);
  await waitFor(() => expect(view.getByText('Start from an idea or reference')).toBeTruthy());
  fireEvent.press(view.getAllByText('Activity').at(-1)!);
  fireEvent.press(await view.findByText('Review refine'));

  expect(await view.findByText('Refine route reached')).toBeTruthy();
  expect(view.getByText('Review source · Revision 1')).toBeTruthy();
  expect(view.queryByTestId('studio-action-rail')).toBeNull();
  expect(view.queryByText('Factory')).toBeNull();
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
  const unavailableViews = view.getByLabelText('Generate technical views');
  expect(unavailableViews.props.accessibilityState).toEqual({ disabled: true, selected: false });
  expect(unavailableViews.props.accessibilityHint).toContain(
    'Choose a confirmable ring direction first',
  );
  await userEvent.setup().press(unavailableViews);
  expect(view.queryByText('Save starting facts')).toBeNull();
  expect(view.queryByText('Views route reached')).toBeNull();
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
  expect(view.getByText('Create review selection: default')).toBeTruthy();
  expect(mockGetProject).toHaveBeenCalledWith('project_hydrated');
});

test('a pending Activity Create hydration cannot override newer global navigation', async () => {
  authenticate();
  const hydration = deferred<any>();
  mockGetProject.mockReturnValue(hydration.promise);
  const view = await render(<App />);

  fireEvent.press(await view.findByRole('tab', { name: 'Activity' }));
  fireEvent.press(await view.findByText('Review create'));
  await waitFor(() => expect(mockGetProject).toHaveBeenCalledWith('project_hydrated'));

  fireEvent.press(view.getByRole('tab', { name: 'Learn' }));
  expect(await view.findByText('Learn the workflow, when you need it.')).toBeTruthy();
  await act(async () => {
    hydration.resolve({ data: hydratedProject, error: null, status: 200 });
    await hydration.promise;
    await Promise.resolve();
  });

  expect(view.getByText('Learn the workflow, when you need it.')).toBeTruthy();
  expect(view.queryByText(/Create review reached for project_hydrated/)).toBeNull();
});

test('Activity reviewing Create restores the exact mutable review draft separately from history', async () => {
  authenticate();
  const creativeDirection = (assetId: string) => ({
    ...hydratedProject.active_revision,
    asset_id: assetId,
    root_id: 'project_hydrated',
    capability: 'CREATIVE_RENDER',
    provenance: 'pre_spec_creative_candidate',
    revision: null,
    design_id: null,
    design_version: null,
  });
  const directionOne = creativeDirection('candidate_direction_1');
  const directionTwo = creativeDirection('candidate_direction_2');
  mockGetProject.mockResolvedValue({
    data: {
      ...hydratedProject,
      active_asset_id: null,
      active_revision: null,
      selected_candidate_asset_id: null,
      creative_candidates: [directionOne, directionTwo],
      assets: [directionOne, directionTwo],
    },
    error: null,
    status: 200,
  });
  mockGetCreativeDirectionReviewDraft.mockResolvedValueOnce({
    data: {
      project_root_id: 'project_hydrated',
      studio_job_id: 'job_create',
      selected_candidate_id: 'candidate_direction_2',
      retained: [{ candidate_id: 'candidate_direction_1', label: 'Slim gallery' }],
      version: 4,
      updated_at: '2026-07-12T00:00:02Z',
    },
    error: null,
    status: 200,
  });

  const view = await render(<App />);
  await waitFor(() => expect(view.getByText('Start from an idea or reference')).toBeTruthy());
  fireEvent.press(view.getAllByText('Activity').at(-1)!);
  fireEvent.press(await view.findByText('Review create'));

  expect(await view.findByText('Create review selection: candidate_direction_2')).toBeTruthy();
  expect(mockGetCreativeDirectionReviewDraft).toHaveBeenCalledWith(
    'project_hydrated', 'job_create',
  );
});

test('Activity generated-direction archive opens the completed Create project in Collections', async () => {
  authenticate();
  const hydration = deferred<any>();
  mockGetProject.mockReturnValue(hydration.promise);
  const view = await render(<App />);
  await waitFor(() => expect(view.getByText('Start from an idea or reference')).toBeTruthy());
  fireEvent.press(view.getAllByText('Activity').at(-1)!);
  const openArchive = await view.findByText('Open hydrated design');
  await act(async () => {
    fireEvent.press(openArchive);
    hydration.resolve({ data: hydratedProject, error: null, status: 200 });
    await hydration.promise;
  });

  expect(await view.findByText('Vary exact project_hydrated')).toBeTruthy();
  expect(mockGetProject).toHaveBeenCalledWith('project_hydrated');
});
