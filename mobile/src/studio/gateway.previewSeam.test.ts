import assert from 'node:assert/strict';
import test from 'node:test';

import type {
  ApiResult,
  DesignFamilyDetail,
  ImageQualityReport,
  ProjectDetail,
  StudioJobRecord,
  StudioPreviewCandidate,
  StudioPreviewCandidateDecisionResult,
} from '../trusted/types';
import { createStudioGateway, ExactStudioLineage, StudioVisualLineage } from './gateway';

const ok = <T>(data: T, status = 200): ApiResult<T> => ({ data, error: null, status });

const qa: ImageQualityReport = {
  verdict: 'pass', accepted: true, review_required: false, score: 0.99,
  summary: 'Exact source geometry retained.', failed_checks: [], warnings: [],
  checks: [{
    key: 'geometry', label: 'Geometry', verdict: 'pass', severity: 'hard',
    message: 'Exact source geometry retained.',
  }],
};

const asset = (
  rootId: string,
  assetId: string,
  designVersion: number | null,
  parentAssetId: string | null = null,
) => ({
  asset_id: assetId, root_id: rootId, parent_asset_id: parentAssetId,
  capability: designVersion === null ? 'VISUAL_ONLY_EDIT' : 'SPEC_RENDER',
  provenance: 'studio', revision: parentAssetId === null ? 1 : 2,
  design_id: designVersion === null ? null : 'design_1', design_version: designVersion,
  region: null, instruction: null, drift: null, pinned: false,
  media_type: 'image/png', image_url: `https://facetta.test/assets/${assetId}/image`,
  created_by: 'designer_1', created_at: '2026-07-15T00:00:00Z',
  legacy_provenance: false,
});

const project = (
  rootId: string,
  activeAssetId: string,
  activeDesignVersion: number | null,
  sourceAssetId = activeAssetId,
  owner = 'designer_1',
): ProjectDetail => {
  const first = asset(rootId, sourceAssetId, activeDesignVersion === null ? null : 1);
  const active = sourceAssetId === activeAssetId
    ? first : asset(rootId, activeAssetId, activeDesignVersion, sourceAssetId);
  const assets = first === active ? [first] : [first, active];
  return {
    id: rootId, root_id: rootId, title: 'Studio design', collection: null, tags: [],
    owner, state: 'refining', design_id: activeDesignVersion === null ? null : 'design_1',
    spec: activeDesignVersion === null ? null : {}, active_asset_id: activeAssetId,
    active_design_version: activeDesignVersion, active_revision: active,
    pinned_revision: null, revisions: assets.map((entry, index) => ({
      revision: index + 1, asset: entry, spec_version: entry.design_version,
      spec_change: [], ignored_fields: [], qa: null, routing: null, created_at: null,
    })),
    assets, derived_assets: [], approval: null, factory_ready: false,
    factory_blockers: [], primary_revision_count: assets.length, has_factory_drawing: false,
    cover_asset_id: activeAssetId, created_at: null, updated_at: null,
  };
};

const job = (rootId: string, sourceAssetId: string): StudioJobRecord => ({
  job_id: `job_${rootId}`, owner: 'designer_1', action_id: 'refine',
  lane: 'trusted_structural', status: 'reviewing', progress: 0.9,
  active_design_id: rootId, source_revision_id: sourceAssetId,
  accepted_output_sha256: null, error_code: null,
  created_at: '2026-07-15T00:00:00Z', updated_at: '2026-07-15T00:00:00Z',
  billing: {
    requested_outputs: 1, credits_per_output: 20, estimated_credits: 20,
    completed_outputs: 0, charged_outputs: 0, charged_credits: 0,
    policy: 'Only accepted requested outputs are charged.',
  },
});

const candidate = (
  kind: StudioPreviewCandidate['kind'],
  rootId: string,
  sourceAssetId: string,
  designVersion: number | null,
): StudioPreviewCandidate => ({
  candidate_id: `candidate_${kind}`,
  kind,
  status: 'reviewing',
  image_run_id: `run_${kind}`,
  project_root_id: rootId,
  source_asset_id: sourceAssetId,
  expected_active_asset_id: sourceAssetId,
  expected_design_version: designVersion,
  source_sha256: 'a'.repeat(64), output_sha256: 'b'.repeat(64),
  requested_change: 'preserve everything outside the selected change',
  verdict: 'pass', qa, studio_job_id: `job_${rootId}`, terminal_asset_id: null,
  created_at: '2026-07-15T00:00:00Z', expires_at: '2026-07-15T01:00:00Z',
  resolved_at: null, available_decisions: ['apply', 'save_as_variation', 'discard'],
  preview_url: `https://facetta.test/studio/preview-candidates/candidate_${kind}/image?owner=designer_1`,
  decision_url: `https://facetta.test/studio/preview-candidates/candidate_${kind}/decision`,
  ...(kind === 'visual'
    ? { scope: 'appearance' as const }
    : kind === 'catalog_revision'
      ? { component_path: 'metal.material' as const, option_id: 'platinum', spec_change: [], next_spec: {} }
      : { operation: 'change_prongs', region_description: 'center setting' }),
} as StudioPreviewCandidate);

const family = (
  lineage: ExactStudioLineage | StudioVisualLineage,
  resolution: Extract<StudioPreviewCandidateDecisionResult, { status: 'saved_as_variation' }>,
  overrides: Partial<DesignFamilyDetail['variations'][number]> = {},
): DesignFamilyDetail => ({
  family_id: resolution.family_id,
  owner: 'designer_1',
  title: 'Studio design family',
  created_at: '2026-07-15T00:00:00Z',
  updated_at: '2026-07-15T00:00:00Z',
  variations: [{
    root_id: resolution.result_project_id,
    title: 'Variation',
    collection: '',
    tags: [],
    owner: 'designer_1',
    counts: {},
    item_count: 1,
    primary_revision_count: 1,
    has_factory_drawing: false,
    cover_asset_id: resolution.terminal_asset_id,
    created_at: '2026-07-15T00:00:00Z',
    updated_at: '2026-07-15T00:00:00Z',
    variation_index: resolution.variation_index,
    variation_label: 'Variation',
    branched_from_project_root_id: lineage.projectId,
    branched_from_asset_id: lineage.sourceAssetId,
    ...overrides,
  }],
});

const baseClient = (
  lineage: ExactStudioLineage | StudioVisualLineage,
  normalized: StudioPreviewCandidate,
  resolution: StudioPreviewCandidateDecisionResult,
  getProject: (projectId: string) => Promise<ApiResult<ProjectDetail>>,
  options: {
    candidates?: StudioPreviewCandidate[];
    getDesignFamily?: (familyId: string) => Promise<ApiResult<DesignFamilyDetail>>;
    onDecision?: () => void;
  } = {},
) => ({
  listStudioJobs: async () => ok({ jobs: [job(lineage.projectId, lineage.sourceAssetId)] }),
  listStudioPreviewCandidates: async (projectId: string, owner: string) => {
    assert.equal(projectId, lineage.projectId);
    assert.equal(owner, 'designer_1');
    return ok({ candidates: options.candidates ?? [normalized] });
  },
  decideStudioPreviewCandidate: async (candidateId: string, request: Record<string, unknown>) => {
    options.onDecision?.();
    assert.equal(candidateId, normalized.candidate_id);
    assert.equal(request.created_by, 'designer_1');
    assert.equal(request.expected_active_asset_id, lineage.sourceAssetId);
    assert.equal(request.expected_design_version,
      'sourceDesignVersion' in lineage ? lineage.sourceDesignVersion : null);
    return ok(resolution);
  },
  getProject,
  getDesignFamily: options.getDesignFamily ?? (async (familyId: string) => {
    if (resolution.status !== 'saved_as_variation') {
      throw new Error('family lookup must only follow a variation decision');
    }
    assert.equal(familyId, resolution.family_id);
    return ok(family(lineage, resolution));
  }),
  listVisualPreviews: async () => { throw new Error('legacy visual list used'); },
  listCatalogPreviews: async () => { throw new Error('legacy catalog list used'); },
  listStudioMarkupCandidates: async () => { throw new Error('legacy markup list used'); },
  acceptVisualPreview: async () => { throw new Error('legacy visual decision used'); },
  saveCatalogPreviewAsVariation: async () => { throw new Error('legacy catalog decision used'); },
  discardStudioMarkupCandidate: async () => { throw new Error('legacy markup decision used'); },
});

test('active Studio review uses one normalized seam for visual Apply', async () => {
  const lineage: StudioVisualLineage = {
    projectId: 'visual_project', sourceAssetId: 'visual_source',
  };
  const normalized = candidate('visual', lineage.projectId, lineage.sourceAssetId, null);
  const resolution: StudioPreviewCandidateDecisionResult = {
    status: 'applied', candidate_id: normalized.candidate_id, kind: 'visual',
    source_project_id: lineage.projectId, result_project_id: lineage.projectId,
    terminal_asset_id: 'visual_applied', studio_job_id: 'job_visual_project',
    family_id: null, variation_index: null,
  };
  const client = baseClient(
    lineage, normalized, resolution,
    async () => ok(project(lineage.projectId, 'visual_applied', null, lineage.sourceAssetId)),
  );
  const gateway = createStudioGateway(client as never);
  const resumed = await gateway.resumeRefine(lineage, 'designer_1');
  assert.equal(resumed.data?.kind, 'visual');
  assert.deepEqual(resumed.data?.intent, {
    kind: 'describe',
    instruction: 'preserve everything outside the selected change',
    scope: 'appearance',
  });
  const applied = await gateway.applyVisualRefine({
    candidateId: normalized.candidate_id, createdBy: 'designer_1',
  });
  assert.equal(applied.error, null);
  assert.equal(applied.data?.candidate.canonicalRevisionId, 'visual_applied');
});

test('active Studio review uses one normalized seam for catalog Save as Variation', async () => {
  const lineage: ExactStudioLineage = {
    projectId: 'catalog_project', sourceAssetId: 'catalog_source', sourceDesignVersion: 1,
  };
  const normalized = candidate('catalog_revision', lineage.projectId, lineage.sourceAssetId, 1);
  const resolution: StudioPreviewCandidateDecisionResult = {
    status: 'saved_as_variation', candidate_id: normalized.candidate_id,
    kind: 'catalog_revision', source_project_id: lineage.projectId,
    result_project_id: 'catalog_variation', terminal_asset_id: 'catalog_variation_asset',
    studio_job_id: 'job_catalog_project', family_id: 'family_1', variation_index: 2,
  };
  const client = baseClient(lineage, normalized, resolution, async (projectId: string) => (
    projectId === lineage.projectId
      ? ok(project(lineage.projectId, lineage.sourceAssetId, 1))
      : ok(project('catalog_variation', 'catalog_variation_asset', 1))
  ));
  const gateway = createStudioGateway(client as never);
  const resumed = await gateway.resumeRefine(lineage, 'designer_1');
  assert.equal(resumed.data?.kind, 'catalog');
  assert.deepEqual(resumed.data?.intent, {
    kind: 'component', componentPath: 'metal.material', optionId: 'platinum',
    requestedChange: 'preserve everything outside the selected change',
  });
  const saved = await gateway.saveCatalogPreviewAsVariation({
    candidateId: normalized.candidate_id, createdBy: 'designer_1', label: 'Platinum direction',
  });
  assert.equal(saved.error, null);
  assert.equal(saved.data?.familyId, 'family_1');
  assert.equal(saved.data?.variationIndex, 2);
});

test('active Studio review uses one normalized seam for markup Discard', async () => {
  const lineage: ExactStudioLineage = {
    projectId: 'markup_project', sourceAssetId: 'markup_source', sourceDesignVersion: 1,
  };
  const normalized = candidate('markup', lineage.projectId, lineage.sourceAssetId, 1);
  const resolution: StudioPreviewCandidateDecisionResult = {
    status: 'discarded', candidate_id: normalized.candidate_id, kind: 'markup',
    source_project_id: lineage.projectId, result_project_id: lineage.projectId,
    terminal_asset_id: null, studio_job_id: 'job_markup_project',
    family_id: null, variation_index: null,
  };
  const client = baseClient(
    lineage, normalized, resolution,
    async () => { throw new Error('discard must not load a changed project'); },
  );
  const gateway = createStudioGateway(client as never);
  const resumed = await gateway.resumeRefine(lineage, 'designer_1');
  assert.equal(resumed.data?.kind, 'markup');
  assert.deepEqual(resumed.data?.intent, {
    kind: 'markup', requestedChange: 'preserve everything outside the selected change',
    regionDescription: 'center setting', impact: 'specification',
  });
  const discarded = await gateway.discardMarkupRefine({
    candidateId: normalized.candidate_id, createdBy: 'designer_1',
  });
  assert.equal(discarded.error, null);
  assert.equal(discarded.data?.candidate.status, 'discarded');
  assert.equal(discarded.data?.project, null);
});

test('Activity resume preserves an exact Describe request represented by the markup authority', async () => {
  const lineage: ExactStudioLineage = {
    projectId: 'describe_project', sourceAssetId: 'describe_source', sourceDesignVersion: 1,
  };
  const normalized = {
    ...candidate('markup', lineage.projectId, lineage.sourceAssetId, 1),
    operation: 'VISUAL_ONLY_EDIT' as const,
    requested_change: 'Warm the metal reflection',
    region_description: 'entire visible jewelry presentation',
  };
  const resolution: StudioPreviewCandidateDecisionResult = {
    status: 'discarded', candidate_id: normalized.candidate_id, kind: 'markup',
    source_project_id: lineage.projectId, result_project_id: lineage.projectId,
    terminal_asset_id: null, studio_job_id: 'job_describe_project',
    family_id: null, variation_index: null,
  };
  const gateway = createStudioGateway(baseClient(
    lineage,
    normalized,
    resolution,
    async () => { throw new Error('resume must not load a changed project'); },
  ) as never);

  const resumed = await gateway.resumeRefine(lineage, 'designer_1');

  assert.deepEqual(resumed.data?.intent, {
    kind: 'describe', instruction: 'Warm the metal reflection', scope: 'appearance',
  });
});

test('resume fails closed when one Refine output has multiple exact candidates', async () => {
  const lineage: StudioVisualLineage = {
    projectId: 'ambiguous_project', sourceAssetId: 'ambiguous_source',
  };
  const normalized = candidate('visual', lineage.projectId, lineage.sourceAssetId, null);
  const duplicate = {
    ...normalized,
    candidate_id: 'candidate_visual_duplicate',
    preview_url: 'https://facetta.test/studio/preview-candidates/candidate_visual_duplicate/image?owner=designer_1',
    decision_url: 'https://facetta.test/studio/preview-candidates/candidate_visual_duplicate/decision',
  };
  const resolution: StudioPreviewCandidateDecisionResult = {
    status: 'discarded', candidate_id: normalized.candidate_id, kind: 'visual',
    source_project_id: lineage.projectId, result_project_id: lineage.projectId,
    terminal_asset_id: null, studio_job_id: 'job_ambiguous_project',
    family_id: null, variation_index: null,
  };
  const client = baseClient(
    lineage, normalized, resolution,
    async () => { throw new Error('ambiguous resume must not load a project'); },
    { candidates: [normalized, duplicate] },
  );
  const gateway = createStudioGateway(client as never);
  const resumed = await gateway.resumeRefine(lineage, 'designer_1');
  assert.equal(resumed.error?.code, 'AMBIGUOUS_REFINE_PREVIEW');
  assert.equal(resumed.data, null);
});

test('Apply rejects a result project owned by another principal', async () => {
  const lineage: StudioVisualLineage = {
    projectId: 'owner_project', sourceAssetId: 'owner_source',
  };
  const normalized = candidate('visual', lineage.projectId, lineage.sourceAssetId, null);
  const resolution: StudioPreviewCandidateDecisionResult = {
    status: 'applied', candidate_id: normalized.candidate_id, kind: 'visual',
    source_project_id: lineage.projectId, result_project_id: lineage.projectId,
    terminal_asset_id: 'owner_applied', studio_job_id: 'job_owner_project',
    family_id: null, variation_index: null,
  };
  const client = baseClient(
    lineage, normalized, resolution,
    async () => ok(project(
      lineage.projectId, 'owner_applied', null, lineage.sourceAssetId, 'another_designer',
    )),
  );
  const gateway = createStudioGateway(client as never);
  assert.equal((await gateway.resumeRefine(lineage, 'designer_1')).error, null);
  const applied = await gateway.applyVisualRefine({
    candidateId: normalized.candidate_id, createdBy: 'designer_1',
  });
  assert.equal(applied.error?.code, 'INVALID_PREVIEW_RESULT_PROJECT');
  assert.equal(applied.data, null);
});

test('variation decisions reject false family membership and branch lineage', async (context) => {
  const lineage: ExactStudioLineage = {
    projectId: 'family_project', sourceAssetId: 'family_source', sourceDesignVersion: 1,
  };
  const normalized = candidate('catalog_revision', lineage.projectId, lineage.sourceAssetId, 1);
  const resolution: Extract<
    StudioPreviewCandidateDecisionResult, { status: 'saved_as_variation' }
  > = {
    status: 'saved_as_variation', candidate_id: normalized.candidate_id,
    kind: 'catalog_revision', source_project_id: lineage.projectId,
    result_project_id: 'family_variation', terminal_asset_id: 'family_variation_asset',
    studio_job_id: 'job_family_project', family_id: 'family_1', variation_index: 2,
  };
  const cases: Array<{
    name: string;
    overrides: Partial<DesignFamilyDetail['variations'][number]>;
    familyId?: string;
  }> = [
    { name: 'returned family id does not match the loaded family', overrides: {}, familyId: 'other_family' },
    { name: 'returned variation index is not a family member', overrides: { variation_index: 3 } },
    { name: 'family branch points at another source revision', overrides: { branched_from_asset_id: 'other_source' } },
  ];
  for (const entry of cases) {
    await context.test(entry.name, async () => {
      const client = baseClient(
        lineage,
        normalized,
        resolution,
        async (projectId: string) => projectId === lineage.projectId
          ? ok(project(lineage.projectId, lineage.sourceAssetId, 1))
          : ok(project('family_variation', 'family_variation_asset', 1)),
        {
          getDesignFamily: async () => ok({
            ...family(lineage, resolution, entry.overrides),
            family_id: entry.familyId ?? resolution.family_id,
          }),
        },
      );
      const gateway = createStudioGateway(client as never);
      assert.equal((await gateway.resumeRefine(lineage, 'designer_1')).error, null);
      const saved = await gateway.saveCatalogPreviewAsVariation({
        candidateId: normalized.candidate_id,
        createdBy: 'designer_1',
        label: 'Family direction',
      });
      assert.equal(saved.error?.code, 'INVALID_PREVIEW_VARIATION_LINEAGE');
      assert.equal(saved.data, null);
    });
  }
});

test('a normalized decision cannot be replayed through the in-session gateway', async () => {
  const lineage: ExactStudioLineage = {
    projectId: 'replay_project', sourceAssetId: 'replay_source', sourceDesignVersion: 1,
  };
  const normalized = candidate('markup', lineage.projectId, lineage.sourceAssetId, 1);
  const resolution: StudioPreviewCandidateDecisionResult = {
    status: 'discarded', candidate_id: normalized.candidate_id, kind: 'markup',
    source_project_id: lineage.projectId, result_project_id: lineage.projectId,
    terminal_asset_id: null, studio_job_id: 'job_replay_project',
    family_id: null, variation_index: null,
  };
  let decisions = 0;
  const client = baseClient(
    lineage, normalized, resolution,
    async () => { throw new Error('discard replay must not load a project'); },
    { onDecision: () => { decisions += 1; } },
  );
  const gateway = createStudioGateway(client as never);
  assert.equal((await gateway.resumeRefine(lineage, 'designer_1')).error, null);
  const request = { candidateId: normalized.candidate_id, createdBy: 'designer_1' };
  assert.equal((await gateway.discardMarkupRefine(request)).error, null);
  assert.equal((await gateway.discardMarkupRefine(request)).error?.code, 'CANDIDATE_NOT_REVIEWABLE');
  assert.equal(decisions, 1);
});
