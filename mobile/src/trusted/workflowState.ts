import type {
  ApiError,
  ApprovalSummary,
  ConfirmedMarkupAnnotation,
  FactoryPackManifest,
  ImageWarningCandidate,
  MarkupApplyResponse,
  MarkupInterpretation,
  MarkupReadResponse,
  ProjectDetail,
  ProjectRevision,
  WorkflowPhase,
} from './types';

export type WorkflowOperation =
  | 'restore'
  | 'create'
  | 'refresh'
  | 'beauty_render'
  | 'read_markup'
  | 'apply_markup'
  | 'product_photo'
  | 'line_art'
  | 'approval'
  | 'factory_pack';

export interface PendingMarkup {
  base_asset_id: string;
  interpretation_id: string;
  markup_asset_id: string | null;
  interpretation: MarkupInterpretation;
  expected_design_version: number | null;
  confirmed: ConfirmedMarkupAnnotation | null;
  confirmed_interpretation_id: string | null;
  requires_reconfirmation: boolean;
}

export interface TrustedWorkflowState {
  phase: WorkflowPhase;
  project_id: string | null;
  project: ProjectDetail | null;
  busy: WorkflowOperation | null;
  error: ApiError | null;
  notice: string | null;
  pending_markup: PendingMarkup | null;
  warning_candidate: ImageWarningCandidate | null;
  last_revision: ProjectRevision | null;
  approval: ApprovalSummary | null;
  factory_pack: FactoryPackManifest | null;
  needs_refresh: boolean;
}

export type TrustedWorkflowEvent =
  | { type: 'operation_started'; operation: WorkflowOperation }
  | { type: 'operation_failed'; operation: WorkflowOperation; error: ApiError }
  | { type: 'project_loaded'; project: ProjectDetail; source: 'create' | 'open' | 'refresh' }
  | { type: 'creation_warning_received'; warning: ImageWarningCandidate }
  | { type: 'beauty_render_warning_received'; warning: ImageWarningCandidate }
  | { type: 'product_photo_warning_received'; warning: ImageWarningCandidate }
  | { type: 'drawing_confirmation_received'; candidate: ImageWarningCandidate }
  | { type: 'phase_selected'; phase: WorkflowPhase }
  | { type: 'markup_interpreted'; base_asset_id: string; response: MarkupReadResponse }
  | {
      type: 'markup_confirmed';
      annotation: ConfirmedMarkupAnnotation;
      confirmed_interpretation_id: string;
      expected_design_version: number;
    }
  | { type: 'markup_discarded' }
  | { type: 'markup_applied'; response: MarkupApplyResponse }
  | { type: 'warning_discarded' }
  | { type: 'approval_loaded'; approval: ApprovalSummary }
  | { type: 'factory_pack_loaded'; manifest: FactoryPackManifest }
  | { type: 'error_cleared' }
  | { type: 'notice_cleared' }
  | { type: 'workspace_cleared' };

export const initialTrustedWorkflowState: TrustedWorkflowState = {
  phase: 'create',
  project_id: null,
  project: null,
  busy: null,
  error: null,
  notice: null,
  pending_markup: null,
  warning_candidate: null,
  last_revision: null,
  approval: null,
  factory_pack: null,
  needs_refresh: false,
};

export function phaseForProject(project: ProjectDetail): WorkflowPhase {
  if (project.factory_ready || project.state === 'factory_ready') return 'factory';
  if (project.state === 'approval_required' || project.state === 'approved') return 'approve';
  return 'refine';
}

export function canSelectPhase(
  state: TrustedWorkflowState,
  phase: WorkflowPhase,
): boolean {
  if (phase === 'create') return state.busy === null;
  if (state.project === null) return false;
  if ((phase === 'approve' || phase === 'factory')
    && (state.project.design_id === null
      || state.project.active_design_version === null)) return false;
  // Factory is also the readiness inspector: a blocked project must be able
  // to show the exact missing source audit or form definition. Only the pack
  // action itself remains gated by ``factory_ready``.
  return true;
}

function localRevisionProject(project: ProjectDetail, revision: ProjectRevision): ProjectDetail {
  const revisions = [
    ...project.revisions.filter((item) => item.revision !== revision.revision),
    revision,
  ].sort((left, right) => left.revision - right.revision);
  const assets = [
    ...project.assets.filter((asset) => asset.asset_id !== revision.asset.asset_id),
    revision.asset,
  ];
  return {
    ...project,
    state: 'refining',
    active_asset_id: revision.asset.asset_id,
    active_design_version: revision.spec_version,
    active_revision: revision.asset,
    revisions,
    assets,
    primary_revision_count: revisions.length,
    approval: null,
    factory_ready: false,
  };
}

function invalidatedPendingMarkup(pending: PendingMarkup | null): PendingMarkup | null {
  if (pending === null) return null;
  return {
    ...pending,
    confirmed: null,
    requires_reconfirmation: true,
  };
}

/**
 * Pure workflow reducer. It never clears a loaded project on an operation
 * failure, which prevents a timeout or rejected edit from blanking the canvas.
 */
export function trustedWorkflowReducer(
  state: TrustedWorkflowState,
  event: TrustedWorkflowEvent,
): TrustedWorkflowState {
  switch (event.type) {
    case 'operation_started':
      return {
        ...state,
        busy: event.operation,
        error: null,
        notice: null,
      };

    case 'operation_failed': {
      const stale = event.error.category === 'stale_version';
      return {
        ...state,
        busy: null,
        error: event.error,
        needs_refresh: state.needs_refresh || stale,
        pending_markup: stale
          ? invalidatedPendingMarkup(state.pending_markup)
          : state.pending_markup,
      };
    }

    case 'project_loaded': {
      const sameProject = state.project_id === event.project.id
        || state.project_id === event.project.root_id;
      const sameActiveRevision = state.project?.active_asset_id
        === event.project.active_asset_id;
      const preserveMarkup = event.source === 'refresh' && sameProject
        && sameActiveRevision;
      const phase = event.source === 'refresh' && sameProject
        && state.phase !== 'create' && state.phase !== 'factory'
        ? state.phase
        : phaseForProject(event.project);
      return {
        ...state,
        phase: event.project.factory_ready ? 'factory' : phase,
        project_id: event.project.id,
        project: event.project,
        busy: null,
        error: event.source === 'refresh' ? state.error : null,
        notice: event.source === 'create' ? 'Project created and recovered as a trusted record.' : null,
        pending_markup: preserveMarkup ? state.pending_markup : null,
        warning_candidate: preserveMarkup ? state.warning_candidate : null,
        approval: event.project.approval,
        factory_pack: event.project.factory_ready ? state.factory_pack : null,
        needs_refresh: false,
      };
    }

    case 'creation_warning_received':
      return {
        ...state,
        phase: 'create',
        project_id: null,
        project: null,
        busy: null,
        error: null,
        warning_candidate: event.warning,
        pending_markup: null,
        notice: 'Review this temporary candidate before a project is created.',
      };

    case 'beauty_render_warning_received':
      return {
        ...state,
        phase: 'refine',
        busy: null,
        error: null,
        warning_candidate: event.warning,
        pending_markup: null,
        notice: 'The beauty render needs designer review. Your confirmed reference remains the active revision.',
      };

    case 'product_photo_warning_received':
      return {
        ...state,
        phase: 'refine',
        busy: null,
        error: null,
        warning_candidate: event.warning,
        pending_markup: null,
        notice: 'The product-photo candidate is temporary. Review it before making it the active revision.',
      };

    case 'drawing_confirmation_received':
      return {
        ...state,
        phase: 'refine',
        busy: null,
        error: null,
        warning_candidate: event.candidate,
        pending_markup: null,
        notice: event.candidate.asset_capability === 'LINE_ART'
          ? 'Confirm the line geometry before Facetta can color it.'
          : 'Review the spec-colored drawing before keeping it in the project.',
      };

    case 'phase_selected':
      if (!canSelectPhase(state, event.phase)) return state;
      return {
        ...state,
        phase: event.phase,
        error: null,
        notice: null,
      };

    case 'markup_interpreted':
      return {
        ...state,
        busy: null,
        error: null,
        pending_markup: {
          base_asset_id: event.base_asset_id,
          interpretation_id: event.response.interpretation_id,
          markup_asset_id: event.response.markup_asset_id,
          interpretation: event.response.interpretation,
          expected_design_version: event.response.expected_design_version,
          confirmed: null,
          confirmed_interpretation_id: null,
          requires_reconfirmation: false,
        },
        warning_candidate: null,
        notice: 'Review exactly what Facetta understood before applying it.',
      };

    case 'markup_confirmed':
      if (state.pending_markup === null) return state;
      return {
        ...state,
        error: null,
        notice: event.annotation.impact === 'specification'
          ? 'Confirmed as an image + specification change.'
          : 'Confirmed as a presentation-only image change.',
        pending_markup: {
          ...state.pending_markup,
          confirmed: event.annotation,
          confirmed_interpretation_id: event.confirmed_interpretation_id,
          expected_design_version: event.expected_design_version,
          requires_reconfirmation: false,
        },
      };

    case 'markup_discarded':
      return {
        ...state,
        pending_markup: null,
        warning_candidate: null,
        error: null,
        notice: null,
      };

    case 'markup_applied': {
      if (event.response.qa.verdict === 'warn') {
        return {
          ...state,
          busy: null,
          error: null,
          warning_candidate: event.response.warning_candidate,
          notice: 'The candidate is not a revision yet. Review or regenerate it.',
        };
      }
      if (event.response.revision === null) return state;
      const project = state.project === null
        ? null
        : localRevisionProject(state.project, event.response.revision);
      return {
        ...state,
        phase: 'refine',
        project,
        busy: null,
        error: null,
        notice: 'Revision accepted. The visual and specification record remain linked.',
        pending_markup: null,
        warning_candidate: null,
        last_revision: event.response.revision,
        approval: null,
        factory_pack: null,
        needs_refresh: true,
      };
    }

    case 'warning_discarded':
      return {
        ...state,
        warning_candidate: null,
        busy: null,
        notice: 'Candidate discarded; the active revision was not changed.',
      };

    case 'approval_loaded':
      return {
        ...state,
        phase: event.approval.pinned && event.approval.all_approved ? 'factory' : 'approve',
        approval: event.approval,
        busy: null,
        error: null,
        notice: event.approval.all_approved
          ? 'Every fact is approved for this exact version.'
          : null,
      };

    case 'factory_pack_loaded':
      return {
        ...state,
        phase: 'factory',
        factory_pack: event.manifest,
        busy: null,
        error: null,
        notice: 'Factory pack verified against the pinned revision.',
      };

    case 'error_cleared':
      return { ...state, error: null };

    case 'notice_cleared':
      return { ...state, notice: null };

    case 'workspace_cleared':
      return initialTrustedWorkflowState;
  }
}
