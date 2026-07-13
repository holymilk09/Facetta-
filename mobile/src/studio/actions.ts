import {
  StudioActionContext, StudioActionDefinition, StudioActionId, StudioJob,
  StudioJobStatus, transitionStudioJobWithAuthority,
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
    authority: 'design_record',
    requiresActiveDesign: true,
    createsJob: false,
    placement: 'internal',
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
    authority: 'design_record',
    requiresActiveDesign: true,
    createsJob: false,
    placement: 'more',
    isAvailable: exactDesign,
  },
  {
    ...jobAction('factory'),
    id: 'factory',
    label: 'Prepare Factory review pack',
    shortLabel: 'Factory',
    description: 'Prepare an eligible exact revision for optional manufacturer review.',
    referenceRoles: ['master_geometry', 'construction_detail'],
    requiresActiveDesign: true,
    placement: 'more',
    isAvailable: (context) => (
      exactDesign(context) && context.factoryEnabled && context.factoryEligible
    ),
  },
] as const;

export function getStudioAction(id: StudioActionId): StudioActionDefinition {
  const action = STUDIO_ACTIONS.find((candidate) => candidate.id === id);
  if (!action) throw new Error(`Unknown Studio action: ${id}`);
  return action;
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

/** Keep the contextual rail honest: More is absent until it has a destination. */
export function getStudioRailActions(
  context: StudioActionContext,
): readonly StudioActionDefinition[] {
  const moreAvailable = getVisibleStudioActions(context, 'more').length > 0;
  return getVisibleStudioActions(context).filter((action) => (
    action.id !== 'more' || moreAvailable
  ));
}
