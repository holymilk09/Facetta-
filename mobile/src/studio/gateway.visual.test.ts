import assert from 'node:assert/strict';
import test from 'node:test';

import { createStudioGateway } from './gateway';
import { createStudioJobTestHarness } from './studioJobTestHarness';
import type { ImageQualityReport, ProjectDetail, StudioJobRecord } from '../trusted/types';

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

const studioJob = (status: StudioJobRecord['status']): StudioJobRecord => ({
  job_id: 'job_visual', owner: 'designer_1', action_id: 'refine',
  lane: 'trusted_structural', status, progress: status === 'queued' ? 0 : 0.05,
  active_design_id: 'project_visual', source_revision_id: 'asset_source',
  accepted_output_sha256: null, error_code: null,
  created_at: '2026-07-12T00:00:00Z',
  updated_at: '2026-07-12T00:00:00Z',
  billing: {
    requested_outputs: 1, credits_per_output: 20, estimated_credits: 20,
    completed_outputs: 0, charged_outputs: 0, charged_credits: 0,
    policy: 'Only accepted requested outputs are charged.',
  },
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
  ...createStudioJobTestHarness('job_visual').client,
  createProjectFromDrawing: async () => { throw new Error('unexpected'); },
  createProjectFromPrompt: async () => { throw new Error('unexpected'); },
  saveAsVariation: async () => { throw new Error('unexpected'); },
  previewCatalogSelection: async () => { throw new Error('unexpected'); },
  acceptCatalogPreview: async () => { throw new Error('unexpected'); },
  discardCatalogPreview: async () => { throw new Error('unexpected'); },
  applyMarkup: async () => { throw new Error('unexpected'); },
  createLineArt: async () => { throw new Error('unexpected'); },
  createStudioBeautyRender: async () => { throw new Error('unexpected'); },
  createStudioProductPhoto: async () => { throw new Error('unexpected'); },
  createMarketingPack: async () => { throw new Error('unexpected'); },
  recordImageRunFeedback: async () => { throw new Error('unexpected'); },
  getProject: async () => { throw new Error('unexpected'); },
  getFactoryPack: async () => { throw new Error('unexpected'); },
});

test('forwards family organization metadata without creating a Studio job', async () => {
  const methods: string[] = [];
  let jobStarts = 0;
  const client = {
    ...baseClient(),
    createStudioJob: async () => {
      jobStarts += 1;
      throw new Error('Favorites must not create Studio jobs');
    },
    favoriteDesignFamily: async (familyId: string, owner: string) => {
      assert.equal(familyId, 'family_ring');
      assert.equal(owner, 'designer_1');
      methods.push('favorite');
      return ok({ status: 'updated' as const }, 204);
    },
    unfavoriteDesignFamily: async (familyId: string, owner: string) => {
      assert.equal(familyId, 'family_ring');
      assert.equal(owner, 'designer_1');
      methods.push('unfavorite');
      return ok({ status: 'updated' as const }, 204);
    },
    updateDesignFamilyTags: async (familyId: string, owner: string, tags: string[]) => {
      assert.equal(familyId, 'family_ring');
      assert.equal(owner, 'designer_1');
      assert.deepEqual(tags, ['bridal', 'sapphire']);
      methods.push('tags');
      return ok({ family_id: familyId, tags }, 200);
    },
  };
  const gateway = createStudioGateway(client as any);

  assert.equal((await gateway.favoriteDesignFamily('family_ring', 'designer_1')).error, null);
  assert.equal((await gateway.unfavoriteDesignFamily('family_ring', 'designer_1')).error, null);
  assert.equal((await gateway.updateDesignFamilyTags(
    'family_ring', 'designer_1', ['bridal', 'sapphire'],
  )).error, null);
  assert.deepEqual(methods, ['favorite', 'unfavorite', 'tags']);
  assert.equal(jobStarts, 0);
});

test('forwards the explicit Collection owner without starting a Studio job', async () => {
  let forwardedRequest: unknown = null;
  let jobStarts = 0;
  const client = {
    ...baseClient(),
    createStudioJob: async () => {
      jobStarts += 1;
      throw new Error('Collection organization must not create Studio jobs');
    },
    createWorkspaceCollection: async (request: unknown) => {
      forwardedRequest = request;
      return ok({
        id: 'collection_campaign',
        name: 'Holiday campaign',
        template: 'campaign' as const,
        metadata: {},
        archived_at: null,
        created_at: '2026-07-12T00:00:00Z',
        updated_at: '2026-07-12T00:00:00Z',
        family_count: 0,
      }, 201);
    },
  };
  const gateway = createStudioGateway(client as any);

  const result = await gateway.createWorkspaceCollection({
    owner: 'designer_1',
    name: 'Holiday campaign',
    template: 'campaign',
  });

  assert.equal(result.error, null);
  assert.deepEqual(forwardedRequest, {
    owner: 'designer_1',
    name: 'Holiday campaign',
    template: 'campaign',
  });
  assert.equal(jobStarts, 0);
});

test('forwards one owner-scoped aggregate Collection membership read without Studio jobs', async () => {
  const owners: string[] = [];
  let jobStarts = 0;
  const client = {
    ...baseClient(),
    createStudioJob: async () => {
      jobStarts += 1;
      throw new Error('Collection reads must not create Studio jobs');
    },
    listWorkspaceCollectionMemberships: async (owner: string) => {
      owners.push(owner);
      return ok({
        family_collection_ids: {
          family_ring: ['collection_client'],
          family_unfiled: [],
        },
      });
    },
  };
  const gateway = createStudioGateway(client as any);

  const result = await gateway.listWorkspaceCollectionMemberships('designer_1');

  assert.equal(result.error, null);
  assert.deepEqual(result.data?.family_collection_ids, {
    family_ring: ['collection_client'],
    family_unfiled: [],
  });
  assert.deepEqual(owners, ['designer_1']);
  assert.equal(jobStarts, 0);
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
        studio_job_id: 'job_visual',
      });
      return ok({
        project_id: projectId, source_asset_id: 'asset_source', image_run_id: 'run_visual',
        candidate: {
          candidate_id: 'candidate_visual', preview_url: 'https://facetta.test/preview.png',
          save_as_variation_url: 'https://facetta.test/studio/image-runs/run_visual/visual-candidates/candidate_visual/save-as-variation',
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
        save_as_variation_url: 'https://facetta.test/studio/image-runs/run_discard/visual-candidates/candidate_discard/save-as-variation',
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

test('tracked visual discard relies on atomic backend settlement without client cancellation', async () => {
  const transitions: string[] = [];
  let cancellations = 0;
  const client = {
    ...baseClient(),
    createStudioJob: async () => ok(studioJob('queued'), 201),
    transitionStudioJob: async (_jobId: string, request: any) => {
      transitions.push(request.status);
      return ok(studioJob(request.status));
    },
    cancelStudioJob: async () => {
      cancellations += 1;
      return ok(studioJob('canceled'));
    },
    createVisualPreview: async (_projectId: string, request: any) => {
      assert.equal(request.studio_job_id, 'job_visual');
      return ok({
        project_id: 'project_visual', source_asset_id: 'asset_source',
        image_run_id: 'run_tracked_discard',
        candidate: {
          candidate_id: 'candidate_tracked_discard',
          preview_url: 'https://facetta.test/tracked-preview.png',
          save_as_variation_url: 'https://facetta.test/studio/image-runs/run_tracked_discard/visual-candidates/candidate_tracked_discard/save-as-variation',
          verdict: 'pass' as const, qa: quality(),
        },
      }, 201);
    },
    discardVisualPreview: async () => ok({
      status: 'discarded' as const, project_id: 'project_visual',
      source_asset_id: 'asset_source', candidate_id: 'candidate_tracked_discard',
    }),
  };
  const gateway = createStudioGateway(client as any);
  const preview = await gateway.previewVisualRefine({
    projectId: 'project_visual', sourceAssetId: 'asset_source',
    createdBy: 'designer_1', instruction: 'soften the reflection', scope: 'appearance',
  });
  assert.equal(preview.error, null);
  const discarded = await gateway.discardVisualRefine({
    candidateId: 'candidate_tracked_discard', createdBy: 'designer_1',
  });
  assert.equal(discarded.error, null);
  assert.equal(discarded.data?.candidate.status, 'discarded');
  assert.deepEqual(transitions, ['running']);
  assert.equal(cancellations, 0);
});

test('post-generation validation failure cannot generically fail a candidate-owned review job', async () => {
  const transitions: string[] = [];
  const client = {
    ...baseClient(),
    createStudioJob: async () => ok(studioJob('queued'), 201),
    transitionStudioJob: async (_jobId: string, request: any) => {
      transitions.push(request.status);
      return ok(studioJob(request.status));
    },
    createVisualPreview: async () => ok({
      project_id: 'wrong_project',
      source_asset_id: 'asset_source',
      image_run_id: 'run_invalid_lineage',
      candidate: {
        candidate_id: 'candidate_invalid_lineage',
        preview_url: 'https://facetta.test/invalid-lineage.png',
        save_as_variation_url: 'https://facetta.test/save-invalid-lineage',
        verdict: 'pass' as const,
        qa: quality(),
      },
    }, 201),
  };
  const gateway = createStudioGateway(client as any);

  const result = await gateway.previewVisualRefine({
    projectId: 'project_visual', sourceAssetId: 'asset_source',
    createdBy: 'designer_1', instruction: 'soften the reflection', scope: 'appearance',
  });

  assert.equal(result.error?.code, 'INVALID_VISUAL_PREVIEW_LINEAGE');
  assert.deepEqual(transitions, ['running']);
  assert.equal(transitions.includes('failed'), false);
});

test('failed-fidelity visual candidates cannot become canonical', async () => {
  let acceptCalls = 0;
  const client = {
    ...baseClient(),
    createVisualPreview: async () => ok({
      project_id: 'project_visual', source_asset_id: 'asset_source', image_run_id: 'run_failed',
      candidate: {
        candidate_id: 'candidate_failed', preview_url: 'https://facetta.test/failed.png',
        save_as_variation_url: 'https://facetta.test/studio/image-runs/run_failed/visual-candidates/candidate_failed/save-as-variation',
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

test('saves a visual preview as one named sibling and leaves source active', async () => {
  let saves = 0;
  const source = project('asset_newer');
  const variationAsset = {
    ...asset('variation_visual', null, 1), root_id: 'variation_visual',
    asset_id: 'variation_visual', capability: 'VARIATION_BRANCH',
  };
  const sibling = {
    ...project('asset_source'), id: 'variation_visual', root_id: 'variation_visual',
    active_asset_id: 'variation_visual', active_revision: variationAsset,
    revisions: [{
      revision: 1, asset: variationAsset, spec_version: null, spec_change: [],
      ignored_fields: [], qa: null, routing: null, created_at: null,
    }],
    assets: [variationAsset], cover_asset_id: 'variation_visual',
  } as ProjectDetail;
  const client = {
    ...baseClient(),
    createVisualPreview: async () => ok({
      project_id: 'project_visual', source_asset_id: 'asset_source', image_run_id: 'run_variation',
      candidate: {
        candidate_id: 'candidate_variation', preview_url: 'https://facetta.test/variation.png',
        save_as_variation_url: 'https://facetta.test/studio/image-runs/run_variation/visual-candidates/candidate_variation/save-as-variation',
        verdict: 'pass' as const, qa: quality(),
      },
    }, 201),
    saveVisualPreviewAsVariation: async (
      runId: string, candidateId: string, capabilityUrl: string, request: any,
    ) => {
      saves += 1;
      assert.equal(runId, 'run_variation');
      assert.equal(candidateId, 'candidate_variation');
      assert.match(capabilityUrl, /save-as-variation$/);
      assert.deepEqual(request, { created_by: 'designer_1', label: 'Warm direction' });
      return ok({
        status: 'saved_as_variation' as const, family_id: 'family_visual',
        variation_index: 2, source_project_id: 'project_visual',
        source_asset_id: 'asset_source', project: sibling,
      }, 201);
    },
    getProject: async () => ok(source),
  };
  const gateway = createStudioGateway(client as any, {
    now: () => new Date('2026-07-12T00:00:00Z'),
  });
  await gateway.previewVisualRefine({
    projectId: 'project_visual', sourceAssetId: 'asset_source', createdBy: 'designer_1',
    instruction: 'warm the gold', scope: 'appearance',
  });
  const saved = await gateway.saveVisualPreviewAsVariation({
    candidateId: 'candidate_variation', createdBy: 'designer_1', label: ' Warm direction ',
  });
  assert.equal(saved.error, null);
  assert.equal(saved.data?.candidate.status, 'saved_as_variation');
  assert.equal(saved.data?.project.root_id, 'variation_visual');
  assert.equal(saves, 1);
  assert.equal(source.active_asset_id, 'asset_newer');
  const repeated = await gateway.saveVisualPreviewAsVariation({
    candidateId: 'candidate_variation', createdBy: 'designer_1', label: 'Duplicate',
  });
  assert.equal(repeated.error?.code, 'CANDIDATE_NOT_FOUND');
  assert.equal(saves, 1);
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
          save_as_variation_url: 'https://facetta.test/studio/image-runs/run_markup/visual-candidates/candidate_markup/save-as-variation',
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
    studio_job_id: 'job_visual',
  });
});

test('keeps two local text edits ordered under one global preview instruction', async () => {
  let received: any = null;
  const client = {
    ...baseClient(),
    createVisualPreview: async (_projectId: string, request: unknown) => {
      received = request;
      return ok({
        project_id: 'project_visual', source_asset_id: 'asset_source',
        image_run_id: 'run_multi_markup',
        candidate: {
          candidate_id: 'candidate_multi_markup',
          preview_url: 'https://facetta.test/multi-markup.png',
          save_as_variation_url: 'https://facetta.test/save-multi-markup',
          verdict: 'pass' as const, qa: quality(),
        },
      }, 201);
    },
  };
  const gateway = createStudioGateway(client as any);
  const result = await gateway.previewVisualRefine({
    projectId: 'project_visual', sourceAssetId: 'asset_source',
    createdBy: 'designer_1',
    instruction: 'Keep the ring identity and camera unchanged.',
    scope: 'marked_region', markupAssetId: 'markup_asset_multi',
    annotations: [
      {
        region_description: ' left side diamond ',
        change_instruction: ' Make this diamond yellow ',
      },
      {
        region_description: ' right side diamond ',
        change_instruction: ' Make this diamond blue ',
      },
    ],
  });

  assert.equal(result.error, null);
  assert.equal(result.data?.candidate.temporary, true);
  assert.deepEqual(result.data?.annotations, [
    { region_description: 'left side diamond', change_instruction: 'Make this diamond yellow' },
    { region_description: 'right side diamond', change_instruction: 'Make this diamond blue' },
  ]);
  assert.deepEqual(received, {
    created_by: 'designer_1', expected_active_asset_id: 'asset_source',
    instruction: 'Keep the ring identity and camera unchanged.', scope: 'marked_region',
    markup_asset_id: 'markup_asset_multi', studio_job_id: 'job_visual',
    annotations: [
      { region_description: 'left side diamond', change_instruction: 'Make this diamond yellow' },
      { region_description: 'right side diamond', change_instruction: 'Make this diamond blue' },
    ],
  });
});
