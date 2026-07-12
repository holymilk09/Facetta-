/// <reference types="node" />

import assert from 'node:assert/strict';
import test from 'node:test';

import type { ProjectDetail, StudioJobRecord } from '../trusted/types';
import { createStudioGateway } from './gateway';

const ok = <T>(data: T, status = 200) => ({ data, error: null, status } as const);

const asset = (id: string, capability = 'CREATIVE_RENDER') => ({
  asset_id: id, root_id: 'project_1', parent_asset_id: null, capability,
  provenance: 'studio', revision: 1, design_id: 'design_1', design_version: 1,
  region: null, instruction: null, drift: null, pinned: false,
  media_type: 'image/png', image_url: `https://test/${id}.png`,
  created_by: 'designer_1', created_at: '2026-07-12T00:00:00Z',
  legacy_provenance: false,
});

const project = (creativeCount = 1): ProjectDetail => {
  const candidates = Array.from({ length: creativeCount }, (_, index) => asset(`candidate_${index + 1}`));
  return {
    id: 'project_1', root_id: 'project_1', title: 'Orbit', collection: null,
    tags: [], owner: 'designer_1', state: 'refining', design_id: 'design_1', spec: {},
    active_asset_id: candidates[0]?.asset_id ?? null, active_design_version: 1,
    active_revision: candidates[0] ?? null, pinned_revision: null,
    revisions: candidates.map((candidate, index) => ({
      revision: index + 1, asset: candidate, spec_version: 1, spec_change: [],
      ignored_fields: [], qa: null, routing: null, created_at: null,
    })),
    assets: candidates, derived_assets: [], approval: null, factory_ready: false,
    factory_blockers: [], primary_revision_count: candidates.length,
    has_factory_drawing: false, cover_asset_id: candidates[0]?.asset_id ?? null,
    created_at: null, updated_at: null,
  };
};

interface JobCall {
  jobId: string;
  request: any;
}

function tracking() {
  const creates: any[] = [];
  const transitions: JobCall[] = [];
  const cancellations: { jobId: string; owner: string }[] = [];
  let counter = 0;
  const record = (id: string, request: any, status: StudioJobRecord['status']): StudioJobRecord => ({
    job_id: id, owner: request.owner, action_id: request.action_id ?? 'create',
    lane: request.lane ?? 'fast_visual', status, progress: request.progress ?? 0,
    active_design_id: request.active_design_id ?? null,
    source_revision_id: request.source_revision_id ?? null, error_code: request.error_code ?? null,
    created_at: '2026-07-12T00:00:00Z', updated_at: '2026-07-12T00:00:01Z',
    billing: {
      requested_outputs: request.requested_outputs ?? 1,
      credits_per_output: request.credits_per_output ?? 15,
      estimated_credits: (request.requested_outputs ?? 1) * (request.credits_per_output ?? 15),
      completed_outputs: request.completed_outputs ?? 0,
      charged_outputs: request.completed_outputs ?? 0,
      charged_credits: (request.completed_outputs ?? 0) * (request.credits_per_output ?? 15),
      policy: 'Only requested completed outputs are charged.',
    },
  });
  return {
    creates,
    transitions,
    cancellations,
    client: {
      createStudioJob: async (request: any) => {
        creates.push(request);
        counter += 1;
        return ok(record(`studio_job_${counter}`, request, 'queued'), 201);
      },
      transitionStudioJob: async (jobId: string, request: any) => {
        transitions.push({ jobId, request });
        return ok(record(jobId, request, request.status));
      },
      cancelStudioJob: async (jobId: string, owner: string) => {
        cancellations.push({ jobId, owner });
        return ok(record(jobId, { owner }, 'canceled'));
      },
    },
  };
}

const quality = {
  verdict: 'pass', accepted: true, review_required: false, score: 1,
  summary: 'Pass', failed_checks: [], warnings: [], checks: [],
} as const;

test('tracked prompt and drawing creation charge only after direction acceptance', async () => {
  const jobs = tracking();
  let drawingCalls = 0;
  const gateway = createStudioGateway({
    ...jobs.client,
    createProjectFromPrompt: async () => ok(project(2), 201),
    createProjectFromDrawing: async () => { drawingCalls += 1; return ok(project(2), 201); },
    selectCreativeCandidate: async () => ok({
      ...project(2), selected_candidate_asset_id: 'candidate_2', active_asset_id: 'candidate_2',
    }),
  } as any, { trackJobs: true });

  const created = await gateway.createFromPrompt({
    prompt: 'Sapphire orbit', variation_count: 2, owner: 'designer_1', title: 'Orbit',
  });
  assert.equal(created.error, null);
  assert.deepEqual(jobs.creates[0], {
    owner: 'designer_1', action_id: 'create', lane: 'fast_visual',
    active_design_id: null, source_revision_id: null,
    requested_outputs: 2, credits_per_output: 15,
  });
  assert.deepEqual(jobs.transitions.slice(0, 2).map((call) => call.request.status), [
    'running', 'reviewing',
  ]);
  assert.equal(jobs.transitions[1]?.request.active_design_id, 'project_1');
  assert.equal(jobs.transitions.some((call) => call.request.completed_outputs !== undefined), false);

  await gateway.selectCreativeDirection('project_1', 'candidate_2', 'designer_1');
  assert.equal(jobs.transitions.at(-1)?.request.status, 'succeeded');
  assert.equal(jobs.transitions.at(-1)?.request.completed_outputs, 2);
  assert.equal(jobs.transitions.at(-1)?.request.source_revision_id, 'candidate_2');

  const drawing = await gateway.createFromDrawing({
    image_base64: 'c2tldGNo', media_type: 'image/png', instruction: 'Preserve it',
    variation_count: 2, owner: 'designer_1', title: 'Drawing',
  });
  assert.equal(drawing.error, null);
  assert.equal(drawingCalls, 1);
  assert.equal(jobs.creates[1]?.requested_outputs, 2);
  assert.equal(jobs.transitions.at(-1)?.request.status, 'reviewing');
});

test('tracked generation failures close the job without charging output', async () => {
  const jobs = tracking();
  const gateway = createStudioGateway({
    ...jobs.client,
    createProjectFromPrompt: async () => { throw new Error('generation offline'); },
  } as any, { trackJobs: true });

  const result = await gateway.createFromPrompt({
    prompt: 'Orbit', owner: 'designer_1', title: 'Orbit',
  });
  assert.equal(result.error?.code, 'UNEXPECTED_GENERATION_FAILURE');
  assert.deepEqual(jobs.transitions.map((call) => call.request.status), ['running', 'failed']);
  assert.equal(jobs.transitions[1]?.request.completed_outputs, undefined);
});

test('catalog preview keeps image-run and Studio-job identities separate through apply', async () => {
  const jobs = tracking();
  const next = project(1);
  next.active_asset_id = 'asset_2';
  next.active_revision = { ...asset('asset_2', 'LOCALIZED_EDIT'), design_version: 2 };
  next.active_design_version = 2;
  const gateway = createStudioGateway({
    ...jobs.client,
    previewCatalogSelection: async () => ok({
      status: 'preview_ready', component_path: 'metal.color', option_id: 'rose',
      isolation_target: 'metal', source_asset_id: 'candidate_1', design_version: 1,
      image_run_id: 'image_run_catalog', spec_change: [], next_spec: {}, qa: quality,
      routing: { attempt_count: 1, used_retry: false, used_fallback: false, cache_hit: false, run_id: 'image_run_catalog' },
      project: project(1), candidate: {
        run_id: 'image_run_catalog', candidate_id: 'candidate_catalog',
        preview_url: 'https://test/preview.png', accept_url: '/accept', discard_url: '/discard',
        verdict: 'pass', expires_in_seconds: 600,
      },
    }, 201),
    acceptCatalogPreview: async () => ok({
      status: 'accepted', asset_id: 'asset_2', design_version: 2,
      image_run_id: 'image_run_catalog', spec_change: [], project: next,
    }, 201),
  } as any, { trackJobs: true });

  const preview = await gateway.previewCatalogRefine({
    projectId: 'project_1', sourceAssetId: 'candidate_1', sourceDesignVersion: 1,
    createdBy: 'designer_1', componentPath: 'metal.color', optionId: 'rose',
  });
  assert.equal(preview.data?.candidate.jobId, 'image_run_catalog');
  assert.equal(jobs.transitions[0]?.jobId, 'studio_job_1');
  assert.equal(jobs.transitions[1]?.request.status, 'reviewing');

  const applied = await gateway.applyCatalogRefine({
    candidateId: 'candidate_catalog', createdBy: 'designer_1',
  });
  assert.equal(applied.error, null);
  assert.equal(jobs.transitions.at(-1)?.request.status, 'succeeded');
  assert.equal(jobs.transitions.at(-1)?.request.completed_outputs, 1);
});

test('discarded view closes reviewing Activity as canceled with zero outputs', async () => {
  const jobs = tracking();
  const gateway = createStudioGateway({
    ...jobs.client,
    createLineArt: async (_projectId: string, request: any) => ok({
      status: 'confirmation_required', project_id: 'project_1', image_run_id: 'image_run_view',
      quality_report: quality,
      routing: { attempt_count: 1, used_retry: false, used_fallback: false, cache_hit: false, run_id: 'image_run_view' },
      view: request.view, candidate: {
        run_id: 'image_run_view', candidate_id: 'candidate_view', preview_url: 'https://test/view.png',
        qa: quality, operation: 'VISUAL_ONLY_EDIT', requested_change: 'Front view', asset_capability: 'LINE_ART',
      }, next: 'Review',
    }, 202),
    recordImageRunFeedback: async () => ok({}),
  } as any, { trackJobs: true });

  await gateway.previewLineArtView({
    projectId: 'project_1', sourceAssetId: 'candidate_1', sourceDesignVersion: 1,
    createdBy: 'designer_1', view: 'front',
  });
  const discarded = await gateway.discardLineArtView({
    candidateId: 'candidate_view', createdBy: 'designer_1',
  });
  assert.equal(discarded.error, null);
  assert.deepEqual(jobs.cancellations.at(-1), {
    jobId: 'studio_job_1', owner: 'designer_1',
  });
});

test('Present distinguishes accepted, review-only, and failed generation outcomes', async () => {
  const jobs = tracking();
  const acceptedProject = project(1);
  acceptedProject.derived_assets = [asset('presentation_1', 'BEAUTY_RENDER')];
  const gateway = createStudioGateway({
    ...jobs.client,
    createBeautyRender: async () => ok({
      status: 'accepted', project: acceptedProject, source_asset_id: 'candidate_1',
      asset_id: 'presentation_1', image_run_id: 'image_run_beauty', qa: quality,
    }, 201),
    createProductPhoto: async () => ok({
      status: 'review_required', project_id: 'project_1', source_asset_id: 'candidate_1',
      image_run_id: 'image_run_product', quality_report: quality,
      routing: { attempt_count: 1, used_retry: false, used_fallback: false, cache_hit: false, run_id: 'image_run_product' },
      presentation: {
        preset: 'catalog_white', framing: 'square', source_asset_id: 'candidate_1',
        design_version: 1,
      },
      warning_candidate: {
        run_id: 'image_run_product', candidate_id: 'candidate_product',
        preview_url: 'https://test/product.png', qa: quality,
        operation: 'VISUAL_ONLY_EDIT', requested_change: 'Product photo', asset_capability: 'PRODUCT_PHOTO',
      },
    }, 202),
    createMarketingPack: async () => ok({
      status: 'failed', project_id: 'project_1', source_asset_id: 'candidate_1',
      design_version: 1, requested_count: 1, candidate_count: 0, failed_count: 1,
      maximum_provider_attempts: 3, actual_attempts: 1, candidates: [], failures: [],
    }, 200),
  } as any, { trackJobs: true });

  await gateway.createBeautyPresentation('project_1', {
    created_by: 'designer_1', expected_asset_id: 'candidate_1',
    expected_design_version: 1, presentation_only: true,
  });
  assert.equal(jobs.transitions.at(-1)?.request.status, 'succeeded');
  assert.equal(jobs.transitions.at(-1)?.request.completed_outputs, 1);

  await gateway.createProductPresentation('project_1', {
    created_by: 'designer_1', expected_asset_id: 'candidate_1', expected_design_version: 1,
    preset: 'catalog_white', framing: 'square', presentation_only: true,
  });
  assert.equal(jobs.transitions.at(-1)?.request.status, 'reviewing');

  await gateway.createMarketingPresentation('project_1', {
    created_by: 'designer_1', expected_asset_id: 'candidate_1', expected_design_version: 1,
    presets: ['catalog_white'],
  });
  assert.equal(jobs.transitions.at(-1)?.request.status, 'failed');
  assert.equal(jobs.transitions.at(-1)?.request.error_code, 'NO_PRESENTATION_OUTPUTS');
});
