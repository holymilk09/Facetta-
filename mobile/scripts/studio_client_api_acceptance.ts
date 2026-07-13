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
  ProjectDetail,
} from '../src/trusted/types';

const baseUrl = process.argv[2];
assert(baseUrl, 'usage: tsx scripts/studio_client_api_acceptance.ts BASE_URL');

const actor = 'usr_client_api_acceptance';
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
  };
}

async function main(): Promise<void> {
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
  assert.equal(creates.length, 10, 'one durable Create job must exist per matrix project');
  assert.equal(refines.length, 10, 'one durable Refine job must exist per matrix project');
  for (const job of [...creates, ...refines]) {
    assert.equal(job.status, 'succeeded');
    assert(job.billing.charged_outputs > 0, `${job.action_id} was not charged atomically`);
  }
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
    settled_activity: { create: creates.length, refine: refines.length },
    canonical_mutation_before_acceptance: false,
    factory_used: false,
  }, null, 2) + '\n');
}

main().catch((error: unknown) => {
  console.error(error);
  process.exitCode = 1;
});
