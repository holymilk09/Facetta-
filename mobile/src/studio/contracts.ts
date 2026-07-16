export const STUDIO_ACTION_IDS = [
  'create',
  'vary',
  'refine',
  'confirm',
  'angles',
  'views',
  'present',
  'more',
  'specifications',
  'factory',
] as const;

export type StudioActionId = typeof STUDIO_ACTION_IDS[number];
export type StudioWorkspaceActionId = Exclude<StudioActionId, 'more'>;

export type StudioLane = 'instant' | 'fast_visual' | 'trusted_structural';

export type ReferenceRole =
  | 'master_geometry'
  | 'material_style'
  | 'construction_detail'
  | 'brand_direction'
  | 'edit_mask'
  | 'model_reference'
  | 'scene_reference';

export type StudioFieldKind = 'text' | 'select' | 'reference' | 'toggle' | 'fixed';

export type StudioInputRequirement =
  | 'brief_or_reference'
  | 'direction'
  | 'instruction'
  | 'view_set'
  | 'angle_set'
  | 'destination'
  | 'design_facts';

export type StudioContextRequirement =
  | 'active_project'
  | 'active_revision'
  | 'selected_pre_spec_visual'
  | 'exact_specification'
  | 'factory_eligible';

export interface StudioActionFieldDefinition {
  id: string;
  label: string;
  kind: StudioFieldKind;
  required: boolean;
  referenceRole?: ReferenceRole;
}

export type StudioOutputType =
  | 'design_revision'
  | 'variation_set'
  | 'visual_angle_set'
  | 'view_set'
  | 'presentation_pack'
  | 'factory_review_pack'
  | 'none';

export type StudioAuthority = 'visual_preview' | 'design_record' | 'production_review';

export type StudioExecutionMode =
  | 'instant_transaction'
  | 'candidate_job'
  | 'terminal_job';

export type StudioReviewAuthority =
  | 'none'
  | 'candidate_decision'
  | 'backend_transaction';

/**
 * Declarative fields can be rendered from this registry. Host-rendered actions
 * own conditional or server-derived controls in their dedicated workspace.
 */
export type StudioUiSchemaMode = 'declarative_fields' | 'host_rendered';

export interface StudioRequestedOutputRange {
  min: number;
  max: number;
}

export interface StudioActionContext {
  activeDesignId: string | null;
  activeRevisionId: string | null;
  hasExactSpecification: boolean;
  /** A selected visual that has not yet been paired with confirmed design facts. */
  hasSelectedPreSpecVisual: boolean;
  /** The backend confirmed the exact active revision is Factory-eligible. */
  factoryEligible: boolean;
}

export interface StudioActionDefinition {
  id: StudioActionId;
  label: string;
  shortLabel: string;
  description: string;
  lane: StudioLane | null;
  executionMode: StudioExecutionMode;
  reviewAuthority: StudioReviewAuthority;
  referenceRoles: readonly ReferenceRole[];
  inputRequirements: readonly StudioInputRequirement[];
  contextRequirements: readonly StudioContextRequirement[];
  uiSchemaMode: StudioUiSchemaMode;
  /** Provider-neutral fields when uiSchemaMode is declarative_fields. */
  fields: readonly StudioActionFieldDefinition[];
  outputType: StudioOutputType;
  creditEstimate: number | null;
  /** Canonical requested-output bounds; null for host-only non-job actions. */
  requestedOutputRange: StudioRequestedOutputRange | null;
  authority: StudioAuthority | null;
  requiresActiveDesign: boolean;
  createsJob: boolean;
  /**
   * Internal actions remain addressable by the host without becoming a
   * competing rail or More-menu destination.
   */
  placement: 'primary' | 'more' | 'internal';
  isAvailable: (context: StudioActionContext) => boolean;
}

export type StudioJobStatus =
  | 'queued'
  | 'running'
  | 'reviewing'
  | 'succeeded'
  | 'failed'
  | 'canceled';

export interface StudioJob {
  id: string;
  actionId: Exclude<StudioActionId, 'more'>;
  lane: StudioLane;
  status: StudioJobStatus;
  progress: number;
  activeDesignId: string | null;
  sourceRevisionId: string | null;
  attemptCount: number;
  createdAt: string;
  updatedAt: string;
  errorCode: string | null;
}

export type PreviewVerdict = 'pass' | 'warn' | 'reject';
export type PreviewCandidateStatus =
  | 'pending_review'
  | 'applied'
  | 'saved_as_variation'
  | 'discarded'
  | 'rejected';
export type PreviewDecision = 'apply' | 'save_as_variation' | 'discard';

export interface PreviewCheck {
  id: string;
  label: string;
  verdict: PreviewVerdict;
  detail: string | null;
}

export interface PreviewCandidate {
  id: string;
  jobId: string;
  sourceRevisionId: string | null;
  assetUrl: string;
  verdict: PreviewVerdict;
  status: PreviewCandidateStatus;
  checks: readonly PreviewCheck[];
  temporary: boolean;
  expiresAt: string | null;
  decision: PreviewDecision | null;
  decidedAt: string | null;
  canonicalRevisionId: string | null;
}

export function decidePreviewCandidate(
  candidate: PreviewCandidate,
  decision: PreviewDecision,
  decidedAt: string,
  canonicalRevisionId: string | null = null,
): PreviewCandidate {
  if (candidate.status !== 'pending_review') {
    throw new Error(`Preview candidate is not reviewable: ${candidate.status}`);
  }
  if (candidate.verdict === 'reject' && decision !== 'discard') {
    throw new Error('Rejected preview candidates cannot become canonical');
  }
  if (decision !== 'discard' && !canonicalRevisionId) {
    throw new Error('Applying a preview requires an explicit canonical revision');
  }
  const status: PreviewCandidateStatus = decision === 'apply'
    ? 'applied'
    : decision === 'save_as_variation'
      ? 'saved_as_variation'
      : 'discarded';
  return {
    ...candidate,
    status,
    temporary: decision === 'discard',
    decision,
    decidedAt,
    canonicalRevisionId: decision === 'discard' ? null : canonicalRevisionId,
  };
}

const JOB_TRANSITIONS: Readonly<Record<StudioJobStatus, readonly StudioJobStatus[]>> = {
  queued: ['running', 'canceled', 'failed'],
  running: ['reviewing', 'canceled', 'failed'],
  reviewing: ['succeeded', 'failed'],
  succeeded: [],
  failed: [],
  canceled: [],
};

export function canTransitionStudioJob(
  from: StudioJobStatus,
  to: StudioJobStatus,
  reviewAuthority: StudioReviewAuthority,
): boolean {
  if (reviewAuthority === 'backend_transaction') return false;
  if (from === 'reviewing' && reviewAuthority === 'candidate_decision') return false;
  return JOB_TRANSITIONS[from].includes(to);
}

export function transitionStudioJobWithAuthority(
  job: StudioJob,
  status: StudioJobStatus,
  updatedAt: string,
  reviewAuthority: StudioReviewAuthority,
): StudioJob {
  if (!canTransitionStudioJob(job.status, status, reviewAuthority)) {
    throw new Error(`Invalid StudioJob transition: ${job.status} -> ${status}`);
  }
  return {
    ...job,
    status,
    progress: status === 'succeeded' ? 1 : job.progress,
    updatedAt,
  };
}
