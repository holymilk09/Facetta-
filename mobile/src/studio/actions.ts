import {
  StudioActionContext, StudioActionDefinition, StudioActionId,
} from './contracts';

const activeDesign = (context: StudioActionContext) => (
  Boolean(context.activeDesignId) && Boolean(context.activeRevisionId)
);

const exactDesign = (context: StudioActionContext) => (
  activeDesign(context) && context.hasExactSpecification
);

export const STUDIO_ACTIONS: readonly StudioActionDefinition[] = [
  {
    id: 'create',
    label: 'Create a design',
    shortLabel: 'Create',
    description: 'Start from a prompt, sketch, product image, or reference.',
    lane: 'fast_visual',
    referenceRoles: ['master_geometry', 'material_style', 'brand_direction'],
    fields: [
      { id: 'brief', label: 'Design brief', kind: 'text', required: true },
      { id: 'master', label: 'Master geometry', kind: 'reference', required: false, referenceRole: 'master_geometry' },
      { id: 'style', label: 'Material or style', kind: 'reference', required: false, referenceRole: 'material_style' },
    ],
    outputType: 'design_revision',
    creditEstimate: 15,
    authority: 'design_record',
    requiresActiveDesign: false,
    createsJob: true,
    placement: 'primary',
    isAvailable: () => true,
  },
  {
    id: 'vary',
    label: 'Save as a variation',
    shortLabel: 'Vary',
    description: 'Copy the exact active revision into a named sibling without replacing it.',
    lane: 'instant',
    referenceRoles: ['master_geometry'],
    fields: [{ id: 'direction', label: 'Variation name', kind: 'text', required: true }],
    outputType: 'variation_set',
    creditEstimate: 0,
    authority: 'design_record',
    requiresActiveDesign: true,
    createsJob: false,
    placement: 'primary',
    isAvailable: activeDesign,
  },
  {
    id: 'refine',
    label: 'Refine this design',
    shortLabel: 'Refine',
    description: 'Preview a targeted change while protecting the rest of the design.',
    lane: 'trusted_structural',
    referenceRoles: ['master_geometry', 'construction_detail', 'edit_mask'],
    fields: [
      { id: 'instruction', label: 'Change instruction', kind: 'text', required: true },
      { id: 'mask', label: 'Target region', kind: 'reference', required: false, referenceRole: 'edit_mask' },
    ],
    outputType: 'design_revision',
    creditEstimate: 20,
    authority: 'design_record',
    requiresActiveDesign: true,
    createsJob: true,
    placement: 'primary',
    isAvailable: activeDesign,
  },
  {
    id: 'confirm',
    label: 'Confirm design details',
    shortLabel: 'Confirm',
    description: 'Record the ring identity and the dimensions you know, while keeping estimates clearly separate.',
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
    placement: 'primary',
    isAvailable: (context) => activeDesign(context)
      && context.hasSelectedPreSpecVisual
      && !context.hasExactSpecification,
  },
  {
    id: 'views',
    label: 'Generate views',
    shortLabel: 'Views',
    description: 'Create consistent angles and presentation views from this revision.',
    lane: 'fast_visual',
    referenceRoles: ['master_geometry', 'construction_detail'],
    fields: [{ id: 'view_set', label: 'Views', kind: 'select', required: true }],
    outputType: 'view_set',
    creditEstimate: 15,
    authority: 'visual_preview',
    requiresActiveDesign: true,
    createsJob: true,
    placement: 'primary',
    isAvailable: exactDesign,
  },
  {
    id: 'present',
    label: 'Present this design',
    shortLabel: 'Present',
    description: 'Prepare client beauty views or a reviewable marketing image set.',
    lane: 'fast_visual',
    referenceRoles: ['master_geometry', 'brand_direction'],
    fields: [
      { id: 'destination', label: 'Presentation destination', kind: 'select', required: true },
      { id: 'brand', label: 'Brand direction', kind: 'reference', required: false, referenceRole: 'brand_direction' },
    ],
    outputType: 'presentation_pack',
    creditEstimate: 18,
    authority: 'visual_preview',
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
    id: 'factory',
    label: 'Promote to Factory',
    shortLabel: 'Factory',
    description: 'Prepare an eligible approved revision for production review.',
    lane: 'trusted_structural',
    referenceRoles: ['master_geometry', 'construction_detail'],
    fields: [{ id: 'confirmed_facts', label: 'Confirmed production facts', kind: 'toggle', required: true }],
    outputType: 'factory_review_pack',
    creditEstimate: 28,
    authority: 'production_review',
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
