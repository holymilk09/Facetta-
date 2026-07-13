/**
 * Real client-to-API Studio acceptance.
 *
 * This process imports the production trusted client/gateway and talks over
 * HTTP to a separately running uvicorn process. The deterministic matrix
 * covers sentence and mixed image starts without entering Factory, and proves
 * that preview work remains temporary until a designer explicitly accepts it.
 */

import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';

import { createStudioGateway } from '../src/studio/gateway';
import { createTrustedApiClient } from '../src/trusted/client';
import type {
  CreativeRoleReferenceRequest,
  CreativeSourceKind,
  JsonObject,
  ProjectDetail,
} from '../src/trusted/types';

const baseUrl = process.argv[2];
assert(baseUrl, 'usage: tsx scripts/studio_client_api_acceptance.ts BASE_URL');

const actor = 'usr_client_api_acceptance';
const failedQaActor = 'usr_failed_qa_acceptance';
const structuralActor = 'usr_structural_api_acceptance';
const FAILED_QA_FIXTURE_PROMPT = '__FACETTA_ACCEPTANCE_FORCE_QA_FAIL__';
const trustedClient = createTrustedApiClient({ baseUrl });
const gateway = createStudioGateway(trustedClient, { trackJobs: true });

const SOURCE_PNG = 'iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAIAAACQkWg2AAAAIklEQVR4nGPMq2hiIAUwkaSaYVQDcYCJSHVwMKqBGECyBgB/6AGI9C+U8AAAAABJRU5ErkJggg==';

type ReferenceRole = CreativeRoleReferenceRequest['role'];

interface AcceptanceCase {
  id: string;
  start: 'sentence' | 'image';
  instruction: string;
  sourceKind: CreativeSourceKind | null;
  directionCount: 1 | 2 | 3 | 4;
  references?: readonly ReferenceRole[];
}

interface AcceptanceResult {
  id: string;
  projectId: string;
  variationProjectId: string;
  sourceKind: CreativeSourceKind | null;
  referenceRoles: readonly ReferenceRole[];
  directionCount: number;
  canonicalRevisionCount: number;
  staleApplyRejected: boolean;
}

interface AcceptanceCanonicalState {
  projects: number;
  image_assets: number;
  revision_records: number;
  designs: number;
  design_versions: number;
  accepted_image_reviews: number;
  failed_image_runs: number;
  charged_outputs: number;
  completed_outputs: number;
}

interface ConfirmedRingFixture {
  image_base64: string;
  media_type: 'image/png';
  confirmed_spec: JsonObject;
}

interface StructuralCutAcceptanceResult {
  projectId: string;
  sourceAssetId: string;
  acceptedAssetId: string;
  sourceDesignVersion: 1;
  acceptedDesignVersion: 2;
  previewWasTemporary: true;
  canonicalRevisionCountBeforeApply: 1;
  canonicalRevisionCountAfterApply: 2;
  chargedOutputs: 1;
}

const CASES: readonly AcceptanceCase[] = [
  {
    id: 'sentence-minimal-signet', start: 'sentence', sourceKind: null, directionCount: 1,
    instruction: 'A restrained oval signet ring with a low polished bezel.',
  },
  {
    id: 'sentence-sculptural-band', start: 'sentence', sourceKind: null, directionCount: 4,
    instruction: 'A sculptural fine-jewelry band with one calm architectural fold.',
  },
  {
    id: 'drawing-front-view', start: 'image', sourceKind: 'drawing', directionCount: 2,
    instruction: 'Preserve every drawn contour and propose two restrained visual directions.',
  },
  {
    id: 'drawing-annotated', start: 'image', sourceKind: 'drawing', directionCount: 3,
    instruction: 'Treat the drawing as master geometry and preserve its asymmetric shoulder.',
  },
  {
    id: 'photograph-signet', start: 'image', sourceKind: 'photograph', directionCount: 2,
    instruction: 'Preserve this photographed signet silhouette and create restrained directions.',
  },
  {
    id: 'photograph-heirloom', start: 'image', sourceKind: 'photograph', directionCount: 1,
    instruction: 'Preserve the photographed heirloom geometry while cleaning only its presentation.',
  },
  {
    id: 'finished-render-white-gold', start: 'image', sourceKind: 'finished_render', directionCount: 3,
    instruction: 'Keep the finished render geometry exact and explore subtle surface directions.',
  },
  {
    id: 'finished-render-yellow-gold', start: 'image', sourceKind: 'finished_render', directionCount: 2,
    instruction: 'Use this finished render as exact geometry and preserve its stone layout.',
  },
  {
    id: 'references-all-roles', start: 'image', sourceKind: 'drawing', directionCount: 4,
    instruction: 'Keep master geometry exact and use each secondary reference only for its labeled role.',
    references: ['material_style', 'construction_detail', 'brand_direction'],
  },
  {
    id: 'references-material-brand', start: 'image', sourceKind: 'finished_render', directionCount: 2,
    instruction: 'Preserve the render exactly; apply material and brand references only as advisory direction.',
    references: ['material_style', 'brand_direction'],
  },
];

const ROLE_ASSET: Readonly<Record<ReferenceRole, { capability: string; provenance: string }>> = {
  material_style: {
    capability: 'CREATIVE_REFERENCE_MATERIAL_STYLE',
    provenance: 'material_style_reference',
  },
  construction_detail: {
    capability: 'CREATIVE_REFERENCE_CONSTRUCTION_DETAIL',
    provenance: 'construction_detail_reference',
  },
  brand_direction: {
    capability: 'CREATIVE_REFERENCE_BRAND_DIRECTION',
    provenance: 'brand_direction_reference',
  },
};

function value<T>(result: { data: T | null; error: unknown; status: number }, step: string): T {
  assert.equal(result.error, null, `${step} failed: ${JSON.stringify(result.error)}`);
  assert.notEqual(result.data, null, `${step} returned no data`);
  return result.data as T;
}

async function sha256(url: string): Promise<string> {
  const response = await fetch(url);
  assert.equal(response.status, 200, `image read failed for ${url}`);
  return createHash('sha256').update(Buffer.from(await response.arrayBuffer())).digest('hex');
}

function references(roles: readonly ReferenceRole[]): CreativeRoleReferenceRequest[] {
  return roles.map((role) => ({ role, image_base64: SOURCE_PNG, media_type: 'image/png' }));
}

function assertSourceKind(project: ProjectDetail, expected: CreativeSourceKind | null, step: string): void {
  assert.equal(project.active_revision?.source_kind ?? null, expected, `${step} lost source_kind`);
}

function assertReferencePersistence(project: ProjectDetail, roles: readonly ReferenceRole[]): void {
  for (const role of roles) {
    const expected = ROLE_ASSET[role];
    const asset = project.assets.find((item) => item.capability === expected.capability);
    assert(asset, `${role} reference was not persisted as a canonical asset`);
    assert.equal(asset.provenance, expected.provenance, `${role} reference provenance changed`);
    assert.equal(asset.parent_asset_id, project.root_id, `${role} reference lost master lineage`);
  }
  if (roles.length > 0) {
    const board = project.assets.find((item) => item.capability === 'CREATIVE_REFERENCE_BOARD');
    assert(board, 'role-labeled reference board was not persisted');
    assert.equal(board.provenance, 'role_labeled_reference_board');
    assert.equal(board.parent_asset_id, project.root_id);
  }
}

async function canonicalState(owner: string): Promise<AcceptanceCanonicalState> {
  const response = await fetch(
    `${baseUrl}/__acceptance__/canonical-state/${encodeURIComponent(owner)}`,
  );
  assert.equal(response.status, 200, 'acceptance state probe failed');
  return await response.json() as AcceptanceCanonicalState;
}

async function confirmedRingFixture(): Promise<ConfirmedRingFixture> {
  const response = await fetch(`${baseUrl}/__acceptance__/confirmed-ring-fixture`);
  assert.equal(response.status, 200, 'confirmed-ring acceptance fixture failed');
  return await response.json() as ConfirmedRingFixture;
}

async function runStructuralCutCase(): Promise<StructuralCutAcceptanceResult> {
  assert.deepEqual(await canonicalState(structuralActor), {
    projects: 0,
    image_assets: 0,
    revision_records: 0,
    designs: 0,
    design_versions: 0,
    accepted_image_reviews: 0,
    failed_image_runs: 0,
    charged_outputs: 0,
    completed_outputs: 0,
  }, 'structural fixture owner did not start isolated');

  const fixture = await confirmedRingFixture();
  const imported = value(await trustedClient.createProjectFromImage({
    image_base64: fixture.image_base64,
    media_type: fixture.media_type,
    confirmed_spec: fixture.confirmed_spec,
    owner: structuralActor,
    title: 'Acceptance: confirmed ring stone-cut refinement',
    collection: 'Studio structural acceptance',
    tags: ['client-api', 'structural', 'stone-cut', 'no-factory'],
  }), 'Structural: import designer-confirmed ring');
  assert.equal(imported.active_design_version, 1);
  assert(imported.active_revision);
  const sourceAssetId = imported.active_asset_id;
  assert(sourceAssetId);
  assert.equal(imported.active_revision.asset_id, imported.active_asset_id);
  assert.equal(imported.active_revision.design_version, 1);
  assert.equal((imported.spec?.stone as JsonObject | undefined)?.cut, 'oval_brilliant');
  assert.equal(imported.factory_ready, false);

  const canonicalAfterImport = await canonicalState(structuralActor);
  assert.deepEqual(canonicalAfterImport, {
    projects: 1,
    image_assets: 1,
    revision_records: 0,
    designs: 1,
    design_versions: 1,
    accepted_image_reviews: 0,
    failed_image_runs: 0,
    charged_outputs: 0,
    completed_outputs: 0,
  }, 'confirmed import did not establish exactly one canonical revision');

  const beforeMap = value(
    await gateway.getStudioComponentTargeting(sourceAssetId),
    'Structural: read unmapped source targeting',
  );
  assert.equal(beforeMap.component_map.state, 'unmapped');
  assert.equal(
    beforeMap.catalog_paths.find((path) => path.component_path === 'stone.cut')?.status,
    'unmapped',
  );

  const prepared = value(
    await gateway.prepareStudioComponentMap(sourceAssetId),
    'Structural: prepare exact source map',
  );
  assert.equal(prepared.component_map.state, 'ready');
  assert.equal(prepared.component_map.mapper_contract, 'facetta.grok-ring-component-map.v1');
  const cutTargeting = prepared.catalog_paths.find(
    (path) => path.component_path === 'stone.cut',
  );
  assert(cutTargeting, 'stone.cut targeting was omitted after source mapping');
  assert.equal(cutTargeting.status, 'ready');
  assert.deepEqual(cutTargeting.required_component_kinds, [
    'center_stone', 'prongs', 'setting',
  ]);

  const cutCatalog = value(
    await gateway.getComponentCatalog('stone.cut'),
    'Structural: load stone-cut catalog',
  );
  assert(cutCatalog.options.some((option) => option.id === 'emerald_cut'));

  const sourceHistory = value(
    await gateway.getStudioProjectHistory(imported.root_id),
    'Structural: history before preview',
  );
  assert.equal(sourceHistory.revisions.length, 1);
  assert.equal(sourceHistory.active_asset_id, sourceAssetId);
  const sourceHash = await sha256(imported.active_revision.image_url!);

  const preview = value(await gateway.previewCatalogRefine({
    projectId: imported.root_id,
    sourceAssetId,
    sourceDesignVersion: 1,
    createdBy: structuralActor,
    componentPath: 'stone.cut',
    optionId: 'emerald_cut',
    variant: 17,
  }), 'Structural: preview stone-cut change');
  assert.equal(preview.componentPath, 'stone.cut');
  assert.equal(preview.optionId, 'emerald_cut');
  assert.deepEqual(preview.lineage, {
    projectId: imported.root_id,
    sourceAssetId,
    sourceDesignVersion: 1,
  });
  assert.equal(preview.candidate.temporary, true);
  assert.equal(preview.candidate.status, 'pending_review');
  assert.equal(preview.candidate.verdict, 'pass');
  assert.notEqual(await sha256(preview.candidate.assetUrl), sourceHash);

  const historyDuringReview = value(
    await gateway.getStudioProjectHistory(imported.root_id),
    'Structural: history while preview is temporary',
  );
  assert.equal(historyDuringReview.revisions.length, 1);
  assert.equal(historyDuringReview.active_asset_id, sourceAssetId);
  const reopenedDuringReview = value(
    await gateway.getProject(imported.root_id),
    'Structural: reopen before Apply',
  );
  assert.equal(reopenedDuringReview.active_asset_id, sourceAssetId);
  assert.equal(reopenedDuringReview.active_design_version, 1);
  assert.equal(
    (reopenedDuringReview.spec?.stone as JsonObject | undefined)?.cut,
    'oval_brilliant',
  );
  assert.equal(await sha256(reopenedDuringReview.active_revision!.image_url!), sourceHash);
  assert.deepEqual(
    await canonicalState(structuralActor),
    canonicalAfterImport,
    'temporary structural preview mutated or charged canonical truth',
  );

  const reviewingActivity = value(
    await gateway.listStudioJobs(structuralActor),
    'Structural: reviewing Activity',
  );
  assert.equal(reviewingActivity.jobs.length, 1);
  const reviewingJob = reviewingActivity.jobs[0];
  assert(reviewingJob);
  assert.equal(reviewingJob.action_id, 'refine');
  assert.equal(reviewingJob.lane, 'trusted_structural');
  assert.equal(reviewingJob.status, 'reviewing');
  assert.equal(reviewingJob.source_revision_id, sourceAssetId);
  assert.equal(reviewingJob.billing.completed_outputs, 0);
  assert.equal(reviewingJob.billing.charged_outputs, 0);
  assert.equal(reviewingJob.billing.charged_credits, 0);

  const applied = value(await gateway.applyCatalogRefine({
    candidateId: preview.candidate.id,
    createdBy: structuralActor,
  }), 'Structural: Apply stone-cut preview');
  assert.equal(applied.candidate.status, 'applied');
  const acceptedAssetId = applied.candidate.canonicalRevisionId;
  assert(acceptedAssetId);
  assert(applied.project);
  assert.equal(applied.project.active_asset_id, acceptedAssetId);
  assert.equal(applied.project.active_design_version, 2);
  assert.equal((applied.project.spec?.stone as JsonObject | undefined)?.cut, 'emerald_cut');

  const acceptedHistory = value(
    await gateway.getStudioProjectHistory(imported.root_id),
    'Structural: reopen accepted history',
  );
  assert.equal(acceptedHistory.revisions.length, 2);
  assert.equal(acceptedHistory.active_asset_id, acceptedAssetId);
  assert.equal(acceptedHistory.revisions[1]?.parent_asset_id, sourceAssetId);
  assert.equal(acceptedHistory.revisions[1]?.design_version, 2);
  const reopenedAccepted = value(
    await gateway.getProject(imported.root_id),
    'Structural: reopen accepted project',
  );
  assert.equal(reopenedAccepted.active_asset_id, acceptedAssetId);
  assert.equal(reopenedAccepted.active_design_version, 2);
  assert.equal((reopenedAccepted.spec?.stone as JsonObject | undefined)?.cut, 'emerald_cut');
  assert.notEqual(await sha256(reopenedAccepted.active_revision!.image_url!), sourceHash);

  assert.deepEqual(await canonicalState(structuralActor), {
    projects: 1,
    image_assets: 2,
    revision_records: 1,
    designs: 1,
    design_versions: 2,
    accepted_image_reviews: 1,
    failed_image_runs: 0,
    charged_outputs: 1,
    completed_outputs: 1,
  }, 'Apply did not settle exactly one charged canonical revision');

  const settledActivity = value(
    await gateway.listStudioJobs(structuralActor),
    'Structural: settled Activity',
  );
  assert.equal(settledActivity.jobs.length, 1);
  const settledJob = settledActivity.jobs[0];
  assert(settledJob);
  assert.equal(settledJob.status, 'succeeded');
  assert.equal(settledJob.billing.completed_outputs, 1);
  assert.equal(settledJob.billing.charged_outputs, 1);
  assert(settledJob.billing.charged_credits > 0);

  return {
    projectId: imported.root_id,
    sourceAssetId,
    acceptedAssetId,
    sourceDesignVersion: 1,
    acceptedDesignVersion: 2,
    previewWasTemporary: true,
    canonicalRevisionCountBeforeApply: 1,
    canonicalRevisionCountAfterApply: 2,
    chargedOutputs: 1,
  };
}

async function runFailedQaCase(): Promise<void> {
  assert.deepEqual(await canonicalState(failedQaActor), {
    projects: 0,
    image_assets: 0,
    revision_records: 0,
    designs: 0,
    design_versions: 0,
    accepted_image_reviews: 0,
    failed_image_runs: 0,
    charged_outputs: 0,
    completed_outputs: 0,
  }, 'failed-QA fixture owner did not start isolated');

  const rejected = await gateway.createFromPrompt({
    prompt: FAILED_QA_FIXTURE_PROMPT,
    variation_count: 1,
    starting_variant: 99,
    owner: failedQaActor,
    title: 'Acceptance: forced QA rejection',
    collection: 'Studio failed-QA acceptance',
    tags: ['client-api', 'failed-qa', 'no-canonical-output'],
  });
  assert.equal(rejected.data, null, 'failed QA returned a Studio project');
  assert.equal(rejected.status, 422);
  assert.equal(rejected.error?.code, 'image_quality_failed');
  assert.equal(rejected.error?.category, 'quality');

  assert.deepEqual(await canonicalState(failedQaActor), {
    projects: 0,
    image_assets: 0,
    revision_records: 0,
    designs: 0,
    design_versions: 0,
    accepted_image_reviews: 0,
    failed_image_runs: 1,
    charged_outputs: 0,
    completed_outputs: 0,
  }, 'failed QA persisted canonical design truth or a charged output');

  const activity = value(await gateway.listStudioJobs(failedQaActor), 'Failed-QA Activity');
  assert.equal(activity.jobs.length, 1);
  const failedCreate = activity.jobs[0];
  assert(failedCreate);
  assert.equal(failedCreate.action_id, 'create');
  assert.equal(failedCreate.status, 'failed');
  assert.equal(failedCreate.error_code, 'image_quality_failed');
  assert.equal(failedCreate.active_design_id, null);
  assert.equal(failedCreate.source_revision_id, null);
  assert.equal(failedCreate.billing.completed_outputs, 0);
  assert.equal(failedCreate.billing.charged_outputs, 0);
  assert.equal(failedCreate.billing.charged_credits, 0);
}

async function create(caseDefinition: AcceptanceCase, index: number): Promise<ProjectDetail> {
  const common = {
    variation_count: caseDefinition.directionCount,
    starting_variant: 5 + (index * 5),
    owner: actor,
    title: `Acceptance ${index + 1}: ${caseDefinition.id}`,
    collection: 'Studio mixed-source acceptance',
    tags: ['client-api', 'mixed-source', 'no-factory', caseDefinition.id],
  };
  if (caseDefinition.start === 'sentence') {
    return value(await gateway.createFromPrompt({
      prompt: caseDefinition.instruction,
      ...common,
    }), `${caseDefinition.id}: Create from sentence`);
  }
  assert(caseDefinition.sourceKind !== null);
  return value(await gateway.createFromDrawing({
    image_base64: SOURCE_PNG,
    media_type: 'image/png',
    source_kind: caseDefinition.sourceKind,
    instruction: caseDefinition.instruction,
    references: references(caseDefinition.references ?? []),
    ...common,
  }), `${caseDefinition.id}: Create from ${caseDefinition.sourceKind}`);
}

async function runCase(caseDefinition: AcceptanceCase, index: number): Promise<AcceptanceResult> {
  const label = caseDefinition.id;
  const created = await create(caseDefinition, index);
  assert.equal(created.revisions.length, 0, `${label}: directions became canonical before selection`);
  assert.equal(created.creative_candidates?.length, caseDefinition.directionCount);
  assert.equal(created.factory_ready, false);
  const candidates = created.creative_candidates ?? [];
  const chosenDirection = candidates[candidates.length - 1];
  assert(chosenDirection);
  assert.equal(
    new Set(candidates.map((candidate) => candidate.sha256)).size,
    candidates.length,
    `${label}: direction bytes are not mutually distinct`,
  );

  const selected = value(await gateway.selectCreativeDirection(
    created.root_id,
    chosenDirection.asset_id,
    actor,
  ), `${label}: Select and save direction`);
  assert.equal(selected.active_asset_id, chosenDirection.asset_id);
  assert.equal(selected.revisions.length, 1);
  assertSourceKind(selected, caseDefinition.sourceKind, `${label}: selected revision`);

  const reopened = value(await gateway.getProject(created.root_id), `${label}: Reopen project`);
  assert.equal(reopened.active_asset_id, chosenDirection.asset_id);
  assertSourceKind(reopened, caseDefinition.sourceKind, `${label}: reopened revision`);
  assertReferencePersistence(reopened, caseDefinition.references ?? []);

  const branch = value(await gateway.saveCurrentAsVariation({
    projectId: reopened.root_id,
    sourceAssetId: chosenDirection.asset_id,
    sourceDesignVersion: null,
    createdBy: actor,
    label: `${label} exploration`,
  }), `${label}: Branch exact selected revision`);
  assert.equal(branch.source_project_id, reopened.root_id);
  assert.equal(branch.source_asset_id, chosenDirection.asset_id);
  assert.notEqual(branch.project.root_id, reopened.root_id);
  assert.equal(branch.project.factory_ready, false);
  assert.equal(
    branch.project.selected_candidate_asset_id,
    branch.project.active_asset_id,
    `${label}: visual-only branch did not select its copied root`,
  );
  assertSourceKind(branch.project, caseDefinition.sourceKind, `${label}: variation branch`);

  const reopenedBranch = value(
    await gateway.getProject(branch.project.root_id),
    `${label}: Reopen variation`,
  );
  assert.equal(reopenedBranch.active_asset_id, branch.project.active_asset_id);
  assert.equal(reopenedBranch.selected_candidate_asset_id, reopenedBranch.active_asset_id);
  assertSourceKind(reopenedBranch, caseDefinition.sourceKind, `${label}: reopened variation`);
  assert.equal(
    await sha256(reopenedBranch.active_revision!.image_url!),
    await sha256(reopened.active_revision!.image_url!),
    `${label}: branch did not preserve exact selected bytes`,
  );

  const beforePreviewHistory = value(
    await gateway.getStudioProjectHistory(reopenedBranch.root_id),
    `${label}: History before preview`,
  );
  assert.equal(beforePreviewHistory.revisions.length, 1);
  const originalRevision = beforePreviewHistory.revisions[0];
  assert(originalRevision);
  assert.equal(
    beforePreviewHistory.active_asset_id,
    originalRevision.asset_id,
    `${label}: reopened history does not identify its active revision`,
  );

  const preview = value(await gateway.previewVisualRefine({
    projectId: reopenedBranch.root_id,
    sourceAssetId: originalRevision.asset_id,
    createdBy: actor,
    instruction: 'Warm the metal while preserving every contour and stone position.',
    scope: 'appearance',
    variant: 70 + index,
  }), `${label}: Refine preview`);
  assert.equal(preview.candidate.temporary, true);
  assert.equal(preview.candidate.status, 'pending_review');
  assert.equal(preview.lineage.sourceAssetId, originalRevision.asset_id);

  const whilePreviewHistory = value(
    await gateway.getStudioProjectHistory(reopenedBranch.root_id),
    `${label}: History while preview is temporary`,
  );
  assert.equal(whilePreviewHistory.revisions.length, 1, `${label}: preview mutated canonical history`);
  assert.equal(whilePreviewHistory.active_asset_id, originalRevision.asset_id);

  // Exercise a real stale-write race once across the matrix. Both previews
  // begin from the same immutable revision; the normal preview is accepted
  // first, so this second pending candidate must never overwrite it.
  let staleCandidateId: string | null = null;
  if (index === 0) {
    const stalePreview = value(await gateway.previewVisualRefine({
      projectId: reopenedBranch.root_id,
      sourceAssetId: originalRevision.asset_id,
      createdBy: actor,
      instruction: 'Cool the metal while preserving every contour and stone position.',
      scope: 'appearance',
      variant: 99 - index,
    }), `${label}: Create candidate that will become stale`);
    assert.equal(stalePreview.candidate.temporary, true);
    assert.equal(stalePreview.candidate.status, 'pending_review');
    assert.equal(stalePreview.lineage.sourceAssetId, originalRevision.asset_id);
    staleCandidateId = stalePreview.candidate.id;

    const withTwoPreviews = value(
      await gateway.getStudioProjectHistory(reopenedBranch.root_id),
      `${label}: History with two temporary candidates`,
    );
    assert.equal(withTwoPreviews.revisions.length, whilePreviewHistory.revisions.length);
    assert.equal(withTwoPreviews.active_asset_id, whilePreviewHistory.active_asset_id);
  }

  const applied = value(await gateway.applyVisualRefine({
    candidateId: preview.candidate.id,
    createdBy: actor,
  }), `${label}: Apply preview`);
  assert.equal(applied.candidate.status, 'applied');
  assert(applied.candidate.canonicalRevisionId);
  assert.equal(applied.project?.active_asset_id, applied.candidate.canonicalRevisionId);
  if (applied.project) assertSourceKind(applied.project, caseDefinition.sourceKind, `${label}: applied revision`);

  const compareHistory = value(
    await gateway.getStudioProjectHistory(reopenedBranch.root_id),
    `${label}: Compare revisions`,
  );
  assert.equal(compareHistory.revisions.length, 2);
  const refinedRevision = compareHistory.revisions[1];
  assert(refinedRevision);
  assert.equal(refinedRevision.parent_asset_id, originalRevision.asset_id);
  assert.notEqual(
    await sha256(originalRevision.image_url),
    await sha256(refinedRevision.image_url),
    `${label}: original and refined bytes are not independently comparable`,
  );

  let staleApplyRejected = false;
  if (staleCandidateId !== null) {
    const beforeStaleApply = compareHistory;
    const beforeStaleActiveHash = await sha256(refinedRevision.image_url);
    const staleApply = await gateway.applyVisualRefine({
      candidateId: staleCandidateId,
      createdBy: actor,
    });
    assert.equal(staleApply.data, null, `${label}: stale Apply unexpectedly returned data`);
    assert(staleApply.error, `${label}: stale Apply unexpectedly succeeded`);
    assert.equal(staleApply.status, 410);
    assert.equal(staleApply.error.code, 'visual_preview_unavailable');
    assert.equal(staleApply.error.category, 'conflict');
    assert.equal(staleApply.error.retryable, false);

    const afterStaleApply = value(
      await gateway.getStudioProjectHistory(reopenedBranch.root_id),
      `${label}: Reopen history after rejected stale Apply`,
    );
    assert.equal(
      afterStaleApply.revisions.length,
      beforeStaleApply.revisions.length,
      `${label}: rejected stale Apply appended canonical history`,
    );
    assert.equal(
      afterStaleApply.active_asset_id,
      beforeStaleApply.active_asset_id,
      `${label}: rejected stale Apply changed the active asset`,
    );
    const afterStaleActive = afterStaleApply.revisions.at(-1);
    assert(afterStaleActive);
    assert.equal(
      await sha256(afterStaleActive.image_url),
      beforeStaleActiveHash,
      `${label}: rejected stale Apply changed the active revision bytes`,
    );
    staleApplyRejected = true;
  }

  const restored = value(await gateway.restoreStudioRevision(
    reopenedBranch.root_id,
    originalRevision.asset_id,
    {
      created_by: actor,
      expected_active_asset_id: refinedRevision.asset_id,
      expected_design_version: null,
    },
  ), `${label}: Restore original as new revision`);
  assert.equal(restored.status, 'restored_as_new_revision');
  assert.equal(restored.restored_from_asset_id, originalRevision.asset_id);
  assert.notEqual(restored.new_asset_id, originalRevision.asset_id, `${label}: restore rewound history`);
  assertSourceKind(restored.project, caseDefinition.sourceKind, `${label}: restored revision`);

  const finalHistory = value(
    await gateway.getStudioProjectHistory(reopenedBranch.root_id),
    `${label}: Reopen restored history`,
  );
  assert.equal(finalHistory.revisions.length, 3);
  assert.equal(finalHistory.active_asset_id, restored.new_asset_id);
  assert.equal(finalHistory.revisions[2]?.action, 'restore');
  assert.equal(finalHistory.revisions[2]?.restored_from_asset_id, originalRevision.asset_id);
  assert.equal(
    await sha256(finalHistory.revisions[2]!.image_url),
    await sha256(originalRevision.image_url),
    `${label}: restore did not preserve exact historical bytes`,
  );

  return {
    id: label,
    projectId: created.root_id,
    variationProjectId: reopenedBranch.root_id,
    sourceKind: caseDefinition.sourceKind,
    referenceRoles: caseDefinition.references ?? [],
    directionCount: candidates.length,
    canonicalRevisionCount: finalHistory.revisions.length,
    staleApplyRejected,
  };
}

async function main(): Promise<void> {
  await runFailedQaCase();
  const structuralCut = await runStructuralCutCase();

  const results: AcceptanceResult[] = [];
  for (const [index, caseDefinition] of CASES.entries()) {
    results.push(await runCase(caseDefinition, index));
  }

  assert.equal(results.length, 10);
  assert.deepEqual(new Set(results.map((item) => item.sourceKind)), new Set([
    null, 'drawing', 'photograph', 'finished_render',
  ]));
  assert.deepEqual(new Set(results.flatMap((item) => item.referenceRoles)), new Set([
    'material_style', 'construction_detail', 'brand_direction',
  ]));

  const activity = value(await gateway.listStudioJobs(actor), 'Activity');
  const creates = activity.jobs.filter((job) => job.action_id === 'create');
  const refines = activity.jobs.filter((job) => job.action_id === 'refine');
  const succeededRefines = refines.filter((job) => job.status === 'succeeded');
  const rejectedStaleRefines = refines.filter((job) => (
    job.status === 'failed' && job.error_code === 'visual_preview_unavailable'
  ));
  assert.equal(creates.length, 10, 'one durable Create job must exist per matrix project');
  assert.equal(succeededRefines.length, 10, 'one successful Refine job must exist per matrix project');
  assert.equal(rejectedStaleRefines.length, 1, 'the stale Apply must leave one honest failed Refine job');
  assert.equal(refines.length, 11, 'only the deliberate stale candidate may add a Refine job');
  for (const job of [...creates, ...succeededRefines]) {
    assert.equal(job.status, 'succeeded');
    assert(job.billing.charged_outputs > 0, `${job.action_id} was not charged atomically`);
  }
  for (const job of rejectedStaleRefines) {
    assert.equal(job.billing.completed_outputs, 0);
    assert.equal(job.billing.charged_outputs, 0);
    assert.equal(job.billing.charged_credits, 0);
  }
  assert.equal(
    results.filter((item) => item.staleApplyRejected).length,
    1,
    'exactly one real-process stale Apply negative case must run',
  );
  assert.equal(activity.jobs.some((job) => job.action_id === 'factory'), false);

  process.stdout.write(JSON.stringify({
    status: 'passed',
    transport: 'production TypeScript trusted client/gateway -> HTTP -> uvicorn/FastAPI',
    matrix_size: results.length,
    starts: {
      sentence: results.filter((item) => item.sourceKind === null).length,
      drawing: results.filter((item) => item.sourceKind === 'drawing').length,
      photograph: results.filter((item) => item.sourceKind === 'photograph').length,
      finished_render: results.filter((item) => item.sourceKind === 'finished_render').length,
      role_labeled_reference_projects: results.filter((item) => item.referenceRoles.length > 0).length,
    },
    projects: results,
    settled_activity: {
      create: creates.length,
      refine_succeeded: succeededRefines.length,
      refine_stale_rejected: rejectedStaleRefines.length,
    },
    failed_qa: {
      canonical_projects: 0,
      canonical_revisions: 0,
      accepted_outputs: 0,
      charged_outputs: 0,
      failed_evidence_runs: 1,
    },
    structural_cut: structuralCut,
    canonical_mutation_before_acceptance: false,
    stale_apply_mutated_canonical_history: false,
    factory_used: false,
  }, null, 2) + '\n');
}

main().catch((error: unknown) => {
  console.error(error);
  process.exitCode = 1;
});
