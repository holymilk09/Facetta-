/// <reference types="node" />

import assert from 'node:assert/strict';
import test from 'node:test';
import { getStudioAction, getStudioRailActions, getVisibleStudioActions } from './actions';
import {
  decidePreviewCandidate, PreviewCandidate, StudioJob, transitionStudioJob,
} from './contracts';
import {
  STUDIO_CREATE_REFERENCE_CONTROLS, STUDIO_PRESENT_CONTROLS,
} from './workspaceControls';

const emptyContext = {
  activeDesignId: null,
  activeRevisionId: null,
  hasExactSpecification: false,
  hasSelectedPreSpecVisual: false,
  factoryEnabled: false,
  factoryEligible: false,
};

test('only Create is visible without an active design', () => {
  assert.deepEqual(
    getVisibleStudioActions(emptyContext).map((action) => action.id),
    ['create'],
  );
  assert.deepEqual(
    getVisibleStudioActions({ ...emptyContext, activeDesignId: 'dsn_1' }).map((action) => action.id),
    ['create'],
  );
});

test('Factory remains absent until the exact revision is eligible', () => {
  const active = {
    ...emptyContext,
    activeDesignId: 'dsn_1',
    activeRevisionId: 'rev_1',
    hasExactSpecification: true,
    factoryEnabled: true,
  };
  assert.deepEqual(
    getVisibleStudioActions(active, 'more').map((action) => action.id),
    ['specifications'],
  );
  assert.deepEqual(
    getVisibleStudioActions({ ...active, factoryEligible: true }, 'more').map((action) => action.id),
    ['specifications', 'factory'],
  );
});

test('the rail hides an empty More menu and exposes secondary exact-design destinations', () => {
  const active = {
    ...emptyContext,
    activeDesignId: 'dsn_1',
    activeRevisionId: 'rev_1',
    hasExactSpecification: false,
    factoryEnabled: true,
  };
  assert.equal(getStudioRailActions(active).some((action) => action.id === 'more'), false);
  assert.equal(getStudioRailActions({
    ...active, hasExactSpecification: true,
  }).at(-1)?.id, 'more');
});

test('pre-spec directions expose Refine and Present while keeping Views spec-backed', () => {
  const selectedCreativeDirection = {
    ...emptyContext,
    activeDesignId: 'project_1',
    activeRevisionId: 'creative_1',
    hasSelectedPreSpecVisual: true,
  };
  assert.deepEqual(
    getStudioRailActions(selectedCreativeDirection).map((action) => action.id),
    ['create', 'vary', 'refine', 'present', 'more'],
  );
});

test('ring fact review is secondary for a selected pre-spec visual and never exposes Factory', () => {
  const preSpec = {
    ...emptyContext,
    activeDesignId: 'project_1',
    activeRevisionId: 'asset_1',
    hasSelectedPreSpecVisual: true,
  };
  assert.equal(getStudioRailActions(preSpec).some((action) => action.id === 'confirm'), false);
  assert.equal(getVisibleStudioActions(preSpec, 'more').some((action) => (
    action.id === 'confirm' && action.shortLabel === 'Ring facts'
  )), true);
  assert.equal(getVisibleStudioActions(preSpec, 'more').some((action) => action.id === 'factory'), false);
  assert.equal(getVisibleStudioActions({
    ...preSpec, hasSelectedPreSpecVisual: false,
  }, 'more').some((action) => action.id === 'confirm'), false);
  assert.equal(getVisibleStudioActions({
    ...preSpec, hasExactSpecification: true,
  }, 'more').some((action) => action.id === 'confirm'), false);
});

test('the current branch action is transparent and does not charge for generation', () => {
  const branch = getStudioAction('vary');
  assert.deepEqual(
    [branch.label, branch.creditEstimate, branch.createsJob, branch.authority],
    ['Save as a variation', 0, false, 'design_record'],
  );
});

test('action schemas match the controls rendered by Create and Present', () => {
  const create = getStudioAction('create');
  const createReferences = create.fields.filter((field) => field.kind === 'reference');
  assert.deepEqual(
    createReferences.map((field) => ({ id: field.id, role: field.referenceRole })),
    STUDIO_CREATE_REFERENCE_CONTROLS.map((control) => ({
      id: control.fieldId, role: control.role,
    })),
  );
  assert.deepEqual(create.referenceRoles, STUDIO_CREATE_REFERENCE_CONTROLS.map(({ role }) => role));

  const present = getStudioAction('present');
  assert.deepEqual(
    present.fields.map(({ id, label }) => ({ id, label })),
    [
      {
        id: STUDIO_PRESENT_CONTROLS.destination.fieldId,
        label: 'Presentation destination',
      },
      {
        id: STUDIO_PRESENT_CONTROLS.direction.fieldId,
        label: STUDIO_PRESENT_CONTROLS.direction.label,
      },
    ],
  );
  assert.equal(present.fields.some((field) => field.kind === 'reference'), false);
  assert.deepEqual(present.referenceRoles, ['master_geometry']);
});

test('StudioJob lifecycle rejects terminal-state mutation', () => {
  const job: StudioJob = {
    id: 'job_1',
    actionId: 'refine',
    lane: 'trusted_structural',
    status: 'queued',
    progress: 0,
    activeDesignId: 'dsn_1',
    sourceRevisionId: 'rev_1',
    attemptCount: 0,
    createdAt: '2026-07-12T00:00:00Z',
    updatedAt: '2026-07-12T00:00:00Z',
    errorCode: null,
  };
  const running = transitionStudioJob(job, 'running', '2026-07-12T00:00:02Z');
  const reviewing = transitionStudioJob(running, 'reviewing', '2026-07-12T00:00:03Z');
  const succeeded = transitionStudioJob(reviewing, 'succeeded', '2026-07-12T00:00:04Z');
  assert.equal(succeeded.progress, 1);
  assert.throws(() => transitionStudioJob(succeeded, 'running', '2026-07-12T00:00:05Z'));
});

const preview = (verdict: PreviewCandidate['verdict']): PreviewCandidate => ({
  id: 'candidate_1',
  jobId: 'job_1',
  sourceRevisionId: 'rev_1',
  assetUrl: 'https://example.test/candidate.png',
  verdict,
  status: 'pending_review',
  checks: [],
  temporary: true,
  expiresAt: null,
  decision: null,
  decidedAt: null,
  canonicalRevisionId: null,
});

test('rejected and discarded previews cannot be applied', () => {
  assert.throws(() => decidePreviewCandidate(
    preview('reject'), 'apply', '2026-07-12T00:01:00Z', 'rev_2',
  ));
  const discarded = decidePreviewCandidate(preview('pass'), 'discard', '2026-07-12T00:01:00Z');
  assert.equal(discarded.status, 'discarded');
  assert.throws(() => decidePreviewCandidate(
    discarded, 'apply', '2026-07-12T00:02:00Z', 'rev_2',
  ));
});

test('apply and save-as-variation require an explicit canonical revision', () => {
  assert.throws(() => decidePreviewCandidate(preview('pass'), 'apply', '2026-07-12T00:01:00Z'));
  const applied = decidePreviewCandidate(
    preview('pass'), 'apply', '2026-07-12T00:01:00Z', 'rev_2',
  );
  const variation = decidePreviewCandidate(
    preview('warn'), 'save_as_variation', '2026-07-12T00:01:00Z', 'rev_3',
  );
  assert.deepEqual([applied.status, applied.decision, applied.canonicalRevisionId], ['applied', 'apply', 'rev_2']);
  assert.deepEqual(
    [variation.status, variation.decision, variation.canonicalRevisionId],
    ['saved_as_variation', 'save_as_variation', 'rev_3'],
  );
});
