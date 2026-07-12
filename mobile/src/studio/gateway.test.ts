/// <reference types="node" />

import assert from 'node:assert/strict';
import test from 'node:test';
import type { ApiResult, CatalogPreviewResult, ProjectDetail } from '../trusted/types';
import { createStudioGateway } from './gateway';

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

const project = (assetId = 'asset_1', designVersion = 1): ProjectDetail => ({
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
  active_revision: asset(assetId, designVersion),
  pinned_revision: null,
  revisions: [],
  assets: [asset(assetId, designVersion)],
  derived_assets: [],
  approval: null,
  factory_ready: false,
  factory_blockers: [],
  primary_revision_count: 1,
  has_factory_drawing: false,
  cover_asset_id: assetId,
  created_at: '2026-07-12T00:00:00Z',
  updated_at: '2026-07-12T00:00:00Z',
});

type GatewayClient = Parameters<typeof createStudioGateway>[0];

function fakeClient(overrides: Partial<GatewayClient> = {}): GatewayClient {
  const unsupported = async () => {
    throw new Error('Unexpected client method');
  };
  return {
    createProjectFromBrief: unsupported,
    createProjectFromPrompt: unsupported,
    selectCreativeCandidate: unsupported,
    saveAsVariation: unsupported,
    previewCatalogSelection: unsupported,
    acceptCatalogPreview: unsupported,
    discardCatalogPreview: unsupported,
    applyMarkup: unsupported,
    discardWarningCandidate: unsupported,
    createLineArt: unsupported,
    createBeautyRender: unsupported,
    createProductPhoto: unsupported,
    createMarketingPack: unsupported,
    acceptWarningCandidate: unsupported,
    recordImageRunFeedback: unsupported,
    getProject: unsupported,
    getFactoryPack: unsupported,
    ...overrides,
  } as GatewayClient;
}

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
    verdict: 'pass',
    expires_in_seconds: 600,
  },
});

test('persists a chosen creative direction without inventing specification authority', async () => {
  const selected = {
    ...project('candidate_2'),
    design_id: null,
    spec: null,
    active_design_version: null,
    selected_candidate_asset_id: 'candidate_2',
  };
  const gateway = createStudioGateway(fakeClient({
    selectCreativeCandidate: async (projectId, candidateId, createdBy) => {
      assert.equal(projectId, 'project_1');
      assert.equal(candidateId, 'candidate_2');
      assert.equal(createdBy, 'designer_1');
      return ok(selected);
    },
  }));

  const result = await gateway.selectCreativeDirection('project_1', 'candidate_2', 'designer_1');
  assert.equal(result.error, null);
  assert.equal(result.data?.selected_candidate_asset_id, 'candidate_2');
  assert.equal(result.data?.active_design_version, null);
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
  const gateway = createStudioGateway(fakeClient({
    saveAsVariation: async () => ok({
      status: 'variation_created',
      family_id: 'family_1',
      variation_index: 2,
      source_project_id: 'project_1',
      source_asset_id: 'different_asset',
      project: project(),
    }, 201),
  }));
  const result = await gateway.saveCurrentAsVariation({
    projectId: 'project_1', sourceAssetId: 'asset_1', sourceDesignVersion: 1,
    createdBy: 'designer_1', label: 'Variation B',
  });
  assert.equal(result.error?.code, 'INVALID_VARIATION_LINEAGE');
});

test('Factory remains disabled until explicitly enabled and backend-eligible', async () => {
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

  const eligibleProject = project();
  eligibleProject.state = 'factory_ready';
  eligibleProject.factory_ready = true;
  eligibleProject.pinned_revision = { ...asset('asset_1', 1), pinned: true };
  const enabled = createStudioGateway(fakeClient({
    getProject: async () => ok(eligibleProject),
  }), { factoryEnabled: true });
  const enabledResult = await enabled.getFactoryEligibility('project_1');
  assert.equal(enabledResult.data?.eligible, true);
  assert.equal(enabledResult.data?.pinnedAssetId, 'asset_1');
});

test('Create, Views, and Present forward typed inputs without model or provider controls', async () => {
  const calls: string[] = [];
  const gateway = createStudioGateway(fakeClient({
    createProjectFromBrief: async (request) => {
      calls.push(`brief:${request.brief}`);
      return ok(project(), 201);
    },
    createProjectFromPrompt: async (request) => {
      calls.push(`prompt:${request.prompt}`);
      return ok(project(), 201);
    },
    createLineArt: async (_projectId, request) => {
      calls.push(`view:${request.expected_asset_id}:${request.expected_design_version}:${request.view}`);
      return unavailable();
    },
    createBeautyRender: async (_projectId, request) => {
      calls.push(`beauty:${request.expected_asset_id}:${request.expected_design_version}`);
      return unavailable();
    },
    createProductPhoto: async (_projectId, request) => {
      calls.push(`product:${request.expected_asset_id}:${request.expected_design_version}:${request.preset}`);
      return unavailable();
    },
    createMarketingPack: async (_projectId, request) => {
      calls.push(`marketing:${request.expected_asset_id}:${request.expected_design_version}:${request.presets.length}`);
      return unavailable();
    },
  }));
  await gateway.createFromBrief({ brief: 'Emerald collar', owner: 'designer_1' });
  await gateway.createFromPrompt({ prompt: 'Emerald collar', owner: 'designer_1', title: 'Collar' });
  await gateway.createLineArtView({
    projectId: 'project_1', sourceAssetId: 'asset_1', sourceDesignVersion: 1,
    createdBy: 'designer_1', view: 'three_quarter',
  });
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
    'brief:Emerald collar',
    'prompt:Emerald collar',
    'view:asset_1:1:three_quarter',
    'beauty:asset_1:1',
    'product:asset_1:1:catalog_white',
    'marketing:asset_1:1:2',
  ]);
});

test('Views stay temporary, bind to the exact revision, and save only after acceptance', async () => {
  const feedback: string[] = [];
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
    acceptWarningCandidate: async () => ok(project(), 201),
    recordImageRunFeedback: async (runId, action) => {
      feedback.push(`${runId}:${action}`);
      return ok({});
    },
  }));

  const preview = await gateway.previewLineArtView({
    projectId: 'project_1', sourceAssetId: 'asset_1', sourceDesignVersion: 1,
    createdBy: 'designer_1', view: 'front',
  });
  assert.equal(preview.data?.previewUrl, 'https://example.test/view.png');
  assert.deepEqual(preview.data?.lineage, {
    projectId: 'project_1', sourceAssetId: 'asset_1', sourceDesignVersion: 1,
  });
  assert.deepEqual(feedback, []);

  const accepted = await gateway.acceptLineArtView({
    candidateId: 'candidate_view', createdBy: 'designer_1',
  });
  assert.equal(accepted.data?.project?.active_asset_id, 'asset_1');
  await new Promise((resolve) => { setTimeout(resolve, 0); });
  assert.deepEqual(feedback, ['run_view:accepted']);
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
    acceptWarningCandidate: async () => { accepted = true; return ok(project(), 201); },
  }));
  await gateway.previewLineArtView({
    projectId: 'project_1', sourceAssetId: 'asset_1', sourceDesignVersion: 1,
    createdBy: 'designer_1', view: 'side',
  });
  const result = await gateway.acceptLineArtView({ candidateId: 'candidate_fail', createdBy: 'designer_1' });
  assert.equal(result.error?.code, 'VIEW_QUALITY_REJECTED');
  assert.equal(accepted, false);
});
