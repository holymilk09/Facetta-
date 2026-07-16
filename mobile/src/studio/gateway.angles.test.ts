/// <reference types="node" />

import assert from 'node:assert/strict';
import test from 'node:test';

import type {
  ProjectDetail, StudioJobRecord, VisualAngleSet, VisualAngleView,
} from '../trusted/types';
import { createStudioGateway } from './gateway';

const ok = <T>(data: T, status = 200) => ({ data, error: null, status } as const);

const sourceAsset = {
  asset_id: 'asset_selected', root_id: 'project_1', parent_asset_id: null,
  capability: 'CREATIVE_RENDER', provenance: 'pre_spec_creative_candidate', revision: 1,
  design_id: null, design_version: null, region: null, instruction: 'Selected design',
  drift: null, pinned: false, media_type: 'image/png',
  image_url: 'https://test/source.png', created_by: 'designer', created_at: null,
  legacy_provenance: false,
};

const project = (derivedAssets: any[] = []): ProjectDetail => ({
  id: 'project_1', root_id: 'project_1', title: 'Selected ring', collection: null,
  tags: [], owner: 'designer', state: 'refining', design_id: null, spec: null,
  active_asset_id: 'asset_selected', active_design_version: null,
  selected_candidate_asset_id: 'asset_selected', confirmable_pre_spec: true,
  active_revision: sourceAsset as any, pinned_revision: null,
  revisions: [{
    revision: 1, asset: sourceAsset as any, spec_version: null, spec_change: [],
    ignored_fields: [], qa: null, routing: null, created_at: null,
  }],
  assets: [sourceAsset as any, ...derivedAssets], derived_assets: derivedAssets,
  approval: null, factory_ready: false, factory_blockers: [], primary_revision_count: 1,
  has_factory_drawing: false, cover_asset_id: 'asset_selected',
  created_at: null, updated_at: null,
});

const angleCandidate = (view: VisualAngleView, index: number) => ({
  candidate_id: `candidate_${view}`,
  image_run_id: `run_${view}`,
  view,
  output_sha256: `${index}`.repeat(64),
  qa: {
    verdict: 'pass' as const, accepted: false, review_required: true,
    score: 1, summary: 'Ready', failed_checks: [], warnings: [], checks: [],
  },
  routing: {
    run_id: `run_${view}`, attempt_count: 1, used_retry: false,
    used_fallback: false, cache_hit: false,
  },
  status: 'reviewing' as const,
  accepted_asset_id: null,
  preview_url: `https://test/${view}.png`,
});

const angleSet = (jobId = 'job_angles'): VisualAngleSet => ({
  angle_set_id: 'angle_set_1',
  studio_job_id: jobId,
  project_id: 'project_1',
  source_asset_id: 'asset_selected',
  source_sha256: 'a'.repeat(64),
  status: 'reviewing',
  expires_at: '2026-07-20T00:00:00Z',
  candidates: [
    angleCandidate('front', 1),
    angleCandidate('three_quarter', 2),
    angleCandidate('side', 3),
  ],
});

const jobRecord = (
  request: any,
  status: StudioJobRecord['status'],
  jobId = 'job_angles',
): StudioJobRecord => ({
  job_id: jobId,
  owner: request.owner ?? 'designer',
  action_id: request.action_id ?? 'angles',
  lane: request.lane ?? 'fast_visual',
  status,
  progress: request.progress ?? (status === 'reviewing' ? 0.9 : 0.05),
  active_design_id: request.active_design_id ?? 'project_1',
  source_revision_id: request.source_revision_id ?? 'asset_selected',
  accepted_output_sha256: null,
  error_code: request.error_code ?? null,
  created_at: '2026-07-17T00:00:00Z',
  updated_at: '2026-07-17T00:00:01Z',
  billing: {
    requested_outputs: request.requested_outputs ?? 3,
    credits_per_output: request.credits_per_output ?? 18,
    estimated_credits: 54,
    completed_outputs: status === 'succeeded' ? 3 : 0,
    charged_outputs: status === 'succeeded' ? 3 : 0,
    charged_credits: status === 'succeeded' ? 54 : 0,
    policy: 'Charge only after accepting all three.',
  },
});

test('visual angles start one first-class three-output Angles job', async () => {
  const createdJobs: any[] = [];
  const createVisualAngleSetCalls: any[] = [];
  const gateway = createStudioGateway({
    createStudioJob: async (request: any) => {
      createdJobs.push(request);
      return ok(jobRecord(request, 'queued'), 201);
    },
    transitionStudioJob: async (jobId: string, request: any) => (
      ok(jobRecord({ ...createdJobs[0], ...request }, request.status, jobId))
    ),
    createVisualAngleSet: async (projectId: string, request: any) => {
      createVisualAngleSetCalls.push({ projectId, request });
      return ok({
        action_id: 'angles' as const,
        status: 'review_required' as const,
        requested_outputs: 3 as const,
        credits_per_output: 18,
        estimated_credits: 54,
        billing_policy: 'Charge only after accepting all three.',
        angle_set: angleSet(request.studio_job_id),
      }, 201);
    },
  } as any);

  const result = await gateway.createVisualAngleSet({
    projectId: 'project_1', sourceAssetId: 'asset_selected',
  }, 'designer');

  assert.equal(result.error, null);
  assert.deepEqual(createdJobs[0], {
    owner: 'designer',
    action_id: 'angles',
    lane: 'fast_visual',
    active_design_id: 'project_1',
    source_revision_id: 'asset_selected',
    requested_outputs: 3,
    credits_per_output: 18,
  });
  assert.deepEqual(createVisualAngleSetCalls[0], {
    projectId: 'project_1',
    request: {
      created_by: 'designer', expected_active_asset_id: 'asset_selected',
      studio_job_id: 'job_angles', variant: 0,
    },
  });
  assert.deepEqual(result.data?.candidates.map((item) => item.view), [
    'front', 'three_quarter', 'side',
  ]);
  assert.equal(result.data?.estimatedCredits, 54);
});

test('an Activity job restores its angle set after a new gateway instance', async () => {
  const reviewingJob = jobRecord({}, 'reviewing');
  const getVisualAngleSetByJobCalls: string[] = [];
  const gateway = createStudioGateway({
    getVisualAngleSetByJob: async (jobId: string) => {
      getVisualAngleSetByJobCalls.push(jobId);
      return ok({ action_id: 'angles' as const, angle_set: angleSet(jobId) });
    },
    listStudioJobs: async () => ok({ jobs: [reviewingJob] }),
  } as any);

  const result = await gateway.resumeVisualAngleSet({
    projectId: 'project_1', sourceAssetId: 'asset_selected',
  }, 'designer', 'job_angles');

  assert.equal(result.error, null);
  assert.deepEqual(getVisualAngleSetByJobCalls, ['job_angles']);
  assert.equal(result.data?.studioJobId, 'job_angles');
  assert.equal(result.data?.creditsPerOutput, 18);
  assert.equal(result.data?.requestedOutputs, 3);
});

test('saving all three files derived angles without replacing the selected design', async () => {
  const derivedAssets = ['front', 'three_quarter', 'side'].map((view, index) => ({
    ...sourceAsset,
    asset_id: `angle_asset_${index + 1}`,
    parent_asset_id: 'asset_selected',
    capability: 'ANGLE_VIEW',
    provenance: `visual_angle_${view}`,
    revision: null,
  }));
  const acceptedProject = project(derivedAssets);
  const gateway = createStudioGateway({
    createStudioJob: async (request: any) => ok(jobRecord(request, 'queued'), 201),
    transitionStudioJob: async (jobId: string, request: any) => (
      ok(jobRecord(request, request.status, jobId))
    ),
    createVisualAngleSet: async (_projectId: string, request: any) => ok({
      action_id: 'angles' as const,
      status: 'review_required' as const,
      requested_outputs: 3 as const,
      credits_per_output: 18,
      estimated_credits: 54,
      billing_policy: 'Charge only after accepting all three.',
      angle_set: angleSet(request.studio_job_id),
    }, 201),
    getProject: async () => ok(project()),
    acceptVisualAngleSet: async () => ok({
      status: 'accepted' as const,
      angle_set_id: 'angle_set_1',
      source_asset_id: 'asset_selected',
      asset_ids: derivedAssets.map((asset) => asset.asset_id),
      capability: 'ANGLE_VIEW' as const,
      active_revision_unchanged: true as const,
      project: acceptedProject,
    }, 201),
  } as any);

  const generated = await gateway.createVisualAngleSet({
    projectId: 'project_1', sourceAssetId: 'asset_selected',
  }, 'designer');
  assert.equal(generated.error, null);
  const saved = await gateway.acceptVisualAngleSet('angle_set_1', 'designer');

  assert.equal(saved.error, null);
  assert.equal(saved.data?.project?.active_asset_id, 'asset_selected');
  assert.equal(saved.data?.project?.active_design_version, null);
  assert.deepEqual(saved.data?.project?.derived_assets.map((asset) => asset.asset_id), [
    'angle_asset_1', 'angle_asset_2', 'angle_asset_3',
  ]);
});

test('discarding the set preserves zero charged outputs', async () => {
  const gateway = createStudioGateway({
    createStudioJob: async (request: any) => ok(jobRecord(request, 'queued'), 201),
    transitionStudioJob: async (jobId: string, request: any) => (
      ok(jobRecord(request, request.status, jobId))
    ),
    createVisualAngleSet: async (_projectId: string, request: any) => ok({
      action_id: 'angles' as const,
      status: 'review_required' as const,
      requested_outputs: 3 as const,
      credits_per_output: 18,
      estimated_credits: 54,
      billing_policy: 'Charge only after accepting all three.',
      angle_set: angleSet(request.studio_job_id),
    }, 201),
    discardVisualAngleSet: async () => ok({
      status: 'discarded' as const,
      angle_set_id: 'angle_set_1',
      source_asset_id: 'asset_selected',
      charged_outputs: 0 as const,
    }),
  } as any);

  await gateway.createVisualAngleSet({
    projectId: 'project_1', sourceAssetId: 'asset_selected',
  }, 'designer');
  const discarded = await gateway.discardVisualAngleSet('angle_set_1', 'designer');

  assert.equal(discarded.error, null);
  assert.equal(discarded.data?.project, null);
  assert.equal(discarded.data?.review.status, 'discarded');
});
