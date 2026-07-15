/// <reference types="node" />

import assert from 'node:assert/strict';
import test from 'node:test';

import { getStudioAction } from './actions';
import type { StudioActionDefinition } from './contracts';
import {
  buildStudioWorkspaceControls,
  getStudioWorkspaceControls,
  STUDIO_MANIFEST_WORKSPACE_ACTION_IDS,
} from './workspaceControls';

test('manifest-backed controls normalize every declarative job action', () => {
  const createFields = getStudioAction('create').fields;
  const varyFields = getStudioAction('vary').fields;
  const viewsFields = getStudioAction('views').fields;
  const presentFields = getStudioAction('present').fields;
  const controls = Object.fromEntries(STUDIO_MANIFEST_WORKSPACE_ACTION_IDS.map((actionId) => (
    [actionId, getStudioWorkspaceControls(actionId)]
  ))) as Record<
    typeof STUDIO_MANIFEST_WORKSPACE_ACTION_IDS[number],
    ReturnType<typeof getStudioWorkspaceControls>
  >;
  assert.deepEqual(
    Object.keys(controls),
    [...STUDIO_MANIFEST_WORKSPACE_ACTION_IDS],
  );
  assert.deepEqual(
    controls.create.fields.map((field) => ({
      fieldId: field.fieldId,
      label: field.label,
      kind: field.kind,
      required: field.required,
      role: field.role,
    })),
    [
      {
        fieldId: 'brief', label: createFields[0]?.label, kind: 'text', required: false, role: null,
      },
      {
        fieldId: 'master', label: createFields[1]?.label, kind: 'reference', required: false,
        role: 'master_geometry',
      },
      {
        fieldId: 'style', label: createFields[2]?.label, kind: 'reference', required: false,
        role: 'material_style',
      },
      {
        fieldId: 'construction', label: createFields[3]?.label, kind: 'reference', required: false,
        role: 'construction_detail',
      },
      {
        fieldId: 'brand', label: createFields[4]?.label, kind: 'reference', required: false,
        role: 'brand_direction',
      },
    ],
  );
  assert.equal(
    controls.create.fields[1]?.help,
    'The source design whose visible form must be preserved.',
  );
  assert.equal(controls.create.fields[0]?.help, null);

  assert.deepEqual(
    controls.vary.fields.map(({ fieldId, label, kind, role }) => ({
      fieldId, label, kind, role,
    })),
    [{ fieldId: 'direction', label: varyFields[0]?.label, kind: 'text', role: null }],
  );
  assert.deepEqual(
    controls.refine.fields.map(({ fieldId, kind, role }) => ({
      fieldId, kind, role,
    })),
    [
      { fieldId: 'instruction', kind: 'text', role: null },
      { fieldId: 'mask', kind: 'reference', role: 'edit_mask' },
    ],
  );
  assert.deepEqual(
    controls.views.fields.map(({ fieldId, label, kind }) => ({
      fieldId, label, kind,
    })),
    [{ fieldId: 'view_set', label: viewsFields[0]?.label, kind: 'select' }],
  );
  assert.deepEqual(
    controls.present.fields.map(({ fieldId, label, kind }) => ({
      fieldId, label, kind,
    })),
    [
      { fieldId: 'destination', label: presentFields[0]?.label, kind: 'select' },
      { fieldId: 'direction', label: presentFields[1]?.label, kind: 'text' },
    ],
  );
  assert.deepEqual(controls.factory.fields, []);
});

test('requested-output choices are inclusive and canonical for every job action', () => {
  assert.deepEqual(getStudioWorkspaceControls('create').requestedOutputChoices, [1, 2, 3, 4]);
  assert.deepEqual(getStudioWorkspaceControls('vary').requestedOutputChoices, [0]);
  assert.deepEqual(getStudioWorkspaceControls('refine').requestedOutputChoices, [1]);
  assert.deepEqual(getStudioWorkspaceControls('views').requestedOutputChoices, [1]);
  assert.deepEqual(getStudioWorkspaceControls('present').requestedOutputChoices, [1, 2, 3, 4]);
  assert.deepEqual(getStudioWorkspaceControls('factory').requestedOutputChoices, [1]);
});

test('the adapter validates output counts and estimates transparent requested-output cost', () => {
  const create = getStudioWorkspaceControls('create');
  assert.equal(create.creditsPerOutput, getStudioAction('create').creditEstimate);
  assert.equal(create.acceptsRequestedOutputCount(1), true);
  assert.equal(create.acceptsRequestedOutputCount(4), true);
  assert.equal(create.acceptsRequestedOutputCount(0), false);
  assert.equal(create.acceptsRequestedOutputCount(5), false);
  assert.equal(create.acceptsRequestedOutputCount(1.5), false);
  assert.equal(create.estimateCredits(4), 60);
  assert.throws(() => create.estimateCredits(5), /Unsupported requested-output count for create/);

  const vary = getStudioWorkspaceControls('vary');
  assert.equal(vary.acceptsRequestedOutputCount(0), true);
  assert.equal(vary.estimateCredits(0), 0);
  assert.equal(vary.acceptsRequestedOutputCount(1), false);

  const present = getStudioWorkspaceControls('present');
  assert.equal(present.estimateCredits(4), 72);
});

const replaceField = (
  action: StudioActionDefinition,
  index: number,
  replacement: Record<string, unknown>,
): StudioActionDefinition => ({
  ...action,
  fields: action.fields.map((field, fieldIndex) => (
    fieldIndex === index ? { ...field, ...replacement } : field
  )) as StudioActionDefinition['fields'],
});

test('the adapter fails closed when field identity, labels, kinds, or roles drift', () => {
  const create = getStudioAction('create');
  const malformed: readonly [StudioActionDefinition, RegExp][] = [
    [replaceField(create, 1, { id: 'geometry' }), /field 2 id changed/],
    [replaceField(create, 1, { label: 'Reference' }), /field master label changed/],
    [replaceField(create, 1, { kind: 'text' }), /field master kind changed/],
    [replaceField(create, 1, { referenceRole: 'material_style' }), /reference role changed/],
    [replaceField(create, 1, { required: true }), /field master requirement changed/],
  ];

  for (const [action, message] of malformed) {
    assert.throws(() => buildStudioWorkspaceControls('create', action), message);
  }
});

test('the adapter fails closed when fields are added, reordered, or made non-declarative', () => {
  const refine = getStudioAction('refine');
  assert.throws(
    () => buildStudioWorkspaceControls('refine', {
      ...refine,
      fields: [...refine.fields, refine.fields[0]!],
    }),
    /field count changed/,
  );
  assert.throws(
    () => buildStudioWorkspaceControls('refine', {
      ...refine,
      fields: [refine.fields[1]!, refine.fields[0]!],
    }),
    /field 1 id changed/,
  );
  assert.throws(
    () => buildStudioWorkspaceControls('refine', {
      ...refine,
      uiSchemaMode: 'host_rendered',
    }),
    /action is not declarative/,
  );
});

test('the adapter fails closed when requested-output bounds drift or are malformed', () => {
  const present = getStudioAction('present');
  for (const requestedOutputRange of [
    null,
    { min: 1, max: 3 },
    { min: 0, max: 3 },
    { min: 4, max: 1 },
    { min: 1.5, max: 4 },
  ] as const) {
    assert.throws(
      () => buildStudioWorkspaceControls('present', { ...present, requestedOutputRange }),
      /Invalid Studio action manifest for present/,
    );
  }
});

test('the adapter fails closed when requested-output pricing is malformed', () => {
  const create = getStudioAction('create');
  for (const creditEstimate of [null, -1, 1.5, Number.NaN] as const) {
    assert.throws(
      () => buildStudioWorkspaceControls('create', { ...create, creditEstimate }),
      /credits per output must be a non-negative safe integer/,
    );
  }
});

test('the adapter rejects a resolver result for a different action', () => {
  assert.throws(
    () => buildStudioWorkspaceControls('create', getStudioAction('present')),
    /resolved action id is present/,
  );
});
