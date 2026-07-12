/// <reference types="jest" />

import { act, renderHook, waitFor } from '@testing-library/react-native';

import type { TrustedApiClient } from './client';
import type {
  ApiResult,
  AssetSummary,
  CreateLineArtRequest,
  CreateProjectFromDrawingRequest,
  CreateProjectFromPromptRequest,
  DrawingConfirmationResult,
  JsonObject,
  LineArtSourceSelection,
  ProjectDetail,
} from './types';
import { useTrustedWorkflow } from './useTrustedWorkflow';

const activeAsset: AssetSummary = {
  asset_id: 'asset_reference',
  root_id: 'project_imported',
  parent_asset_id: null,
  capability: 'SOURCE_REFERENCE',
  provenance: 'designer_confirmed_import',
  revision: 1,
  design_id: 'design_imported',
  design_version: 4,
  region: null,
  instruction: null,
  drift: null,
  pinned: false,
  media_type: 'image/png',
  image_url: 'https://facetta.test/assets/asset_reference/image',
  created_by: 'usr_designer',
  created_at: null,
  legacy_provenance: false,
};

const project: ProjectDetail = {
  id: 'project_imported',
  root_id: 'project_imported',
  title: 'Imported designer plate',
  collection: null,
  tags: [],
  owner: 'usr_designer',
  state: 'refining',
  design_id: 'design_imported',
  spec: { jewelry_type: 'ring' },
  active_asset_id: activeAsset.asset_id,
  active_design_version: 4,
  active_revision: activeAsset,
  pinned_revision: null,
  revisions: [],
  assets: [activeAsset],
  derived_assets: [],
  approval: null,
  factory_ready: false,
  factory_blockers: [],
  primary_revision_count: 1,
  has_factory_drawing: false,
  cover_asset_id: activeAsset.asset_id,
  created_at: null,
  updated_at: null,
};

const drawingResult: DrawingConfirmationResult = {
  status: 'confirmation_required',
  project_id: project.id,
  image_run_id: 'run_line',
  quality_report: {
    verdict: 'pass',
    accepted: false,
    review_required: true,
    score: 95,
    summary: 'Geometry is ready for designer confirmation.',
    failed_checks: [],
    warnings: [],
    checks: [],
  },
  routing: {
    attempt_count: 1,
    used_retry: false,
    used_fallback: false,
    cache_hit: false,
    run_id: 'run_line',
  },
  view: 'front',
  candidate: {
    run_id: 'run_line',
    candidate_id: 'candidate_line',
    preview_url: 'https://facetta.test/image-runs/run_line/candidates/candidate_line/image',
    qa: {
      verdict: 'pass',
      accepted: false,
      review_required: true,
      score: 95,
      summary: 'Geometry is ready for designer confirmation.',
      failed_checks: [],
      warnings: [],
      checks: [],
    },
    operation: 'VISUAL_ONLY_EDIT',
    requested_change: 'Create isolated line art.',
    asset_capability: 'LINE_ART',
  },
  next: 'Confirm the selected-view geometry.',
};

describe('useTrustedWorkflow line-art source isolation', () => {
  test('carries the same defensive source-region snapshot through regeneration', async () => {
    const getProject = jest.fn(async (): Promise<ApiResult<ProjectDetail>> => ({
      data: project,
      error: null,
      status: 200,
    }));
    const createLineArt = jest.fn(
      async (
        _projectId: string,
        _request: CreateLineArtRequest,
      ): Promise<ApiResult<DrawingConfirmationResult>> => ({
        data: drawingResult,
        error: null,
        status: 202,
      }),
    );
    const recordImageRunFeedback = jest.fn(
      async (): Promise<ApiResult<JsonObject>> => ({ data: {}, error: null, status: 201 }),
    );
    const api = {
      getProject,
      createLineArt,
      recordImageRunFeedback,
    } as unknown as TrustedApiClient;

    const { result } = await renderHook(() => useTrustedWorkflow(api, {
      designer: 'usr_designer',
      initialProjectId: project.id,
      restoreLastProject: false,
    }));

    await waitFor(() => expect(result.current.state.project?.id).toBe(project.id));

    const sourceSelection: LineArtSourceSelection = {
      source_region_description: 'Front elevation in the upper-left reference panel.',
      source_region: { x: 0.08, y: 0.12, width: 0.55, height: 0.38 },
    };
    await act(async () => {
      await result.current.createLineArt('front', sourceSelection);
    });
    await waitFor(() => expect(result.current.state.warning_candidate?.asset_capability)
      .toBe('LINE_ART'));

    sourceSelection.source_region!.x = 0.9;
    await act(async () => {
      await result.current.regenerateWarningCandidate();
    });

    expect(createLineArt).toHaveBeenCalledTimes(2);
    expect(createLineArt.mock.calls[0]?.[1]).toMatchObject({
      view: 'front',
      source_region_description: 'Front elevation in the upper-left reference panel.',
      source_region: { x: 0.08, y: 0.12, width: 0.55, height: 0.38 },
      variant: 0,
    });
    expect(createLineArt.mock.calls[1]?.[1]).toMatchObject({
      view: 'front',
      source_region_description: 'Front elevation in the upper-left reference panel.',
      source_region: { x: 0.08, y: 0.12, width: 0.55, height: 0.38 },
      variant: 1,
    });
  });
});

describe('useTrustedWorkflow creative drawing intake', () => {
  test('submits a category-neutral prompt project with multiple visual directions', async () => {
    const creativeProject: ProjectDetail = {
      ...project,
      id: 'project_prompt',
      root_id: 'project_prompt',
      title: 'Emerald lariat exploration',
      design_id: null,
      spec: null,
      active_design_version: null,
      approval: null,
      factory_ready: false,
      factory_blockers: [],
    };
    const createProjectFromPrompt = jest.fn(async (
      _request: CreateProjectFromPromptRequest,
    ): Promise<ApiResult<ProjectDetail>> => ({
      data: creativeProject,
      error: null,
      status: 201,
    }));
    const api = { createProjectFromPrompt } as unknown as TrustedApiClient;
    const { result } = await renderHook(() => useTrustedWorkflow(api, {
      designer: 'usr_designer',
      restoreLastProject: false,
    }));

    await act(async () => {
      await result.current.createFromPrompt({
        prompt: '  A platinum floral lariat necklace with emerald leaves.  ',
        variation_count: 4,
        title: 'Emerald lariat exploration',
      });
    });

    expect(createProjectFromPrompt).toHaveBeenCalledWith({
      prompt: 'A platinum floral lariat necklace with emerald leaves.',
      variation_count: 4,
      title: 'Emerald lariat exploration',
      owner: 'usr_designer',
    });
    expect(result.current.state.project?.id).toBe('project_prompt');
    expect(result.current.state.project?.design_id).toBeNull();
  });

  test('rejects a blank creative prompt before a provider request', async () => {
    const createProjectFromPrompt = jest.fn();
    const api = { createProjectFromPrompt } as unknown as TrustedApiClient;
    const { result } = await renderHook(() => useTrustedWorkflow(api, {
      designer: 'usr_designer',
      restoreLastProject: false,
    }));

    await act(async () => {
      await result.current.createFromPrompt({
        prompt: '   ',
        title: 'Study',
      });
    });
    expect(result.current.state.error?.code).toBe('CREATIVE_PROMPT_REQUIRED');
    expect(createProjectFromPrompt).not.toHaveBeenCalled();
  });

  test('submits a neutral multi-candidate request without inventing a spec', async () => {
    const creativeProject: ProjectDetail = {
      ...project,
      id: 'project_creative',
      root_id: 'project_creative',
      title: 'Pendant study',
      design_id: null,
      spec: null,
      active_design_version: null,
      approval: null,
      factory_ready: false,
      factory_blockers: [],
    };
    const createProjectFromDrawing = jest.fn(async (
      _request: CreateProjectFromDrawingRequest,
    ): Promise<ApiResult<ProjectDetail>> => ({
      data: creativeProject,
      error: null,
      status: 201,
    }));
    const api = { createProjectFromDrawing } as unknown as TrustedApiClient;
    const { result } = await renderHook(() => useTrustedWorkflow(api, {
      designer: 'usr_designer',
      restoreLastProject: false,
    }));

    await act(async () => {
      await result.current.createFromDrawing({
        image_base64: '  c291cmNl  ',
        media_type: 'image/png',
        instruction: '  Preserve every visible link and render polished platinum.  ',
        variation_count: 3,
        title: 'Pendant study',
        source_region_description: '  Front necklace elevation  ',
        source_region: { x: 0.2, y: 0.1, width: 0.6, height: 0.5 },
      });
    });

    expect(createProjectFromDrawing).toHaveBeenCalledWith({
      image_base64: 'c291cmNl',
      media_type: 'image/png',
      instruction: 'Preserve every visible link and render polished platinum.',
      variation_count: 3,
      title: 'Pendant study',
      source_region_description: 'Front necklace elevation',
      source_region: { x: 0.2, y: 0.1, width: 0.6, height: 0.5 },
      owner: 'usr_designer',
    });
    expect(result.current.state.project?.id).toBe('project_creative');
    expect(result.current.state.project?.design_id).toBeNull();
  });

  test('rejects missing image or direction before a provider request', async () => {
    const createProjectFromDrawing = jest.fn();
    const api = { createProjectFromDrawing } as unknown as TrustedApiClient;
    const { result } = await renderHook(() => useTrustedWorkflow(api, {
      designer: 'usr_designer',
      restoreLastProject: false,
    }));

    await act(async () => {
      await result.current.createFromDrawing({
        image_base64: '',
        instruction: 'render',
        title: 'Study',
      });
    });
    expect(result.current.state.error?.code).toBe('IMAGE_REQUIRED');
    await act(async () => result.current.clearError());
    await act(async () => {
      await result.current.createFromDrawing({
        image_base64: 'c291cmNl',
        instruction: '   ',
        title: 'Study',
      });
    });
    expect(result.current.state.error?.code).toBe('CREATIVE_DIRECTION_REQUIRED');
    expect(createProjectFromDrawing).not.toHaveBeenCalled();
  });

});
