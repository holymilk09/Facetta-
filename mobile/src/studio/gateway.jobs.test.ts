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

const unselectedProject = (creativeCount: number): ProjectDetail => {
  const base = project(0);
  const candidates = Array.from(
    { length: creativeCount },
    (_, index) => ({
      ...asset(`direction_${index + 1}`),
      revision: null,
      design_id: null,
      design_version: null,
    }),
  );
  return {
    ...base,
    design_id: null,
    spec: null,
    active_asset_id: null,
    active_design_version: null,
    active_revision: null,
    revisions: [],
    creative_candidates: candidates,
    assets: candidates,
    primary_revision_count: 0,
    cover_asset_id: candidates[0]?.asset_id ?? null,
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

test('job-centric review restores immutable stale source with fail-closed decisions', async () => {
  const staleProject = project(2);
  staleProject.active_asset_id = 'candidate_2';
  staleProject.active_revision = staleProject.revisions[1]!.asset;
  const reviewingJob: StudioJobRecord = {
    job_id: 'studio_job_stale_refine', owner: 'designer_1', action_id: 'refine',
    lane: 'trusted_structural', status: 'reviewing', progress: 0.9,
    active_design_id: 'project_1', source_revision_id: 'candidate_1', error_code: null,
    created_at: '2026-07-12T00:00:00Z', updated_at: '2026-07-12T00:00:01Z',
    billing: {
      requested_outputs: 1, credits_per_output: 20, estimated_credits: 20,
      completed_outputs: 0, charged_outputs: 0, charged_credits: 0,
      policy: 'Only accepted outputs are charged.',
    },
  };
  const gateway = createStudioGateway({
    getStudioJob: async () => ok(reviewingJob),
    getProject: async () => ok(staleProject),
  } as any, { trackJobs: true });

  const resumed = await gateway.resumeReviewJob(reviewingJob.job_id, 'designer_1');
  assert.equal(resumed.error, null);
  assert.equal(resumed.data?.sourceIsActive, false);
  assert.equal(resumed.data?.lineage.sourceAssetId, 'candidate_1');
  assert.deepEqual(resumed.data?.allowedDecisions, {
    apply: false, discard: true, saveAsVariation: true,
  });
});

test('tracked prompt and drawing creation charge only after direction acceptance', async () => {
  const jobs = tracking();
  let drawingCalls = 0;
  const commits: { projectId: string; studioJobId?: string }[] = [];
  const gateway = createStudioGateway({
    ...jobs.client,
    createProjectFromPrompt: async () => ok(unselectedProject(2), 201),
    createProjectFromDrawing: async () => { drawingCalls += 1; return ok(unselectedProject(2), 201); },
    commitCreativeDirections: async (projectId: string, request: { studio_job_id?: string }) => {
      commits.push({ projectId, studioJobId: request.studio_job_id });
      return ok({
        project: {
          ...project(2), selected_candidate_asset_id: 'direction_2',
          active_asset_id: 'direction_2',
        },
        retained_variations: [],
      });
    },
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

  await gateway.completeCreativeDirectionReview({
    projectId: 'project_1', selectedCandidateId: 'direction_2', retained: [],
    createdBy: 'designer_1',
  });
  assert.deepEqual(commits[0], { projectId: 'project_1', studioJobId: 'studio_job_1' });
  assert.deepEqual(jobs.transitions.map((call) => call.request.status), [
    'running', 'reviewing',
  ]);

  const drawing = await gateway.createFromDrawing({
    image_base64: 'c2tldGNo', source_kind: 'drawing', media_type: 'image/png', instruction: 'Preserve it',
    variation_count: 2, owner: 'designer_1', title: 'Drawing',
  });
  assert.equal(drawing.error, null);
  assert.equal(drawingCalls, 1);
  assert.equal(jobs.creates[1]?.requested_outputs, 2);
  assert.equal(jobs.transitions.at(-1)?.request.status, 'reviewing');
});

test('a restarted gateway settles the durable reviewing Create job supplied by Activity', async () => {
  const commits: { studioJobId?: string }[] = [];
  const gateway = createStudioGateway({
    commitCreativeDirections: async (
      _projectId: string, request: { studio_job_id?: string },
    ) => {
      commits.push({ studioJobId: request.studio_job_id });
      return ok({
        project: {
          ...project(2), selected_candidate_asset_id: 'direction_2',
          active_asset_id: 'direction_2',
        },
        retained_variations: [],
      });
    },
  } as any, { trackJobs: true });

  const result = await gateway.completeCreativeDirectionReview({
    projectId: 'project_1', selectedCandidateId: 'direction_2', retained: [],
    createdBy: 'designer_1', studioJobId: 'studio_job_rehydrated',
  });
  assert.equal(result.error, null);
  assert.deepEqual(commits, [{ studioJobId: 'studio_job_rehydrated' }]);
});

test('atomic Create review forwards the same-session durable job exactly once', async () => {
  const jobs = tracking();
  const commits: { projectId: string; studioJobId?: string }[] = [];
  const gateway = createStudioGateway({
    ...jobs.client,
    createProjectFromPrompt: async () => ok(unselectedProject(3), 201),
    commitCreativeDirections: async (projectId: string, request: { studio_job_id?: string }) => {
      commits.push({ projectId, studioJobId: request.studio_job_id });
      return ok({
        project: {
          ...project(3), selected_candidate_asset_id: 'direction_3',
          active_asset_id: 'direction_3',
        },
        retained_variations: [{
          status: 'variation_created' as const,
          family_id: 'family_1', variation_index: 2,
          source_project_id: 'project_1', source_asset_id: 'direction_2',
          project: project(1),
        }],
      }, 200);
    },
  } as any, { trackJobs: true });

  await gateway.createFromPrompt({
    prompt: 'Sapphire orbit', variation_count: 3, owner: 'designer_1', title: 'Orbit',
  });
  const committed = await gateway.completeCreativeDirectionReview({
    projectId: 'project_1', selectedCandidateId: 'direction_3',
    retained: [{ candidateId: 'direction_2', label: 'Direction 2' }],
    createdBy: 'designer_1',
  });

  assert.equal(committed.error, null);
  assert.deepEqual(commits, [{ projectId: 'project_1', studioJobId: 'studio_job_1' }]);
  assert.deepEqual(jobs.transitions.map((call) => call.request.status), [
    'running', 'reviewing',
  ]);
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
  assert.equal(jobs.transitions[1]?.request.progress, 1);
  assert.equal(jobs.transitions[1]?.request.completed_outputs, undefined);
});

test('tracked markup refuses compatibility-only candidates before review', async () => {
  const jobs = tracking();
  let genericDecisions = 0;
  let boundJobId: string | undefined;
  const gateway = createStudioGateway({
    ...jobs.client,
    applyMarkup: async (_assetId: string, request: any) => {
      boundJobId = request.studio_job_id;
      return ok({
        revision: null, spec_version: 1, spec_change: [], ignored_fields: [],
        qa: quality,
        routing: {
          attempt_count: 1, used_retry: false, used_fallback: false,
          cache_hit: false, run_id: 'image_run_markup',
        },
        image_run_id: 'image_run_markup',
        warning_candidate: {
          run_id: 'image_run_markup', candidate_id: 'compatibility_only',
          preview_url: '/image-runs/image_run_markup/candidates/compatibility_only/image',
          qa: quality, operation: 'LOCAL_EDIT', requested_change: 'Soften the halo',
          asset_capability: 'LOCALIZED_EDIT',
        },
      }, 201);
    },
    listStudioMarkupCandidates: async () => ok({ candidates: [] }),
    acceptWarningCandidate: async () => {
      genericDecisions += 1;
      return ok(project(1));
    },
    discardWarningCandidate: async () => {
      genericDecisions += 1;
      return ok({ status: 'discarded' });
    },
  } as any, { trackJobs: true });

  const result = await gateway.previewMarkupRefine({
    projectId: 'project_1', sourceAssetId: 'candidate_1', sourceDesignVersion: 1,
    createdBy: 'designer_1', annotation: {
      region_description: 'halo', change_instruction: 'Soften the halo',
      impact: 'visual_only', target_section: null, target_ref: null, index: null,
      target_component_id: null, target_element_id: null,
      form_view: 'three_quarter', mask_base64: null,
    },
  });

  assert.equal(boundJobId, 'studio_job_1');
  assert.equal(result.error?.code, 'DURABLE_MARKUP_PREVIEW_MISSING');
  assert.equal(genericDecisions, 0);
  // The backend owns candidate-decision settlement after entering review.
  // The client fails closed without fabricating a terminal job transition.
  assert.deepEqual(jobs.transitions.map((call) => call.request.status), ['running']);
  assert.equal(jobs.transitions.some((call) => call.request.completed_outputs), false);
});

test('catalog preview keeps image-run and Studio-job identities separate through apply', async () => {
  const jobs = tracking();
  let previewStudioJobId: string | undefined;
  const next = project(1);
  next.active_asset_id = 'asset_2';
  next.active_revision = { ...asset('asset_2', 'LOCALIZED_EDIT'), design_version: 2 };
  next.active_design_version = 2;
  const gateway = createStudioGateway({
    ...jobs.client,
    previewCatalogSelection: async (_assetId: string, request: any) => {
      previewStudioJobId = request.studio_job_id;
      return ok({
      status: 'preview_ready', component_path: 'metal.color', option_id: 'rose',
      isolation_target: 'metal', source_asset_id: 'candidate_1', design_version: 1,
      image_run_id: 'image_run_catalog', spec_change: [], next_spec: {}, qa: quality,
      routing: { attempt_count: 1, used_retry: false, used_fallback: false, cache_hit: false, run_id: 'image_run_catalog' },
      project: project(1), candidate: {
        run_id: 'image_run_catalog', candidate_id: 'candidate_catalog',
        preview_url: 'https://test/preview.png', accept_url: '/accept', discard_url: '/discard',
        save_as_variation_url: '/save-as-variation',
        verdict: 'pass', studio_job_id: request.studio_job_id, expires_in_seconds: 600,
      },
    }, 201);
    },
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
  assert.equal(previewStudioJobId, 'studio_job_1');
  assert.equal(jobs.transitions[0]?.jobId, 'studio_job_1');
  assert.deepEqual(jobs.transitions.map((call) => call.request.status), ['running']);

  const applied = await gateway.applyCatalogRefine({
    candidateId: 'candidate_catalog', createdBy: 'designer_1',
  });
  assert.equal(applied.error, null);
  assert.deepEqual(jobs.transitions.map((call) => call.request.status), ['running']);
});

test('saving a catalog preview variation resolves Activity once with one completed output', async () => {
  const jobs = tracking();
  const source = project(2);
  source.active_asset_id = 'candidate_2';
  source.active_revision = source.revisions[1]!.asset;
  const sibling = {
    ...project(1), id: 'variation_2', root_id: 'variation_2',
    active_asset_id: 'variation_2', active_design_version: 1,
    active_revision: { ...asset('variation_2', 'VARIATION_BRANCH'), root_id: 'variation_2' },
    design_id: 'design_variation', spec: {}, cover_asset_id: 'variation_2',
  };
  const gateway = createStudioGateway({
    ...jobs.client,
    previewCatalogSelection: async (_assetId: string, request: any) => ok({
      status: 'preview_ready', component_path: 'metal.color', option_id: 'rose',
      isolation_target: 'metal', source_asset_id: 'candidate_1', design_version: 1,
      image_run_id: 'image_run_variation', spec_change: [], next_spec: {}, qa: quality,
      routing: { attempt_count: 1, used_retry: false, used_fallback: false, cache_hit: false, run_id: 'image_run_variation' },
      project: project(1), candidate: {
        run_id: 'image_run_variation', candidate_id: 'candidate_variation',
        preview_url: 'https://test/preview.png', accept_url: '/accept', discard_url: '/discard',
        save_as_variation_url: '/save-as-variation', verdict: 'pass',
        studio_job_id: request.studio_job_id, expires_in_seconds: 600,
      },
    }, 201),
    saveCatalogPreviewAsVariation: async () => ok({
      status: 'saved_as_variation', family_id: 'family_1', variation_index: 2,
      source_project_id: 'project_1', source_asset_id: 'candidate_1',
      design_id: 'design_variation', design_version: 1, project: sibling,
    }, 201),
    getProject: async () => ok(source),
  } as any, { trackJobs: true });

  await gateway.previewCatalogRefine({
    projectId: 'project_1', sourceAssetId: 'candidate_1', sourceDesignVersion: 1,
    createdBy: 'designer_1', componentPath: 'metal.color', optionId: 'rose',
  });
  const saved = await gateway.saveCatalogPreviewAsVariation({
    candidateId: 'candidate_variation', createdBy: 'designer_1', label: 'Rose halo',
  });
  assert.equal(saved.error, null);
  assert.equal(source.active_asset_id, 'candidate_2');
  assert.deepEqual(jobs.transitions.map((call) => call.request.status), ['running']);
});

test('a restarted gateway resumes catalog review by its durable exact Refine job', async () => {
  let acceptedCandidate: string | null = null;
  let publicTerminalTransitions = 0;
  const next = project(1);
  next.active_asset_id = 'asset_2';
  next.active_revision = { ...asset('asset_2', 'LOCALIZED_EDIT'), design_version: 2 };
  next.active_design_version = 2;
  const reviewingJob: StudioJobRecord = {
    job_id: 'studio_job_catalog_resume', owner: 'designer_1', action_id: 'refine',
    lane: 'trusted_structural', status: 'reviewing', progress: 0.9,
    active_design_id: 'project_1', source_revision_id: 'candidate_1', error_code: null,
    created_at: '2026-07-12T00:00:00Z', updated_at: '2026-07-12T00:00:01Z',
    billing: {
      requested_outputs: 1, credits_per_output: 20, estimated_credits: 20,
      completed_outputs: 0, charged_outputs: 0, charged_credits: 0,
      policy: 'Only accepted outputs are charged.',
    },
  };
  const gateway = createStudioGateway({
    listStudioJobs: async () => ok({ jobs: [reviewingJob] }),
    listCatalogPreviews: async () => ok({ candidates: [{
      candidate: {
        run_id: 'image_run_resume', candidate_id: 'candidate_catalog_resume',
        preview_url: 'https://test/resume.png', accept_url: '/accept',
        discard_url: '/discard', save_as_variation_url: '/save-as-variation',
        verdict: 'pass', studio_job_id: reviewingJob.job_id, expires_in_seconds: 600,
      },
      source_asset_id: 'candidate_1', component_path: 'metal.color', option_id: 'rose',
      requested_change: 'Apply rose gold', next_spec: {}, spec_change: [], qa: quality,
      routing: { attempt_count: 1, used_retry: false, used_fallback: false,
        cache_hit: false, run_id: 'image_run_resume' },
      expires_at: '2099-01-01T00:00:00Z',
    }] }),
    acceptCatalogPreview: async (candidate: any) => {
      acceptedCandidate = candidate.candidate_id;
      return ok({
        status: 'accepted' as const, asset_id: 'asset_2', design_version: 2,
        image_run_id: 'image_run_resume', spec_change: [], project: next,
      }, 201);
    },
    transitionStudioJob: async () => {
      publicTerminalTransitions += 1;
      throw new Error('catalog decisions are server-settled');
    },
  } as any, { trackJobs: true });

  const resumed = await gateway.resumeRefine({
    projectId: 'project_1', sourceAssetId: 'candidate_1', sourceDesignVersion: 1,
  }, 'designer_1');
  assert.equal(resumed.error, null);
  assert.equal(resumed.data?.candidate.id, 'candidate_catalog_resume');
  const accepted = await gateway.applyCatalogRefine({
    candidateId: 'candidate_catalog_resume', createdBy: 'designer_1',
  });
  assert.equal(accepted.error, null);
  assert.equal(acceptedCandidate, 'candidate_catalog_resume');
  assert.equal(publicTerminalTransitions, 0);
});

test('Views binds the canonical preview request to its durable job before atomic zero-charge discard', async () => {
  const jobs = tracking();
  let lineArtRequest: any = null;
  const gateway = createStudioGateway({
    ...jobs.client,
    createLineArt: async (_projectId: string, request: any) => {
      lineArtRequest = request;
      return ok({
        status: 'confirmation_required', project_id: 'project_1', image_run_id: 'image_run_view',
        quality_report: quality,
        routing: { attempt_count: 1, used_retry: false, used_fallback: false, cache_hit: false, run_id: 'image_run_view' },
        view: request.view, candidate: {
          run_id: 'image_run_view', candidate_id: 'candidate_view', preview_url: 'https://test/view.png',
          qa: quality, operation: 'VISUAL_ONLY_EDIT', requested_change: 'Front view', asset_capability: 'LINE_ART',
        }, next: 'Review',
      }, 202);
    },
    discardStudioViewCandidate: async () => ok({
      status: 'discarded' as const, project_id: 'project_1', source_asset_id: 'candidate_1',
      design_version: 1, candidate_id: 'candidate_view',
    }),
  } as any, { trackJobs: true });

  await gateway.previewLineArtView({
    projectId: 'project_1', sourceAssetId: 'candidate_1', sourceDesignVersion: 1,
    createdBy: 'designer_1', view: 'front',
  });
  assert.deepEqual(jobs.transitions.map((call) => call.request.status), ['running']);
  const discarded = await gateway.discardLineArtView({
    candidateId: 'candidate_view', createdBy: 'designer_1',
  });
  assert.equal(discarded.error, null);
  assert.equal(lineArtRequest.studio_job_id, 'studio_job_1');
  assert.equal(jobs.cancellations.length, 0);
});

test('Present rejects generation-time acceptance and keeps review-only outputs uncharged', async () => {
  const jobs = tracking();
  const boundJobIds: string[] = [];
  const acceptedProject = project(1);
  acceptedProject.derived_assets = [asset('presentation_1', 'BEAUTY_RENDER')];
  const gateway = createStudioGateway({
    ...jobs.client,
    createStudioBeautyRender: async (_projectId: string, request: any) => {
      boundJobIds.push(request.studio_job_id);
      return ok({
        status: 'accepted', project: acceptedProject, source_asset_id: 'candidate_1',
        asset_id: 'presentation_1', image_run_id: 'image_run_beauty', qa: quality,
      }, 201);
    },
    createStudioProductPhoto: async (_projectId: string, request: any) => {
      boundJobIds.push(request.studio_job_id);
      return ok({
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
      }, 202);
    },
    createMarketingPack: async (_projectId: string, request: any) => {
      boundJobIds.push(request.studio_job_id);
      return ok({
        status: 'failed', project_id: 'project_1', source_asset_id: 'candidate_1',
        design_version: 1, requested_count: 1, candidate_count: 0, failed_count: 1,
        maximum_provider_attempts: 3, actual_attempts: 1, candidates: [], failures: [],
      }, 200);
    },
  } as any, { trackJobs: true });

  const bypassed = await gateway.createBeautyPresentation('project_1', {
    created_by: 'designer_1', expected_asset_id: 'candidate_1',
    expected_design_version: 1, presentation_only: true,
  });
  assert.equal(bypassed.error?.code, 'PRESENTATION_REVIEW_BYPASSED');
  assert.equal(jobs.transitions.at(-1)?.request.status, 'failed');
  assert.equal(jobs.transitions.some((call) => call.request.completed_outputs), false);

  await gateway.createProductPresentation('project_1', {
    created_by: 'designer_1', expected_asset_id: 'candidate_1', expected_design_version: 1,
    preset: 'catalog_white', framing: 'square', presentation_only: true,
  });
  assert.deepEqual(jobs.transitions.filter((call) => call.jobId === 'studio_job_2')
    .map((call) => call.request.status), ['running']);

  await gateway.createMarketingPresentation('project_1', {
    created_by: 'designer_1', expected_asset_id: 'candidate_1', expected_design_version: 1,
    presets: ['catalog_white'],
  });
  assert.equal(jobs.transitions.at(-1)?.request.status, 'failed');
  assert.equal(jobs.transitions.at(-1)?.request.error_code, 'NO_PRESENTATION_OUTPUTS');
  assert.deepEqual(boundJobIds, ['studio_job_1', 'studio_job_2', 'studio_job_3']);
});

test('marketing presentation decisions resolve independently and charge only saved outputs', async () => {
  const jobs = tracking();
  let current = project(1);
  const acceptedCalls: string[] = [];
  const discardedCalls: string[] = [];
  const decisionRequests: unknown[] = [];
  const derived = (id: string) => ({
    ...asset(id, 'MARKETING_IMAGE'),
    parent_asset_id: 'candidate_1',
    revision: null,
  });
  const gateway = createStudioGateway({
    ...jobs.client,
    createMarketingPack: async () => ok({
      status: 'review_required', project_id: 'project_1', source_asset_id: 'candidate_1',
      design_version: 1, requested_count: 2, candidate_count: 2, failed_count: 0,
      maximum_provider_attempts: 6, actual_attempts: 2, failures: [],
      candidates: [
        { preset: 'catalog_white', framing: 'square', image_run_id: 'run_white',
          candidate_id: 'candidate_white', preview_url: 'https://test/white.png', qa: quality, routing: {} },
        { preset: 'luxury_studio', framing: 'square', image_run_id: 'run_luxury',
          candidate_id: 'candidate_luxury', preview_url: 'https://test/luxury.png', qa: quality, routing: {} },
      ],
    }, 202),
    getProject: async () => ok(current),
    acceptPresentationCandidate: async (runId: string, candidateId: string, request: unknown) => {
      acceptedCalls.push(`${runId}:${candidateId}`);
      decisionRequests.push(request);
      current = {
        ...current,
        derived_assets: [...current.derived_assets, derived('marketing_saved')],
        assets: [...current.assets, derived('marketing_saved')],
      };
      return ok({
        status: 'accepted' as const, project_id: 'project_1', source_asset_id: 'candidate_1',
        source_design_version: 1, asset_id: 'marketing_saved', capability: 'MARKETING_IMAGE' as const,
        project: current,
      }, 201);
    },
    discardPresentationCandidate: async (runId: string, candidateId: string, request: unknown) => {
      discardedCalls.push(`${runId}:${candidateId}`);
      decisionRequests.push(request);
      return ok({
        status: 'discarded' as const, project_id: 'project_1', source_asset_id: 'candidate_1',
        source_design_version: 1, candidate_id: candidateId,
      });
    },
  } as any, { trackJobs: true });

  const generated = await gateway.createMarketingPresentation('project_1', {
    created_by: 'designer_1', expected_asset_id: 'candidate_1', expected_design_version: 1,
    presets: ['catalog_white', 'luxury_studio'], framing: 'square',
  });
  assert.equal(generated.error, null);
  assert.deepEqual(jobs.transitions.map((call) => call.request.status), ['running']);
  const transitionsBeforeDecisions = jobs.transitions.length;

  const saved = await gateway.acceptPresentationCandidate({
    candidateId: 'candidate_white', createdBy: 'designer_1',
  });
  assert.equal(saved.error, null);
  assert.equal(saved.data?.project.active_asset_id, 'candidate_1');
  assert.equal(saved.data?.project.active_design_version, 1);
  assert.deepEqual(jobs.transitions.map((call) => call.request.status), ['running']);

  const discarded = await gateway.discardPresentationCandidate({
    candidateId: 'candidate_luxury', createdBy: 'designer_1',
  });
  assert.equal(discarded.error, null);
  assert.deepEqual(acceptedCalls, ['run_white:candidate_white']);
  assert.deepEqual(discardedCalls, ['run_luxury:candidate_luxury']);
  assert.deepEqual(decisionRequests, [
    { created_by: 'designer_1', expected_project_id: 'project_1',
      expected_source_asset_id: 'candidate_1', expected_design_version: 1 },
    { created_by: 'designer_1', expected_project_id: 'project_1',
      expected_source_asset_id: 'candidate_1', expected_design_version: 1 },
  ]);
  assert.equal(jobs.cancellations.length, 0);
  assert.equal(jobs.transitions.length, transitionsBeforeDecisions);
});

test('pre-spec presentation jobs charge only saved derived outputs', async () => {
  const jobs = tracking();
  const sourceHash = 'c'.repeat(64);
  const source = {
    ...asset('candidate_1'), design_id: null, design_version: null,
  };
  let current: ProjectDetail = {
    ...project(1), design_id: null, spec: null, active_design_version: null,
    selected_candidate_asset_id: 'candidate_1', active_revision: source,
    assets: [source], derived_assets: [], revisions: [{
      revision: 1, asset: source, spec_version: null, spec_change: [],
      ignored_fields: [], qa: null, routing: null, created_at: null,
    }],
  };
  let counter = 0;
  const gateway = createStudioGateway({
    ...jobs.client,
    createPreSpecPresentation: async (_projectId: string, request: any) => {
      counter += 1;
      return ok({
        status: 'review_required' as const, project_id: 'project_1',
        source_asset_id: 'candidate_1', source_sha256: sourceHash,
        design_version: null, destination: request.destination,
        client_format: request.client_format ?? 'product',
        candidate: {
          candidate_id: `candidate_present_${counter}`,
          image_run_id: `run_present_${counter}`,
          preview_url: `https://test/present_${counter}.png`,
          studio_job_id: request.studio_job_id ?? null,
          capability: request.destination === 'client'
            ? 'CLIENT_PRODUCT_PHOTO' as const : 'MARKETING_IMAGE' as const,
          preset: request.preset, framing: request.framing ?? 'square', qa: quality,
        },
      }, 201);
    },
    getProject: async () => ok(current),
    acceptPreSpecPresentation: async (_runId: string, _candidateId: string) => {
      const saved = {
        ...asset('presentation_saved', 'CLIENT_PRODUCT_PHOTO'),
        parent_asset_id: 'candidate_1', revision: null,
        design_id: null, design_version: null,
      };
      current = {
        ...current, assets: [...current.assets, saved], derived_assets: [saved],
      };
      return ok({
        status: 'accepted' as const, project_id: 'project_1',
        source_asset_id: 'candidate_1', source_sha256: sourceHash,
        design_version: null, asset_id: saved.asset_id,
        capability: 'CLIENT_PRODUCT_PHOTO' as const, project: current,
      }, 201);
    },
    discardPreSpecPresentation: async (_runId: string, candidateId: string) => ok({
      status: 'discarded' as const, project_id: 'project_1',
      source_asset_id: 'candidate_1', source_sha256: sourceHash,
      design_version: null, candidate_id: candidateId,
    }),
  } as any, { trackJobs: true });

  await gateway.createPreSpecPresentation('project_1', {
    created_by: 'designer_1', expected_active_asset_id: 'candidate_1',
    destination: 'client', preset: 'catalog_white',
  });
  await gateway.createPreSpecPresentation('project_1', {
    created_by: 'designer_1', expected_active_asset_id: 'candidate_1',
    destination: 'marketing', preset: 'dark_editorial',
  });
  assert.equal(jobs.creates.length, 2);
  assert.equal(jobs.transitions.filter((call) => (
    call.request.status === 'reviewing'
  )).length, 0);

  const saved = await gateway.acceptPreSpecPresentation({
    candidateId: 'candidate_present_1', createdBy: 'designer_1',
  });
  assert.equal(saved.error, null);
  assert.equal(saved.data?.project.active_asset_id, 'candidate_1');
  assert.equal(saved.data?.project.active_design_version, null);
  assert.equal(jobs.transitions.some((call) => (
    call.request.status === 'succeeded'
  )), false);

  const discarded = await gateway.discardPreSpecPresentation({
    candidateId: 'candidate_present_2', createdBy: 'designer_1',
  });
  assert.equal(discarded.error, null);
  assert.equal(jobs.cancellations.length, 0);
});

test('presentation decisions fail closed if the selected revision changes before review', async () => {
  const jobs = tracking();
  let acceptCalls = 0;
  const stale = project(1);
  stale.active_asset_id = 'different_asset';
  stale.active_revision = { ...asset('different_asset'), design_version: 2 };
  stale.active_design_version = 2;
  const gateway = createStudioGateway({
    ...jobs.client,
    createStudioProductPhoto: async () => ok({
      status: 'review_required', project_id: 'project_1', image_run_id: 'run_product',
      quality_report: quality, routing: {},
      presentation: { preset: 'catalog_white', framing: 'square',
        source_asset_id: 'candidate_1', design_version: 1 },
      warning_candidate: { run_id: 'run_product', candidate_id: 'candidate_product',
        preview_url: 'https://test/product.png', qa: quality,
        operation: 'VISUAL_ONLY_EDIT', requested_change: 'Product photo', asset_capability: 'CLIENT_PRODUCT_PHOTO' },
    }, 202),
    getProject: async () => ok(stale),
    acceptPresentationCandidate: async () => { acceptCalls += 1; return ok({}); },
  } as any, { trackJobs: true });

  await gateway.createProductPresentation('project_1', {
    created_by: 'designer_1', expected_asset_id: 'candidate_1', expected_design_version: 1,
    preset: 'catalog_white', framing: 'square', presentation_only: true,
  });
  const result = await gateway.acceptPresentationCandidate({
    candidateId: 'candidate_product', createdBy: 'designer_1',
  });
  assert.equal(result.error?.code, 'STALE_PRESENTATION_SOURCE');
  assert.equal(acceptCalls, 0);
  assert.deepEqual(jobs.transitions.map((call) => call.request.status), ['running']);
  assert.equal(jobs.transitions.some((call) => call.request.status === 'failed'), false);
});

test('discarding the only exact presentation delegates atomic zero-charge settlement', async () => {
  const jobs = tracking();
  const current = project(1);
  const gateway = createStudioGateway({
    ...jobs.client,
    createStudioProductPhoto: async () => ok({
      status: 'review_required', project_id: 'project_1', image_run_id: 'run_product',
      quality_report: quality, routing: {},
      presentation: { preset: 'catalog_white', framing: 'square',
        source_asset_id: 'candidate_1', design_version: 1 },
      warning_candidate: { run_id: 'run_product', candidate_id: 'candidate_product',
        preview_url: 'https://test/product.png', qa: quality,
        operation: 'VISUAL_ONLY_EDIT', requested_change: 'Product photo', asset_capability: 'CLIENT_PRODUCT_PHOTO' },
    }, 202),
    getProject: async () => ok(current),
    discardPresentationCandidate: async (_runId: string, candidateId: string) => ok({
      status: 'discarded' as const, project_id: 'project_1', source_asset_id: 'candidate_1',
      source_design_version: 1, candidate_id: candidateId,
    }),
  } as any, { trackJobs: true });

  await gateway.createProductPresentation('project_1', {
    created_by: 'designer_1', expected_asset_id: 'candidate_1', expected_design_version: 1,
    preset: 'catalog_white', framing: 'square', presentation_only: true,
  });
  const transitionsBeforeDecision = jobs.transitions.length;
  const result = await gateway.discardPresentationCandidate({
    candidateId: 'candidate_product', createdBy: 'designer_1',
  });
  assert.equal(result.error, null);
  assert.equal(jobs.cancellations.length, 0);
  assert.equal(jobs.transitions.length, transitionsBeforeDecision);
  assert.equal(jobs.transitions.some((call) => call.request.completed_outputs), false);
});

test('exact presentation decision errors leave the durable reviewing job untouched', async () => {
  const jobs = tracking();
  const current = project(1);
  const gateway = createStudioGateway({
    ...jobs.client,
    createStudioProductPhoto: async () => ok({
      status: 'review_required', project_id: 'project_1', image_run_id: 'run_product_error',
      quality_report: quality, routing: {}, presentation: {
        preset: 'catalog_white', framing: 'square', source_asset_id: 'candidate_1', design_version: 1,
      }, warning_candidate: {
        run_id: 'run_product_error', candidate_id: 'candidate_product_error',
        preview_url: 'https://test/product-error.png', qa: quality,
        operation: 'VISUAL_ONLY_EDIT', requested_change: 'Product photo',
        asset_capability: 'CLIENT_PRODUCT_PHOTO',
      },
    }, 202),
    getProject: async () => ok(current),
    acceptPresentationCandidate: async () => ({
      data: null,
      error: { code: 'STALE_PRESENTATION_SOURCE', message: 'stale', category: 'conflict' as const,
        status: 409, retryable: false },
      status: 409,
    }),
  } as any, { trackJobs: true });
  await gateway.createProductPresentation('project_1', {
    created_by: 'designer_1', expected_asset_id: 'candidate_1', expected_design_version: 1,
    preset: 'catalog_white', framing: 'square', presentation_only: true,
  });
  const transitionsBeforeDecision = jobs.transitions.length;
  const result = await gateway.acceptPresentationCandidate({
    candidateId: 'candidate_product_error', createdBy: 'designer_1',
  });
  assert.equal(result.error?.code, 'STALE_PRESENTATION_SOURCE');
  assert.equal(jobs.transitions.length, transitionsBeforeDecision);
  assert.equal(jobs.transitions.some((call) => call.request.status === 'failed'), false);
});
