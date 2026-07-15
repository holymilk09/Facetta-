/// <reference types="node" />

import assert from 'node:assert/strict';
import test from 'node:test';
import type {
  ApiErrorCategory, ApiResult, CatalogPreviewResult, ProjectDetail,
  SaveRevisionAsVariationResult, StudioJobRecord,
} from '../trusted/types';
import { createStudioGateway } from './gateway';
import { createStudioJobTestHarness } from './studioJobTestHarness';

const ok = <T>(data: T, status = 200): ApiResult<T> => ({ data, error: null, status });
const unavailable = <T>(): ApiResult<T> => ({
  data: null,
  error: {
    code: 'NOT_AVAILABLE',
    message: 'Endpoint unavailable in this test.',
    category: 'not_found',
    status: 404,
    retryable: false,
  },
  status: 404,
});

const asset = (assetId: string, designVersion: number) => ({
  asset_id: assetId,
  root_id: 'project_1',
  parent_asset_id: null,
  capability: 'SPEC_RENDER',
  provenance: 'studio',
  revision: designVersion,
  design_id: 'design_1',
  design_version: designVersion,
  region: null,
  instruction: null,
  drift: null,
  pinned: false,
  media_type: 'image/png',
  image_url: 'https://example.test/image.png',
  created_by: 'designer_1',
  created_at: '2026-07-12T00:00:00Z',
  legacy_provenance: false,
});

const project = (assetId = 'asset_1', designVersion = 1): ProjectDetail => {
  const active = asset(assetId, designVersion);
  const lineageAssets = assetId === 'asset_1' ? [active] : [asset('asset_1', 1), active];
  return {
    id: 'project_1',
    root_id: 'project_1',
    title: 'Test design',
    collection: null,
    tags: [],
    owner: 'designer_1',
    state: 'refining',
    design_id: 'design_1',
    spec: {},
    active_asset_id: assetId,
    active_design_version: designVersion,
    active_revision: active,
    pinned_revision: null,
    revisions: lineageAssets.map((entry, index) => ({
      revision: index + 1, asset: entry, spec_version: entry.design_version,
      spec_change: [], ignored_fields: [], qa: null, routing: null, created_at: null,
    })),
    assets: lineageAssets,
    derived_assets: [],
    approval: null,
    factory_ready: false,
    factory_blockers: [],
    primary_revision_count: lineageAssets.length,
    has_factory_drawing: false,
    cover_asset_id: assetId,
    created_at: '2026-07-12T00:00:00Z',
    updated_at: '2026-07-12T00:00:00Z',
  };
};

const HISTORICAL_SOURCE_SHA256 = 'a'.repeat(64);

const historicalVariationRequest = {
  projectId: 'project_1',
  sourceAssetId: 'asset_1',
  sourceDesignVersion: 1,
  sourceSha256: HISTORICAL_SOURCE_SHA256,
  expectedActiveAssetId: 'asset_2',
  expectedActiveDesignVersion: 2,
  createdBy: 'designer_1',
  label: 'Earlier geometry study',
  operationId: 'vary:history-0001',
};

function historicalVariationResult(): SaveRevisionAsVariationResult {
  const active = {
    ...asset('variation_2', 1),
    root_id: 'variation_2',
    parent_asset_id: null,
    capability: 'VARIATION_BRANCH',
    provenance: 'studio_variation_branch',
    design_id: 'child_design',
    sha256: HISTORICAL_SOURCE_SHA256,
  };
  const child: ProjectDetail = {
    id: 'variation_2', root_id: 'variation_2', title: 'Earlier geometry study',
    collection: null, tags: [], owner: 'designer_1', state: 'refining',
    design_id: 'child_design', spec: {}, active_asset_id: 'variation_2',
    active_design_version: 1, active_revision: active, pinned_revision: null,
    revisions: [{
      revision: 1, asset: active, spec_version: 1, spec_change: [], ignored_fields: [],
      qa: null, routing: null, created_at: null,
    }],
    assets: [active], derived_assets: [], approval: null, factory_ready: false,
    factory_blockers: [], primary_revision_count: 1, has_factory_drawing: false,
    cover_asset_id: 'variation_2', created_at: '2026-07-15T00:00:00Z',
    updated_at: '2026-07-15T00:00:00Z',
  };
  return {
    status: 'variation_created', family_id: 'family_1', variation_index: 2,
    source_project_id: 'project_1', source_asset_id: 'asset_1',
    source_design_version: 1, source_sha256: HISTORICAL_SOURCE_SHA256,
    guarded_active_asset_id: 'asset_2', guarded_active_design_version: 2,
    child_project_root_id: 'variation_2', child_family_id: 'family_1',
    child_variation_index: 2, child_branched_from_project_root_id: 'project_1',
    child_branched_from_asset_id: 'asset_1', child_asset_id: 'variation_2',
    child_design_id: 'child_design', child_design_version: 1,
    child_sha256: HISTORICAL_SOURCE_SHA256,
    component_map_status: 'unmapped', component_map_sha256: null,
    variation: {
      project_root_id: 'variation_2', asset_id: 'variation_2',
      design_id: 'child_design', design_version: 1, family_id: 'family_1',
      variation_index: 2, branched_from_project_root_id: 'project_1',
      branched_from_asset_id: 'asset_1', component_map_status: 'unmapped',
      component_map_sha256: null,
    },
    project: child,
  };
}

type GatewayClient = Parameters<typeof createStudioGateway>[0];

function fakeClient(overrides: Partial<GatewayClient> = {}): GatewayClient {
  const jobs = createStudioJobTestHarness('studio_job_catalog');
  const unsupported = async () => {
    throw new Error('Unexpected client method');
  };
  return {
    createProjectFromPrompt: unsupported,
    saveAsVariation: unsupported,
    previewCatalogSelection: unsupported,
    acceptCatalogPreview: unsupported,
    discardCatalogPreview: unsupported,
    applyMarkup: unsupported,
    createLineArt: unsupported,
    createStudioBeautyRender: unsupported,
    createStudioProductPhoto: unsupported,
    createMarketingPack: unsupported,
    recordImageRunFeedback: unsupported,
    getProject: unsupported,
    getFactoryPack: unsupported,
    ...jobs.client,
    getStudioCapabilities: async () => ok({
      factory_review: { enabled: false, scope: 'principal' as const },
      workspace_entitlements_available: false as const,
    }),
    ...overrides,
  } as GatewayClient;
}

test('Studio facade owns project and Activity reads and normalizes trusted errors', async () => {
  const getProject = async (projectId: string) => {
    assert.equal(projectId, 'project_1');
    return ok(project());
  };
  const listStudioJobs = async () => ({
    data: null,
    error: {
      code: 'TEMPORARY_FAILURE', message: 'Try again.', category: 'unknown' as const,
      status: 503, retryable: true,
    },
    status: 503,
  });
  const gateway = createStudioGateway(fakeClient({
    getProject,
    listStudioJobs,
    assetImageUrl: (assetId: string) => `https://facetta.test/assets/${assetId}`,
  }));

  const loaded = await gateway.getProject('project_1');
  assert.equal(loaded.error, null);
  assert.equal(loaded.data?.active_asset_id, 'asset_1');
  assert.equal(gateway.assetImageUrl('asset_1'), 'https://facetta.test/assets/asset_1');

  const activity = await gateway.listStudioJobs('designer_1');
  assert.equal(activity.data, null);
  assert.equal(activity.error?.category, 'unavailable');
  assert.equal(activity.error?.retryable, true);
});

const catalogPreview = (): CatalogPreviewResult => ({
  status: 'preview_ready',
  component_path: 'metal.color',
  option_id: 'rose',
  isolation_target: 'all visible metal surfaces',
  source_asset_id: 'asset_1',
  design_version: 1,
  image_run_id: 'run_1',
  spec_change: [],
  next_spec: {},
  qa: {
    verdict: 'pass',
    accepted: true,
    review_required: false,
    score: 1,
    summary: 'Pass',
    failed_checks: [],
    warnings: [],
    checks: [{ key: 'identity', label: 'Identity', verdict: 'pass', severity: 'hard', message: 'Preserved' }],
  },
  routing: { attempt_count: 1, used_retry: false, used_fallback: false, cache_hit: false, run_id: 'run_1' },
  project: project(),
  candidate: {
    run_id: 'run_1',
    candidate_id: 'candidate_1',
    preview_url: 'https://example.test/preview.png',
    accept_url: 'https://example.test/accept',
    discard_url: 'https://example.test/discard',
    save_as_variation_url: 'https://example.test/save-as-variation',
    verdict: 'pass',
    studio_job_id: 'studio_job_catalog',
    expires_in_seconds: 600,
  },
});

const catalogStudioJob = (status: StudioJobRecord['status']): StudioJobRecord => ({
  job_id: 'studio_job_catalog', owner: 'designer_1', action_id: 'refine',
  lane: 'trusted_structural', status, progress: status === 'queued' ? 0 : 0.05,
  active_design_id: 'project_1', source_revision_id: 'asset_1',
  accepted_output_sha256: null, error_code: null,
  created_at: '2026-07-13T00:00:00Z', updated_at: '2026-07-13T00:00:01Z',
  billing: {
    requested_outputs: 1, credits_per_output: 20, estimated_credits: 20,
    completed_outputs: 0, charged_outputs: 0, charged_credits: 0,
    policy: 'Only accepted requested outputs are charged.',
  },
});

test('commits an Original and all retained directions through one atomic client call', async () => {
  const selected = {
    ...project('candidate_3'),
    design_id: null,
    spec: null,
    active_design_version: null,
    selected_candidate_asset_id: 'candidate_3',
  };
  const retainedVariation = {
    status: 'variation_created' as const,
    family_id: 'family_1', variation_index: 2,
    source_project_id: 'project_1', source_asset_id: 'candidate_2',
    project: project('variation_2'),
  };
  const commitCalls: unknown[][] = [];
  const commitCreativeDirections = async (...args: unknown[]) => {
    commitCalls.push(args);
    return ok({
      project: selected,
      retained_variations: [retainedVariation],
    }, 200);
  };
  const gateway = createStudioGateway(fakeClient({ commitCreativeDirections }));

  const result = await gateway.completeCreativeDirectionReview({
    projectId: 'project_1', selectedCandidateId: 'candidate_3',
    retained: [{ candidateId: 'candidate_2', label: ' Direction 2 ' }],
    createdBy: 'designer_1', studioJobId: 'studio_job_create',
  });

  assert.equal(result.error, null);
  assert.equal(commitCalls.length, 1);
  assert.deepEqual(commitCalls[0], ['project_1', {
    created_by: 'designer_1', selected_candidate_id: 'candidate_3',
    retained: [{ candidate_id: 'candidate_2', label: 'Direction 2' }],
    studio_job_id: 'studio_job_create',
  }]);
  assert.equal(result.data?.retained_variations[0]?.source_asset_id, 'candidate_2');
});

test('rejects a partial or rebound atomic Create response', async () => {
  const gateway = createStudioGateway(fakeClient({
    commitCreativeDirections: async () => ok({
      project: {
        ...project('candidate_other'),
        selected_candidate_asset_id: 'candidate_other',
      },
      retained_variations: [],
    }, 200),
  }));

  const result = await gateway.completeCreativeDirectionReview({
    projectId: 'project_1', selectedCandidateId: 'candidate_3',
    retained: [{ candidateId: 'candidate_2', label: 'Direction 2' }],
    createdBy: 'designer_1',
  });

  assert.equal(result.error?.code, 'INVALID_CREATIVE_DIRECTION_COMMIT');
});

test('saves an exact catalog preview as a named sibling without advancing its source', async () => {
  let saveCalls = 0;
  const source = project('asset_2', 2);
  const sibling = {
    ...project('variation_2', 1), id: 'variation_2', root_id: 'variation_2',
    active_asset_id: 'variation_2', active_revision: {
      ...asset('variation_2', 1), root_id: 'variation_2', asset_id: 'variation_2',
      design_id: 'design_variation', design_version: 1,
    },
    design_id: 'design_variation', spec: {},
  } as ProjectDetail;
  const gateway = createStudioGateway(fakeClient({
    previewCatalogSelection: async () => ok(catalogPreview(), 201),
    saveCatalogPreviewAsVariation: async (_candidate, request) => {
      saveCalls += 1;
      assert.deepEqual(request, { created_by: 'designer_1', label: 'Rose halo' });
      return ok({
        status: 'saved_as_variation' as const, family_id: 'family_1', variation_index: 2,
        source_project_id: 'project_1', source_asset_id: 'asset_1',
        design_id: 'design_variation', design_version: 1, project: sibling,
      }, 201);
    },
    getProject: async () => ok(source),
  }));
  const preview = await gateway.previewCatalogRefine({
    projectId: 'project_1', sourceAssetId: 'asset_1', sourceDesignVersion: 1,
    createdBy: 'designer_1', componentPath: 'metal.color', optionId: 'rose',
  });
  assert.equal(preview.error, null);

  const blank = await gateway.saveCatalogPreviewAsVariation({
    candidateId: 'candidate_1', createdBy: 'designer_1', label: '   ',
  });
  assert.equal(blank.error?.code, 'VARIATION_LABEL_REQUIRED');
  assert.equal(saveCalls, 0);

  const saved = await gateway.saveCatalogPreviewAsVariation({
    candidateId: 'candidate_1', createdBy: 'designer_1', label: '  Rose halo  ',
  });
  assert.equal(saved.error, null);
  assert.equal(saved.data?.candidate.status, 'saved_as_variation');
  assert.equal(saved.data?.project.root_id, 'variation_2');
  assert.equal(saved.data?.familyId, 'family_1');
  assert.equal(source.active_asset_id, 'asset_2');
  assert.equal(saveCalls, 1);

  const repeated = await gateway.saveCatalogPreviewAsVariation({
    candidateId: 'candidate_1', createdBy: 'designer_1', label: 'Duplicate',
  });
  assert.equal(repeated.error?.code, 'CANDIDATE_NOT_FOUND');
  assert.equal(saveCalls, 1);
});

test('catalog refine preserves lineage and applies only through an explicit decision', async () => {
  let acceptCalls = 0;
  const client = fakeClient({
    previewCatalogSelection: async (assetId, request) => {
      assert.equal(assetId, 'asset_1');
      assert.equal(request.expected_design_version, 1);
      return ok(catalogPreview(), 201);
    },
    acceptCatalogPreview: async (candidate, request) => {
      acceptCalls += 1;
      assert.equal(candidate.candidate_id, 'candidate_1');
      assert.equal(request.expected_design_version, 1);
      return ok({
        status: 'accepted',
        asset_id: 'asset_2',
        design_version: 2,
        image_run_id: 'run_1',
        spec_change: [],
        project: project('asset_2', 2),
      }, 201);
    },
  });
  const gateway = createStudioGateway(client, { now: () => new Date('2026-07-12T00:00:00Z') });
  const preview = await gateway.previewCatalogRefine({
    projectId: 'project_1',
    sourceAssetId: 'asset_1',
    sourceDesignVersion: 1,
    createdBy: 'designer_1',
    componentPath: 'metal.color',
    optionId: 'rose',
  });
  assert.equal(preview.error, null);
  if (preview.error !== null) return;
  assert.deepEqual(preview.data.lineage, {
    projectId: 'project_1', sourceAssetId: 'asset_1', sourceDesignVersion: 1,
  });
  assert.equal(preview.data.candidate.status, 'pending_review');
  assert.equal(preview.data.candidate.temporary, true);

  const applied = await gateway.applyCatalogRefine({
    candidateId: preview.data.candidate.id, createdBy: 'designer_1',
  });
  assert.equal(applied.error, null);
  if (applied.error !== null) return;
  assert.equal(applied.data.candidate.status, 'applied');
  assert.equal(applied.data.candidate.canonicalRevisionId, 'asset_2');
  assert.equal(acceptCalls, 1);
  const repeated = await gateway.applyCatalogRefine({
    candidateId: preview.data.candidate.id, createdBy: 'designer_1',
  });
  assert.equal(repeated.error?.code, 'CANDIDATE_NOT_REVIEWABLE');
});

test('catalog refine rejects a component or option rebound before review', async (context) => {
  const cases: readonly { name: string; response: CatalogPreviewResult }[] = [
    {
      name: 'component path',
      response: { ...catalogPreview(), component_path: 'stone.cut' },
    },
    {
      name: 'option id',
      response: { ...catalogPreview(), option_id: 'yellow' },
    },
  ];

  for (const testCase of cases) {
    await context.test(testCase.name, async () => {
      const gateway = createStudioGateway(fakeClient({
        previewCatalogSelection: async () => ok(testCase.response, 201),
      }));

      const preview = await gateway.previewCatalogRefine({
        projectId: 'project_1',
        sourceAssetId: 'asset_1',
        sourceDesignVersion: 1,
        createdBy: 'designer_1',
        componentPath: 'metal.color',
        optionId: 'rose',
      });

      assert.equal(preview.data, null);
      assert.equal(preview.error?.code, 'INVALID_PREVIEW_LINEAGE');
    });
  }
});

test('instant catalog refine creates a temporary candidate without a Studio job', async () => {
  let jobCreates = 0;
  const requests: any[] = [];
  const gateway = createStudioGateway(fakeClient({
    createStudioJob: async () => {
      jobCreates += 1;
      return ok(catalogStudioJob('queued'), 201);
    },
    transitionStudioJob: async () => ok(catalogStudioJob('running')),
    previewCatalogSelection: async (_assetId, request) => {
      requests.push(request);
      return ok({
        ...catalogPreview(),
        routing: {
          attempt_count: 0, used_retry: false, used_fallback: false,
          cache_hit: false, run_id: 'run_1',
        },
        candidate: { ...catalogPreview().candidate, studio_job_id: null },
      }, 201);
    },
  }));

  const preview = await gateway.previewCatalogRefine({
    projectId: 'project_1', sourceAssetId: 'asset_1', sourceDesignVersion: 1,
    createdBy: 'designer_1', componentPath: 'metal.color', optionId: 'rose',
    executionMode: 'instant',
  });

  assert.equal(preview.error, null);
  assert.equal(preview.data?.executionMode, 'instant');
  assert.equal(preview.data?.estimatedCredits, 0);
  assert.equal(jobCreates, 0);
  assert.deepEqual(requests, [{
    component_path: 'metal.color', option_id: 'rose', expected_design_version: 1,
    created_by: 'designer_1', execution_mode: 'instant',
  }]);
});

test('only deployment skew may fall back from instant to a tracked provider preview', async () => {
  const requests: any[] = [];
  let jobCreates = 0;
  const gateway = createStudioGateway(fakeClient({
    createStudioJob: async () => {
      jobCreates += 1;
      return ok(catalogStudioJob('queued'), 201);
    },
    transitionStudioJob: async (_jobId, request) => ok(catalogStudioJob(request.status)),
    previewCatalogSelection: async (_assetId, request) => {
      requests.push(request);
      if (request.execution_mode === 'instant') return {
        data: null,
        error: {
          code: 'instant_gold_color_unsupported',
          message: 'Quick preview support is not deployed for this option.',
          category: 'capability' as const,
          status: 422,
          retryable: false,
        },
        status: 422,
      };
      return ok({
        ...catalogPreview(),
        option_id: 'future_gold',
        candidate: {
          ...catalogPreview().candidate,
          studio_job_id: 'studio_job_catalog',
        },
      }, 201);
    },
  }));

  const preview = await gateway.previewCatalogRefine({
    projectId: 'project_1', sourceAssetId: 'asset_1', sourceDesignVersion: 1,
    createdBy: 'designer_1', componentPath: 'metal.color', optionId: 'future_gold',
    executionMode: 'instant',
  });

  assert.equal(preview.error, null);
  assert.equal(preview.data?.executionMode, 'provider');
  assert.equal(preview.data?.estimatedCredits, 20);
  assert.equal(jobCreates, 1);
  assert.equal(requests.length, 2);
  assert.equal(requests[0].execution_mode, 'instant');
  assert.equal(requests[0].studio_job_id, undefined);
  assert.equal(requests[1].execution_mode, 'provider');
  assert.equal(requests[1].studio_job_id, 'studio_job_catalog');
});

test('instant safety, lineage, authorization, and integrity errors never start provider work', async () => {
  const cases: { code: string; category: ApiErrorCategory; status: number }[] = [
    { code: 'instant_preview_path_unsupported', category: 'capability', status: 422 },
    { code: 'instant_preview_target_unavailable', category: 'capability', status: 422 },
    { code: 'instant_gold_color_raster_too_large', category: 'capability', status: 422 },
    { code: 'instant_gold_color_orientation_unsupported', category: 'capability', status: 422 },
    { code: 'instant_gold_color_mask_mismatch', category: 'capability', status: 422 },
    { code: 'instant_gold_color_verification_failed', category: 'capability', status: 422 },
    { code: 'instant_gold_color_qa_failed', category: 'quality', status: 422 },
    { code: 'stale_design_version', category: 'stale_version', status: 409 },
    { code: 'candidate_payload_tampered', category: 'conflict', status: 409 },
    { code: 'AUTHENTICATION_REQUIRED', category: 'authentication', status: 401 },
    { code: 'FORBIDDEN', category: 'authorization', status: 403 },
    { code: 'INVALID_RESPONSE', category: 'decode', status: 200 },
    { code: 'NETWORK_ERROR', category: 'network', status: 0 },
  ];

  for (const item of cases) {
    let previewCalls = 0;
    let jobCreates = 0;
    const gateway = createStudioGateway(fakeClient({
      createStudioJob: async () => {
        jobCreates += 1;
        return ok(catalogStudioJob('queued'), 201);
      },
      previewCatalogSelection: async () => {
        previewCalls += 1;
        return {
          data: null,
          error: {
            code: item.code, message: item.code, category: item.category,
            status: item.status, retryable: false,
          },
          status: item.status,
        };
      },
    }));

    const result = await gateway.previewCatalogRefine({
      projectId: 'project_1', sourceAssetId: 'asset_1', sourceDesignVersion: 1,
      createdBy: 'designer_1', componentPath: 'metal.color', optionId: 'rose',
      executionMode: 'instant',
    });
    assert.equal(result.error?.code, item.code);
    assert.equal(previewCalls, 1, item.code);
    assert.equal(jobCreates, 0, item.code);
  }
});

test('resumes the latest exact-lineage catalog preview and hydrates Apply', async () => {
  let acceptedCandidate = '';
  const gateway = createStudioGateway(fakeClient({
    listCatalogPreviews: async () => ok({ candidates: [{
      candidate: {
        run_id: 'run_resume', candidate_id: 'candidate_resume',
        preview_url: 'https://example.test/resume.png',
        accept_url: 'https://example.test/resume/accept',
        discard_url: 'https://example.test/resume', verdict: 'pass', expires_in_seconds: 3600,
        save_as_variation_url: 'https://example.test/resume/save-as-variation',
        studio_job_id: 'studio_job_catalog',
      },
      source_asset_id: 'asset_1', component_path: 'metal.color', option_id: 'rose',
      requested_change: 'Apply rose gold', next_spec: {}, spec_change: [],
      qa: {
        verdict: 'pass', accepted: true, review_required: false, score: 1,
        summary: 'Pass', failed_checks: [], warnings: [],
        checks: [{ key: 'identity', label: 'Identity', verdict: 'pass', severity: 'hard', message: 'Preserved' }],
      },
      routing: { attempt_count: 1, used_retry: false, used_fallback: false, cache_hit: false, run_id: 'run_resume' },
      expires_at: '2099-01-01T00:00:00Z',
    }] }),
    listStudioJobs: async () => ok({ jobs: [catalogStudioJob('reviewing')] }),
    acceptCatalogPreview: async (candidate) => {
      acceptedCandidate = candidate.candidate_id;
      return ok({
        status: 'accepted' as const, asset_id: 'asset_2', design_version: 2,
        image_run_id: 'run_resume', spec_change: [], project: project('asset_2', 2),
      }, 201);
    },
  }));

  const resumed = await gateway.resumeRefine({
    projectId: 'project_1', sourceAssetId: 'asset_1', sourceDesignVersion: 1,
  }, 'designer_1');
  assert.equal(resumed.error, null);
  if (resumed.error !== null || resumed.data === null) return;
  assert.equal(resumed.data.kind, 'catalog');
  assert.equal(resumed.data.candidate.id, 'candidate_resume');
  assert.deepEqual(resumed.data.intent, {
    kind: 'component', componentPath: 'metal.color', optionId: 'rose',
    requestedChange: 'Apply rose gold',
  });

  const applied = await gateway.applyCatalogRefine({
    candidateId: 'candidate_resume', createdBy: 'designer_1',
  });
  assert.equal(applied.error, null);
  assert.equal(acceptedCandidate, 'candidate_resume');
  assert.equal(applied.data?.project?.active_asset_id, 'asset_2');
});

test('discard is terminal and never calls the accept endpoint', async () => {
  let acceptCalls = 0;
  const gateway = createStudioGateway(fakeClient({
    previewCatalogSelection: async () => ok(catalogPreview(), 201),
    discardCatalogPreview: async () => ok({ status: 'discarded' as const }, 204),
    acceptCatalogPreview: async () => {
      acceptCalls += 1;
      throw new Error('must not accept');
    },
  }));
  const preview = await gateway.previewCatalogRefine({
    projectId: 'project_1', sourceAssetId: 'asset_1', sourceDesignVersion: 1,
    createdBy: 'designer_1', componentPath: 'metal.color', optionId: 'rose',
  });
  if (preview.error !== null) throw new Error(preview.error.message);
  const discarded = await gateway.discardCatalogRefine({
    candidateId: preview.data.candidate.id, createdBy: 'designer_1',
  });
  assert.equal(discarded.error, null);
  assert.equal(discarded.data?.candidate.status, 'discarded');
  const apply = await gateway.applyCatalogRefine({
    candidateId: preview.data.candidate.id, createdBy: 'designer_1',
  });
  assert.equal(apply.error?.code, 'CANDIDATE_NOT_REVIEWABLE');
  assert.equal(acceptCalls, 0);
});

test('variation source mismatch is rejected instead of silently branching latest', async () => {
  let receivedOperationId = '';
  const gateway = createStudioGateway(fakeClient({
    saveAsVariation: async (_projectId, request) => {
      receivedOperationId = request.operation_id;
      return ok({
        status: 'variation_created',
        family_id: 'family_1',
        variation_index: 2,
        source_project_id: 'project_1',
        source_asset_id: 'different_asset',
        project: project(),
      }, 201);
    },
  }));
  const result = await gateway.saveCurrentAsVariation({
    projectId: 'project_1', sourceAssetId: 'asset_1', sourceDesignVersion: 1,
    createdBy: 'designer_1', label: 'Variation B', operationId: 'vary:request-0001',
  });
  assert.equal(receivedOperationId, 'vary:request-0001');
  assert.equal(result.error?.code, 'INVALID_VARIATION_LINEAGE');
});

test('branches a saved revision with one mutation and independent source and active guards', async () => {
  const calls: unknown[][] = [];
  let projectReads = 0;
  const gateway = createStudioGateway(fakeClient({
    saveRevisionAsVariation: async (...args) => {
      calls.push(args);
      return ok(historicalVariationResult(), 201);
    },
    getProject: async () => {
      projectReads += 1;
      return ok(project());
    },
  }));

  const result = await gateway.saveRevisionAsVariation(historicalVariationRequest);

  assert.equal(result.error, null);
  assert.equal(projectReads, 0);
  assert.deepEqual(calls, [[
    'project_1',
    'asset_1',
    {
      created_by: 'designer_1', expected_active_asset_id: 'asset_2',
      expected_active_design_version: 2, expected_source_design_version: 1,
      expected_source_sha256: HISTORICAL_SOURCE_SHA256,
      label: 'Earlier geometry study', operation_id: 'vary:history-0001',
    },
  ]]);
  assert.equal(result.data?.project.root_id, 'variation_2');
  assert.equal(result.data?.child_sha256, HISTORICAL_SOURCE_SHA256);
});

test('fails closed when any returned saved-revision lineage proof is rebound', async () => {
  const cases: Array<{
    name: string;
    mutate: (value: SaveRevisionAsVariationResult) => void;
  }> = [
    { name: 'source project', mutate: (value) => { value.source_project_id = 'other_project'; } },
    { name: 'source asset', mutate: (value) => { value.source_asset_id = 'other_asset'; } },
    { name: 'source version', mutate: (value) => { value.source_design_version = 9; } },
    { name: 'source hash', mutate: (value) => { value.source_sha256 = 'b'.repeat(64); } },
    { name: 'active asset guard', mutate: (value) => { value.guarded_active_asset_id = 'asset_1'; } },
    { name: 'active version guard', mutate: (value) => { value.guarded_active_design_version = 1; } },
    { name: 'child root', mutate: (value) => { value.child_project_root_id = 'other_child'; } },
    { name: 'child asset', mutate: (value) => { value.child_asset_id = 'other_asset'; } },
    { name: 'family', mutate: (value) => { value.child_family_id = 'other_family'; } },
    { name: 'variation index', mutate: (value) => { value.child_variation_index = 3; } },
    {
      name: 'branch source',
      mutate: (value) => { value.child_branched_from_asset_id = 'asset_2'; },
    },
    { name: 'child design version', mutate: (value) => { value.child_design_version = 2; } },
    { name: 'child byte hash', mutate: (value) => { value.child_sha256 = 'c'.repeat(64); } },
    {
      name: 'active revision hash',
      mutate: (value) => { value.project.active_revision!.sha256 = 'd'.repeat(64); },
    },
    {
      name: 'extra child revision',
      mutate: (value) => { value.project.revisions.push(value.project.revisions[0]!); },
    },
    {
      name: 'nested member branch',
      mutate: (value) => { value.variation.branched_from_project_root_id = 'other_project'; },
    },
    {
      name: 'component map proof',
      mutate: (value) => {
        value.component_map_status = 'mapped';
        value.component_map_sha256 = 'e'.repeat(64);
      },
    },
  ];

  for (const scenario of cases) {
    const response = JSON.parse(JSON.stringify(
      historicalVariationResult(),
    )) as SaveRevisionAsVariationResult;
    scenario.mutate(response);
    const gateway = createStudioGateway(fakeClient({
      saveRevisionAsVariation: async () => ok(response, 201),
    }));
    const result = await gateway.saveRevisionAsVariation(historicalVariationRequest);
    assert.equal(
      result.error?.code,
      'INVALID_VARIATION_LINEAGE',
      `${scenario.name} must fail closed`,
    );
  }
});

test('rejects an unverifiable revision hash locally and preserves stale conflicts', async () => {
  let calls = 0;
  const gateway = createStudioGateway(fakeClient({
    saveRevisionAsVariation: async () => {
      calls += 1;
      return {
        data: null,
        error: {
          code: 'stale_active_asset', message: 'The source Variation changed.',
          category: 'stale_version', status: 409, retryable: false,
        },
        status: 409,
      };
    },
  }));

  const invalid = await gateway.saveRevisionAsVariation({
    ...historicalVariationRequest, sourceSha256: 'not-a-hash',
  });
  assert.equal(invalid.error?.code, 'INVALID_VARIATION_SOURCE_HASH');
  assert.equal(calls, 0);

  const stale = await gateway.saveRevisionAsVariation(historicalVariationRequest);
  assert.equal(stale.error?.code, 'stale_active_asset');
  assert.equal(stale.error?.category, 'conflict');
  assert.equal(calls, 1);
});

test('accepts an exact pre-spec saved revision without inventing a design version', async () => {
  const response = historicalVariationResult();
  response.source_design_version = null;
  response.child_design_id = null;
  response.child_design_version = null;
  response.project.design_id = null;
  response.project.active_design_version = null;
  response.project.active_revision!.design_id = null;
  response.project.active_revision!.design_version = null;
  response.project.revisions[0]!.asset.design_id = null;
  response.project.revisions[0]!.asset.design_version = null;
  response.project.revisions[0]!.spec_version = null;
  response.variation.design_id = null;
  response.variation.design_version = null;
  const gateway = createStudioGateway(fakeClient({
    saveRevisionAsVariation: async () => ok(response, 201),
  }));

  const result = await gateway.saveRevisionAsVariation({
    ...historicalVariationRequest, sourceDesignVersion: null,
  });

  assert.equal(result.error, null);
  assert.equal(result.data?.child_design_version, null);
});

test('keeps an explicit Create candidate as a sibling and verifies its exact source', async () => {
  let receivedCandidate = '';
  let receivedRequest: unknown = null;
  const gateway = createStudioGateway(fakeClient({
    saveCreativeCandidateAsVariation: async (_projectId, candidateId, request) => {
      receivedCandidate = candidateId;
      receivedRequest = request;
      return ok({
        status: 'variation_created',
        family_id: 'family_1', variation_index: 2,
        source_project_id: 'project_1', source_asset_id: candidateId,
        project: project('variation_2', 1),
      }, 201);
    },
  }));

  const result = await gateway.saveCreativeDirectionAsVariation({
    projectId: 'project_1', candidateId: 'candidate_2', activeAssetId: 'candidate_1',
    activeDesignVersion: 3, createdBy: 'designer_1', label: 'Direction 2',
    operationId: 'create-direction:direction-2',
  });

  assert.equal(result.error, null);
  assert.equal(receivedCandidate, 'candidate_2');
  assert.deepEqual(receivedRequest, {
    created_by: 'designer_1', expected_active_asset_id: 'candidate_1',
    expected_design_version: 3, label: 'Direction 2',
    operation_id: 'create-direction:direction-2',
  });
  assert.equal(result.data?.source_asset_id, 'candidate_2');
});

test('rejects a Create variation response rebound to a different candidate', async () => {
  const gateway = createStudioGateway(fakeClient({
    saveCreativeCandidateAsVariation: async () => ok({
      status: 'variation_created',
      family_id: 'family_1', variation_index: 2,
      source_project_id: 'project_1', source_asset_id: 'candidate_other',
      project: project('variation_2', 1),
    }, 201),
  }));

  const result = await gateway.saveCreativeDirectionAsVariation({
    projectId: 'project_1', candidateId: 'candidate_2', activeAssetId: 'candidate_1',
    activeDesignVersion: null, createdBy: 'designer_1', label: 'Direction 2',
    operationId: 'create-direction:direction-2',
  });
  assert.equal(result.error?.code, 'INVALID_VARIATION_LINEAGE');
});

test('Factory remains disabled until server-entitled and backend-eligible', async () => {
  let projectReads = 0;
  const disabled = createStudioGateway(fakeClient({
    getProject: async () => {
      projectReads += 1;
      return ok(project());
    },
  }));
  const eligibility = await disabled.getFactoryEligibility('project_1');
  assert.equal(eligibility.data?.eligible, false);
  assert.equal(projectReads, 0);

  const reviewable = createStudioGateway(fakeClient({
    getStudioCapabilities: async () => ok({
      factory_review: { enabled: true, scope: 'principal' as const },
      workspace_entitlements_available: false as const,
    }),
    getProject: async () => ok(project()),
  }));
  const reviewableResult = await reviewable.getFactoryEligibility('project_1');
  assert.equal(reviewableResult.data?.reviewEligible, true);
  assert.equal(reviewableResult.data?.packReady, false);
  assert.equal(reviewableResult.data?.activeAssetId, 'asset_1');
  assert.equal(reviewableResult.data?.pinnedAssetId, null);

  const eligibleProject = project();
  eligibleProject.state = 'factory_ready';
  eligibleProject.factory_ready = true;
  eligibleProject.pinned_revision = { ...asset('asset_1', 1), pinned: true };
  const enabled = createStudioGateway(fakeClient({
    getStudioCapabilities: async () => ok({
      factory_review: { enabled: true, scope: 'principal' as const },
      workspace_entitlements_available: false as const,
    }),
    getProject: async () => ok(eligibleProject),
  }));
  const enabledResult = await enabled.getFactoryEligibility('project_1');
  assert.equal(enabledResult.data?.eligible, true);
  assert.equal(enabledResult.data?.reviewEligible, true);
  assert.equal(enabledResult.data?.packReady, true);
  assert.equal(enabledResult.data?.pinnedAssetId, 'asset_1');
});

test('Confirm keeps the opaque token private and separates duplicate project reviews', async () => {
  let promoteRequest: any = null;
  const promoted = project('asset_confirmed');
  const gateway = createStudioGateway(fakeClient({
    confirmCreativeCandidateDesign: async () => ({
      data: {
        confirmation_token: 'confirmation-token-1234567890123456',
        expires_at: '2099-01-01T00:00:00Z',
        candidate_id: 'candidate_1', candidate_sha256: 'a'.repeat(64),
        spec_visual_hash: 'b'.repeat(16),
        fact_groups: [{ key: 'ring_fit', label: 'Sizing and proportions', facts: [
          {
            key: 'ring_size', label: 'Ring size', value: '6.5',
            path: 'ring_size.value', raw_value: 6.5, authority: 'estimated',
          },
        ] }],
        unresolved_source_questions: [],
        audit_eligibility: { eligible: true, state: 'complete', reason: 'Ready.' },
      }, error: null, status: 200,
    }),
    promoteCreativeCandidate: async (_projectId, _candidateId, request) => {
      promoteRequest = request;
      return { data: promoted, error: null, status: 201 };
    },
  }));
  const loaded = await gateway.loadDesignConfirmation({
    projectId: 'project_1', sourceAssetId: 'candidate_1', createdBy: 'designer_1',
  });
  assert.equal(loaded.error, null);
  if (loaded.error !== null) return;
  assert.equal('confirmation_token' in loaded.data, false);
  const duplicate = await gateway.loadDesignConfirmation({
    projectId: 'project_2', sourceAssetId: 'candidate_1', createdBy: 'designer_1',
  });
  assert.equal(duplicate.error, null);
  if (duplicate.error !== null) return;
  assert.notEqual(loaded.data.reviewId, duplicate.data.reviewId);
  const audit = await gateway.auditDesignConfirmation({
    ...loaded.data, designerAcknowledged: true,
  });
  assert.equal(audit.error, null);
  if (audit.error !== null) return;
  const saved = await gateway.saveDesignConfirmation(audit.data);
  assert.equal(saved.error, null);
  assert.equal(promoteRequest.confirmation_token, 'confirmation-token-1234567890123456');
  assert.equal(Object.keys(promoteRequest).sort().join(','), 'confirmation_token,created_by');
});

test('Starting facts send only typed changed paths while retaining the opaque confirmation token', async () => {
  let promoteRequest: any = null;
  const gateway = createStudioGateway(fakeClient({
    confirmCreativeCandidateDesign: async () => ({
      data: {
        confirmation_token: 'confirmation-token-1234567890123456',
        expires_at: '2099-01-01T00:00:00Z',
        candidate_id: 'candidate_1', candidate_sha256: 'a'.repeat(64),
        spec_visual_hash: 'b'.repeat(16),
        fact_groups: [
          { key: 'design', label: 'Design', facts: [{
            key: 'template', label: 'Design type', value: 'solitaire',
            path: null, raw_value: 'solitaire', authority: 'estimated',
          }] },
          { key: 'metal', label: 'Metal', facts: [{
            key: 'material', label: 'Metal', value: 'gold',
            path: 'metal.material', raw_value: 'gold', authority: 'suggested',
          }] },
          { key: 'ring_fit', label: 'Ring and fit', facts: [{
            key: 'ring_size', label: 'Ring size', value: '6.5',
            path: 'ring_size.value', raw_value: 6.5, authority: 'estimated',
          }] },
        ],
        unresolved_source_questions: [],
        audit_eligibility: { eligible: true, state: 'complete', reason: 'Ready.' },
      }, error: null, status: 200,
    }),
    promoteCreativeCandidate: async (_projectId, _candidateId, request) => {
      promoteRequest = request;
      return { data: project('asset_corrected'), error: null, status: 201 };
    },
  }));
  const loaded = await gateway.loadDesignConfirmation({
    projectId: 'project_1', sourceAssetId: 'candidate_1', createdBy: 'designer_1',
  });
  assert.equal(loaded.error, null);
  if (loaded.error !== null) return;
  assert.equal('confirmation_token' in loaded.data, false);
  const changed = {
    ...loaded.data,
    designerAcknowledged: true,
    factGroups: loaded.data.factGroups.map((group) => ({
      ...group,
      facts: group.facts.map((fact) => fact.path === 'metal.material'
        ? { ...fact, value: 'platinum', rawValue: 'platinum', authority: 'designer_supplied' as const }
        : fact.path === 'ring_size.value'
          ? { ...fact, value: '7.25', rawValue: 7.25, authority: 'designer_supplied' as const }
          : fact),
    })),
  };
  const audit = await gateway.auditDesignConfirmation(changed);
  assert.equal(audit.error, null);
  if (audit.error !== null) return;
  assert.equal(audit.data.status, 'pass');
  const saved = await gateway.saveDesignConfirmation(audit.data);
  assert.equal(saved.error, null);
  assert.deepEqual(promoteRequest, {
    created_by: 'designer_1',
    confirmation_token: 'confirmation-token-1234567890123456',
    corrections: [
      { path: 'metal.material', value: 'platinum' },
      { path: 'ring_size.value', value: 7.25 },
    ],
  });
});

test('Starting facts preserve Factory source questions without blocking Studio', async () => {
  let promoted = false;
  const gateway = createStudioGateway(fakeClient({
    confirmCreativeCandidateDesign: async () => ({
      data: {
        confirmation_token: 'confirmation-token-1234567890123456',
        expires_at: '2099-01-01T00:00:00Z',
        candidate_id: 'candidate_1', candidate_sha256: 'a'.repeat(64),
        spec_visual_hash: 'b'.repeat(16), fact_groups: [],
        unresolved_source_questions: ['Confirm the band profile.'],
        audit_eligibility: { eligible: true, state: 'ready', reason: 'Source review remains.' },
      }, error: null, status: 200,
    }),
    promoteCreativeCandidate: async () => { promoted = true; return { data: project(), error: null, status: 201 }; },
  }));
  const loaded = await gateway.loadDesignConfirmation({
    projectId: 'project_1', sourceAssetId: 'candidate_1', createdBy: 'designer_1',
  });
  assert.equal(loaded.error, null);
  if (loaded.error !== null) return;
  const audited = await gateway.auditDesignConfirmation({
    ...loaded.data, designerAcknowledged: true,
  });
  assert.equal(audited.error, null);
  if (audited.error !== null) return;
  assert.equal(audited.data.status, 'pass');
  const saved = await gateway.saveDesignConfirmation(audited.data);
  assert.equal(saved.error, null);
  assert.equal(promoted, true);
});

test('Confirm removes expired opaque drafts before later access', async () => {
  let current = new Date('2026-07-13T00:00:00Z');
  const gateway = createStudioGateway(fakeClient({
    confirmCreativeCandidateDesign: async (_projectId, candidateId) => ({
      data: {
        confirmation_token: `confirmation-token-${candidateId}-1234567890123456`,
        expires_at: '2026-07-13T00:05:00Z',
        candidate_id: candidateId, candidate_sha256: 'a'.repeat(64),
        spec_visual_hash: 'b'.repeat(16), fact_groups: [],
        unresolved_source_questions: [],
        audit_eligibility: { eligible: true, state: 'complete', reason: 'Ready.' },
      }, error: null, status: 200,
    }),
  }), { now: () => current });
  const first = await gateway.loadDesignConfirmation({
    projectId: 'project_1', sourceAssetId: 'candidate_1', createdBy: 'designer_1',
  });
  assert.equal(first.error, null);
  if (first.error !== null) return;
  current = new Date('2026-07-13T00:06:00Z');
  await gateway.loadDesignConfirmation({
    projectId: 'project_2', sourceAssetId: 'candidate_2', createdBy: 'designer_1',
  });
  const stale = await gateway.auditDesignConfirmation({
    ...first.data, designerAcknowledged: true,
  });
  assert.equal(stale.error?.code, 'CONFIRM_REVIEW_EXPIRED');
});

test('Create and Present use canonical typed seams while Views exposes only its job-bound preview flow', async () => {
  const calls: string[] = [];
  let legacyPresentationCalls = 0;
  const client = fakeClient({
    createProjectFromPrompt: async (request) => {
      calls.push(`prompt:${request.prompt}`);
      return ok(project(), 201);
    },
    createStudioBeautyRender: async (_projectId, request) => {
      calls.push(`beauty:${request.expected_asset_id}:${request.expected_design_version}:${request.presentation_only}`);
      return unavailable();
    },
    createStudioProductPhoto: async (_projectId, request) => {
      calls.push(`product:${request.expected_asset_id}:${request.expected_design_version}:${request.preset}:${request.presentation_only}`);
      return unavailable();
    },
    createMarketingPack: async (_projectId, request) => {
      calls.push(`marketing:${request.expected_asset_id}:${request.expected_design_version}:${request.presets.length}`);
      return unavailable();
    },
  });
  Object.assign(client, {
    createBeautyRender: async () => {
      legacyPresentationCalls += 1;
      return unavailable();
    },
    createProductPhoto: async () => {
      legacyPresentationCalls += 1;
      return unavailable();
    },
  });
  const gateway = createStudioGateway(client);
  assert.equal('createFromBrief' in gateway, false);
  assert.equal('selectCreativeDirection' in gateway, false);
  assert.equal('createLineArtView' in gateway, false);
  await gateway.createFromPrompt({ prompt: 'Emerald collar', owner: 'designer_1', title: 'Collar' });
  await gateway.createBeautyPresentation('project_1', {
    created_by: 'designer_1', expected_asset_id: 'asset_1', expected_design_version: 1,
  });
  await gateway.createProductPresentation('project_1', {
    created_by: 'designer_1', expected_asset_id: 'asset_1', expected_design_version: 1,
    preset: 'catalog_white',
  });
  await gateway.createMarketingPresentation('project_1', {
    created_by: 'designer_1', expected_asset_id: 'asset_1', expected_design_version: 1,
    presets: ['catalog_white', 'luxury_studio'],
  });
  assert.deepEqual(calls, [
    'prompt:Emerald collar',
    'beauty:asset_1:1:true',
    'product:asset_1:1:catalog_white:true',
    'marketing:asset_1:1:2',
  ]);
  assert.equal(legacyPresentationCalls, 0);
});

test('Create forwards prompt advisory references through the typed gateway seam', async () => {
  let observed: Parameters<NonNullable<ReturnType<typeof fakeClient>['createProjectFromPrompt']>>[0] | null = null;
  const gateway = createStudioGateway(fakeClient({
    createProjectFromPrompt: async (request) => {
      observed = request;
      return ok(project(), 201);
    },
  }));

  const result = await gateway.createFromPrompt({
    prompt: 'A minimal gold cuff',
    owner: 'designer_1',
    title: 'Gold cuff',
    variation_count: 2,
    references: [{
      role: 'brand_direction',
      image_base64: 'YnJhbmQ=',
      media_type: 'image/png',
    }],
  });

  assert.equal(result.error, null);
  assert.deepEqual(observed, {
    prompt: 'A minimal gold cuff',
    owner: 'designer_1',
    title: 'Gold cuff',
    variation_count: 2,
    references: [{
      role: 'brand_direction',
      image_base64: 'YnJhbmQ=',
      media_type: 'image/png',
    }],
    studio_job_id: 'studio_job_catalog',
  });
});

test('Create rejects output counts outside the canonical manifest before any mutation', async () => {
  let createStudioJobCalls = 0;
  let createProjectCalls = 0;
  const gateway = createStudioGateway(fakeClient({
    createStudioJob: async () => {
      createStudioJobCalls += 1;
      return unavailable();
    },
    createProjectFromPrompt: async () => {
      createProjectCalls += 1;
      return unavailable();
    },
  }));

  const result = await gateway.createFromPrompt({
    prompt: 'A minimal gold cuff',
    owner: 'designer_1',
    title: 'Gold cuff',
    // Simulate malformed runtime input that bypassed the compile-time client.
    variation_count: 5 as unknown as 1,
  });

  assert.equal(result.status, 422);
  assert.equal(result.error?.code, 'INVALID_REQUESTED_OUTPUT_COUNT');
  assert.equal(result.error?.category, 'validation');
  assert.equal(createStudioJobCalls, 0);
  assert.equal(createProjectCalls, 0);
});

test('Views stay temporary, bind to the exact revision, and save only after acceptance', async () => {
  const acceptedProject = project();
  acceptedProject.derived_assets = [{
    ...asset('view_asset', 1), capability: 'LINE_ART', parent_asset_id: 'asset_1',
  }];
  const gateway = createStudioGateway(fakeClient({
    createLineArt: async (projectId, request) => ok({
      status: 'confirmation_required' as const,
      project_id: projectId,
      image_run_id: 'run_view',
      quality_report: {
        verdict: 'pass' as const, accepted: true, review_required: false, score: 1,
        summary: 'Geometry preserved', failed_checks: [], warnings: [],
        checks: [{ key: 'geometry', label: 'Geometry', verdict: 'pass' as const, severity: 'hard' as const, message: 'Matched source' }],
      },
      routing: { attempt_count: 1, used_retry: false, used_fallback: false, cache_hit: false, run_id: 'run_view' },
      view: request.view,
      candidate: {
        run_id: 'run_view', candidate_id: 'candidate_view',
        preview_url: 'https://example.test/view.png', qa: {
          verdict: 'pass' as const, accepted: true, review_required: false, score: 1,
          summary: 'Geometry preserved', failed_checks: [], warnings: [], checks: [],
        },
        operation: 'VISUAL_ONLY_EDIT' as const, requested_change: 'Front line art', asset_capability: 'LINE_ART',
      },
      next: 'Confirm the view',
    }, 202),
    acceptStudioViewCandidate: async () => ok({
      status: 'accepted' as const, project_id: 'project_1', source_asset_id: 'asset_1',
      design_version: 1, asset_id: 'view_asset', project: acceptedProject,
    }, 201),
  }));

  const preview = await gateway.previewLineArtView({
    projectId: 'project_1', sourceAssetId: 'asset_1', sourceDesignVersion: 1,
    createdBy: 'designer_1', view: 'front',
  });
  assert.equal(preview.data?.previewUrl, 'https://example.test/view.png');
  assert.deepEqual(preview.data?.lineage, {
    projectId: 'project_1', sourceAssetId: 'asset_1', sourceDesignVersion: 1,
  });

  const accepted = await gateway.acceptLineArtView({
    candidateId: 'candidate_view', createdBy: 'designer_1',
  });
  assert.equal(accepted.data?.project?.active_asset_id, 'asset_1');
});

test('Views fail closed when fidelity checks reject a candidate', async () => {
  let accepted = false;
  const gateway = createStudioGateway(fakeClient({
    createLineArt: async () => ok({
      status: 'confirmation_required' as const, project_id: 'project_1', image_run_id: 'run_fail',
      quality_report: {
        verdict: 'fail' as const, accepted: false, review_required: true, score: 0,
        summary: 'Drift', failed_checks: ['geometry'], warnings: [], checks: [],
      },
      routing: { attempt_count: 1, used_retry: false, used_fallback: false, cache_hit: false, run_id: 'run_fail' },
      view: 'side' as const,
      candidate: {
        run_id: 'run_fail', candidate_id: 'candidate_fail', preview_url: 'https://example.test/fail.png',
        qa: { verdict: 'fail' as const, accepted: false, review_required: true, score: 0, summary: 'Drift', failed_checks: ['geometry'], warnings: [], checks: [] },
        operation: 'VISUAL_ONLY_EDIT' as const, requested_change: 'Side line art', asset_capability: 'LINE_ART',
      }, next: 'Do not accept',
    }, 202),
    acceptStudioViewCandidate: async () => { accepted = true; return ok({} as never, 201); },
  }));
  await gateway.previewLineArtView({
    projectId: 'project_1', sourceAssetId: 'asset_1', sourceDesignVersion: 1,
    createdBy: 'designer_1', view: 'side',
  });
  const result = await gateway.acceptLineArtView({ candidateId: 'candidate_fail', createdBy: 'designer_1' });
  assert.equal(result.error?.code, 'VIEW_QUALITY_REJECTED');
  assert.equal(accepted, false);
});

test('Views resume from durable review state after a fresh gateway instance', async () => {
  const acceptedProject = project();
  acceptedProject.derived_assets = [{
    ...asset('view_resumed_asset', 1), capability: 'LINE_ART', parent_asset_id: 'asset_1',
  }];
  const gateway = createStudioGateway(fakeClient({
    listStudioViewCandidates: async () => ok({ candidates: [{
      candidate_id: 'candidate_resumed_view', image_run_id: 'run_resumed_view',
      studio_job_id: 'job_resumed_view', project_id: 'project_1', source_asset_id: 'asset_1',
      design_version: 1, view: 'front' as const, status: 'reviewing' as const,
      accepted_asset_id: null, expires_at: '2026-07-14T00:00:00Z',
      preview_url: 'https://example.test/resumed-view.png',
      qa: { verdict: 'pass' as const, accepted: true, review_required: false, score: 99,
        summary: '', failed_checks: [], warnings: [], checks: [] },
    }] }),
    listStudioJobs: async () => ok({ jobs: [{
      job_id: 'job_resumed_view', owner: 'designer_1', action_id: 'views' as const,
      lane: 'fast_visual' as const, status: 'reviewing' as const, progress: 0.9,
      active_design_id: 'project_1', source_revision_id: 'asset_1',
      accepted_output_sha256: null, error_code: null,
      created_at: '2026-07-13T00:00:00Z', updated_at: '2026-07-13T00:00:01Z',
      billing: { requested_outputs: 1, credits_per_output: 15, estimated_credits: 15,
        completed_outputs: 0, charged_outputs: 0, charged_credits: 0, policy: 'accepted outputs only' },
    }] }),
    acceptStudioViewCandidate: async () => ok({
      status: 'accepted' as const, project_id: 'project_1', source_asset_id: 'asset_1',
      design_version: 1, asset_id: 'view_resumed_asset', project: acceptedProject,
    }, 201),
  }));
  const resumed = await gateway.resumeViews({
    projectId: 'project_1', sourceAssetId: 'asset_1', sourceDesignVersion: 1,
  }, 'designer_1');
  assert.equal(resumed.error, null);
  assert.equal(resumed.data?.candidateId, 'candidate_resumed_view');
  const accepted = await gateway.acceptLineArtView({
    candidateId: 'candidate_resumed_view', createdBy: 'designer_1',
  });
  assert.equal(accepted.error, null);
  assert.equal(accepted.data?.project?.active_asset_id, 'asset_1');
});
