/// <reference types="node" />

import assert from 'node:assert/strict';
import test from 'node:test';
import {
  getStudioAction, getStudioActionPrerequisite, getStudioActionUnavailableReason,
  getStudioRailActions, getVisibleStudioActions, STUDIO_ACTIONS, transitionStudioJob,
} from './actions';
import {
  decidePreviewCandidate, PreviewCandidate, STUDIO_ACTION_IDS, StudioJob,
} from './contracts';
import {
  STUDIO_CREATE_REFERENCE_CONTROLS, STUDIO_PRESENT_CONTROLS,
} from './workspaceControls';

const emptyContext = {
  activeDesignId: null,
  activeRevisionId: null,
  hasExactSpecification: false,
  hasSelectedPreSpecVisual: false,
  factoryEligible: false,
};

test('the action registry defines every Studio action exactly once', () => {
  const registeredIds = STUDIO_ACTIONS.map((action) => action.id);
  assert.equal(new Set(registeredIds).size, registeredIds.length);
  assert.deepEqual(registeredIds, [...STUDIO_ACTION_IDS]);
});

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

test('Factory remains absent until the backend confirms exact-revision eligibility', () => {
  const active = {
    ...emptyContext,
    activeDesignId: 'dsn_1',
    activeRevisionId: 'rev_1',
    hasExactSpecification: true,
  };
  assert.deepEqual(
    getVisibleStudioActions(active, 'more').map((action) => action.id),
    ['specifications'],
  );
  assert.deepEqual(
    getVisibleStudioActions({
      ...active, factoryEligible: true,
    }, 'more').map((action) => action.id),
    ['specifications', 'factory'],
  );
  const factory = getStudioAction('factory');
  assert.equal(factory.contextRequirements.includes('factory_eligible'), true);
  assert.equal(factory.outputType, 'factory_review_pack');
  assert.equal(factory.createsJob, true);
  assert.deepEqual(
    getVisibleStudioActions({
      ...active, hasExactSpecification: false, factoryEligible: true,
    }, 'more').map((action) => action.id),
    [],
  );
});

test('the active-design rail keeps the same six spatial destinations', () => {
  const active = {
    ...emptyContext,
    activeDesignId: 'dsn_1',
    activeRevisionId: 'rev_1',
    hasExactSpecification: false,
  };
  const expected = ['create', 'vary', 'refine', 'views', 'present', 'more'];
  assert.deepEqual(getStudioRailActions(active).map((action) => action.id), expected);
  assert.deepEqual(getStudioRailActions({
    ...active, hasExactSpecification: true,
  }).map((action) => action.id), expected);
});

test('Views stay visible with an explicit prerequisite until design facts are exact', () => {
  const selectedCreativeDirection = {
    ...emptyContext,
    activeDesignId: 'project_1',
    activeRevisionId: 'creative_1',
    hasSelectedPreSpecVisual: true,
  };
  assert.deepEqual(
    getStudioRailActions(selectedCreativeDirection).map((action) => action.id),
    ['create', 'vary', 'refine', 'views', 'present', 'more'],
  );
  assert.deepEqual(
    getStudioRailActions({
      ...selectedCreativeDirection,
      hasExactSpecification: true,
    }).map((action) => action.id),
    ['create', 'vary', 'refine', 'views', 'present', 'more'],
  );
  assert.deepEqual(
    [getStudioAction('views').label, getStudioAction('views').shortLabel],
    ['Generate technical views', 'Views'],
  );
  assert.equal(
    getStudioActionUnavailableReason(getStudioAction('views'), selectedCreativeDirection),
    'Confirm design facts first',
  );
  assert.equal(
    getStudioActionPrerequisite(getStudioAction('views'), selectedCreativeDirection)?.id,
    'confirm',
  );
  assert.equal(
    getStudioActionUnavailableReason(getStudioAction('views'), {
      ...selectedCreativeDirection, hasExactSpecification: true,
    }),
    null,
  );
  assert.equal(
    getStudioActionPrerequisite(getStudioAction('views'), {
      ...selectedCreativeDirection, hasExactSpecification: true,
    }),
    null,
  );
  const nonConfirmableDirection = {
    ...selectedCreativeDirection,
    hasSelectedPreSpecVisual: false,
  };
  assert.equal(
    getStudioActionUnavailableReason(getStudioAction('views'), nonConfirmableDirection),
    'Choose a confirmable ring direction first',
  );
  assert.equal(
    getStudioActionPrerequisite(getStudioAction('views'), nonConfirmableDirection),
    null,
  );
  assert.equal(
    getStudioActionPrerequisite(getStudioAction('present'), selectedCreativeDirection),
    null,
  );
});

test('More exposes starting design facts for a pre-spec visual and never exposes Factory', () => {
  const preSpec = {
    ...emptyContext,
    activeDesignId: 'project_1',
    activeRevisionId: 'asset_1',
    hasSelectedPreSpecVisual: true,
  };
  assert.equal(getStudioRailActions(preSpec).some((action) => action.id === 'confirm'), false);
  assert.equal(getVisibleStudioActions(preSpec, 'more').some((action) => (
    action.id === 'confirm' || action.shortLabel === 'Starting design facts'
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
    [
      branch.label, branch.creditEstimate, branch.createsJob, branch.authority,
      branch.executionMode, branch.reviewAuthority,
    ],
    [
      'Save as a variation', 0, false, 'design_record',
      'instant_transaction', 'none',
    ],
  );
});

test('canonical job behavior is derived from manifest orchestration', () => {
  for (const actionId of ['create', 'vary', 'refine', 'views', 'present', 'factory'] as const) {
    const action = getStudioAction(actionId);
    assert.equal(action.createsJob, action.executionMode !== 'instant_transaction');
    assert.equal(
      action.reviewAuthority,
      action.executionMode === 'candidate_job'
        ? 'candidate_decision'
        : action.executionMode === 'terminal_job'
          ? 'generic_transition'
          : 'none',
    );
  }
});

test('action schemas match the controls rendered by Create and Present', () => {
  const create = getStudioAction('create');
  assert.deepEqual(create.inputRequirements, ['brief_or_reference']);
  assert.deepEqual(create.contextRequirements, []);
  const createReferences = create.fields.filter((field) => field.kind === 'reference');
  assert.deepEqual(
    createReferences.map((field) => ({ id: field.id, role: field.referenceRole })),
    STUDIO_CREATE_REFERENCE_CONTROLS.map((control) => ({
      id: control.fieldId, role: control.role,
    })),
  );
  assert.deepEqual(create.referenceRoles, STUDIO_CREATE_REFERENCE_CONTROLS.map(({ role }) => role));

  const present = getStudioAction('present');
  assert.deepEqual(present.inputRequirements, ['destination']);
  assert.deepEqual(
    present.contextRequirements,
    ['active_project', 'active_revision'],
  );
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

test('every action exposes typed input, context, authority, pricing, and UI schema', () => {
  for (const id of [
    'create', 'vary', 'refine', 'confirm', 'views', 'present', 'more',
    'specifications', 'factory',
  ] as const) {
    const action = getStudioAction(id);
    assert.ok(Array.isArray(action.inputRequirements), `${id} input requirements`);
    assert.ok(Array.isArray(action.contextRequirements), `${id} context requirements`);
    assert.ok(Array.isArray(action.fields), `${id} UI schema`);
    assert.ok(
      action.uiSchemaMode === 'declarative_fields' || action.uiSchemaMode === 'host_rendered',
      `${id} UI schema mode`,
    );
    if (action.uiSchemaMode === 'host_rendered') {
      assert.deepEqual(action.fields, [], `${id} host-rendered actions do not advertise fake fields`);
    }
    assert.ok('creditEstimate' in action, `${id} credit estimate`);
    assert.ok('authority' in action, `${id} authority`);
  }
});

test('dynamic design-fact workflows explicitly use their dedicated host UI', () => {
  for (const id of ['confirm', 'specifications'] as const) {
    const action = getStudioAction(id);
    assert.equal(action.uiSchemaMode, 'host_rendered');
    assert.deepEqual(action.inputRequirements, ['design_facts']);
    assert.deepEqual(action.fields, []);
  }
  assert.deepEqual(
    getStudioAction('confirm').contextRequirements,
    ['active_project', 'active_revision', 'selected_pre_spec_visual'],
  );
  assert.deepEqual(
    getStudioAction('specifications').contextRequirements,
    ['active_project', 'active_revision', 'exact_specification'],
  );
});

test('StudioJob lifecycle derives candidate review authority from the registry', () => {
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
  assert.throws(
    () => transitionStudioJob(reviewing, 'succeeded', '2026-07-12T00:00:04Z'),
    /Invalid StudioJob transition/,
  );
  assert.throws(
    () => transitionStudioJob(reviewing, 'failed', '2026-07-12T00:00:04Z'),
    /Invalid StudioJob transition/,
  );

  const terminalJob = { ...job, actionId: 'factory' as const };
  const terminalRunning = transitionStudioJob(
    terminalJob, 'running', '2026-07-12T00:00:02Z',
  );
  const terminalReviewing = transitionStudioJob(
    terminalRunning, 'reviewing', '2026-07-12T00:00:03Z',
  );
  const succeeded = transitionStudioJob(
    terminalReviewing, 'succeeded', '2026-07-12T00:00:04Z',
  );
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
