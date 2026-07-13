/**
 * Real client-to-API Studio acceptance.
 *
 * This process imports the production trusted client/gateway and talks over
 * HTTP to a separately running uvicorn process. It intentionally avoids
 * Factory and asserts that preview work is temporary until acceptance.
 */

import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';

import { createStudioGateway } from '../src/studio/gateway';
import { createTrustedApiClient } from '../src/trusted/client';

const baseUrl = process.argv[2];
assert(baseUrl, 'usage: tsx scripts/studio_client_api_acceptance.ts BASE_URL');

const actor = 'usr_client_api_acceptance';
const trustedClient = createTrustedApiClient({ baseUrl });
const gateway = createStudioGateway(trustedClient, { trackJobs: true });

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

async function main(): Promise<void> {
const created = value(await gateway.createFromDrawing({
  image_base64: 'iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAIAAACQkWg2AAAAIklEQVR4nGPMq2hiIAUwkaSaYVQDcYCJSHVwMKqBGECyBgB/6AGI9C+U8AAAAABJRU5ErkJggg==',
  media_type: 'image/png',
  source_kind: 'photograph',
  instruction: 'Preserve this photographed signet silhouette and create two restrained visual directions',
  variation_count: 2,
  starting_variant: 7,
  owner: actor,
  title: 'Real client API acceptance',
  collection: 'Studio acceptance',
  tags: ['client-api', 'no-factory'],
}), 'Create');

assert.equal(created.revisions.length, 0, 'directions must not become revisions before selection');
assert.equal(created.creative_candidates?.length, 2);
assert.equal(created.factory_ready, false);
const firstDirection = created.creative_candidates![0];
const chosenDirection = created.creative_candidates![1];
assert.notEqual(firstDirection.sha256, chosenDirection.sha256, 'directions must be distinct');

const selected = value(await gateway.selectCreativeDirection(
  created.root_id,
  chosenDirection.asset_id,
  actor,
), 'Select');
assert.equal(selected.active_asset_id, chosenDirection.asset_id);
assert.equal(selected.active_revision?.source_kind, 'photograph');
assert.deepEqual(selected.revisions.map((item) => item.asset.asset_id), [chosenDirection.asset_id]);

const beforePreviewHistory = value(
  await gateway.getStudioProjectHistory(created.root_id),
  'History before preview',
);
assert.equal(beforePreviewHistory.revisions.length, 1);

const preview = value(await gateway.previewVisualRefine({
  projectId: created.root_id,
  sourceAssetId: chosenDirection.asset_id,
  createdBy: actor,
  instruction: 'Warm the metal while preserving every contour',
  scope: 'appearance',
  variant: 3,
}), 'Refine preview');
assert.equal(preview.candidate.temporary, true);
assert.equal(preview.candidate.status, 'pending_review');
assert.equal(preview.lineage.sourceAssetId, chosenDirection.asset_id);

const whilePreviewHistory = value(
  await gateway.getStudioProjectHistory(created.root_id),
  'History while preview is temporary',
);
assert.equal(whilePreviewHistory.revisions.length, 1, 'preview must not mutate canonical history');
assert.equal(whilePreviewHistory.active_asset_id, chosenDirection.asset_id);

const applied = value(await gateway.applyVisualRefine({
  candidateId: preview.candidate.id,
  createdBy: actor,
}), 'Apply');
assert.equal(applied.candidate.status, 'applied');
assert(applied.candidate.canonicalRevisionId);
assert.equal(applied.project?.active_asset_id, applied.candidate.canonicalRevisionId);
assert.equal(applied.project?.active_revision?.source_kind, 'photograph');

const compareHistory = value(
  await gateway.getStudioProjectHistory(created.root_id),
  'Compare history',
);
assert.equal(compareHistory.revisions.length, 2);
const originalRevision = compareHistory.revisions[0];
const refinedRevision = compareHistory.revisions[1];
assert.equal(refinedRevision.parent_asset_id, originalRevision.asset_id);
assert.notEqual(
  await sha256(originalRevision.image_url),
  await sha256(refinedRevision.image_url),
  'original and refined revision bytes must remain independently comparable',
);

const restored = value(await gateway.restoreStudioRevision(
  created.root_id,
  originalRevision.asset_id,
  {
    created_by: actor,
    expected_active_asset_id: refinedRevision.asset_id,
    expected_design_version: null,
  },
), 'Restore');
assert.equal(restored.status, 'restored_as_new_revision');
assert.equal(restored.restored_from_asset_id, originalRevision.asset_id);
assert.notEqual(restored.new_asset_id, originalRevision.asset_id, 'restore must append, not rewind');
assert.equal(restored.project.active_revision?.source_kind, 'photograph');

const restoredHistory = value(
  await gateway.getStudioProjectHistory(created.root_id),
  'History after restore',
);
assert.equal(restoredHistory.revisions.length, 3);
assert.equal(restoredHistory.active_asset_id, restored.new_asset_id);
assert.equal(restoredHistory.revisions[2].action, 'restore');
assert.equal(restoredHistory.revisions[2].restored_from_asset_id, originalRevision.asset_id);
assert.equal(
  await sha256(restoredHistory.revisions[2].image_url),
  await sha256(originalRevision.image_url),
  'restored revision must preserve the selected historical bytes',
);

const presentation = value(await gateway.createPreSpecPresentation(created.root_id, {
  created_by: actor,
  expected_active_asset_id: restored.new_asset_id,
  destination: 'client',
  client_format: 'beauty',
  preset: 'luxury_studio',
  framing: 'portrait',
  custom_instruction: 'Soft daylight and generous negative space',
  variant: 2,
}), 'Client preview');
assert.equal(presentation.status, 'review_required');
assert.equal(presentation.candidate.capability, 'CLIENT_BEAUTY_RENDER');

const beforePresentationSave = value(await gateway.getProject(created.root_id), 'Project before Client save');
assert.equal(beforePresentationSave.active_asset_id, restored.new_asset_id);
assert.equal(
  beforePresentationSave.derived_assets.some((asset) => asset.capability === 'CLIENT_BEAUTY_RENDER'),
  false,
);
const derivedCountBeforeClientSave = beforePresentationSave.derived_assets.length;

const savedPresentation = value(await gateway.acceptPreSpecPresentation({
  candidateId: presentation.candidate.candidate_id,
  createdBy: actor,
}), 'Save Client presentation');
assert.equal(savedPresentation.project.active_asset_id, restored.new_asset_id);
assert.equal(savedPresentation.project.factory_ready, false);
assert.equal(savedPresentation.project.derived_assets.length, derivedCountBeforeClientSave + 1);
const clientAsset = savedPresentation.project.derived_assets.find(
  (asset) => asset.capability === 'CLIENT_BEAUTY_RENDER',
);
assert(clientAsset);
assert.equal(clientAsset.parent_asset_id, restored.new_asset_id);

const finalHistory = value(
  await gateway.getStudioProjectHistory(created.root_id),
  'Final history',
);
assert.equal(finalHistory.revisions.length, 3, 'Client output must not enter canonical design history');
assert.equal(finalHistory.active_asset_id, restored.new_asset_id);

const activity = value(await gateway.listStudioJobs(actor), 'Activity');
const terminalActions = new Map(activity.jobs.map((job) => [job.action_id, job]));
for (const action of ['create', 'refine', 'present'] as const) {
  const job = terminalActions.get(action);
  assert(job, `${action} Activity job was not persisted`);
  assert.equal(job.status, 'succeeded');
  assert(job.billing.charged_outputs > 0, `${action} acceptance was not charged atomically`);
}
assert.equal(terminalActions.has('factory'), false, 'acceptance must not enter Factory');

process.stdout.write(JSON.stringify({
  status: 'passed',
  transport: 'production TypeScript trusted client/gateway -> HTTP -> uvicorn/FastAPI',
  project_id: created.root_id,
  direction_count: created.creative_candidates?.length,
  canonical_revision_count: finalHistory.revisions.length,
  accepted_derivative: 'CLIENT_BEAUTY_RENDER',
  settled_activity_actions: ['create', 'refine', 'present'],
  factory_used: false,
}, null, 2) + '\n');
}

main().catch((error: unknown) => {
  console.error(error);
  process.exitCode = 1;
});
