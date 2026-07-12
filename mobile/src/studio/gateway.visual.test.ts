import assert from 'node:assert/strict';
import test from 'node:test';

import { createStudioGateway } from './gateway';
import type { ImageQualityReport, ProjectDetail } from '../trusted/types';

const ok = <T>(data: T, status = 200) => ({ data, error: null, status } as const);

const quality = (verdict: 'pass' | 'warn' | 'fail' = 'pass'): ImageQualityReport => ({
  verdict,
  accepted: verdict === 'pass',
  review_required: verdict === 'warn',
  score: verdict === 'fail' ? 0.4 : 0.98,
  summary: verdict === 'fail' ? 'Geometry drifted.' : 'Source geometry preserved.',
  failed_checks: verdict === 'fail' ? ['geometry'] : [],
  warnings: verdict === 'warn' ? ['Review material color.'] : [],
  checks: [{
    key: 'geometry', label: 'Geometry', verdict,
    severity: 'hard', message: verdict === 'fail' ? 'Outside drift exceeded.' : 'Preserved.',
  }],
});

const asset = (assetId: string, parentAssetId: string | null, revision: number) => ({
  asset_id: assetId,
  root_id: 'project_visual',
  parent_asset_id: parentAssetId,
  capability: 'VISUAL_ONLY_EDIT',
  provenance: 'studio_visual_preview',
  revision,
  design_id: null,
  design_version: null,
  region: null,
  instruction: 'warm the gold',
  drift: null,
  pinned: false,
  media_type: 'image/png',
  image_url: `https://facetta.test/assets/${assetId}/image`,
  created_by: 'designer_1',
  created_at: null,
  legacy_provenance: false,
});

const project = (activeAssetId: string): ProjectDetail => {
  const first = asset('asset_source', null, 1);
  const current = activeAssetId === first.asset_id ? first : asset(activeAssetId, first.asset_id, 2);
  return {
    id: 'project_visual', root_id: 'project_visual', title: 'Visual direction',
    collection: null, tags: [], owner: 'designer_1', state: 'refining',
    design_id: null, spec: null, active_asset_id: current.asset_id,
    active_design_version: null, active_revision: current, pinned_revision: null,
    revisions: [first, ...(current === first ? [] : [current])].map((entry, index) => ({
      revision: index + 1, asset: entry, spec_version: null, spec_change: [],
      ignored_fields: [], qa: null, routing: null, created_at: null,
    })),
    assets: [first, ...(current === first ? [] : [current])], derived_assets: [],
    approval: null, factory_ready: false, factory_blockers: [],
    primary_revision_count: current === first ? 1 : 2, has_factory_drawing: false,
    cover_asset_id: current.asset_id, created_at: null, updated_at: null,
  };
};

const baseClient = () => ({
  createProjectFromBrief: async () => { throw new Error('unexpected'); },
  createProjectFromDrawing: async () => { throw new Error('unexpected'); },
  createProjectFromPrompt: async () => { throw new Error('unexpected'); },
  selectCreativeCandidate: async () => { throw new Error('unexpected'); },
  saveAsVariation: async () => { throw new Error('unexpected'); },
  previewCatalogSelection: async () => { throw new Error('unexpected'); },
  acceptCatalogPreview: async () => { throw new Error('unexpected'); },
  discardCatalogPreview: async () => { throw new Error('unexpected'); },
  applyMarkup: async () => { throw new Error('unexpected'); },
  acceptWarningCandidate: async () => { throw new Error('unexpected'); },
  discardWarningCandidate: async () => { throw new Error('unexpected'); },
  createLineArt: async () => { throw new Error('unexpected'); },
  createBeautyRender: async () => { throw new Error('unexpected'); },
  createProductPhoto: async () => { throw new Error('unexpected'); },
  createMarketingPack: async () => { throw new Error('unexpected'); },
  recordImageRunFeedback: async () => { throw new Error('unexpected'); },
  getProject: async () => { throw new Error('unexpected'); },
  getFactoryPack: async () => { throw new Error('unexpected'); },
  createStudioJob: async () => { throw new Error('unexpected'); },
  transitionStudioJob: async () => { throw new Error('unexpected'); },
});

test('pre-spec visual refinement stays temporary until Apply appends an image-only revision', async () => {
  let accepted = 0;
  const client = {
    ...baseClient(),
    createVisualPreview: async (projectId: string, request: any) => {
      assert.equal(projectId, 'project_visual');
      assert.deepEqual(request, {
        created_by: 'designer_1', expected_active_asset_id: 'asset_source',
        instruction: 'warm the gold', scope: 'appearance', variant: 3,
      });
      return ok({
        project_id: projectId, source_asset_id: 'asset_source', image_run_id: 'run_visual',
        candidate: {
          candidate_id: 'candidate_visual', preview_url: 'https://facetta.test/preview.png',
          verdict: 'pass' as const, qa: quality(),
        },
      }, 201);
    },
    acceptVisualPreview: async (_runId: string, _candidateId: string, request: any) => {
      accepted += 1;
      assert.equal(request.expected_active_asset_id, 'asset_source');
      return ok({
        status: 'applied' as const, project_id: 'project_visual',
        source_asset_id: 'asset_source', new_asset_id: 'asset_applied',
        design_version: null, project: project('asset_applied'),
      }, 201);
    },
    discardVisualPreview: async () => { throw new Error('unexpected'); },
  };
  const gateway = createStudioGateway(client as any, {
    now: () => new Date('2026-07-12T00:00:00Z'),
  });
  const preview = await gateway.previewVisualRefine({
    projectId: 'project_visual', sourceAssetId: 'asset_source', createdBy: 'designer_1',
    instruction: '  warm the gold  ', scope: 'appearance', variant: 3,
  });
  assert.equal(preview.error, null);
  assert.equal(preview.data?.candidate.temporary, true);
  assert.equal(preview.data?.candidate.status, 'pending_review');
  assert.equal(accepted, 0);

  const applied = await gateway.applyVisualRefine({
    candidateId: 'candidate_visual', createdBy: 'designer_1',
  });
  assert.equal(applied.error, null);
  assert.equal(applied.data?.candidate.status, 'applied');
  assert.equal(applied.data?.candidate.canonicalRevisionId, 'asset_applied');
  assert.equal(applied.data?.project?.active_design_version, null);
  assert.equal(accepted, 1);
});

test('discard is terminal and never returns a changed project', async () => {
  const client = {
    ...baseClient(),
    createVisualPreview: async () => ok({
      project_id: 'project_visual', source_asset_id: 'asset_source', image_run_id: 'run_discard',
      candidate: {
        candidate_id: 'candidate_discard', preview_url: 'https://facetta.test/preview.png',
        verdict: 'warn' as const, qa: quality('warn'),
      },
    }, 201),
    acceptVisualPreview: async () => { throw new Error('unexpected'); },
    discardVisualPreview: async () => ok({
      status: 'discarded' as const, project_id: 'project_visual', candidate_id: 'candidate_discard',
    }),
  };
  const gateway = createStudioGateway(client as any);
  await gateway.previewVisualRefine({
    projectId: 'project_visual', sourceAssetId: 'asset_source', createdBy: 'designer_1',
    instruction: 'soften the reflection', scope: 'marked_region', maskBase64: 'mask-bytes',
  });
  const discarded = await gateway.discardVisualRefine({
    candidateId: 'candidate_discard', createdBy: 'designer_1',
  });
  assert.equal(discarded.error, null);
  assert.equal(discarded.data?.project, null);
  assert.equal(discarded.data?.candidate.status, 'discarded');
  const replay = await gateway.applyVisualRefine({
    candidateId: 'candidate_discard', createdBy: 'designer_1',
  });
  assert.equal(replay.error?.code, 'CANDIDATE_NOT_REVIEWABLE');
});

test('failed-fidelity visual candidates cannot become canonical', async () => {
  let acceptCalls = 0;
  const client = {
    ...baseClient(),
    createVisualPreview: async () => ok({
      project_id: 'project_visual', source_asset_id: 'asset_source', image_run_id: 'run_failed',
      candidate: {
        candidate_id: 'candidate_failed', preview_url: 'https://facetta.test/failed.png',
        verdict: 'fail' as const, qa: quality('fail'),
      },
    }, 202),
    acceptVisualPreview: async () => { acceptCalls += 1; throw new Error('unexpected'); },
    discardVisualPreview: async () => { throw new Error('unexpected'); },
  };
  const gateway = createStudioGateway(client as any);
  await gateway.previewVisualRefine({
    projectId: 'project_visual', sourceAssetId: 'asset_source', createdBy: 'designer_1',
    instruction: 'change only the center stone color', scope: 'appearance',
  });
  const result = await gateway.applyVisualRefine({
    candidateId: 'candidate_failed', createdBy: 'designer_1',
  });
  assert.equal(result.error?.code, 'CANDIDATE_REJECTED');
  assert.equal(acceptCalls, 0);
});

test('marked-region refinement can reference server-validated markup instead of sending a raw mask', async () => {
  let received: unknown = null;
  const client = {
    ...baseClient(),
    createVisualPreview: async (_projectId: string, request: unknown) => {
      received = request;
      return ok({
        project_id: 'project_visual', source_asset_id: 'asset_source', image_run_id: 'run_markup',
        candidate: {
          candidate_id: 'candidate_markup', preview_url: 'https://facetta.test/markup.png',
          verdict: 'pass' as const, qa: quality(),
        },
      }, 201);
    },
    acceptVisualPreview: async () => { throw new Error('unexpected'); },
    discardVisualPreview: async () => { throw new Error('unexpected'); },
  };
  const gateway = createStudioGateway(client as any);
  const result = await gateway.previewVisualRefine({
    projectId: 'project_visual', sourceAssetId: 'asset_source', createdBy: 'designer_1',
    instruction: 'cool the marked stone only', scope: 'marked_region',
    markupAssetId: 'markup_asset_1',
  });
  assert.equal(result.error, null);
  assert.deepEqual(received, {
    created_by: 'designer_1', expected_active_asset_id: 'asset_source',
    instruction: 'cool the marked stone only', scope: 'marked_region',
    markup_asset_id: 'markup_asset_1',
  });
});
