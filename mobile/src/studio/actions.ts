import {
  StudioActionContext, StudioActionDefinition, StudioActionId,
} from './contracts';
import { STUDIO_JOB_ACTION_MANIFEST } from './generatedActionManifest';

const jobAction = (id: keyof typeof STUDIO_JOB_ACTION_MANIFEST) => (
  STUDIO_JOB_ACTION_MANIFEST[id]
);

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
    fields: jobAction('create').ui_schema,
    outputType: jobAction('create').output_type,
    creditEstimate: jobAction('create').credits_per_output,
    requiresActiveDesign: false,
    createsJob: true,
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
    fields: jobAction('vary').ui_schema,
    outputType: jobAction('vary').output_type,
    creditEstimate: jobAction('vary').credits_per_output,
    requiresActiveDesign: true,
    createsJob: false,
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
    fields: jobAction('refine').ui_schema,
    outputType: jobAction('refine').output_type,
    creditEstimate: jobAction('refine').credits_per_output,
    requiresActiveDesign: true,
    createsJob: true,
    placement: 'primary',
    isAvailable: activeDesign,
  },
  {
    id: 'confirm',
    label: 'Review ring design facts',
    shortLabel: 'Ring facts',
    description: 'For ring designs, record the identity and dimensions you know while keeping estimates clearly separate.',
    lane: 'instant',
    referenceRoles: ['master_geometry', 'construction_detail'],
    fields: [
      { id: 'design_name', label: 'Design name', kind: 'text', required: true },
      { id: 'ring_size', label: 'Ring size', kind: 'text', required: false },
      { id: 'top_width', label: 'Top width', kind: 'text', required: false },
      { id: 'band_width', label: 'Band width', kind: 'text', required: false },
      { id: 'stone_dimensions', label: 'Stone dimensions', kind: 'text', required: false },
    ],
    outputType: 'none',
    creditEstimate: 0,
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
    label: 'Generate views',
    shortLabel: 'Views',
    description: 'Create consistent angles and presentation views from this revision.',
    referenceRoles: ['master_geometry', 'construction_detail'],
    fields: jobAction('views').ui_schema,
    outputType: jobAction('views').output_type,
    creditEstimate: jobAction('views').credits_per_output,
    requiresActiveDesign: true,
    createsJob: true,
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
    fields: jobAction('present').ui_schema,
    outputType: jobAction('present').output_type,
    creditEstimate: jobAction('present').credits_per_output,
    requiresActiveDesign: true,
    createsJob: true,
    placement: 'primary',
    isAvailable: activeDesign,
  },
  {
    id: 'more',
    label: 'More actions',
    shortLabel: 'More',
    description: 'Open optional destinations and utilities.',
    lane: null,
    referenceRoles: [],
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
    referenceRoles: ['master_geometry', 'construction_detail'],
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
    id: 'factory_readiness',
    label: 'Prepare for Factory',
    shortLabel: 'Factory readiness',
    description: 'Review exact design facts and resolve blockers before optional Factory preparation.',
    lane: 'instant',
    referenceRoles: ['master_geometry', 'construction_detail'],
    fields: [],
    outputType: 'none',
    creditEstimate: 0,
    authority: 'design_record',
    requiresActiveDesign: true,
    createsJob: false,
    placement: 'more',
    // Kept in the typed registry for compatibility while a neutral readiness
    // experience is designed under Advanced specifications. Factory language
    // is not exposed in Studio until the exact revision is actually eligible.
    isAvailable: () => false,
  },
  {
    ...jobAction('factory'),
    id: 'factory',
    label: 'Prepare Factory review pack',
    shortLabel: 'Factory',
    description: 'Prepare an eligible exact revision for optional manufacturer review.',
    referenceRoles: ['master_geometry', 'construction_detail'],
    fields: jobAction('factory').ui_schema,
    outputType: jobAction('factory').output_type,
    creditEstimate: jobAction('factory').credits_per_output,
    requiresActiveDesign: true,
    createsJob: true,
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
