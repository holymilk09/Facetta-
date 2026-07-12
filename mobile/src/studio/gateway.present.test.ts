/// <reference types="node" />

import assert from 'node:assert/strict';
import test from 'node:test';

import { createStudioGateway } from './gateway';

const ok = <T>(data: T, status = 200) => ({ data, error: null, status } as const);

const visualAsset = (id: string, capability = 'CREATIVE_RENDER', parent: string | null = null) => ({
  asset_id: id, root_id: 'project_visual', parent_asset_id: parent, capability,
  provenance: 'studio', revision: capability === 'CREATIVE_RENDER' ? 1 : null,
  design_id: null, design_version: null, region: null, instruction: null,
  drift: null, pinned: false, media_type: 'image/png', image_url: `https://test/${id}.png`,
  created_by: 'designer', created_at: null, legacy_provenance: false,
});

const visualProject = (derived: ReturnType<typeof visualAsset>[] = []) => ({
  id: 'project_visual', root_id: 'project_visual', title: 'Visual direction', collection: null,
  tags: [], owner: 'designer', state: 'refining' as const, design_id: null, spec: null,
  active_asset_id: 'asset_visual', selected_candidate_asset_id: 'asset_visual',
  active_design_version: null, active_revision: visualAsset('asset_visual'),
  pinned_revision: null, revisions: [{
    revision: 1, asset: visualAsset('asset_visual'), spec_version: null,
    spec_change: [], ignored_fields: [], qa: null, routing: null, created_at: null,
  }], assets: [visualAsset('asset_visual'), ...derived], derived_assets: derived,
  approval: null, factory_ready: false, factory_blockers: [], primary_revision_count: 1,
  has_factory_drawing: false, cover_asset_id: 'asset_visual', created_at: null, updated_at: null,
});

test('Present rejects a response that is not bound to the exact requested revision', async () => {
  const gateway = createStudioGateway({
    createMarketingPack: async () => ({
      data: {
        status: 'review_required',
        project_id: 'project_1',
        source_asset_id: 'different_asset',
        design_version: 7,
        requested_count: 1,
        candidate_count: 0,
        failed_count: 1,
        maximum_provider_attempts: 3,
        actual_attempts: 1,
        candidates: [],
        failures: [],
      },
      error: null,
      status: 201,
    }),
  } as unknown as Parameters<typeof createStudioGateway>[0]);

  const result = await gateway.createMarketingPresentation('project_1', {
    created_by: 'designer',
    expected_asset_id: 'asset_7',
    expected_design_version: 7,
    presets: ['catalog_white'],
  });

  assert.equal(result.data, null);
  assert.equal(result.error?.code, 'INVALID_PRESENTATION_LINEAGE');
  assert.equal(result.error?.category, 'invalid_response');
});

test('pre-spec Client presentation saves only a derived exact-source asset', async () => {
  const sourceHash = 'a'.repeat(64);
  const candidate = {
    candidate_id: 'candidate_client', image_run_id: 'run_client',
    preview_url: 'https://test/client.png', capability: 'CLIENT_BEAUTY_RENDER' as const,
    preset: 'luxury_studio' as const, framing: 'portrait' as const,
    qa: { verdict: 'pass' as const, accepted: true, review_required: false,
      score: 98, summary: '', failed_checks: [], warnings: [], checks: [] },
  };
  const savedAsset = visualAsset('asset_client', 'CLIENT_BEAUTY_RENDER', 'asset_visual');
  const gateway = createStudioGateway({
    createPreSpecPresentation: async () => ok({
      status: 'review_required' as const, project_id: 'project_visual',
      source_asset_id: 'asset_visual', source_sha256: sourceHash,
      design_version: null, destination: 'client' as const,
      client_format: 'beauty' as const, candidate,
    }, 201),
    getProject: async () => ok(visualProject()),
    acceptPreSpecPresentation: async (_runId: string, _candidateId: string, request: any) => {
      assert.equal(request.expected_source_sha256, sourceHash);
      return ok({
        status: 'accepted' as const, project_id: 'project_visual',
        source_asset_id: 'asset_visual', source_sha256: sourceHash,
        design_version: null, asset_id: 'asset_client',
        capability: 'CLIENT_BEAUTY_RENDER' as const,
        project: visualProject([savedAsset]),
      }, 201);
    },
  } as unknown as Parameters<typeof createStudioGateway>[0]);

  const preview = await gateway.createPreSpecPresentation('project_visual', {
    created_by: 'designer', expected_active_asset_id: 'asset_visual',
    destination: 'client', client_format: 'beauty', preset: 'luxury_studio',
  });
  assert.equal(preview.error, null);
  const accepted = await gateway.acceptPreSpecPresentation({
    candidateId: 'candidate_client', createdBy: 'designer',
  });
  assert.equal(accepted.error, null);
  assert.equal(accepted.data?.project.active_asset_id, 'asset_visual');
  assert.equal(accepted.data?.project.active_design_version, null);
  assert.equal(accepted.data?.project.derived_assets[0]?.asset_id, 'asset_client');
});

test('pre-spec Marketing discard uses source hash and creates no saved output', async () => {
  const sourceHash = 'b'.repeat(64);
  let decision: unknown = null;
  const gateway = createStudioGateway({
    createPreSpecPresentation: async () => ok({
      status: 'review_required' as const, project_id: 'project_visual',
      source_asset_id: 'asset_visual', source_sha256: sourceHash,
      design_version: null, destination: 'marketing' as const,
      client_format: 'product' as const,
      candidate: {
        candidate_id: 'candidate_marketing', image_run_id: 'run_marketing',
        preview_url: 'https://test/marketing.png', capability: 'MARKETING_IMAGE' as const,
        preset: 'dark_editorial' as const, framing: 'square' as const,
        qa: { verdict: 'pass' as const, accepted: true, review_required: false,
          score: 96, summary: '', failed_checks: [], warnings: [], checks: [] },
      },
    }, 201),
    getProject: async () => ok(visualProject()),
    discardPreSpecPresentation: async (_runId: string, _candidateId: string, request: unknown) => {
      decision = request;
      return ok({
        status: 'discarded' as const, project_id: 'project_visual',
        source_asset_id: 'asset_visual', source_sha256: sourceHash,
        design_version: null, candidate_id: 'candidate_marketing',
      });
    },
  } as unknown as Parameters<typeof createStudioGateway>[0]);

  await gateway.createPreSpecPresentation('project_visual', {
    created_by: 'designer', expected_active_asset_id: 'asset_visual',
    destination: 'marketing', preset: 'dark_editorial',
  });
  const discarded = await gateway.discardPreSpecPresentation({
    candidateId: 'candidate_marketing', createdBy: 'designer',
  });
  assert.equal(discarded.error, null);
  assert.deepEqual(decision, {
    created_by: 'designer', expected_active_asset_id: 'asset_visual',
    expected_source_sha256: sourceHash,
  });
  assert.equal(discarded.data?.project.derived_assets.length, 0);
});

test('pre-spec Present rejects a preview bound to a different active visual', async () => {
  const gateway = createStudioGateway({
    createPreSpecPresentation: async () => ok({
      status: 'review_required' as const, project_id: 'project_visual',
      source_asset_id: 'different_asset', source_sha256: 'd'.repeat(64),
      design_version: null, destination: 'client' as const,
      client_format: 'product' as const,
      candidate: {
        candidate_id: 'candidate_wrong', image_run_id: 'run_wrong',
        preview_url: 'https://test/wrong.png', capability: 'CLIENT_PRODUCT_PHOTO' as const,
        preset: 'catalog_white' as const, framing: 'square' as const,
        qa: { verdict: 'pass' as const, accepted: true, review_required: false,
          score: 90, summary: '', failed_checks: [], warnings: [], checks: [] },
      },
    }, 201),
  } as unknown as Parameters<typeof createStudioGateway>[0]);
  const result = await gateway.createPreSpecPresentation('project_visual', {
    created_by: 'designer', expected_active_asset_id: 'asset_visual',
    destination: 'client', preset: 'catalog_white',
  });
  assert.equal(result.data, null);
  assert.equal(result.error?.code, 'INVALID_PRE_SPEC_PRESENTATION_LINEAGE');
  assert.equal(result.error?.category, 'invalid_response');
});

test('pre-spec Present fails before save when the selected visual changed', async () => {
  const sourceHash = 'e'.repeat(64);
  let acceptCalls = 0;
  const stale = visualProject();
  stale.active_asset_id = 'new_visual';
  stale.selected_candidate_asset_id = 'new_visual';
  stale.active_revision = visualAsset('new_visual');
  const gateway = createStudioGateway({
    createPreSpecPresentation: async () => ok({
      status: 'review_required' as const, project_id: 'project_visual',
      source_asset_id: 'asset_visual', source_sha256: sourceHash,
      design_version: null, destination: 'client' as const,
      client_format: 'product' as const,
      candidate: {
        candidate_id: 'candidate_stale', image_run_id: 'run_stale',
        preview_url: 'https://test/stale.png', capability: 'CLIENT_PRODUCT_PHOTO' as const,
        preset: 'catalog_white' as const, framing: 'square' as const,
        qa: { verdict: 'pass' as const, accepted: true, review_required: false,
          score: 95, summary: '', failed_checks: [], warnings: [], checks: [] },
      },
    }, 201),
    getProject: async () => ok(stale),
    acceptPreSpecPresentation: async () => {
      acceptCalls += 1;
      return ok({});
    },
  } as unknown as Parameters<typeof createStudioGateway>[0]);
  await gateway.createPreSpecPresentation('project_visual', {
    created_by: 'designer', expected_active_asset_id: 'asset_visual',
    destination: 'client', preset: 'catalog_white',
  });
  const result = await gateway.acceptPreSpecPresentation({
    candidateId: 'candidate_stale', createdBy: 'designer',
  });
  assert.equal(result.data, null);
  assert.equal(result.error?.code, 'STALE_PRESENTATION_SOURCE');
  assert.equal(acceptCalls, 0);
});

test('pre-spec Present resumes a durable preview after gateway refresh', async () => {
  const sourceHash = 'f'.repeat(64);
  let decision: unknown = null;
  const gateway = createStudioGateway({
    listPreSpecPresentations: async () => ok({
      candidates: [{
        candidate_id: 'candidate_resumed', image_run_id: 'run_resumed',
        project_id: 'project_visual', source_asset_id: 'asset_visual',
        source_sha256: sourceHash, design_version: null, destination: 'client' as const,
        preview_url: 'https://test/resumed.png', studio_job_id: 'job_resumed',
        capability: 'CLIENT_PRODUCT_PHOTO' as const,
        preset: 'catalog_white' as const, framing: 'square' as const,
        qa: { verdict: 'pass' as const, accepted: true, review_required: false,
          score: 96, summary: '', failed_checks: [], warnings: [], checks: [] },
        status: 'reviewing' as const, accepted_asset_id: null,
        expires_at: '2026-07-13T12:00:00Z',
      }],
    }),
    getProject: async () => ok(visualProject()),
    acceptPreSpecPresentation: async (_runId: string, _candidateId: string, request: unknown) => {
      decision = request;
      const saved = {
        ...visualAsset('asset_resumed'), parent_asset_id: 'asset_visual',
        capability: 'CLIENT_PRODUCT_PHOTO',
      };
      const project = visualProject();
      project.assets = [...project.assets, saved];
      project.derived_assets = [saved];
      return ok({
        status: 'accepted' as const, project_id: 'project_visual',
        source_asset_id: 'asset_visual', source_sha256: sourceHash,
        design_version: null, asset_id: 'asset_resumed',
        capability: 'CLIENT_PRODUCT_PHOTO' as const, project,
      }, 201);
    },
  } as unknown as Parameters<typeof createStudioGateway>[0]);

  const resumed = await gateway.resumePreSpecPresentations({
    projectId: 'project_visual', sourceAssetId: 'asset_visual',
  }, 'designer');
  assert.equal(resumed.error, null);
  assert.equal(resumed.data?.[0]?.candidate.candidate_id, 'candidate_resumed');

  const accepted = await gateway.acceptPreSpecPresentation({
    candidateId: 'candidate_resumed', createdBy: 'designer',
  });
  assert.equal(accepted.error, null);
  assert.deepEqual(decision, {
    created_by: 'designer', expected_active_asset_id: 'asset_visual',
    expected_source_sha256: sourceHash,
  });
});

test('exact Present resumes only candidates bound to the immutable revision and reviewing job', async () => {
  const lineage = {
    projectId: 'project_exact', sourceAssetId: 'asset_exact', sourceDesignVersion: 9,
  };
  const candidate = {
    candidate_id: 'candidate_exact', image_run_id: 'run_exact',
    project_id: 'project_exact', source_asset_id: 'asset_exact',
    source_sha256: '9'.repeat(64), design_version: 9, destination: 'client' as const,
    preview_url: 'https://test/exact.png', studio_job_id: 'job_exact',
    capability: 'CLIENT_PRODUCT_PHOTO' as const,
    preset: 'catalog_white' as const, framing: 'square' as const,
    qa: { verdict: 'pass' as const, accepted: true, review_required: false,
      score: 99, summary: '', failed_checks: [], warnings: [], checks: [] },
    status: 'reviewing' as const, accepted_asset_id: null,
    expires_at: '2026-07-14T12:00:00Z',
  };
  const gateway = createStudioGateway({
    listPreSpecPresentations: async () => ok({ candidates: [candidate] }),
    listStudioJobs: async () => ok({ jobs: [{
      job_id: 'job_exact', owner: 'designer', action_id: 'present' as const,
      lane: 'fast_visual' as const, status: 'reviewing' as const, progress: 0.9,
      active_design_id: 'project_exact', source_revision_id: 'asset_exact', error_code: null,
      created_at: '2026-07-13T00:00:00Z', updated_at: '2026-07-13T00:00:01Z',
      billing: { requested_outputs: 1, credits_per_output: 18, estimated_credits: 18,
        completed_outputs: 0, charged_outputs: 0, charged_credits: 0, policy: 'accepted outputs only' },
    }] }),
  } as unknown as Parameters<typeof createStudioGateway>[0]);

  const resumed = await gateway.resumeExactPresentations(lineage, 'designer');
  assert.equal(resumed.error, null);
  assert.equal(resumed.data?.[0]?.candidate.candidate_id, 'candidate_exact');

  const staleGateway = createStudioGateway({
    listPreSpecPresentations: async () => ok({ candidates: [candidate] }),
    listStudioJobs: async () => ok({ jobs: [{
      job_id: 'job_exact', owner: 'designer', action_id: 'present' as const,
      lane: 'fast_visual' as const, status: 'reviewing' as const, progress: 0.9,
      active_design_id: 'project_exact', source_revision_id: 'different_asset', error_code: null,
      created_at: '2026-07-13T00:00:00Z', updated_at: '2026-07-13T00:00:01Z',
      billing: { requested_outputs: 1, credits_per_output: 18, estimated_credits: 18,
        completed_outputs: 0, charged_outputs: 0, charged_credits: 0, policy: 'accepted outputs only' },
    }] }),
  } as unknown as Parameters<typeof createStudioGateway>[0]);
  const stale = await staleGateway.resumeExactPresentations(lineage, 'designer');
  assert.equal(stale.error?.code, 'STUDIO_REVIEW_JOB_MISMATCH');
});
