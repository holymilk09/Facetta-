import { getStudioAction } from './actions';
import type {
  ReferenceRole, StudioActionDefinition, StudioFieldKind,
} from './contracts';

export const STUDIO_MANIFEST_WORKSPACE_ACTION_IDS = [
  'create', 'vary', 'refine', 'views', 'present', 'factory',
] as const;

export type StudioManifestWorkspaceActionId =
  typeof STUDIO_MANIFEST_WORKSPACE_ACTION_IDS[number];

export interface StudioManifestWorkspaceFieldControl {
  fieldId: string;
  label: string;
  kind: StudioFieldKind;
  required: boolean;
  role: ReferenceRole | null;
  /** Designer guidance owned by the host, not by the backend manifest. */
  help: string | null;
}

export interface StudioManifestWorkspaceControls {
  actionId: StudioManifestWorkspaceActionId;
  fields: readonly StudioManifestWorkspaceFieldControl[];
  /** Inclusive canonical choices derived from requestedOutputRange. */
  requestedOutputChoices: readonly number[];
  /** Canonical charge for one requested output; internal retries are not represented here. */
  creditsPerOutput: number;
  acceptsRequestedOutputCount: (count: number) => boolean;
  /** Throws when count is not one of requestedOutputChoices. */
  estimateCredits: (count: number) => number;
}

interface StudioWorkspaceFieldExpectation {
  fieldId: string;
  label: string;
  kind: StudioFieldKind;
  required: boolean;
  role?: ReferenceRole;
}

interface StudioWorkspaceActionExpectation {
  fields: readonly StudioWorkspaceFieldExpectation[];
  requestedOutputChoices: readonly number[];
}

/**
 * This is a deliberate compatibility boundary, not another UI schema. A
 * generated manifest change must be reviewed here before a workspace can
 * render different controls or output counts.
 */
const STUDIO_WORKSPACE_EXPECTATIONS = {
  create: {
    fields: [
      { fieldId: 'brief', label: 'Design sentence', kind: 'text', required: false },
      {
        fieldId: 'master', label: 'Master geometry', kind: 'reference', required: false,
        role: 'master_geometry',
      },
      {
        fieldId: 'style', label: 'Material & style', kind: 'reference', required: false,
        role: 'material_style',
      },
      {
        fieldId: 'construction', label: 'Construction detail', kind: 'reference', required: false,
        role: 'construction_detail',
      },
      {
        fieldId: 'brand', label: 'Brand direction', kind: 'reference', required: false,
        role: 'brand_direction',
      },
    ],
    requestedOutputChoices: [1, 2, 3, 4],
  },
  vary: {
    fields: [
      { fieldId: 'direction', label: 'Variation name', kind: 'text', required: true },
    ],
    requestedOutputChoices: [0],
  },
  refine: {
    fields: [
      {
        fieldId: 'instruction', label: 'What would you like to change?', kind: 'text', required: true,
      },
      {
        fieldId: 'mask', label: 'Target region', kind: 'reference', required: false,
        role: 'edit_mask',
      },
    ],
    requestedOutputChoices: [1],
  },
  views: {
    fields: [
      { fieldId: 'view_set', label: 'Views', kind: 'select', required: true },
    ],
    requestedOutputChoices: [1],
  },
  present: {
    fields: [
      {
        fieldId: 'destination', label: 'Presentation destination', kind: 'select', required: true,
      },
      {
        fieldId: 'direction', label: 'Optional art direction', kind: 'text', required: false,
      },
    ],
    requestedOutputChoices: [1, 2, 3, 4],
  },
  factory: {
    fields: [],
    requestedOutputChoices: [1],
  },
} as const satisfies Record<
  StudioManifestWorkspaceActionId, StudioWorkspaceActionExpectation
>;

/** Host-owned explanations can evolve without changing the server contract. */
const STUDIO_WORKSPACE_FIELD_HELP: Readonly<Record<string, string>> = {
  'create:master': 'The source design whose visible form must be preserved.',
  'create:style': 'Surface, color, and finish only—not jewelry geometry.',
  'create:construction': 'Visual guidance for one detail, not a confirmed production fact.',
  'create:brand': 'Mood and visual language only—not product geometry or branding to copy.',
};

function invalidManifest(
  actionId: StudioManifestWorkspaceActionId,
  detail: string,
): never {
  throw new Error(`Invalid Studio action manifest for ${actionId}: ${detail}`);
}

function deriveRequestedOutputChoices(
  actionId: StudioManifestWorkspaceActionId,
  action: StudioActionDefinition,
): readonly number[] {
  const range = action.requestedOutputRange;
  if (range === null || typeof range !== 'object') {
    return invalidManifest(actionId, 'requested-output range is missing');
  }
  if (!Number.isSafeInteger(range.min) || !Number.isSafeInteger(range.max)) {
    return invalidManifest(actionId, 'requested-output bounds must be safe integers');
  }
  if (range.min < 0 || range.max < range.min) {
    return invalidManifest(actionId, 'requested-output bounds are invalid');
  }
  const expected = STUDIO_WORKSPACE_EXPECTATIONS[actionId].requestedOutputChoices;
  if (range.max - range.min + 1 !== expected.length) {
    return invalidManifest(actionId, 'requested-output choices changed');
  }
  const choices = expected.map((_, index) => range.min + index);
  if (choices.some((choice, index) => choice !== expected[index])) {
    return invalidManifest(actionId, 'requested-output choices changed');
  }
  return Object.freeze(choices);
}

function deriveCreditsPerOutput(
  actionId: StudioManifestWorkspaceActionId,
  action: StudioActionDefinition,
): number {
  const credits = action.creditEstimate;
  if (credits === null || !Number.isSafeInteger(credits) || credits < 0) {
    return invalidManifest(actionId, 'credits per output must be a non-negative safe integer');
  }
  return credits;
}

/**
 * Validate one resolved action before adapting it for a workspace. The strict
 * comparison is intentional: missing, reordered, or repurposed fields never
 * degrade into a plausible-looking but incorrect form.
 */
export function buildStudioWorkspaceControls(
  actionId: StudioManifestWorkspaceActionId,
  action: StudioActionDefinition,
): StudioManifestWorkspaceControls {
  if (action.id !== actionId) {
    return invalidManifest(actionId, `resolved action id is ${action.id}`);
  }
  if (action.uiSchemaMode !== 'declarative_fields') {
    return invalidManifest(actionId, 'action is not declarative');
  }
  if (!Array.isArray(action.fields)) {
    return invalidManifest(actionId, 'fields are missing');
  }

  const expectation = STUDIO_WORKSPACE_EXPECTATIONS[actionId];
  if (action.fields.length !== expectation.fields.length) {
    return invalidManifest(actionId, 'field count changed');
  }

  const seenFieldIds = new Set<string>();
  const fields = expectation.fields.map((expected, index) => {
    const field = action.fields[index];
    if (field === undefined || typeof field !== 'object') {
      return invalidManifest(actionId, `field ${index + 1} is missing`);
    }
    if (typeof field.id !== 'string' || field.id !== expected.fieldId) {
      return invalidManifest(actionId, `field ${index + 1} id changed`);
    }
    if (seenFieldIds.has(field.id)) {
      return invalidManifest(actionId, `field id ${field.id} is duplicated`);
    }
    seenFieldIds.add(field.id);
    if (typeof field.label !== 'string'
      || field.label !== expected.label
      || field.label.trim().length === 0) {
      return invalidManifest(actionId, `field ${field.id} label changed`);
    }
    if (field.kind !== expected.kind) {
      return invalidManifest(actionId, `field ${field.id} kind changed`);
    }
    if (field.required !== expected.required) {
      return invalidManifest(actionId, `field ${field.id} requirement changed`);
    }
    const expectedRole = 'role' in expected ? expected.role : null;
    const role = field.referenceRole ?? null;
    if (role !== expectedRole) {
      return invalidManifest(actionId, `field ${field.id} reference role changed`);
    }
    if (field.kind === 'reference' && role === null) {
      return invalidManifest(actionId, `reference field ${field.id} has no role`);
    }
    if (field.kind !== 'reference' && role !== null) {
      return invalidManifest(actionId, `non-reference field ${field.id} has a role`);
    }
    return Object.freeze({
      fieldId: field.id,
      label: field.label,
      kind: field.kind,
      required: field.required,
      role,
      help: STUDIO_WORKSPACE_FIELD_HELP[`${actionId}:${field.id}`] ?? null,
    });
  });

  const requestedOutputChoices = deriveRequestedOutputChoices(actionId, action);
  const creditsPerOutput = deriveCreditsPerOutput(actionId, action);
  const acceptsRequestedOutputCount = (count: number): boolean => (
    Number.isSafeInteger(count) && requestedOutputChoices.includes(count)
  );
  const estimateCredits = (count: number): number => {
    if (!acceptsRequestedOutputCount(count)) {
      throw new Error(`Unsupported requested-output count for ${actionId}: ${count}`);
    }
    const estimate = count * creditsPerOutput;
    if (!Number.isSafeInteger(estimate)) {
      return invalidManifest(actionId, 'credit estimate exceeds the safe integer range');
    }
    return estimate;
  };

  return Object.freeze({
    actionId,
    fields: Object.freeze(fields),
    requestedOutputChoices,
    creditsPerOutput,
    acceptsRequestedOutputCount,
    estimateCredits,
  });
}

/** Resolve, validate, and normalize the canonical action registry entry. */
export function getStudioWorkspaceControls(
  actionId: StudioManifestWorkspaceActionId,
): StudioManifestWorkspaceControls {
  return buildStudioWorkspaceControls(actionId, getStudioAction(actionId));
}

export const STUDIO_CREATE_REFERENCE_CONTROLS = [
  { fieldId: 'master', role: 'master_geometry', label: 'Master geometry', help: 'The source design whose visible form must be preserved.' },
  { fieldId: 'style', role: 'material_style', label: 'Material & style', help: 'Surface, color, and finish only—not jewelry geometry.' },
  { fieldId: 'construction', role: 'construction_detail', label: 'Construction detail', help: 'Visual guidance for one detail, not a confirmed production fact.' },
  { fieldId: 'brand', role: 'brand_direction', label: 'Brand direction', help: 'Mood and visual language only—not product geometry or branding to copy.' },
] as const satisfies readonly {
  fieldId: string; role: ReferenceRole; label: string; help: string;
}[];

export type CreateReferenceRole = typeof STUDIO_CREATE_REFERENCE_CONTROLS[number]['role'];

export const STUDIO_PRESENT_CONTROLS = {
  destination: { fieldId: 'destination', label: 'Presentation destination' },
  direction: { fieldId: 'direction', label: 'Optional art direction' },
} as const;
