import {
  StudioActionContext, StudioActionDefinition, StudioActionId, StudioJob,
  StudioJobStatus, StudioWorkspaceActionId, transitionStudioJobWithAuthority,
} from './contracts';
import { STUDIO_JOB_ACTION_MANIFEST } from './generatedActionManifest';

const jobAction = (id: keyof typeof STUDIO_JOB_ACTION_MANIFEST) => {
  const definition = STUDIO_JOB_ACTION_MANIFEST[id];
  return {
    lane: definition.lane,
    executionMode: definition.execution_mode,
    reviewAuthority: definition.review_authority,
    inputRequirements: definition.input_requirements,
    contextRequirements: definition.context_requirements,
    uiSchemaMode: 'declarative_fields' as const,
    fields: definition.ui_schema,
    outputType: definition.output_type,
    creditEstimate: definition.credits_per_output,
    requestedOutputRange: {
      min: definition.min_requested_outputs,
      max: definition.max_requested_outputs,
    },
    authority: definition.authority,
    createsJob: definition.execution_mode !== 'instant_transaction',
  };
};

const activeDesign = (context: StudioActionContext) => (
  Boolean(context.activeDesignId) && Boolean(context.activeRevisionId)
);

const exactDesign = (context: StudioActionContext) => (
  activeDesign(context) && context.hasExactSpecification
);

export const STUDIO_ACTIONS: readonly StudioActionDefinition[] = [
  {
    ...jobAction('create'),
    id: 'create',
    label: 'Create a design',
    shortLabel: 'Create',
    description: 'Start from a prompt, sketch, product image, or reference.',
    referenceRoles: [
      'master_geometry', 'material_style', 'construction_detail', 'brand_direction',
    ],
    requiresActiveDesign: false,
    placement: 'primary',
    isAvailable: () => true,
  },
  {
    ...jobAction('vary'),
    id: 'vary',
    label: 'Save as a variation',
    shortLabel: 'Vary',
    description: 'Copy the exact active revision into a named sibling without replacing it.',
    referenceRoles: ['master_geometry'],
    requiresActiveDesign: true,
    placement: 'primary',
    isAvailable: activeDesign,
  },
  {
    ...jobAction('refine'),
    id: 'refine',
    label: 'Refine this design',
    shortLabel: 'Refine',
    description: 'Preview a targeted change while protecting the rest of the design.',
    referenceRoles: ['master_geometry', 'construction_detail', 'edit_mask'],
    requiresActiveDesign: true,
    placement: 'primary',
    isAvailable: activeDesign,
  },
  {
    id: 'confirm',
    label: 'Review starting design facts',
    shortLabel: 'Starting design facts',
    description: 'For ring directions, record the identity and dimensions you know while keeping image-derived estimates clearly separate.',
    lane: 'instant',
    executionMode: 'instant_transaction',
    reviewAuthority: 'none',
    referenceRoles: ['master_geometry', 'construction_detail'],
    inputRequirements: ['design_facts'],
    contextRequirements: ['active_project', 'active_revision', 'selected_pre_spec_visual'],
    uiSchemaMode: 'host_rendered',
    fields: [],
    outputType: 'none',
    creditEstimate: 0,
    requestedOutputRange: null,
    authority: 'design_record',
    requiresActiveDesign: true,
    createsJob: false,
    placement: 'more',
    isAvailable: (context) => activeDesign(context)
      && context.hasSelectedPreSpecVisual
      && !context.hasExactSpecification,
  },
  {
    ...jobAction('views'),
    id: 'views',
    label: 'Generate technical views',
    shortLabel: 'Views',
    description: 'Create consistent line-art angles from this revision and its confirmed design facts.',
    referenceRoles: ['master_geometry', 'construction_detail'],
    requiresActiveDesign: true,
    placement: 'primary',
    isAvailable: exactDesign,
  },
  {
    ...jobAction('present'),
    id: 'present',
    label: 'Present this design',
    shortLabel: 'Present',
    description: 'Prepare client beauty views or a reviewable marketing image set.',
    referenceRoles: ['master_geometry'],
    requiresActiveDesign: true,
    placement: 'primary',
    isAvailable: activeDesign,
  },
  {
    id: 'more',
    label: 'More actions',
    shortLabel: 'More',
    description: 'Open optional destinations and utilities.',
    lane: null,
    executionMode: 'instant_transaction',
    reviewAuthority: 'none',
    referenceRoles: [],
    inputRequirements: [],
    contextRequirements: ['active_project', 'active_revision'],
    uiSchemaMode: 'host_rendered',
    fields: [],
    outputType: 'none',
    creditEstimate: null,
    requestedOutputRange: null,
    authority: null,
    requiresActiveDesign: true,
    createsJob: false,
    placement: 'primary',
    isAvailable: activeDesign,
  },
  {
    id: 'specifications',
    label: 'Advanced specifications',
    shortLabel: 'Specifications',
    description: 'Review or correct recorded design facts on the exact revision.',
    lane: 'instant',
    executionMode: 'instant_transaction',
    reviewAuthority: 'none',
    referenceRoles: ['master_geometry', 'construction_detail'],
    inputRequirements: ['design_facts'],
    contextRequirements: ['active_project', 'active_revision', 'exact_specification'],
    uiSchemaMode: 'host_rendered',
    fields: [],
    outputType: 'none',
    creditEstimate: 0,
    requestedOutputRange: null,
    authority: 'design_record',
    requiresActiveDesign: true,
    createsJob: false,
    placement: 'more',
    isAvailable: exactDesign,
  },
  {
    ...jobAction('factory'),
    id: 'factory',
    label: 'Prepare for Factory review',
    shortLabel: 'Factory',
    description: 'Prepare an eligible exact ring revision for optional manufacturer review.',
    referenceRoles: ['master_geometry', 'construction_detail'],
    requiresActiveDesign: true,
    placement: 'more',
    isAvailable: (context) => (
      exactDesign(context) && context.factoryEligible
    ),
  },
] as const;

export function getStudioAction(id: StudioActionId): StudioActionDefinition {
  const action = STUDIO_ACTIONS.find((candidate) => candidate.id === id);
  if (!action) throw new Error(`Unknown Studio action: ${id}`);
  return action;
}

/**
 * Fail closed before mounting workspaces whose availability carries backend
 * eligibility, not just progressive-disclosure state. Other workspaces can be
 * opened while a newly hydrated project is settling into React state; Factory
 * must always be rechecked against the current exact-revision context.
 */
export function canMountStudioWorkspace(
  actionId: StudioWorkspaceActionId,
  context: StudioActionContext,
): boolean {
  return actionId !== 'factory' || getStudioAction(actionId).isAvailable(context);
}

/** Apply the canonical action's review authority to local lifecycle checks. */
export function transitionStudioJob(
  job: StudioJob,
  status: StudioJobStatus,
  updatedAt: string,
): StudioJob {
  return transitionStudioJobWithAuthority(
    job,
    status,
    updatedAt,
    getStudioAction(job.actionId).reviewAuthority,
  );
}

export function getVisibleStudioActions(
  context: StudioActionContext,
  placement: StudioActionDefinition['placement'] = 'primary',
): readonly StudioActionDefinition[] {
  return STUDIO_ACTIONS.filter(
    (action) => action.placement === placement && action.isAvailable(context),
  );
}

/**
 * Keep the active-design commands stable inside the contextual switcher.
 * Availability determines whether a command can run, not whether the
 * designer must rediscover it.
 */
export function getStudioContextActions(
  context: StudioActionContext,
): readonly StudioActionDefinition[] {
  if (!activeDesign(context)) return getVisibleStudioActions(context);
  return STUDIO_ACTIONS.filter((action) => action.placement === 'primary');
}

export function getStudioActionUnavailableReason(
  action: StudioActionDefinition,
  context: StudioActionContext,
): string | null {
  if (action.id === 'more') {
    return getVisibleStudioActions(context, 'more').length > 0
      ? null
      : 'No optional actions yet';
  }
  if (action.isAvailable(context)) return null;
  if (action.id === 'views' && activeDesign(context) && !context.hasExactSpecification) {
    return context.hasSelectedPreSpecVisual
      ? 'Save starting facts first'
      : 'Choose a confirmable ring direction first';
  }
  return action.requiresActiveDesign ? 'Open a saved revision first' : 'Unavailable';
}

/**
 * Resolve a safe, zero-credit action that can satisfy a blocked action's
 * prerequisite. A caller may make the blocked destination actionable only
 * when this function returns an available action.
 */
export function getStudioActionPrerequisite(
  action: StudioActionDefinition,
  context: StudioActionContext,
): StudioActionDefinition | null {
  if (action.id !== 'views' || action.isAvailable(context)) return null;
  const confirm = getStudioAction('confirm');
  return confirm.isAvailable(context) ? confirm : null;
}

export type StudioActionLaunchIntent =
  | {
    type: 'open_workspace';
    actionId: StudioWorkspaceActionId;
    continueTo: Extract<StudioWorkspaceActionId, 'refine' | 'views'> | null;
  }
  | { type: 'toggle_optional' }
  | { type: 'unavailable'; reason: string };

/**
 * Resolve a contextual command without teaching presentation code about the
 * host router's continuation flags. The action registry remains the single
 * source of truth for visibility, prerequisites, and optional destinations.
 */
export function resolveStudioActionLaunch(
  actionId: StudioActionId,
  context: StudioActionContext,
): StudioActionLaunchIntent {
  const action = getStudioAction(actionId);
  const unavailableReason = getStudioActionUnavailableReason(action, context);
  const prerequisite = getStudioActionPrerequisite(action, context);
  if (actionId === 'more') {
    return unavailableReason === null
      ? { type: 'toggle_optional' }
      : { type: 'unavailable', reason: unavailableReason };
  }
  if (prerequisite !== null) {
    return {
      type: 'open_workspace',
      actionId: prerequisite.id as StudioWorkspaceActionId,
      continueTo: actionId === 'views' ? 'views' : 'refine',
    };
  }
  if (unavailableReason !== null) {
    return { type: 'unavailable', reason: unavailableReason };
  }
  return {
    type: 'open_workspace',
    actionId,
    continueTo: null,
  };
}
