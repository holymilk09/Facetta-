import assert from 'node:assert/strict';
import test from 'node:test';

import { createStudioGateway } from './gateway';
import { createStudioJobTestHarness } from './studioJobTestHarness';
import type { ProjectDetail } from '../trusted/types';

const ok = <T>(data: T, status = 200) => ({ data, error: null, status } as const);

const project = (assetId: string): ProjectDetail => {
  const source = {
    asset_id: 'asset_1', root_id: 'project_1', parent_asset_id: null,
    capability: 'SPEC_RENDER', provenance: 'studio', revision: 1,
    design_id: 'design_1', design_version: 1, region: null, instruction: null,
    drift: null, pinned: false, media_type: 'image/png', image_url: 'https://test/source.png',
    created_by: 'designer_1', created_at: null, legacy_provenance: false,
  };
  const active = {
    asset_id: assetId, root_id: 'project_1', parent_asset_id: null,
    capability: 'LOCALIZED_EDIT', provenance: 'studio', revision: 2,
    design_id: 'design_1', design_version: 1, region: null, instruction: null,
    drift: null, pinned: false, media_type: 'image/png', image_url: 'https://test/image.png',
    created_by: 'designer_1', created_at: null, legacy_provenance: false,
  };
  const assets = assetId === source.asset_id ? [source] : [source, active];
  return {
    id: 'project_1', root_id: 'project_1', title: 'Orbit', collection: null,
    tags: [], owner: 'designer_1', state: 'refining', design_id: 'design_1', spec: {},
    active_asset_id: assetId, active_design_version: 1,
    active_revision: assetId === source.asset_id ? source : active,
    pinned_revision: null,
    revisions: assets.map((entry, index) => ({
      revision: index + 1, asset: entry, spec_version: 1, spec_change: [],
      ignored_fields: [], qa: null, routing: null, created_at: null,
    })),
    assets, derived_assets: [], approval: null,
    factory_ready: false, factory_blockers: [], primary_revision_count: assets.length,
    has_factory_drawing: false, cover_asset_id: assetId, created_at: null, updated_at: null,
  };
};

const quality = {
  verdict: 'pass', accepted: true, review_required: false, score: 1,
  summary: 'Pass', failed_checks: [], warnings: [], checks: [{
    key: 'geometry', label: 'Geometry', verdict: 'pass', severity: 'hard', message: 'Preserved',
  }],
};

const durableMarkup = (
  candidateId: string, runId: string, requestedChange: string, regionDescription: string,
) => ({
  candidate_id: candidateId, image_run_id: runId, project_root_id: 'project_1',
  source_asset_id: 'asset_1', expected_active_asset_id: 'asset_1', design_version: 1,
  operation: 'LOCAL_EDIT', requested_change: requestedChange,
  region_description: regionDescription, qa: quality, status: 'reviewing' as const,
  studio_job_id: 'job_refine_1', expires_at: '2099-01-01T00:00:00Z',
  preview_url: `https://test/studio/markup-candidates/${runId}/${candidateId}/image`,
  accept_url: `/studio/markup-candidates/${runId}/${candidateId}/accept`,
  discard_url: `/studio/markup-candidates/${runId}/${candidateId}/discard`,
  save_as_variation_url: `/studio/markup-candidates/${runId}/${candidateId}/save-as-variation`,
});

const baseClient = () => ({
  ...createStudioJobTestHarness('job_refine_1').client,
  createProjectFromPrompt: async () => { throw new Error('unexpected'); },
  saveAsVariation: async () => { throw new Error('unexpected'); },
  previewCatalogSelection: async () => { throw new Error('unexpected'); },
  acceptCatalogPreview: async () => { throw new Error('unexpected'); },
  discardCatalogPreview: async () => { throw new Error('unexpected'); },
  createLineArt: async () => { throw new Error('unexpected'); },
  createStudioBeautyRender: async () => { throw new Error('unexpected'); },
  createStudioProductPhoto: async () => { throw new Error('unexpected'); },
  createMarketingPack: async () => { throw new Error('unexpected'); },
  recordImageRunFeedback: async () => { throw new Error('unexpected'); },
  getProject: async () => { throw new Error('unexpected'); },
  getFactoryPack: async () => { throw new Error('unexpected'); },
});

test('markup refinement stays temporary until explicit apply', async () => {
  let acceptCalls = 0;
  const client = {
    ...baseClient(),
    applyMarkup: async (_assetId: string, request: any) => {
      assert.equal(request.preview_only, true);
      assert.equal(request.studio_job_id, 'job_refine_1');
      return ok({
        revision: null, spec_version: 1, spec_change: [], ignored_fields: [],
        qa: quality, routing: { attempt_count: 1, used_retry: false, used_fallback: false, cache_hit: false, run_id: 'run_1' },
        image_run_id: 'run_1', warning_candidate: {
          run_id: 'run_1', candidate_id: 'candidate_1', preview_url: 'https://test/preview.png',
          qa: quality, operation: 'LOCAL_EDIT', requested_change: 'make the halo lighter', asset_capability: 'LOCALIZED_EDIT',
        },
      }, 201);
    },
    listStudioMarkupCandidates: async () => ok({
      candidates: [durableMarkup('candidate_1', 'run_1', 'make the halo lighter', 'halo')],
    }),
    acceptStudioMarkupCandidate: async () => {
      acceptCalls += 1;
      return ok({
        status: 'applied' as const, candidate_id: 'candidate_1',
        asset_id: 'asset_2', project: project('asset_2'),
      }, 201);
    },
    discardStudioMarkupCandidate: async () => { throw new Error('unexpected'); },
  };
  const gateway = createStudioGateway(client as any, { now: () => new Date('2026-07-12T00:00:00Z') });
  const preview = await gateway.previewMarkupRefine({
    projectId: 'project_1', sourceAssetId: 'asset_1', sourceDesignVersion: 1,
    createdBy: 'designer_1', annotation: {
      region_description: 'halo', change_instruction: 'make the halo lighter',
      impact: 'visual_only', target_section: null, target_ref: null, index: null,
      target_component_id: null,
      target_element_id: null, form_view: 'three_quarter', mask_base64: null,
    },
  });
  assert.equal(preview.error, null);
  assert.equal(preview.data?.candidate.temporary, true);
  assert.equal(acceptCalls, 0);

  const applied = await gateway.applyMarkupRefine({ candidateId: 'candidate_1', createdBy: 'designer_1' });
  assert.equal(applied.error, null);
  assert.equal(applied.data?.project?.active_asset_id, 'asset_2');
  assert.equal(acceptCalls, 1);
});

test('discard makes a markup candidate terminal without changing the project', async () => {
  let discarded = 0;
  const client = {
    ...baseClient(),
    applyMarkup: async () => ok({
      revision: null, spec_version: 1, spec_change: [], ignored_fields: [], qa: quality,
      routing: { attempt_count: 1, used_retry: false, used_fallback: false, cache_hit: false, run_id: 'run_2' },
      image_run_id: 'run_2', warning_candidate: {
        run_id: 'run_2', candidate_id: 'candidate_2', preview_url: 'https://test/preview.png',
        qa: quality, operation: 'LOCAL_EDIT', requested_change: 'warmer background', asset_capability: 'LOCALIZED_EDIT',
      },
    }, 201),
    listStudioMarkupCandidates: async () => ok({
      candidates: [durableMarkup('candidate_2', 'run_2', 'warmer background', 'background')],
    }),
    acceptStudioMarkupCandidate: async () => { throw new Error('unexpected'); },
    discardStudioMarkupCandidate: async () => {
      discarded += 1;
      return ok({ status: 'discarded' as const, candidate_id: 'candidate_2' });
    },
  };
  const gateway = createStudioGateway(client as any);
  await gateway.previewMarkupRefine({
    projectId: 'project_1', sourceAssetId: 'asset_1', sourceDesignVersion: 1,
    createdBy: 'designer_1', annotation: {
      region_description: 'background', change_instruction: 'warmer background',
      impact: 'visual_only', target_section: null, target_ref: null, index: null,
      target_component_id: null,
      target_element_id: null, form_view: 'three_quarter', mask_base64: null,
    },
  });
  const result = await gateway.discardMarkupRefine({ candidateId: 'candidate_2', createdBy: 'designer_1' });
  assert.equal(result.data?.project, null);
  assert.equal(result.data?.candidate.status, 'discarded');
  assert.equal(discarded, 1);
  const replay = await gateway.applyMarkupRefine({ candidateId: 'candidate_2', createdBy: 'designer_1' });
  assert.equal(replay.error?.code, 'CANDIDATE_NOT_REVIEWABLE');
});

test('a fresh gateway resumes durable markup and saves it as a sibling variation', async () => {
  const source = project('asset_2');
  const variation = {
    ...project('variation_1'), id: 'variation_1', root_id: 'variation_1',
    active_asset_id: 'variation_1', cover_asset_id: 'variation_1',
  } as ProjectDetail;
  let saved = 0;
  const client = {
    ...baseClient(),
    listStudioJobs: async () => ok({ jobs: [{
      job_id: 'job_refine_1', owner: 'designer_1', action_id: 'refine',
      lane: 'trusted_structural', status: 'reviewing', progress: 0.9,
      active_design_id: 'project_1', source_revision_id: 'asset_1',
      requested_outputs: 1, completed_outputs: 0, charged_outputs: 0,
      credits_per_output: 20, estimated_credits: 20, charged_credits: 0,
      attempt_count: 1, error_code: null, created_at: '2026-07-12T00:00:00Z',
      updated_at: '2026-07-12T00:00:01Z', billing: {
        requested_outputs: 1, completed_outputs: 0, charged_outputs: 0,
        credits_per_output: 20, estimated_credits: 20, charged_credits: 0,
        internal_retries_charged: false,
      },
    }] }),
    listStudioMarkupCandidates: async () => ok({ candidates: [{
      candidate_id: 'candidate_durable', image_run_id: 'run_durable',
      project_root_id: 'project_1', source_asset_id: 'asset_1',
      expected_active_asset_id: 'asset_1', design_version: 1,
      operation: 'LOCAL_EDIT', requested_change: 'soften the halo',
      region_description: 'halo', qa: quality, status: 'reviewing',
      studio_job_id: 'job_refine_1', expires_at: '2099-01-01T00:00:00Z',
      preview_url: 'https://test/studio/markup-candidates/run_durable/candidate_durable/image',
      accept_url: '/studio/markup-candidates/run_durable/candidate_durable/accept',
      discard_url: '/studio/markup-candidates/run_durable/candidate_durable/discard',
      save_as_variation_url: '/studio/markup-candidates/run_durable/candidate_durable/save-as-variation',
    }] }),
    getProject: async (projectId: string) => {
      assert.equal(projectId, 'project_1');
      return ok(source);
    },
    saveStudioMarkupPreviewAsVariation: async (_candidate: unknown, request: any) => {
      saved += 1;
      assert.equal(request.label, 'Soft halo');
      return ok({
        status: 'saved_as_variation' as const, family_id: 'family_1',
        variation_index: 2, source_project_id: 'project_1',
        source_asset_id: 'asset_1', project: variation,
      }, 201);
    },
  };
  const gateway = createStudioGateway(client as any, {
    now: () => new Date('2026-07-12T00:00:00Z'),
  });
  const resumed = await gateway.resumeRefine({
    projectId: 'project_1', sourceAssetId: 'asset_1', sourceDesignVersion: 1,
  }, 'designer_1');
  assert.equal(resumed.error, null);
  assert.equal(resumed.data?.kind, 'markup');
  assert.equal(resumed.data?.candidate.id, 'candidate_durable');
  assert.deepEqual(resumed.data?.intent, {
    kind: 'markup', requestedChange: 'soften the halo',
    regionDescription: 'halo', impact: 'specification',
  });

  const result = await gateway.saveMarkupPreviewAsVariation({
    candidateId: 'candidate_durable', createdBy: 'designer_1', label: ' Soft halo ',
  });
  assert.equal(result.error, null);
  assert.equal(result.data?.project.root_id, 'variation_1');
  assert.equal(result.data?.candidate.status, 'saved_as_variation');
  assert.equal(saved, 1);
  assert.equal(source.active_asset_id, 'asset_2');
});
