import { createTrustedApiClient, TrustedApiClient, TrustedApiClientOptions } from '../trusted/client';
import type {
  ApiError,
  ApiResult,
  BeautyRenderRequest,
  BeautyRenderResult,
  CatalogPreviewRequest,
  CatalogPreviewAcceptResult,
  CatalogPreviewCandidate,
  CatalogPreviewResult,
  CommitCreativeDirectionsResult,
  ComponentCatalog,
  CreateLineArtRequest,
  CreateProjectFromBriefRequest,
  CreateProjectFromDrawingRequest,
  CreateProjectFromPromptRequest,
  CreateVisualPreviewRequest,
  DrawingConfirmationResult,
  FactoryPackManifest,
  StudioCapabilities,
  ImageQualityReport,
  JsonObject,
  MarketingPackRequest,
  MarketingPackResult,
  MarkupApplyRequest,
  PreSpecPresentationRequest,
  PreSpecPresentationResumeCandidate,
  PreSpecPresentationResult,
  ProductPhotoRequest,
  ProductPhotoResult,
  ProjectCreationResult,
  ProjectDetail,
  SaveAsVariationResult,
  StudioJobAction,
  StudioJobRecord,
  StudioMarkupResumeCandidate,
} from '../trusted/types';
import { getStudioAction } from './actions';
import {
  decidePreviewCandidate,
  PreviewCandidate,
  PreviewCheck,
} from './contracts';

export type StudioGatewayErrorCategory =
  | 'network'
  | 'authentication'
  | 'not_found'
  | 'validation'
  | 'conflict'
  | 'quality'
  | 'unavailable'
  | 'invalid_response';

export interface StudioGatewayError {
  code: string;
  message: string;
  category: StudioGatewayErrorCategory;
  status: number;
  retryable: boolean;
}

export type StudioGatewayResult<T> =
  | { data: T; error: null; status: number }
  | { data: null; error: StudioGatewayError; status: number };

export interface ExactStudioLineage {
  projectId: string;
  sourceAssetId: string;
  sourceDesignVersion: number;
}

/** Immutable visual lineage before a specification has been confirmed. */
export interface StudioVisualLineage {
  projectId: string;
  sourceAssetId: string;
}

export interface StudioCreativeDirectionReviewRequest {
  projectId: string;
  selectedCandidateId: string;
  retained: readonly { candidateId: string; label: string }[];
  createdBy: string;
  studioJobId?: string;
}

export type StudioDesignFactAuthority = 'suggested' | 'estimated' | 'designer_supplied';

export interface StudioProjectedFact {
  key: string;
  label: string;
  value: string;
  authority: StudioDesignFactAuthority;
}

export interface StudioProjectedFactGroup {
  key: 'design' | 'center_stone' | 'setting' | 'metal' | 'ring_fit' | 'accents';
  label: string;
  facts: readonly StudioProjectedFact[];
}

export interface StudioDesignConfirmationReview {
  reviewId: string;
  designerAcknowledged: boolean;
  factGroups: readonly StudioProjectedFactGroup[];
  unresolvedQuestions: readonly string[];
  sourceReview: {
    eligible: boolean;
    state: 'not_ready' | 'ready' | 'complete';
    reason: string;
  };
}

export interface StudioDesignConfirmationAudit {
  auditId: string;
  status: 'pass' | 'fail';
  issues: readonly string[];
  review: StudioDesignConfirmationReview;
}

export interface StudioDesignConfirmationReceipt {
  confirmationId: string;
  auditId: string;
  project: ProjectDetail;
}

/**
 * Typed boundary for the future confirmation DTO. A transport may be mocked
 * during Studio integration without weakening the visual lineage contract.
 */
export interface StudioDesignConfirmationGateway {
  loadDesignConfirmation(request: StudioVisualLineage & {
    createdBy: string;
    notes?: string;
  }): Promise<StudioGatewayResult<StudioDesignConfirmationReview>>;
  auditDesignConfirmation(
    review: StudioDesignConfirmationReview,
  ): Promise<StudioGatewayResult<StudioDesignConfirmationAudit>>;
  saveDesignConfirmation(
    audit: StudioDesignConfirmationAudit,
  ): Promise<StudioGatewayResult<StudioDesignConfirmationReceipt>>;
}

export function createStudioDesignConfirmationGateway(
  transport: StudioDesignConfirmationGateway,
): StudioDesignConfirmationGateway {
  return transport;
}

export type StudioVisualPreviewRequest = StudioVisualLineage & {
  createdBy: string;
  instruction: string;
  variant?: number;
} & (
  | { scope: 'appearance'; maskBase64?: never; markupAssetId?: never }
  | { scope: 'marked_region'; maskBase64: string; markupAssetId?: never }
  | { scope: 'marked_region'; markupAssetId: string; maskBase64?: never }
);

export interface StudioVisualPreview {
  candidate: PreviewCandidate;
  lineage: StudioVisualLineage;
  instruction: string;
  scope: CreateVisualPreviewRequest['scope'];
}

export interface StudioCatalogPreview {
  candidate: PreviewCandidate;
  lineage: ExactStudioLineage;
  componentPath: CatalogPreviewRequest['component_path'];
  optionId: string;
}

export interface StudioMarkupPreview {
  candidate: PreviewCandidate;
  lineage: ExactStudioLineage;
  annotation: MarkupApplyRequest['annotation'];
}

export interface StudioResumedRefinePreview {
  candidate: PreviewCandidate;
  kind: 'catalog' | 'markup' | 'visual';
  understoodAs: string;
}

export interface StudioReviewJobEnvelope {
  job: StudioJobRecord;
  project: ProjectDetail;
  lineage: ExactStudioLineage | StudioVisualLineage;
  sourceImageUrl: string | null;
  sourceIsActive: boolean;
  allowedDecisions: {
    apply: boolean;
    discard: true;
    saveAsVariation: boolean;
  };
}

export interface StudioVariationRequest extends StudioVisualLineage {
  sourceDesignVersion: number | null;
  createdBy: string;
  label: string;
}

export interface StudioCatalogPreviewRequest extends ExactStudioLineage {
  createdBy: string;
  componentPath: CatalogPreviewRequest['component_path'];
  optionId: string;
  variant?: number;
  stoneSpecies?: string;
  chainGeometry?: CatalogPreviewRequest['chain_geometry'];
  chainProduction?: CatalogPreviewRequest['chain_production'];
}

export interface StudioMarkupPreviewRequest extends ExactStudioLineage {
  createdBy: string;
  annotation: MarkupApplyRequest['annotation'];
  markupAssetId?: string | null;
  variant?: number;
}

export interface StudioCandidateDecisionRequest {
  candidateId: string;
  createdBy: string;
}

export interface StudioCandidateVariationRequest extends StudioCandidateDecisionRequest {
  label: string;
}

export interface StudioCandidateVariationResult {
  candidate: PreviewCandidate;
  project: ProjectDetail;
  familyId: string;
  variationIndex: number;
}

export interface StudioCandidateDecisionResult {
  candidate: PreviewCandidate;
  project: ProjectDetail | null;
}

export interface StudioViewRequest extends ExactStudioLineage {
  createdBy: string;
  view: CreateLineArtRequest['view'];
  sourceRegionDescription?: string;
  sourceRegion?: CreateLineArtRequest['source_region'];
  variant?: number;
}

export interface StudioViewPreview {
  candidateId: string;
  runId: string;
  previewUrl: string;
  view: CreateLineArtRequest['view'];
  lineage: ExactStudioLineage;
  verdict: 'pass' | 'warn' | 'fail';
  checks: readonly PreviewCheck[];
}

export interface StudioViewDecisionResult {
  preview: StudioViewPreview;
  project: ProjectDetail | null;
}

export interface StudioExactPresentationPreview {
  candidate: PreSpecPresentationResumeCandidate;
  lineage: ExactStudioLineage;
}

export interface StudioPresentationDecisionResult {
  candidateId: string;
  project: ProjectDetail;
}

export interface StudioPreSpecPresentationDecisionResult {
  candidateId: string;
  project: ProjectDetail;
}

export interface StudioFactoryEligibility {
  enabled: boolean;
  eligible: boolean;
  projectId: string;
  pinnedAssetId: string | null;
  designVersion: number | null;
  blockers: readonly string[];
}

type GatewayTrustedClient = Pick<TrustedApiClient,
  | 'createProjectFromBrief'
  | 'createProjectFromDrawing'
  | 'createProjectFromPrompt'
  | 'selectCreativeCandidate'
  | 'commitCreativeDirections'
  | 'saveAsVariation'
  | 'saveCreativeCandidateAsVariation'
  | 'previewCatalogSelection'
  | 'listCatalogPreviews'
  | 'acceptCatalogPreview'
  | 'discardCatalogPreview'
  | 'saveCatalogPreviewAsVariation'
  | 'applyMarkup'
  | 'listStudioMarkupCandidates'
  | 'acceptStudioMarkupCandidate'
  | 'discardStudioMarkupCandidate'
  | 'saveStudioMarkupPreviewAsVariation'
  | 'acceptWarningCandidate'
  | 'discardWarningCandidate'
  | 'acceptPresentationCandidate'
  | 'discardPresentationCandidate'
  | 'listStudioViewCandidates'
  | 'acceptStudioViewCandidate'
  | 'discardStudioViewCandidate'
  | 'createLineArt'
  | 'createBeautyRender'
  | 'createProductPhoto'
  | 'createMarketingPack'
  | 'recordImageRunFeedback'
  | 'getProject'
  | 'getFactoryPack'
  | 'prepareFactoryPack'
  | 'createChecklist'
  | 'respondChecklist'
  | 'getComponentCatalog'
  | 'getStudioComponentTargeting'
  | 'prepareStudioComponentMap'
  | 'readMarkup'
  | 'reviseStudioFacts'
  | 'getDesignFamily'
  | 'listDesignFamilies'
  | 'getStudioProjectHistory'
  | 'restoreStudioRevision'
  | 'assetImageUrl'
  | 'createStudioJob'
  | 'listStudioJobs'
  | 'getStudioJob'
  | 'transitionStudioJob'
  | 'cancelStudioJob'
  | 'createVisualPreview'
  | 'listVisualPreviews'
  | 'acceptVisualPreview'
  | 'discardVisualPreview'
  | 'saveVisualPreviewAsVariation'
  | 'listPreSpecPresentations'
  | 'createPreSpecPresentation'
  | 'acceptPreSpecPresentation'
  | 'discardPreSpecPresentation'
  | 'confirmCreativeCandidateDesign'
  | 'promoteCreativeCandidate'
> & Partial<Pick<TrustedApiClient, 'getStudioCapabilities'>>;

export interface StudioGatewayOptions {
  /** Persist designer-visible Activity. Disabled for isolated adapters/tests. */
  trackJobs?: boolean;
  now?: () => Date;
}

interface ActiveStudioJob {
  jobId: string;
  owner: string;
}

const gatewayError = (
  code: string,
  message: string,
  category: StudioGatewayErrorCategory,
  status = 0,
  retryable = false,
): StudioGatewayResult<never> => ({
  data: null,
  error: { code, message, category, status, retryable },
  status,
});

function mapError(error: ApiError): StudioGatewayError {
  const category: StudioGatewayErrorCategory = error.category === 'network'
    ? 'network'
    : error.category === 'authentication'
      ? 'authentication'
      : error.category === 'not_found'
        ? 'not_found'
    : error.category === 'validation'
      ? 'validation'
      : error.category === 'conflict' || error.category === 'stale_version'
        ? 'conflict'
        : error.category === 'quality'
          ? 'quality'
          : error.category === 'decode'
            ? 'invalid_response'
            : 'unavailable';
  return {
    code: error.code,
    message: error.message,
    category,
    status: error.status,
    retryable: error.retryable,
  };
}

function mapResult<T>(result: ApiResult<T>): StudioGatewayResult<T> {
  return result.error === null
    ? result
    : { data: null, error: mapError(result.error), status: result.status };
}

function exactLineage(project: ProjectDetail): ExactStudioLineage | null {
  if (
    project.active_asset_id === null
    || project.active_design_version === null
    || project.active_revision === null
    || project.active_revision.asset_id !== project.active_asset_id
    || project.active_revision.design_version !== project.active_design_version
  ) return null;
  return {
    projectId: project.root_id,
    sourceAssetId: project.active_asset_id,
    sourceDesignVersion: project.active_design_version,
  };
}

function previewChecks(result: CatalogPreviewResult): readonly PreviewCheck[] {
  return qualityPreviewChecks(result.qa);
}

function qualityPreviewChecks(qa: ImageQualityReport): readonly PreviewCheck[] {
  return qa.checks.map((check) => ({
    id: check.key,
    label: check.label,
    verdict: check.verdict === 'fail' ? 'reject' : check.verdict,
    detail: check.message || null,
  }));
}

function expiresAt(now: Date, seconds: number): string {
  return new Date(now.getTime() + seconds * 1000).toISOString();
}

function sameJson(left: unknown, right: unknown): boolean {
  if (left === right) return true;
  if (Array.isArray(left) || Array.isArray(right)) {
    return Array.isArray(left) && Array.isArray(right)
      && left.length === right.length
      && left.every((value, index) => sameJson(value, right[index]));
  }
  if (left !== null && right !== null && typeof left === 'object' && typeof right === 'object') {
    const leftRecord = left as Record<string, unknown>;
    const rightRecord = right as Record<string, unknown>;
    const keys = Object.keys(leftRecord);
    return keys.length === Object.keys(rightRecord).length
      && keys.every((key) => Object.prototype.hasOwnProperty.call(rightRecord, key)
        && sameJson(leftRecord[key], rightRecord[key]));
  }
  return false;
}

function preservesProposedSpec(projectSpec: JsonObject | null | undefined, proposed: JsonObject): boolean {
  if (projectSpec === null || projectSpec === undefined) return false;
  const generated = new Set(['design_id', 'version', 'created_by', 'created_at']);
  return Object.keys(proposed).every((key) => (
    generated.has(key) || (Object.prototype.hasOwnProperty.call(projectSpec, key)
      && sameJson(projectSpec[key], proposed[key]))
  ));
}

export function createStudioGateway(
  client: GatewayTrustedClient,
  options: StudioGatewayOptions = {},
) {
  const trackJobs = options.trackJobs ?? false;
  const now = options.now ?? (() => new Date());
  let confirmationReviewSequence = 0;
  // Same-session convenience only. The durable StudioJob id is sent to the
  // selection endpoint, and Activity supplies it again after a restart.
  const creativeJobs = new Map<string, ActiveStudioJob>();
  const catalogCandidates = new Map<string, {
    trusted: CatalogPreviewCandidate;
    preview: PreviewCandidate;
    lineage: ExactStudioLineage;
    proposedSpec: JsonObject;
    studioJob: ActiveStudioJob | null;
  }>();
  const markupCandidates = new Map<string, {
    trusted: StudioMarkupResumeCandidate | null;
    runId: string;
    candidateId: string;
    preview: PreviewCandidate;
    lineage: ExactStudioLineage;
    studioJob: ActiveStudioJob | null;
  }>();
  const viewCandidates = new Map<string, {
    preview: StudioViewPreview;
    status: 'pending_review' | 'accepted' | 'discarded';
    studioJob: ActiveStudioJob | null;
  }>();
  type PresentationDecision = 'pending_review' | 'accepted' | 'discarded';
  interface PresentationGroup {
    studioJob: ActiveStudioJob | null;
    lineage: ExactStudioLineage;
    decisions: Map<string, PresentationDecision>;
  }
  const presentationCandidates = new Map<string, {
    runId: string;
    candidateId: string;
    capability: 'CLIENT_BEAUTY_RENDER' | 'CLIENT_PRODUCT_PHOTO' | 'MARKETING_IMAGE';
    group: PresentationGroup;
  }>();
  const designConfirmations = new Map<string, {
    lineage: StudioVisualLineage;
    createdBy: string;
    candidateSha256: string;
    specVisualHash: string;
    confirmationToken: string;
    expiresAt: string;
    originalValues: Map<string, string>;
  }>();
  const pruneExpiredConfirmations = (): void => {
    const timestamp = now().getTime();
    designConfirmations.forEach((confirmation, reviewId) => {
      if (Date.parse(confirmation.expiresAt) <= timestamp) {
        designConfirmations.delete(reviewId);
      }
    });
  };
  const visualCandidates = new Map<string, {
    runId: string;
    saveAsVariationUrl: string;
    preview: StudioVisualPreview;
    studioJob: ActiveStudioJob | null;
  }>();
  const preSpecPresentationCandidates = new Map<string, {
    runId: string;
    candidateId: string;
    sourceHash: string;
    capability: 'CLIENT_BEAUTY_RENDER' | 'CLIENT_PRODUCT_PHOTO' | 'MARKETING_IMAGE';
    lineage: StudioVisualLineage;
    studioJob: ActiveStudioJob | null;
    status: 'pending_review' | 'accepted' | 'discarded';
  }>();

  const requireCandidate = (candidateId: string) => catalogCandidates.get(candidateId) ?? null;

  const trackingError = (error: unknown): StudioGatewayResult<never> => gatewayError(
    'STUDIO_ACTIVITY_UNAVAILABLE',
    error instanceof Error ? error.message : 'Studio Activity could not be updated.',
    'unavailable',
    0,
    true,
  );

  const startJob = async (
    actionId: StudioJobAction,
    owner: string,
    requestedOutputs: number,
    lineage?: StudioVisualLineage,
  ): Promise<StudioGatewayResult<ActiveStudioJob | null>> => {
    if (!trackJobs) return { data: null, error: null, status: 0 };
    const action = getStudioAction(actionId);
    if (action.lane === null || action.creditEstimate === null) {
      return gatewayError(
        'INVALID_STUDIO_ACTION', 'This action cannot create a Studio job.',
        'validation', 422,
      );
    }
    try {
      const created = await client.createStudioJob({
        owner,
        action_id: actionId,
        lane: action.lane,
        active_design_id: lineage?.projectId ?? null,
        source_revision_id: lineage?.sourceAssetId ?? null,
        requested_outputs: requestedOutputs,
        credits_per_output: action.creditEstimate,
      });
      if (created.error !== null) {
        return { data: null, error: mapError(created.error), status: created.status };
      }
      const running = await client.transitionStudioJob(created.data.job_id, {
        owner,
        status: 'running',
        progress: 0.05,
      });
      if (running.error !== null) {
        return { data: null, error: mapError(running.error), status: running.status };
      }
      return {
        data: { jobId: running.data.job_id, owner },
        error: null,
        status: running.status,
      };
    } catch (error) {
      return trackingError(error);
    }
  };

  const transitionJob = async (
    job: ActiveStudioJob | null,
    status: 'reviewing' | 'succeeded' | 'failed',
    progress: number,
    completedOutputs?: number,
    errorCode?: string,
    binding?: { activeDesignId?: string; sourceRevisionId?: string },
  ): Promise<StudioGatewayResult<StudioJobRecord | null>> => {
    if (job === null) return { data: null, error: null, status: 0 };
    try {
      const result = await client.transitionStudioJob(job.jobId, {
        owner: job.owner,
        status,
        progress,
        ...(completedOutputs === undefined ? {} : { completed_outputs: completedOutputs }),
        ...(errorCode === undefined ? {} : { error_code: errorCode }),
        ...(binding?.activeDesignId === undefined
          ? {} : { active_design_id: binding.activeDesignId }),
        ...(binding?.sourceRevisionId === undefined
          ? {} : { source_revision_id: binding.sourceRevisionId }),
      });
      return result.error === null
        ? result
        : { data: null, error: mapError(result.error), status: result.status };
    } catch (error) {
      return trackingError(error);
    }
  };

  const failJob = async (
    job: ActiveStudioJob | null,
    code: string,
    progress = 1,
  ): Promise<void> => {
    // Preserve the action's original error. Activity repair is retryable, but
    // it must never disguise why generation itself failed. A terminal failure
    // uses monotonic completion progress so a job already at review (0.9)
    // cannot get stranded there by a rejected backward progress transition.
    await transitionJob(job, 'failed', progress, undefined, code);
  };

  const finishPresentationGroup = async (
    group: PresentationGroup,
  ): Promise<StudioGatewayResult<StudioJobRecord | null>> => {
    const decisions = [...group.decisions.values()];
    if (decisions.some((decision) => decision === 'pending_review')) {
      return { data: null, error: null, status: 0 };
    }
    // Exact presentation decision endpoints settle the bound StudioJob and
    // accepted-output billing atomically. A second mobile transition could
    // double-charge or overwrite the server's grouped decision state.
    return { data: null, error: null, status: 0 };
  };

  const registerPresentationCandidates = (
    studioJob: ActiveStudioJob | null,
    lineage: ExactStudioLineage,
    candidates: readonly {
      runId: string;
      candidateId: string;
      capability: 'CLIENT_BEAUTY_RENDER' | 'CLIENT_PRODUCT_PHOTO' | 'MARKETING_IMAGE';
    }[],
  ): boolean => {
    if (candidates.length === 0
      || candidates.some(({ candidateId, runId }) => !candidateId || !runId)
      || new Set(candidates.map(({ candidateId }) => candidateId)).size !== candidates.length
      || candidates.some(({ candidateId }) => presentationCandidates.has(candidateId))) {
      return false;
    }
    const group: PresentationGroup = {
      studioJob,
      lineage,
      decisions: new Map(candidates.map(({ candidateId }) => [candidateId, 'pending_review'])),
    };
    candidates.forEach((candidate) => presentationCandidates.set(candidate.candidateId, {
      ...candidate,
      group,
    }));
    return true;
  };

  const requireReviewJob = async (
    jobId: string | null,
    owner: string,
    actionId: 'views' | 'present',
    lineage: ExactStudioLineage,
    candidateCount: number,
  ): Promise<StudioGatewayResult<ActiveStudioJob>> => {
    if (jobId === null) return gatewayError(
      'STUDIO_REVIEW_JOB_MISSING',
      'This saved preview is missing its durable Activity record.',
      'invalid_response', 409,
    );
    const listed = await client.listStudioJobs(owner, 'reviewing');
    if (listed.error !== null) {
      return { data: null, error: mapError(listed.error), status: listed.status };
    }
    const job = listed.data.jobs.find((item) => item.job_id === jobId);
    if (job === undefined
      || job.action_id !== actionId
      || job.status !== 'reviewing'
      || job.active_design_id !== lineage.projectId
      || job.source_revision_id !== lineage.sourceAssetId
      || job.billing.requested_outputs < candidateCount) {
      return gatewayError(
        'STUDIO_REVIEW_JOB_MISMATCH',
        'This saved preview is not bound to the selected immutable revision and Activity job.',
        'conflict', 409,
      );
    }
    return { data: { jobId, owner }, error: null, status: listed.status };
  };

  const callTracked = async <T>(
    job: ActiveStudioJob | null,
    operation: () => Promise<ApiResult<T>>,
  ): Promise<StudioGatewayResult<T>> => {
    try {
      const result = await operation();
      if (result.error !== null) {
        await failJob(job, result.error.code);
        return { data: null, error: mapError(result.error), status: result.status };
      }
      return result;
    } catch (error) {
      await failJob(job, 'UNEXPECTED_GENERATION_FAILURE');
      return gatewayError(
        'UNEXPECTED_GENERATION_FAILURE',
        error instanceof Error ? error.message : 'The Studio request failed unexpectedly.',
        'unavailable', 0, true,
      );
    }
  };

  const creativeOutputCount = (project: ProjectDetail, requested: number): number => {
    // New Studio projects keep generated directions outside the immutable
    // revision chain until the designer explicitly selects one. Count that
    // canonical pre-selection collection first; revisions/active_revision are
    // compatibility fallbacks for already-selected and historical payloads.
    const directions = project.creative_candidates?.filter((candidate) => (
      candidate.capability === 'CREATIVE_RENDER'
      && candidate.design_version === null
    )).length ?? 0;
    const outputs = project.revisions.filter(
      (revision) => revision.asset.capability === 'CREATIVE_RENDER',
    ).length;
    return Math.min(
      requested,
      Math.max(directions, outputs, project.active_revision === null ? 0 : 1),
    );
  };

  const getFactoryEligibility = async (
    projectId: string,
  ): Promise<StudioGatewayResult<StudioFactoryEligibility>> => {
    const capabilities = client.getStudioCapabilities === undefined
      ? gatewayError(
        'FACTORY_ENTITLEMENT_UNAVAILABLE',
        'Facetta could not verify Factory access.',
        'unavailable', 0, true,
      )
      : mapResult<StudioCapabilities>(await client.getStudioCapabilities());
    if (capabilities.error !== null) return {
      data: null, error: capabilities.error, status: capabilities.status,
    };
    if (!capabilities.data.factory_review.enabled) return {
      data: {
        enabled: false,
        eligible: false,
        projectId,
        pinnedAssetId: null,
        designVersion: null,
        blockers: ['Factory review is not enabled for this account.'],
      },
      error: null,
      status: 200,
    };
    const result = await client.getProject(projectId);
    if (result.error !== null) return { data: null, error: mapError(result.error), status: result.status };
    const pinned = result.data.pinned_revision;
    const blockers = result.data.factory_blockers.map((blocker) => blocker.detail);
    const eligible = result.data.factory_ready && pinned !== null
      && pinned.design_version !== null && blockers.length === 0;
    return {
      data: {
        enabled: true,
        eligible,
        projectId: result.data.root_id,
        pinnedAssetId: pinned?.asset_id ?? null,
        designVersion: pinned?.design_version ?? null,
        blockers: eligible ? [] : blockers.length > 0
          ? blockers : ['An approved, pinned revision is required.'],
      },
      error: null,
      status: result.status,
    };
  };

  return {
    /**
     * Studio-facing reads and mutations intentionally live on this facade.
     * Workspaces should depend on these contracts rather than the much larger
     * trusted client, while the gateway remains the sole compatibility seam.
     */
    async getProject(
      ...args: Parameters<GatewayTrustedClient['getProject']>
    ) {
      return mapResult(await client.getProject(...args));
    },

    async getComponentCatalog(
      ...args: Parameters<GatewayTrustedClient['getComponentCatalog']>
    ): Promise<StudioGatewayResult<ComponentCatalog>> {
      const result = await client.getComponentCatalog(...args);
      if (result.error !== null) {
        return {
          data: null,
          error: mapError(result.error as ApiError),
          status: result.status,
        };
      }
      return result;
    },

    async getStudioComponentTargeting(
      ...args: Parameters<GatewayTrustedClient['getStudioComponentTargeting']>
    ) {
      return mapResult(await client.getStudioComponentTargeting(...args));
    },

    async prepareStudioComponentMap(
      ...args: Parameters<GatewayTrustedClient['prepareStudioComponentMap']>
    ) {
      return mapResult(await client.prepareStudioComponentMap(...args));
    },

    async readMarkup(
      ...args: Parameters<GatewayTrustedClient['readMarkup']>
    ) {
      return mapResult(await client.readMarkup(...args));
    },

    async reviseStudioFacts(
      ...args: Parameters<GatewayTrustedClient['reviseStudioFacts']>
    ) {
      return mapResult(await client.reviseStudioFacts(...args));
    },

    async getDesignFamily(
      ...args: Parameters<GatewayTrustedClient['getDesignFamily']>
    ) {
      return mapResult(await client.getDesignFamily(...args));
    },

    async listDesignFamilies(
      ...args: Parameters<GatewayTrustedClient['listDesignFamilies']>
    ) {
      return mapResult(await client.listDesignFamilies(...args));
    },

    async getStudioProjectHistory(
      ...args: Parameters<GatewayTrustedClient['getStudioProjectHistory']>
    ) {
      return mapResult(await client.getStudioProjectHistory(...args));
    },

    async restoreStudioRevision(
      ...args: Parameters<GatewayTrustedClient['restoreStudioRevision']>
    ) {
      return mapResult(await client.restoreStudioRevision(...args));
    },

    async saveAsVariation(
      ...args: Parameters<GatewayTrustedClient['saveAsVariation']>
    ) {
      return mapResult(await client.saveAsVariation(...args));
    },

    assetImageUrl(...args: Parameters<GatewayTrustedClient['assetImageUrl']>) {
      return client.assetImageUrl(...args);
    },

    async listStudioJobs(
      ...args: Parameters<GatewayTrustedClient['listStudioJobs']>
    ) {
      return mapResult(await client.listStudioJobs(...args));
    },

    async resumeReviewJob(
      jobId: string,
      owner: string,
    ): Promise<StudioGatewayResult<StudioReviewJobEnvelope>> {
      const jobResult = await client.getStudioJob(jobId, owner);
      if (jobResult.error !== null) return {
        data: null, error: mapError(jobResult.error), status: jobResult.status,
      };
      const job = jobResult.data;
      if (job.status !== 'reviewing'
        || !['refine', 'views', 'present'].includes(job.action_id)
        || job.active_design_id === null
        || job.source_revision_id === null) {
        return gatewayError(
          'STUDIO_REVIEW_JOB_NOT_REVIEWABLE',
          'This Activity item no longer has a reviewable result.',
          'conflict', 409,
        );
      }
      const projectResult = await client.getProject(job.active_design_id);
      if (projectResult.error !== null) return {
        data: null, error: mapError(projectResult.error), status: projectResult.status,
      };
      const project = projectResult.data;
      const revision = project.revisions.find(
        (item) => item.asset.asset_id === job.source_revision_id,
      );
      if (project.root_id !== job.active_design_id || revision === undefined) {
        return gatewayError(
          'STUDIO_REVIEW_SOURCE_UNAVAILABLE',
          'The immutable source revision for this result is unavailable.',
          'invalid_response', 409,
        );
      }
      const lineage: ExactStudioLineage | StudioVisualLineage = revision.asset.design_version === null
        ? { projectId: project.root_id, sourceAssetId: revision.asset.asset_id }
        : {
          projectId: project.root_id,
          sourceAssetId: revision.asset.asset_id,
          sourceDesignVersion: revision.asset.design_version,
        };
      const sourceIsActive = project.active_asset_id === revision.asset.asset_id
        && project.active_design_version === revision.asset.design_version;
      return {
        data: {
          job, project, lineage,
          sourceImageUrl: revision.asset.image_url ?? null,
          sourceIsActive,
          allowedDecisions: {
            apply: sourceIsActive,
            discard: true,
            saveAsVariation: job.action_id === 'refine',
          },
        },
        error: null,
        status: projectResult.status,
      };
    },

    async cancelStudioJob(
      ...args: Parameters<GatewayTrustedClient['cancelStudioJob']>
    ) {
      return mapResult(await client.cancelStudioJob(...args));
    },

    async createStudioJob(
      ...args: Parameters<GatewayTrustedClient['createStudioJob']>
    ) {
      return mapResult(await client.createStudioJob(...args));
    },

    async transitionStudioJob(
      ...args: Parameters<GatewayTrustedClient['transitionStudioJob']>
    ) {
      return mapResult(await client.transitionStudioJob(...args));
    },

    async getFactoryPack(
      ...args: Parameters<GatewayTrustedClient['getFactoryPack']>
    ) {
      return mapResult(await client.getFactoryPack(...args));
    },

    async prepareFactoryPack(
      ...args: Parameters<GatewayTrustedClient['prepareFactoryPack']>
    ) {
      return mapResult(await client.prepareFactoryPack(...args));
    },

    async createChecklist(
      ...args: Parameters<GatewayTrustedClient['createChecklist']>
    ) {
      return mapResult(await client.createChecklist(...args));
    },

    async respondChecklist(
      ...args: Parameters<GatewayTrustedClient['respondChecklist']>
    ) {
      return mapResult(await client.respondChecklist(...args));
    },

    async loadDesignConfirmation(request: StudioVisualLineage & {
      createdBy: string; notes?: string;
    }): Promise<StudioGatewayResult<StudioDesignConfirmationReview>> {
      pruneExpiredConfirmations();
      const result = await client.confirmCreativeCandidateDesign(
        request.projectId, request.sourceAssetId,
        { created_by: request.createdBy, notes: request.notes, run_independent_audit: true },
      );
      if (result.error !== null) return { data: null, error: mapError(result.error), status: result.status };
      if (result.data.candidate_id !== request.sourceAssetId) return gatewayError(
        'CONFIRM_SOURCE_MISMATCH', 'The reviewed details did not match the selected visual.',
        'conflict', 409,
      );
      if (Date.parse(result.data.expires_at) <= now().getTime()) return gatewayError(
        'CONFIRM_REVIEW_EXPIRED', 'Reload the selected visual before reviewing these details.',
        'conflict', 409,
      );
      confirmationReviewSequence += 1;
      const reviewId = [
        request.projectId, request.sourceAssetId,
        result.data.candidate_sha256, result.data.spec_visual_hash,
        confirmationReviewSequence,
      ].join(':');
      const factGroups = result.data.fact_groups.map((group) => ({
        key: group.key, label: group.label,
        facts: group.facts.map((fact) => ({ ...fact })),
      }));
      designConfirmations.set(reviewId, {
        lineage: request,
        createdBy: request.createdBy,
        candidateSha256: result.data.candidate_sha256,
        specVisualHash: result.data.spec_visual_hash,
        confirmationToken: result.data.confirmation_token,
        expiresAt: result.data.expires_at,
        originalValues: new Map(factGroups.flatMap((group) => group.facts.map(
          (fact) => [`${group.key}.${fact.key}`, fact.value] as const,
        ))),
      });
      return {
        data: {
          reviewId, factGroups,
          designerAcknowledged: false,
          unresolvedQuestions: result.data.unresolved_source_questions,
          sourceReview: result.data.audit_eligibility,
        },
        error: null,
        status: result.status,
      };
    },

    async auditDesignConfirmation(
      review: StudioDesignConfirmationReview,
    ): Promise<StudioGatewayResult<StudioDesignConfirmationAudit>> {
      pruneExpiredConfirmations();
      const stored = designConfirmations.get(review.reviewId);
      if (!stored) return gatewayError(
        'CONFIRM_REVIEW_EXPIRED', 'Reload the selected visual before saving these details.',
        'conflict', 409,
      );
      const changedValues = review.factGroups.flatMap((group) => group.facts.filter(
        (fact) => stored.originalValues.get(`${group.key}.${fact.key}`) !== fact.value,
      ));
      const issues = [
        ...(review.designerAcknowledged ? [] : [
          'Acknowledge that these are image-derived suggestions before creating Design v1.',
        ]),
        ...(changedValues.length === 0 ? [] : [
          'Create Design v1 first, then refine changed facts as a new immutable revision.',
        ]),
      ];
      return {
        data: {
          auditId: review.reviewId,
          status: issues.length === 0 ? 'pass' : 'fail',
          issues,
          review,
        },
        error: null,
        status: 200,
      };
    },

    async saveDesignConfirmation(
      audit: StudioDesignConfirmationAudit,
    ): Promise<StudioGatewayResult<StudioDesignConfirmationReceipt>> {
      if (audit.status !== 'pass'
        || !audit.review.designerAcknowledged) return gatewayError(
        'CONFIRM_AUDIT_REQUIRED', 'Review the image-derived starting facts before saving.',
        'validation', 422,
      );
      pruneExpiredConfirmations();
      const stored = designConfirmations.get(audit.auditId);
      if (!stored) return gatewayError(
        'CONFIRM_REVIEW_EXPIRED', 'Reload the selected visual before saving these details.',
        'conflict', 409,
      );
      const promoted = await client.promoteCreativeCandidate(
        stored.lineage.projectId,
        stored.lineage.sourceAssetId,
        {
          created_by: stored.createdBy,
          confirmation_token: stored.confirmationToken,
        },
      );
      if (promoted.error !== null) return { data: null, error: mapError(promoted.error), status: promoted.status };
      designConfirmations.delete(audit.auditId);
      return {
        data: { confirmationId: audit.auditId, auditId: audit.auditId, project: promoted.data },
        error: null,
        status: promoted.status,
      };
    },

    createFromBrief(request: CreateProjectFromBriefRequest): Promise<StudioGatewayResult<ProjectCreationResult>> {
      return client.createProjectFromBrief(request).then(mapResult);
    },

    async createFromPrompt(
      request: CreateProjectFromPromptRequest,
    ): Promise<StudioGatewayResult<ProjectDetail>> {
      const requested = request.variation_count ?? 1;
      const started = await startJob('create', request.owner, requested);
      if (started.error !== null) return started;
      const result = await callTracked(started.data, () => client.createProjectFromPrompt(request));
      if (result.error !== null) return result;
      const completedOutputs = creativeOutputCount(result.data, requested);
      if (completedOutputs === 0) {
        await failJob(started.data, 'NO_CREATIVE_OUTPUTS', 0.9);
        return gatewayError(
          'NO_CREATIVE_OUTPUTS', 'The request did not return a reviewable direction.',
          'quality', result.status,
        );
      }
      const reviewing = await transitionJob(
        started.data, 'reviewing', 0.9, undefined, undefined,
        { activeDesignId: result.data.root_id },
      );
      if (reviewing.error !== null) return reviewing;
      if (started.data !== null) {
        creativeJobs.set(result.data.root_id, started.data);
      }
      return result;
    },

    async createFromDrawing(
      request: CreateProjectFromDrawingRequest,
    ): Promise<StudioGatewayResult<ProjectDetail>> {
      const requested = request.variation_count ?? 1;
      const started = await startJob('create', request.owner, requested);
      if (started.error !== null) return started;
      const result = await callTracked(started.data, () => client.createProjectFromDrawing(request));
      if (result.error !== null) return result;
      const completedOutputs = creativeOutputCount(result.data, requested);
      if (completedOutputs === 0) {
        await failJob(started.data, 'NO_CREATIVE_OUTPUTS', 0.9);
        return gatewayError(
          'NO_CREATIVE_OUTPUTS', 'The drawing did not return a reviewable direction.',
          'quality', result.status,
        );
      }
      const reviewing = await transitionJob(
        started.data, 'reviewing', 0.9, undefined, undefined,
        { activeDesignId: result.data.root_id },
      );
      if (reviewing.error !== null) return reviewing;
      if (started.data !== null) {
        creativeJobs.set(result.data.root_id, started.data);
      }
      return result;
    },

    async selectCreativeDirection(
      projectId: string,
      candidateId: string,
      createdBy: string,
      studioJobId?: string,
    ): Promise<StudioGatewayResult<ProjectDetail>> {
      const tracked = creativeJobs.get(projectId) ?? null;
      const durableJobId = studioJobId ?? tracked?.jobId;
      const result = await client.selectCreativeCandidate(
        projectId, candidateId, createdBy, durableJobId,
      );
      if (result.error !== null) {
        return { data: null, error: mapError(result.error), status: result.status };
      }
      // When present, the backend verifies and settles the durable reviewing
      // job atomically with candidate selection. A second client transition
      // would reintroduce restart sensitivity and could double-settle billing.
      creativeJobs.delete(projectId);
      return result;
    },

    async completeCreativeDirectionReview(
      request: StudioCreativeDirectionReviewRequest,
    ): Promise<StudioGatewayResult<CommitCreativeDirectionsResult>> {
      const retainedCandidateIds = request.retained.map((direction) => direction.candidateId);
      const valid = request.projectId.trim().length > 0
        && request.selectedCandidateId.trim().length > 0
        && request.createdBy.trim().length > 0
        && request.retained.length <= 3
        && request.retained.every((direction) => (
          direction.candidateId.trim().length > 0 && direction.label.trim().length > 0
        ))
        && !retainedCandidateIds.includes(request.selectedCandidateId)
        && new Set(retainedCandidateIds).size === retainedCandidateIds.length;
      if (!valid) return gatewayError(
        'INVALID_CREATIVE_DIRECTION_REVIEW',
        'Choose one Original and review the directions you want to keep.',
        'validation', 422,
      );

      const tracked = creativeJobs.get(request.projectId) ?? null;
      const studioJobId = request.studioJobId ?? tracked?.jobId;
      const result = await client.commitCreativeDirections(request.projectId, {
        created_by: request.createdBy,
        selected_candidate_id: request.selectedCandidateId,
        retained: request.retained.map((direction) => ({
          candidate_id: direction.candidateId,
          label: direction.label.trim(),
        })),
        ...(studioJobId === undefined ? {} : { studio_job_id: studioJobId }),
      });
      if (result.error !== null) {
        return { data: null, error: mapError(result.error), status: result.status };
      }

      const selectedAssetId = result.data.project.selected_candidate_asset_id
        ?? result.data.project.active_asset_id;
      const returnedCandidateIds = result.data.retained_variations.map(
        (variation) => variation.source_asset_id,
      );
      if (
        selectedAssetId !== request.selectedCandidateId
        || result.data.retained_variations.length !== retainedCandidateIds.length
        || result.data.retained_variations.some((variation) => (
          variation.source_project_id !== request.projectId
        ))
        || new Set(returnedCandidateIds).size !== returnedCandidateIds.length
        || retainedCandidateIds.some((candidateId) => !returnedCandidateIds.includes(candidateId))
      ) return gatewayError(
        'INVALID_CREATIVE_DIRECTION_COMMIT',
        'The saved direction set did not match your review.',
        'invalid_response', result.status,
      );

      creativeJobs.delete(request.projectId);
      return result;
    },

    async saveCurrentAsVariation(
      request: StudioVariationRequest,
    ): Promise<StudioGatewayResult<SaveAsVariationResult>> {
      const result = await client.saveAsVariation(request.projectId, {
        created_by: request.createdBy,
        expected_active_asset_id: request.sourceAssetId,
        expected_design_version: request.sourceDesignVersion,
        label: request.label,
      });
      if (result.error !== null) return { data: null, error: mapError(result.error), status: result.status };
      if (result.data.source_asset_id !== request.sourceAssetId) {
        return gatewayError(
          'INVALID_VARIATION_LINEAGE',
          'The variation response did not preserve the requested source revision.',
          'invalid_response',
          result.status,
        );
      }
      return result;
    },

    async saveCreativeDirectionAsVariation(request: {
      projectId: string;
      candidateId: string;
      activeAssetId: string;
      createdBy: string;
      label: string;
    }): Promise<StudioGatewayResult<SaveAsVariationResult>> {
      const result = await client.saveCreativeCandidateAsVariation(
        request.projectId,
        request.candidateId,
        {
          created_by: request.createdBy,
          expected_active_asset_id: request.activeAssetId,
          expected_design_version: null,
          label: request.label,
        },
      );
      if (result.error !== null) {
        return { data: null, error: mapError(result.error), status: result.status };
      }
      if (result.data.source_asset_id !== request.candidateId) {
        return gatewayError(
          'INVALID_VARIATION_LINEAGE',
          'The saved variation did not preserve the chosen direction.',
          'invalid_response', result.status,
        );
      }
      return result;
    },

    async resumeRefine(
      lineage: ExactStudioLineage | StudioVisualLineage,
      createdBy: string,
      reviewJobId?: string,
    ): Promise<StudioGatewayResult<StudioResumedRefinePreview | null>> {
      const jobs = trackJobs
        ? await client.listStudioJobs(createdBy, 'reviewing') : null;
      const matchingJob = jobs?.error === null
        ? [...jobs.data.jobs].reverse().find((job) => (
            job.action_id === 'refine'
            && (reviewJobId === undefined || job.job_id === reviewJobId)
            && job.active_design_id === lineage.projectId
            && job.source_revision_id === lineage.sourceAssetId
          )) ?? null
        : null;
      const studioJob = matchingJob === null ? null : {
        jobId: matchingJob.job_id, owner: createdBy,
      };
      if (reviewJobId !== undefined && matchingJob === null) return gatewayError(
        'RESUME_REFINE_JOB_MISMATCH',
        'This saved refinement is not bound to the selected Activity job.',
        'conflict', 409,
      );

      if ('sourceDesignVersion' in lineage) {
        const markupResult = typeof client.listStudioMarkupCandidates === 'function'
          ? await client.listStudioMarkupCandidates(lineage.projectId) : null;
        if (markupResult !== null && markupResult.error !== null) return {
          data: null, error: mapError(markupResult.error), status: markupResult.status,
        };
        const latestMarkup = markupResult?.error === null
          ? [...markupResult.data.candidates]
          .filter((item) => item.project_root_id === lineage.projectId
            && item.source_asset_id === lineage.sourceAssetId
            && item.design_version === lineage.sourceDesignVersion)
          .filter((item) => matchingJob === null || item.studio_job_id === matchingJob.job_id)
          .sort((left, right) => (
            Date.parse(left.expires_at) - Date.parse(right.expires_at)
            || left.candidate_id.localeCompare(right.candidate_id)
          )).at(-1) : undefined;
        if (latestMarkup !== undefined) {
          const candidate: PreviewCandidate = {
            id: latestMarkup.candidate_id,
            jobId: latestMarkup.image_run_id,
            sourceRevisionId: lineage.sourceAssetId,
            assetUrl: latestMarkup.preview_url,
            verdict: latestMarkup.qa.verdict === 'fail' ? 'reject' : latestMarkup.qa.verdict,
            status: 'pending_review', checks: qualityPreviewChecks(latestMarkup.qa),
            temporary: true, expiresAt: latestMarkup.expires_at,
            decision: null, decidedAt: null, canonicalRevisionId: null,
          };
          markupCandidates.set(candidate.id, {
            trusted: latestMarkup, runId: latestMarkup.image_run_id,
            candidateId: latestMarkup.candidate_id, preview: candidate, lineage, studioJob,
          });
          return {
            data: {
              candidate, kind: 'markup',
              understoodAs: 'A pending marked-region preview was restored for review.',
            },
            error: null, status: markupResult?.status ?? 200,
          };
        }
        const result = await client.listCatalogPreviews(lineage.sourceAssetId);
        if (result.error !== null) return {
          data: null, error: mapError(result.error), status: result.status,
        };
        if (result.data.candidates.some((item) => item.source_asset_id !== lineage.sourceAssetId)) {
          return gatewayError(
            'RESUME_REFINE_LINEAGE_MISMATCH',
            'A pending preview no longer matches the selected revision.',
            'conflict', 409,
          );
        }
        const latest = [...result.data.candidates]
        .filter((item) => reviewJobId === undefined
          || item.candidate.studio_job_id === reviewJobId)
        .sort((left, right) => (
          Date.parse(left.expires_at) - Date.parse(right.expires_at)
          || left.candidate.candidate_id.localeCompare(right.candidate.candidate_id)
        )).at(-1);
        if (latest === undefined) return { data: null, error: null, status: result.status };
        const catalogJobId = latest.candidate.studio_job_id ?? null;
        const catalogJob = catalogJobId === null ? null
          : jobs?.error === null
            ? jobs.data.jobs.find((job) => (
              job.job_id === catalogJobId
              && job.action_id === 'refine'
              && job.status === 'reviewing'
              && job.active_design_id === lineage.projectId
              && job.source_revision_id === lineage.sourceAssetId
            )) ?? null
            : null;
        if (trackJobs && (catalogJobId === null || catalogJob === null)) {
          return gatewayError(
            'RESUME_REFINE_JOB_MISMATCH',
            'This pending component preview is not bound to its exact Activity request.',
            'conflict', 409,
          );
        }
        const catalogStudioJob = catalogJob === null ? null : {
          jobId: catalogJob.job_id, owner: createdBy,
        };
        const candidate: PreviewCandidate = {
          id: latest.candidate.candidate_id,
          jobId: latest.candidate.run_id,
          sourceRevisionId: lineage.sourceAssetId,
          assetUrl: latest.candidate.preview_url,
          verdict: latest.candidate.verdict,
          status: 'pending_review',
          checks: qualityPreviewChecks(latest.qa),
          temporary: true,
          expiresAt: latest.expires_at,
          decision: null, decidedAt: null, canonicalRevisionId: null,
        };
        catalogCandidates.set(candidate.id, {
          trusted: latest.candidate, preview: candidate, lineage,
          proposedSpec: latest.next_spec, studioJob: catalogStudioJob,
        });
        return {
          data: {
            candidate, kind: 'catalog',
            understoodAs: 'A pending component preview was restored for review.',
          },
          error: null,
          status: result.status,
        };
      }

      const result = await client.listVisualPreviews(lineage.projectId);
      if (result.error !== null) return {
        data: null, error: mapError(result.error), status: result.status,
      };
      if (result.data.candidates.some((item) => item.source_asset_id !== lineage.sourceAssetId)) {
        return gatewayError(
          'RESUME_REFINE_LINEAGE_MISMATCH',
          'A pending preview no longer matches the selected visual.',
          'conflict', 409,
        );
      }
      const latest = [...result.data.candidates]
      .filter((item) => reviewJobId === undefined || item.studio_job_id === reviewJobId)
      .sort((left, right) => (
        Date.parse(left.expires_at) - Date.parse(right.expires_at)
        || left.candidate_id.localeCompare(right.candidate_id)
      )).at(-1);
      if (latest === undefined) return { data: null, error: null, status: result.status };
      const candidate: PreviewCandidate = {
        id: latest.candidate_id,
        jobId: latest.image_run_id,
        sourceRevisionId: lineage.sourceAssetId,
        assetUrl: latest.preview_url,
        verdict: latest.verdict,
        status: 'pending_review',
        checks: qualityPreviewChecks(latest.qa),
        temporary: true,
        expiresAt: latest.expires_at,
        decision: null, decidedAt: null, canonicalRevisionId: null,
      };
      visualCandidates.set(candidate.id, {
        runId: latest.image_run_id,
        saveAsVariationUrl: latest.save_as_variation_url,
        preview: {
          candidate, lineage,
          instruction: latest.requested_change,
          scope: latest.scope,
        },
        studioJob,
      });
      return {
        data: {
          candidate, kind: 'visual',
          understoodAs: 'A pending visual preview was restored for review.',
        },
        error: null,
        status: result.status,
      };
    },

    async previewVisualRefine(
      request: StudioVisualPreviewRequest,
    ): Promise<StudioGatewayResult<StudioVisualPreview>> {
      const instruction = request.instruction.trim();
      if (instruction.length === 0) return gatewayError(
        'VISUAL_INSTRUCTION_REQUIRED',
        'Describe the visual change before creating a preview.',
        'validation', 422,
      );
      if (
        request.scope === 'marked_region'
        && (typeof request.maskBase64 === 'string'
          ? request.maskBase64 : request.markupAssetId).trim().length === 0
      ) {
        return gatewayError(
          'VISUAL_MASK_REQUIRED',
          'Mark the region that should change before creating this preview.',
          'validation', 422,
        );
      }
      const lineage: StudioVisualLineage = {
        projectId: request.projectId,
        sourceAssetId: request.sourceAssetId,
      };
      const started = await startJob('refine', request.createdBy, 1, lineage);
      if (started.error !== null) return started;
      const trustedRequest: CreateVisualPreviewRequest = request.scope === 'appearance'
        ? {
            created_by: request.createdBy,
            expected_active_asset_id: request.sourceAssetId,
            instruction,
            scope: 'appearance',
            ...(started.data === null ? {} : { studio_job_id: started.data.jobId }),
            ...(request.variant === undefined ? {} : { variant: request.variant }),
          }
        : typeof request.maskBase64 === 'string'
          ? {
            created_by: request.createdBy,
            expected_active_asset_id: request.sourceAssetId,
            instruction,
            scope: 'marked_region',
            ...(started.data === null ? {} : { studio_job_id: started.data.jobId }),
            mask_base64: request.maskBase64,
            ...(request.variant === undefined ? {} : { variant: request.variant }),
          }
          : {
            created_by: request.createdBy,
            expected_active_asset_id: request.sourceAssetId,
            instruction,
            scope: 'marked_region',
            ...(started.data === null ? {} : { studio_job_id: started.data.jobId }),
            markup_asset_id: request.markupAssetId,
            ...(request.variant === undefined ? {} : { variant: request.variant }),
          };
      const result = await callTracked(
        started.data,
        () => client.createVisualPreview(request.projectId, trustedRequest),
      );
      if (result.error !== null) return result;
      if (
        result.data.project_id !== request.projectId
        || result.data.source_asset_id !== request.sourceAssetId
      ) {
        await failJob(started.data, 'INVALID_VISUAL_PREVIEW_LINEAGE', 0.9);
        return gatewayError(
          'INVALID_VISUAL_PREVIEW_LINEAGE',
          'The visual preview did not match the requested immutable image revision.',
          'invalid_response', result.status,
        );
      }
      const trustedCandidate = result.data.candidate;
      const candidate: PreviewCandidate = {
        id: trustedCandidate.candidate_id,
        jobId: result.data.image_run_id,
        sourceRevisionId: request.sourceAssetId,
        assetUrl: trustedCandidate.preview_url,
        verdict: trustedCandidate.verdict === 'fail' ? 'reject' : trustedCandidate.verdict,
        status: 'pending_review',
        checks: qualityPreviewChecks(trustedCandidate.qa),
        temporary: true,
        expiresAt: null,
        decision: null,
        decidedAt: null,
        canonicalRevisionId: null,
      };
      const preview: StudioVisualPreview = {
        candidate,
        lineage,
        instruction,
        scope: request.scope,
      };
      visualCandidates.set(candidate.id, {
        runId: result.data.image_run_id,
        saveAsVariationUrl: trustedCandidate.save_as_variation_url,
        preview,
        studioJob: started.data,
      });
      // The visual-preview endpoint reserves the exact Refine job before
      // provider work and owns its reviewing state. The candidate decision
      // endpoints are the only authority for terminal status and billing.
      return { data: preview, error: null, status: result.status };
    },

    async applyVisualRefine(
      request: StudioCandidateDecisionRequest,
    ): Promise<StudioGatewayResult<StudioCandidateDecisionResult>> {
      const stored = visualCandidates.get(request.candidateId);
      if (stored === undefined) return gatewayError(
        'CANDIDATE_NOT_FOUND', 'This visual preview is no longer available.', 'validation', 404,
      );
      if (stored.preview.candidate.status !== 'pending_review') return gatewayError(
        'CANDIDATE_NOT_REVIEWABLE', 'This visual preview already has a final decision.', 'conflict', 409,
      );
      if (stored.preview.candidate.verdict === 'reject') return gatewayError(
        'CANDIDATE_REJECTED', 'A preview that failed fidelity checks cannot become design history.',
        'quality', 422,
      );
      const lineage = stored.preview.lineage;
      const result = await callTracked(stored.studioJob, () => client.acceptVisualPreview(
        stored.runId,
        stored.preview.candidate.id,
        { created_by: request.createdBy, expected_active_asset_id: lineage.sourceAssetId },
      ));
      if (result.error !== null) return result;
      if (
        result.data.project_id !== lineage.projectId
        || result.data.source_asset_id !== lineage.sourceAssetId
        || result.data.new_asset_id === lineage.sourceAssetId
        || result.data.project.active_asset_id !== result.data.new_asset_id
        || result.data.project.active_design_version !== null
      ) {
        await failJob(stored.studioJob, 'INVALID_VISUAL_ACCEPT_LINEAGE', 0.95);
        return gatewayError(
          'INVALID_VISUAL_ACCEPT_LINEAGE',
          'Applying the preview did not append the expected pre-spec image revision.',
          'invalid_response', result.status,
        );
      }
      const candidate = decidePreviewCandidate(
        stored.preview.candidate, 'apply', now().toISOString(), result.data.new_asset_id,
      );
      stored.preview = { ...stored.preview, candidate };
      // The acceptance endpoint appends the revision and settles accepted
      // output billing in one backend transaction. A public lifecycle update
      // here would either double-settle or report completion without authority.
      return { data: { candidate, project: result.data.project }, error: null, status: result.status };
    },

    async discardVisualRefine(
      request: StudioCandidateDecisionRequest,
    ): Promise<StudioGatewayResult<StudioCandidateDecisionResult>> {
      const stored = visualCandidates.get(request.candidateId);
      if (stored === undefined) return gatewayError(
        'CANDIDATE_NOT_FOUND', 'This visual preview is no longer available.', 'validation', 404,
      );
      if (stored.preview.candidate.status !== 'pending_review') return gatewayError(
        'CANDIDATE_NOT_REVIEWABLE', 'This visual preview already has a final decision.', 'conflict', 409,
      );
      const lineage = stored.preview.lineage;
      const result = await callTracked(stored.studioJob, () => client.discardVisualPreview(
        stored.runId,
        stored.preview.candidate.id,
        { created_by: request.createdBy, expected_active_asset_id: lineage.sourceAssetId },
      ));
      if (result.error !== null) return result;
      if (
        result.data.project_id !== lineage.projectId
        || result.data.candidate_id !== stored.preview.candidate.id
      ) {
        await failJob(stored.studioJob, 'INVALID_VISUAL_DISCARD_LINEAGE', 0.95);
        return gatewayError(
          'INVALID_VISUAL_DISCARD_LINEAGE',
          'The discarded preview did not match the pending candidate.',
          'invalid_response', result.status,
        );
      }
      const candidate = decidePreviewCandidate(
        stored.preview.candidate, 'discard', now().toISOString(),
      );
      stored.preview = { ...stored.preview, candidate };
      // Discard and zero-charge Activity settlement are one backend
      // transaction. Generic cancellation cannot run from reviewing.
      return { data: { candidate, project: null }, error: null, status: result.status };
    },

    async saveVisualPreviewAsVariation(
      request: StudioCandidateVariationRequest,
    ): Promise<StudioGatewayResult<StudioCandidateVariationResult>> {
      const stored = visualCandidates.get(request.candidateId);
      if (stored === undefined) return gatewayError(
        'CANDIDATE_NOT_FOUND', 'This visual preview is no longer available.', 'validation', 404,
      );
      const label = request.label.trim();
      if (label.length === 0) return gatewayError(
        'VARIATION_LABEL_REQUIRED', 'Name the variation before saving it.', 'validation', 422,
      );
      if (stored.preview.candidate.status !== 'pending_review') return gatewayError(
        'CANDIDATE_NOT_REVIEWABLE', 'This visual preview already has a final decision.', 'conflict', 409,
      );
      if (stored.preview.candidate.verdict === 'reject') return gatewayError(
        'CANDIDATE_REJECTED', 'A preview that failed fidelity checks cannot become a variation.',
        'quality', 422,
      );
      const lineage = stored.preview.lineage;
      const result = await callTracked(stored.studioJob, () => client.saveVisualPreviewAsVariation(
        stored.runId, stored.preview.candidate.id, stored.saveAsVariationUrl,
        { created_by: request.createdBy, label },
      ));
      if (result.error !== null) return result;
      const source = await client.getProject(lineage.projectId);
      if (
        source.error !== null
        || source.data.active_asset_id !== lineage.sourceAssetId
        || source.data.active_design_version !== null
        || result.data.project.root_id === lineage.projectId
        || result.data.project.active_asset_id !== result.data.project.root_id
        || result.data.project.active_design_version !== null
      ) {
        await failJob(stored.studioJob, 'INVALID_VISUAL_VARIATION_LINEAGE', 0.95);
        return gatewayError(
          'INVALID_VISUAL_VARIATION_LINEAGE',
          'The saved variation did not preserve the selected source revision.',
          'invalid_response', result.status,
        );
      }
      const candidate = decidePreviewCandidate(
        stored.preview.candidate, 'save_as_variation', now().toISOString(),
        result.data.project.active_asset_id,
      );
      // Variation acceptance and billing are likewise atomic on the backend.
      visualCandidates.delete(request.candidateId);
      return {
        data: {
          candidate, project: result.data.project, familyId: result.data.family_id,
          variationIndex: result.data.variation_index,
        },
        error: null, status: result.status,
      };
    },

    async previewCatalogRefine(
      request: StudioCatalogPreviewRequest,
    ): Promise<StudioGatewayResult<StudioCatalogPreview>> {
      const lineage: ExactStudioLineage = {
        projectId: request.projectId,
        sourceAssetId: request.sourceAssetId,
        sourceDesignVersion: request.sourceDesignVersion,
      };
      const started = await startJob('refine', request.createdBy, 1, lineage);
      if (started.error !== null) return started;
      const trustedRequest: CatalogPreviewRequest = {
        component_path: request.componentPath,
        option_id: request.optionId,
        expected_design_version: request.sourceDesignVersion,
        created_by: request.createdBy,
        ...(request.variant === undefined ? {} : { variant: request.variant }),
        ...(request.stoneSpecies === undefined ? {} : { stone_species: request.stoneSpecies }),
        ...(request.chainGeometry === undefined ? {} : { chain_geometry: request.chainGeometry }),
        ...(request.chainProduction === undefined ? {} : { chain_production: request.chainProduction }),
        ...(started.data === null ? {} : { studio_job_id: started.data.jobId }),
      };
      const result = await callTracked(
        started.data,
        () => client.previewCatalogSelection(request.sourceAssetId, trustedRequest),
      );
      if (result.error !== null) return result;
      if (
        result.data.source_asset_id !== request.sourceAssetId
        || result.data.design_version !== request.sourceDesignVersion
        || result.data.project.root_id !== request.projectId
        || (result.data.candidate.studio_job_id ?? null) !== (started.data?.jobId ?? null)
      ) {
        await failJob(started.data, 'INVALID_PREVIEW_LINEAGE', 0.9);
        return gatewayError(
          'INVALID_PREVIEW_LINEAGE',
          'The preview response did not match the requested immutable revision.',
          'invalid_response',
          result.status,
        );
      }
      const candidate: PreviewCandidate = {
        id: result.data.candidate.candidate_id,
        jobId: result.data.image_run_id,
        sourceRevisionId: request.sourceAssetId,
        assetUrl: result.data.candidate.preview_url,
        verdict: result.data.candidate.verdict,
        status: 'pending_review',
        checks: previewChecks(result.data),
        temporary: true,
        expiresAt: expiresAt(now(), result.data.candidate.expires_in_seconds),
        decision: null,
        decidedAt: null,
        canonicalRevisionId: null,
      };
      catalogCandidates.set(candidate.id, {
        trusted: result.data.candidate,
        preview: candidate,
        lineage,
        proposedSpec: result.data.next_spec,
        studioJob: started.data,
      });
      return {
        data: {
          candidate,
          lineage,
          componentPath: request.componentPath,
          optionId: request.optionId,
        },
        error: null,
        status: result.status,
      };
    },

    async applyCatalogRefine(
      request: StudioCandidateDecisionRequest,
    ): Promise<StudioGatewayResult<StudioCandidateDecisionResult>> {
      const stored = requireCandidate(request.candidateId);
      if (stored === null) return gatewayError(
        'CANDIDATE_NOT_FOUND', 'This preview is no longer available.', 'validation', 404,
      );
      if (stored.preview.status !== 'pending_review') return gatewayError(
        'CANDIDATE_NOT_REVIEWABLE', 'This preview already has a final decision.', 'conflict', 409,
      );
      const result = await client.acceptCatalogPreview(
        stored.trusted,
        {
          expected_design_version: stored.lineage.sourceDesignVersion,
          created_by: request.createdBy,
        },
      );
      if (result.error !== null) return {
        data: null, error: mapError(result.error), status: result.status,
      };
      const projectLineage = exactLineage(result.data.project);
      if (
        result.data.image_run_id !== stored.preview.jobId
        || result.data.design_version !== stored.lineage.sourceDesignVersion + 1
        || projectLineage === null
        || projectLineage.sourceAssetId !== result.data.asset_id
      ) {
        return gatewayError(
          'INVALID_ACCEPT_LINEAGE',
          'The accepted preview did not produce the expected canonical revision.',
          'invalid_response',
          result.status,
        );
      }
      const candidate = decidePreviewCandidate(
        stored.preview, 'apply', now().toISOString(), result.data.asset_id,
      );
      stored.preview = candidate;
      return { data: { candidate, project: result.data.project }, error: null, status: result.status };
    },

    async discardCatalogRefine(
      request: StudioCandidateDecisionRequest,
    ): Promise<StudioGatewayResult<StudioCandidateDecisionResult>> {
      const stored = requireCandidate(request.candidateId);
      if (stored === null) return gatewayError(
        'CANDIDATE_NOT_FOUND', 'This preview is no longer available.', 'validation', 404,
      );
      if (stored.preview.status !== 'pending_review') return gatewayError(
        'CANDIDATE_NOT_REVIEWABLE', 'This preview already has a final decision.', 'conflict', 409,
      );
      const result = await client.discardCatalogPreview(stored.trusted);
      if (result.error !== null) return {
        data: null, error: mapError(result.error), status: result.status,
      };
      const candidate = decidePreviewCandidate(stored.preview, 'discard', now().toISOString());
      stored.preview = candidate;
      return { data: { candidate, project: null }, error: null, status: result.status };
    },

    async saveCatalogPreviewAsVariation(
      request: StudioCandidateVariationRequest,
    ): Promise<StudioGatewayResult<StudioCandidateVariationResult>> {
      const stored = requireCandidate(request.candidateId);
      if (stored === null) return gatewayError(
        'CANDIDATE_NOT_FOUND', 'This preview is no longer available.', 'validation', 404,
      );
      const label = request.label.trim();
      if (label.length === 0) return gatewayError(
        'VARIATION_LABEL_REQUIRED', 'Name the variation before saving it.', 'validation', 422,
      );
      if (stored.preview.status !== 'pending_review') return gatewayError(
        'CANDIDATE_NOT_REVIEWABLE', 'This preview already has a final decision.', 'conflict', 409,
      );
      const result = await client.saveCatalogPreviewAsVariation(
        stored.trusted, { created_by: request.createdBy, label },
      );
      if (result.error !== null) return {
        data: null, error: mapError(result.error), status: result.status,
      };
      const source = await client.getProject(stored.lineage.projectId);
      if (
        source.error !== null
        || source.data.active_asset_id !== stored.lineage.sourceAssetId
        || source.data.active_design_version !== stored.lineage.sourceDesignVersion
        || result.data.project.root_id === stored.lineage.projectId
        || result.data.project.active_asset_id !== result.data.project.root_id
        || result.data.project.active_design_version !== 1
        || result.data.design_version !== 1
        || !preservesProposedSpec(result.data.project.spec, stored.proposedSpec)
      ) {
        return gatewayError(
          'INVALID_CATALOG_VARIATION_LINEAGE',
          'The saved variation did not preserve the proposed specification and source revision.',
          'invalid_response', result.status,
        );
      }
      const candidate = decidePreviewCandidate(
        stored.preview, 'save_as_variation', now().toISOString(),
        result.data.project.active_asset_id,
      );
      catalogCandidates.delete(request.candidateId);
      return {
        data: {
          candidate, project: result.data.project, familyId: result.data.family_id,
          variationIndex: result.data.variation_index,
        },
        error: null, status: result.status,
      };
    },

    async previewMarkupRefine(
      request: StudioMarkupPreviewRequest,
    ): Promise<StudioGatewayResult<StudioMarkupPreview>> {
      const lineage = {
        projectId: request.projectId,
        sourceAssetId: request.sourceAssetId,
        sourceDesignVersion: request.sourceDesignVersion,
      };
      const started = await startJob('refine', request.createdBy, 1, lineage);
      if (started.error !== null) return started;
      const studioJob = started.data;
      const result = await callTracked(studioJob, () => client.applyMarkup(
        request.sourceAssetId,
        {
          annotation: request.annotation,
          markup_asset_id: request.markupAssetId ?? null,
          expected_design_version: request.sourceDesignVersion,
          created_by: request.createdBy,
          ...(request.variant === undefined ? {} : { variant: request.variant }),
          preview_only: true,
          ...(studioJob === null ? {} : { studio_job_id: studioJob.jobId }),
        },
      ));
      if (result.error !== null) return result;
      const warning = result.data.warning_candidate;
      if (
        result.data.revision !== null
        || result.data.spec_version !== request.sourceDesignVersion
        || warning === null
        || warning.candidate_id === null
        || warning.preview_url === null
      ) {
        await failJob(studioJob, 'INVALID_MARKUP_PREVIEW', 0.9);
        return gatewayError(
          'INVALID_MARKUP_PREVIEW',
          'The refinement response did not remain a temporary candidate on the requested revision.',
          'invalid_response',
          result.status,
        );
      }
      const durable = studioJob === null
        ? null : await client.listStudioMarkupCandidates(lineage.projectId);
      if (durable?.error !== null && durable !== null) return {
        data: null, error: mapError(durable.error), status: durable.status,
      };
      const trusted = durable?.error === null ? durable.data.candidates.find((item) => (
        item.candidate_id === warning.candidate_id
        && item.image_run_id === warning.run_id
        && item.studio_job_id === studioJob?.jobId
        && item.source_asset_id === lineage.sourceAssetId
        && item.design_version === lineage.sourceDesignVersion
      )) : undefined;
      if (studioJob !== null && trusted === undefined) {
        await failJob(studioJob, 'DURABLE_MARKUP_PREVIEW_MISSING', 0.9);
        return gatewayError(
          'DURABLE_MARKUP_PREVIEW_MISSING',
          'The temporary refinement could not be reopened safely.',
          'invalid_response', durable?.status ?? result.status,
        );
      }
      const candidateQa = trusted?.qa ?? warning.qa;
      const candidateVerdict = candidateQa.verdict === 'fail'
        ? 'reject' as const : candidateQa.verdict;
      const candidate: PreviewCandidate = {
        id: trusted?.candidate_id ?? warning.candidate_id,
        jobId: trusted?.image_run_id ?? warning.run_id,
        sourceRevisionId: request.sourceAssetId,
        assetUrl: trusted?.preview_url ?? warning.preview_url,
        verdict: candidateVerdict,
        status: 'pending_review',
        checks: qualityPreviewChecks(candidateQa),
        temporary: true,
        expiresAt: trusted?.expires_at ?? null,
        decision: null,
        decidedAt: null,
        canonicalRevisionId: null,
      };
      markupCandidates.set(candidate.id, {
        trusted: trusted ?? null,
        runId: warning.run_id,
        candidateId: warning.candidate_id,
        preview: candidate,
        lineage,
        studioJob,
      });
      return {
        data: {
          candidate,
          lineage,
          annotation: request.annotation,
        },
        error: null,
        status: result.status,
      };
    },

    async applyMarkupRefine(
      request: StudioCandidateDecisionRequest,
    ): Promise<StudioGatewayResult<StudioCandidateDecisionResult>> {
      const stored = markupCandidates.get(request.candidateId);
      if (stored === undefined) return gatewayError(
        'CANDIDATE_NOT_FOUND', 'This preview is no longer available.', 'validation', 404,
      );
      if (stored.preview.status !== 'pending_review') return gatewayError(
        'CANDIDATE_NOT_REVIEWABLE', 'This preview already has a final decision.', 'conflict', 409,
      );
      if (stored.preview.verdict === 'reject') return gatewayError(
        'CANDIDATE_REJECTED', 'A rejected preview cannot become design history.', 'quality', 422,
      );
      const result = stored.trusted === null
        ? await client.acceptWarningCandidate(
            stored.runId, stored.candidateId,
            stored.lineage.sourceDesignVersion, request.createdBy,
          )
        : await client.acceptStudioMarkupCandidate(stored.trusted, {
            expected_active_asset_id: stored.lineage.sourceAssetId,
            expected_design_version: stored.lineage.sourceDesignVersion,
            created_by: request.createdBy,
          });
      if (result.error !== null) return {
        data: null, error: mapError(result.error), status: result.status,
      };
      const acceptedProject = 'project' in result.data ? result.data.project : result.data;
      const lineage = exactLineage(acceptedProject);
      if (lineage === null || lineage.projectId !== stored.lineage.projectId
        || lineage.sourceAssetId === stored.lineage.sourceAssetId) {
        await failJob(stored.studioJob, 'INVALID_ACCEPT_LINEAGE', 0.95);
        return gatewayError(
          'INVALID_ACCEPT_LINEAGE', 'The accepted preview did not append a new exact revision.',
          'invalid_response', result.status,
        );
      }
      const candidate = decidePreviewCandidate(
        stored.preview, 'apply', now().toISOString(), lineage.sourceAssetId,
      );
      stored.preview = candidate;
      return { data: { candidate, project: acceptedProject }, error: null, status: result.status };
    },

    async discardMarkupRefine(
      request: StudioCandidateDecisionRequest,
    ): Promise<StudioGatewayResult<StudioCandidateDecisionResult>> {
      const stored = markupCandidates.get(request.candidateId);
      if (stored === undefined) return gatewayError(
        'CANDIDATE_NOT_FOUND', 'This preview is no longer available.', 'validation', 404,
      );
      if (stored.preview.status !== 'pending_review') return gatewayError(
        'CANDIDATE_NOT_REVIEWABLE', 'This preview already has a final decision.', 'conflict', 409,
      );
      const result = stored.trusted === null
        ? await client.discardWarningCandidate(
            stored.runId, stored.candidateId, request.createdBy,
          )
        : await client.discardStudioMarkupCandidate(stored.trusted, {
            expected_active_asset_id: stored.lineage.sourceAssetId,
            expected_design_version: stored.lineage.sourceDesignVersion,
            created_by: request.createdBy,
          });
      if (result.error !== null) return {
        data: null, error: mapError(result.error), status: result.status,
      };
      const candidate = decidePreviewCandidate(stored.preview, 'discard', now().toISOString());
      stored.preview = candidate;
      return { data: { candidate, project: null }, error: null, status: result.status };
    },

    async saveMarkupPreviewAsVariation(
      request: StudioCandidateVariationRequest,
    ): Promise<StudioGatewayResult<StudioCandidateVariationResult>> {
      const stored = markupCandidates.get(request.candidateId);
      if (stored === undefined) return gatewayError(
        'CANDIDATE_NOT_FOUND', 'This preview is no longer available.', 'validation', 404,
      );
      if (stored.trusted === null) return gatewayError(
        'VARIATION_REQUIRES_DURABLE_PREVIEW',
        'Reopen this exact refinement from Activity before saving it as a variation.',
        'unavailable', 409,
      );
      const label = request.label.trim();
      if (label.length === 0) return gatewayError(
        'VARIATION_LABEL_REQUIRED', 'Name the variation before saving it.', 'validation', 422,
      );
      if (stored.preview.status !== 'pending_review' || stored.preview.verdict === 'reject') {
        return gatewayError(
          'CANDIDATE_NOT_REVIEWABLE', 'This preview cannot be saved.', 'conflict', 409,
        );
      }
      const result = await client.saveStudioMarkupPreviewAsVariation(stored.trusted, {
        created_by: request.createdBy, label,
      });
      if (result.error !== null) return {
        data: null, error: mapError(result.error), status: result.status,
      };
      const source = await client.getProject(stored.lineage.projectId);
      if (
        source.error !== null
        || source.data.active_asset_id !== stored.lineage.sourceAssetId
        || source.data.active_design_version !== stored.lineage.sourceDesignVersion
        || result.data.project.root_id === stored.lineage.projectId
        || result.data.project.active_asset_id !== result.data.project.root_id
        || result.data.project.active_design_version !== 1
      ) return gatewayError(
        'INVALID_MARKUP_VARIATION_LINEAGE',
        'The saved variation did not preserve the exact source revision.',
        'invalid_response', result.status,
      );
      const candidate = decidePreviewCandidate(
        stored.preview, 'save_as_variation', now().toISOString(),
        result.data.project.active_asset_id,
      );
      markupCandidates.delete(request.candidateId);
      return {
        data: {
          candidate, project: result.data.project, familyId: result.data.family_id,
          variationIndex: result.data.variation_index,
        },
        error: null, status: result.status,
      };
    },

    createLineArtView(request: StudioViewRequest): Promise<StudioGatewayResult<DrawingConfirmationResult>> {
      return client.createLineArt(request.projectId, {
        created_by: request.createdBy,
        expected_asset_id: request.sourceAssetId,
        expected_design_version: request.sourceDesignVersion,
        view: request.view,
        ...(request.sourceRegionDescription === undefined
          ? {} : { source_region_description: request.sourceRegionDescription }),
        ...(request.sourceRegion === undefined ? {} : { source_region: request.sourceRegion }),
        ...(request.variant === undefined ? {} : { variant: request.variant }),
      }).then(mapResult);
    },

    async previewLineArtView(
      request: StudioViewRequest,
    ): Promise<StudioGatewayResult<StudioViewPreview>> {
      const lineage: ExactStudioLineage = {
        projectId: request.projectId,
        sourceAssetId: request.sourceAssetId,
        sourceDesignVersion: request.sourceDesignVersion,
      };
      const started = await startJob('views', request.createdBy, 1, lineage);
      if (started.error !== null) return started;
      const result = await callTracked(started.data, () => client.createLineArt(
        request.projectId,
        {
          created_by: request.createdBy,
          expected_asset_id: request.sourceAssetId,
          expected_design_version: request.sourceDesignVersion,
          view: request.view,
          ...(started.data === null ? {} : { studio_job_id: started.data.jobId }),
          ...(request.sourceRegionDescription === undefined
            ? {} : { source_region_description: request.sourceRegionDescription }),
          ...(request.sourceRegion === undefined ? {} : { source_region: request.sourceRegion }),
          ...(request.variant === undefined ? {} : { variant: request.variant }),
        },
      ));
      if (result.error !== null) return result;
      const candidateId = result.data.candidate.candidate_id;
      const previewUrl = result.data.candidate.preview_url;
      if (
        result.data.project_id !== request.projectId
        || result.data.view !== request.view
        || candidateId === null
        || previewUrl === null
      ) {
        await failJob(started.data, 'INVALID_VIEW_PREVIEW', 0.9);
        return gatewayError(
          'INVALID_VIEW_PREVIEW',
          'The view preview was not bound to the requested immutable revision.',
          'invalid_response',
          result.status,
        );
      }
      const preview: StudioViewPreview = {
        candidateId,
        runId: result.data.image_run_id,
        previewUrl,
        view: result.data.view,
        lineage,
        verdict: result.data.quality_report.verdict,
        checks: result.data.quality_report.checks.map((check) => ({
          id: check.key,
          label: check.label,
          verdict: check.verdict === 'fail' ? 'reject' : check.verdict,
          detail: check.message || null,
        })),
      };
      viewCandidates.set(candidateId, {
        preview, status: 'pending_review', studioJob: started.data,
      });
      return { data: preview, error: null, status: result.status };
    },

    async resumeViews(
      lineage: ExactStudioLineage,
      createdBy: string,
      reviewJobId?: string,
    ): Promise<StudioGatewayResult<StudioViewPreview | null>> {
      const listed = await client.listStudioViewCandidates(createdBy, lineage.projectId);
      if (listed.error !== null) {
        return { data: null, error: mapError(listed.error), status: listed.status };
      }
      const matching = listed.data.candidates.filter((candidate) => (
        candidate.project_id === lineage.projectId
        && candidate.source_asset_id === lineage.sourceAssetId
        && candidate.design_version === lineage.sourceDesignVersion
        && (reviewJobId === undefined || candidate.studio_job_id === reviewJobId)
      ));
      if (matching.length === 0) return { data: null, error: null, status: listed.status };
      const candidate = matching[0];
      const job = await requireReviewJob(
        candidate.studio_job_id, createdBy, 'views', lineage, 1,
      );
      if (job.error !== null) return job;
      const preview: StudioViewPreview = {
        candidateId: candidate.candidate_id,
        runId: candidate.image_run_id,
        previewUrl: candidate.preview_url,
        view: candidate.view,
        lineage,
        verdict: candidate.qa.verdict,
        checks: candidate.qa.checks.map((check) => ({
          id: check.key,
          label: check.label,
          verdict: check.verdict === 'fail' ? 'reject' : check.verdict,
          detail: check.message || null,
        })),
      };
      viewCandidates.set(candidate.candidate_id, {
        preview, status: 'pending_review', studioJob: job.data,
      });
      return { data: preview, error: null, status: listed.status };
    },

    async acceptLineArtView(
      request: StudioCandidateDecisionRequest,
    ): Promise<StudioGatewayResult<StudioViewDecisionResult>> {
      const stored = viewCandidates.get(request.candidateId);
      if (stored === undefined) return gatewayError(
        'VIEW_CANDIDATE_NOT_FOUND', 'This view preview is no longer available.', 'validation', 404,
      );
      if (stored.status !== 'pending_review') return gatewayError(
        'VIEW_CANDIDATE_NOT_REVIEWABLE', 'This view preview already has a final decision.', 'conflict', 409,
      );
      if (stored.preview.verdict === 'fail') return gatewayError(
        'VIEW_QUALITY_REJECTED',
        'This view failed fidelity checks and cannot be saved.',
        'quality',
        422,
      );
      const lineage = stored.preview.lineage;
      const result = await client.acceptStudioViewCandidate(
        stored.preview.runId,
        stored.preview.candidateId,
        {
          created_by: request.createdBy,
          expected_project_id: lineage.projectId,
          expected_source_asset_id: lineage.sourceAssetId,
          expected_design_version: lineage.sourceDesignVersion,
        },
      );
      if (result.error !== null) {
        return { data: null, error: mapError(result.error), status: result.status };
      }
      const acceptedLineage = exactLineage(result.data.project);
      if (
        result.data.project_id !== lineage.projectId
        || result.data.source_asset_id !== lineage.sourceAssetId
        || result.data.design_version !== lineage.sourceDesignVersion
        || acceptedLineage === null
        || acceptedLineage.sourceAssetId !== lineage.sourceAssetId
        || acceptedLineage.sourceDesignVersion !== lineage.sourceDesignVersion
        || !result.data.project.derived_assets.some((asset) => (
          asset.asset_id === result.data.asset_id
          && asset.parent_asset_id === lineage.sourceAssetId
          && asset.design_version === lineage.sourceDesignVersion
          && asset.capability === 'LINE_ART'
        ))
      ) {
        await failJob(stored.studioJob, 'INVALID_VIEW_ACCEPT_LINEAGE', 0.95);
        return gatewayError(
          'INVALID_VIEW_ACCEPT_LINEAGE',
          'Saving the derived view unexpectedly changed the active design revision.',
          'invalid_response',
          result.status,
        );
      }
      stored.status = 'accepted';
      return {
        data: { preview: stored.preview, project: result.data.project },
        error: null,
        status: result.status,
      };
    },

    async discardLineArtView(
      request: StudioCandidateDecisionRequest,
    ): Promise<StudioGatewayResult<StudioViewDecisionResult>> {
      const stored = viewCandidates.get(request.candidateId);
      if (stored === undefined) return gatewayError(
        'VIEW_CANDIDATE_NOT_FOUND', 'This view preview is no longer available.', 'validation', 404,
      );
      if (stored.status !== 'pending_review') return gatewayError(
        'VIEW_CANDIDATE_NOT_REVIEWABLE', 'This view preview already has a final decision.', 'conflict', 409,
      );
      const lineage = stored.preview.lineage;
      const discarded = await client.discardStudioViewCandidate(
        stored.preview.runId,
        stored.preview.candidateId,
        {
          created_by: request.createdBy,
          expected_project_id: lineage.projectId,
          expected_source_asset_id: lineage.sourceAssetId,
          expected_design_version: lineage.sourceDesignVersion,
        },
      );
      if (discarded.error !== null) {
        return { data: null, error: mapError(discarded.error), status: discarded.status };
      }
      if (discarded.data.project_id !== lineage.projectId
        || discarded.data.source_asset_id !== lineage.sourceAssetId
        || discarded.data.design_version !== lineage.sourceDesignVersion
        || discarded.data.candidate_id !== stored.preview.candidateId) {
        return gatewayError(
          'INVALID_VIEW_DISCARD_LINEAGE',
          'Discarding the view could not be confirmed for the selected design revision.',
          'invalid_response', discarded.status,
        );
      }
      stored.status = 'discarded';
      return {
        data: { preview: stored.preview, project: null }, error: null, status: discarded.status,
      };
    },

    async resumePreSpecPresentations(
      lineage: StudioVisualLineage,
      createdBy: string,
      reviewJobId?: string,
    ): Promise<StudioGatewayResult<PreSpecPresentationResult[]>> {
      const result = await client.listPreSpecPresentations(
        createdBy, lineage.projectId,
      );
      if (result.error !== null) {
        return { data: null, error: mapError(result.error), status: result.status };
      }
      const resumed: PreSpecPresentationResult[] = [];
      for (const candidate of result.data.candidates) {
        if (candidate.design_version !== null
          || candidate.project_id !== lineage.projectId
          || candidate.source_asset_id !== lineage.sourceAssetId
          || (reviewJobId !== undefined && candidate.studio_job_id !== reviewJobId)
          || !/^[0-9a-f]{64}$/.test(candidate.source_sha256)
          || preSpecPresentationCandidates.has(candidate.candidate_id)) continue;
        preSpecPresentationCandidates.set(candidate.candidate_id, {
          runId: candidate.image_run_id,
          candidateId: candidate.candidate_id,
          sourceHash: candidate.source_sha256,
          capability: candidate.capability,
          lineage,
          studioJob: candidate.studio_job_id === null ? null : {
            jobId: candidate.studio_job_id,
            owner: createdBy,
          },
          status: 'pending_review',
        });
        resumed.push({
          status: 'review_required',
          project_id: candidate.project_id,
          source_asset_id: candidate.source_asset_id,
          source_sha256: candidate.source_sha256,
          design_version: null,
          destination: candidate.destination,
          client_format: candidate.capability === 'CLIENT_BEAUTY_RENDER'
            ? 'beauty' : 'product',
          candidate,
        });
      }
      return { data: resumed, error: null, status: result.status };
    },

    async resumeExactPresentations(
      lineage: ExactStudioLineage,
      createdBy: string,
      reviewJobId?: string,
    ): Promise<StudioGatewayResult<StudioExactPresentationPreview[]>> {
      const listed = await client.listPreSpecPresentations(createdBy, lineage.projectId);
      if (listed.error !== null) {
        return { data: null, error: mapError(listed.error), status: listed.status };
      }
      const matching = listed.data.candidates.filter((candidate) => (
        candidate.project_id === lineage.projectId
        && candidate.source_asset_id === lineage.sourceAssetId
        && candidate.design_version === lineage.sourceDesignVersion
        && (reviewJobId === undefined || candidate.studio_job_id === reviewJobId)
      ));
      const byJob = new Map<string, PreSpecPresentationResumeCandidate[]>();
      for (const candidate of matching) {
        if (candidate.studio_job_id === null) return gatewayError(
          'STUDIO_REVIEW_JOB_MISSING',
          'This saved presentation is missing its durable Activity record.',
          'invalid_response', 409,
        );
        const group = byJob.get(candidate.studio_job_id) ?? [];
        group.push(candidate);
        byJob.set(candidate.studio_job_id, group);
      }
      for (const [jobId, candidates] of byJob) {
        const job = await requireReviewJob(
          jobId, createdBy, 'present', lineage, candidates.length,
        );
        if (job.error !== null) return job;
        const alreadyHydrated = candidates.every((candidate) => (
          presentationCandidates.has(candidate.candidate_id)
        ));
        if (!alreadyHydrated && !registerPresentationCandidates(
          job.data,
          lineage,
          candidates.map((candidate) => ({
            runId: candidate.image_run_id,
            candidateId: candidate.candidate_id,
            capability: candidate.capability,
          })),
        )) return gatewayError(
          'INVALID_PRESENTATION_CANDIDATE',
          'The saved presentation previews could not be restored safely.',
          'invalid_response', 409,
        );
      }
      return {
        data: matching.map((candidate) => ({ candidate, lineage })),
        error: null,
        status: listed.status,
      };
    },

    async createPreSpecPresentation(
      projectId: string,
      request: PreSpecPresentationRequest,
    ): Promise<StudioGatewayResult<PreSpecPresentationResult>> {
      const lineage: StudioVisualLineage = {
        projectId,
        sourceAssetId: request.expected_active_asset_id,
      };
      const started = await startJob('present', request.created_by, 1, lineage);
      if (started.error !== null) return started;
      const result = await callTracked(
        started.data,
        () => client.createPreSpecPresentation(projectId, {
          ...request,
          ...(started.data === null ? {} : { studio_job_id: started.data.jobId }),
        }),
      );
      if (result.error !== null) return result;
      const candidate = result.data.candidate;
      if (result.data.project_id !== projectId
        || result.data.source_asset_id !== lineage.sourceAssetId
        || result.data.design_version !== null
        || !/^[0-9a-f]{64}$/.test(result.data.source_sha256)
        || (started.data !== null
          && candidate.studio_job_id !== started.data.jobId)
        || preSpecPresentationCandidates.has(candidate.candidate_id)) {
        await failJob(started.data, 'INVALID_PRE_SPEC_PRESENTATION_LINEAGE', 0.95);
        return gatewayError(
          'INVALID_PRE_SPEC_PRESENTATION_LINEAGE',
          'The presentation preview did not match the selected visual.',
          'invalid_response', result.status,
        );
      }
      preSpecPresentationCandidates.set(candidate.candidate_id, {
        runId: candidate.image_run_id,
        candidateId: candidate.candidate_id,
        sourceHash: result.data.source_sha256,
        capability: candidate.capability,
        lineage,
        studioJob: started.data,
        status: 'pending_review',
      });
      return result;
    },

    async acceptPreSpecPresentation(
      request: StudioCandidateDecisionRequest,
    ): Promise<StudioGatewayResult<StudioPreSpecPresentationDecisionResult>> {
      const stored = preSpecPresentationCandidates.get(request.candidateId);
      if (stored === undefined) return gatewayError(
        'PRESENTATION_NOT_FOUND', 'This presentation preview is no longer available.',
        'validation', 404,
      );
      if (stored.status !== 'pending_review') return gatewayError(
        'PRESENTATION_NOT_REVIEWABLE', 'This presentation already has a final decision.',
        'conflict', 409,
      );
      const before = await client.getProject(stored.lineage.projectId);
      if (before.error !== null) {
        return { data: null, error: mapError(before.error), status: before.status };
      }
      if (before.data.active_design_version !== null
        || before.data.active_asset_id !== stored.lineage.sourceAssetId
        || before.data.selected_candidate_asset_id !== stored.lineage.sourceAssetId) {
        await failJob(stored.studioJob, 'STALE_PRESENTATION_SOURCE', 0.95);
        return gatewayError(
          'STALE_PRESENTATION_SOURCE',
          'The selected visual changed while this presentation was awaiting review.',
          'conflict', 409,
        );
      }
      const accepted = await client.acceptPreSpecPresentation(
        stored.runId, stored.candidateId, {
          created_by: request.createdBy,
          expected_active_asset_id: stored.lineage.sourceAssetId,
          expected_source_sha256: stored.sourceHash,
        },
      );
      if (accepted.error !== null) {
        await failJob(stored.studioJob, accepted.error.code, 0.95);
        return { data: null, error: mapError(accepted.error), status: accepted.status };
      }
      const saved = accepted.data.project.derived_assets.find((asset) => (
        asset.asset_id === accepted.data.asset_id
        && asset.parent_asset_id === stored.lineage.sourceAssetId
        && asset.design_version === null
        && asset.capability === stored.capability
      ));
      if (accepted.data.project_id !== stored.lineage.projectId
        || accepted.data.source_asset_id !== stored.lineage.sourceAssetId
        || accepted.data.source_sha256 !== stored.sourceHash
        || accepted.data.design_version !== null
        || accepted.data.project.active_asset_id !== stored.lineage.sourceAssetId
        || accepted.data.project.active_design_version !== null
        || saved === undefined) {
        await failJob(stored.studioJob, 'INVALID_PRE_SPEC_PRESENTATION_ACCEPT', 0.95);
        return gatewayError(
          'INVALID_PRE_SPEC_PRESENTATION_ACCEPT',
          'Saving the presentation did not preserve the selected visual.',
          'invalid_response', accepted.status,
        );
      }
      stored.status = 'accepted';
      return {
        data: { candidateId: stored.candidateId, project: accepted.data.project },
        error: null,
        status: accepted.status,
      };
    },

    async discardPreSpecPresentation(
      request: StudioCandidateDecisionRequest,
    ): Promise<StudioGatewayResult<StudioPreSpecPresentationDecisionResult>> {
      const stored = preSpecPresentationCandidates.get(request.candidateId);
      if (stored === undefined) return gatewayError(
        'PRESENTATION_NOT_FOUND', 'This presentation preview is no longer available.',
        'validation', 404,
      );
      if (stored.status !== 'pending_review') return gatewayError(
        'PRESENTATION_NOT_REVIEWABLE', 'This presentation already has a final decision.',
        'conflict', 409,
      );
      const before = await client.getProject(stored.lineage.projectId);
      if (before.error !== null) {
        return { data: null, error: mapError(before.error), status: before.status };
      }
      const discarded = await client.discardPreSpecPresentation(
        stored.runId, stored.candidateId, {
          created_by: request.createdBy,
          expected_active_asset_id: stored.lineage.sourceAssetId,
          expected_source_sha256: stored.sourceHash,
        },
      );
      if (discarded.error !== null) {
        return { data: null, error: mapError(discarded.error), status: discarded.status };
      }
      if (discarded.data.project_id !== stored.lineage.projectId
        || discarded.data.source_asset_id !== stored.lineage.sourceAssetId
        || discarded.data.source_sha256 !== stored.sourceHash
        || discarded.data.design_version !== null
        || discarded.data.candidate_id !== stored.candidateId) {
        await failJob(stored.studioJob, 'INVALID_PRE_SPEC_PRESENTATION_DISCARD', 0.95);
        return gatewayError(
          'INVALID_PRE_SPEC_PRESENTATION_DISCARD',
          'Discarding the presentation could not be confirmed.',
          'invalid_response', discarded.status,
        );
      }
      stored.status = 'discarded';
      return {
        data: { candidateId: stored.candidateId, project: before.data },
        error: null,
        status: discarded.status,
      };
    },

    async createBeautyPresentation(
      projectId: string,
      request: BeautyRenderRequest,
    ): Promise<StudioGatewayResult<BeautyRenderResult>> {
      const lineage: ExactStudioLineage = {
        projectId,
        sourceAssetId: request.expected_asset_id,
        sourceDesignVersion: request.expected_design_version,
      };
      const started = await startJob('present', request.created_by, 1, lineage);
      if (started.error !== null) return started;
      const result = await callTracked(
        started.data,
        () => client.createBeautyRender(projectId, {
          ...request,
          ...(started.data === null ? {} : { studio_job_id: started.data.jobId }),
        }) as Promise<ApiResult<BeautyRenderResult>>,
      );
      if (result.error !== null) return result;
      if (result.data.status !== 'review_required') {
        await failJob(started.data, 'PRESENTATION_REVIEW_BYPASSED', 0.95);
        return gatewayError(
          'PRESENTATION_REVIEW_BYPASSED',
          'A Client presentation must remain temporary until the designer reviews it.',
          'invalid_response',
          result.status,
        );
      }
      if (
        result.data.project_id !== projectId
        || result.data.source_asset_id !== request.expected_asset_id
      ) {
        await failJob(started.data, 'INVALID_PRESENTATION_LINEAGE', 0.95);
        return gatewayError(
          'INVALID_PRESENTATION_LINEAGE',
          'The beauty-render response did not match the requested immutable revision.',
          'invalid_response',
          result.status,
        );
      }
      const candidateId = result.data.warning_candidate.candidate_id;
      const runId = result.data.warning_candidate.run_id;
      if (candidateId === null || !registerPresentationCandidates(
        started.data,
        lineage,
        [{ runId, candidateId, capability: 'CLIENT_BEAUTY_RENDER' }],
      )) {
        await failJob(started.data, 'INVALID_PRESENTATION_CANDIDATE', 0.95);
        return gatewayError(
          'INVALID_PRESENTATION_CANDIDATE',
          'The presentation preview could not be bound to this saved revision.',
          'invalid_response',
          result.status,
        );
      }
      return result;
    },

    async createProductPresentation(
      projectId: string,
      request: ProductPhotoRequest,
    ): Promise<StudioGatewayResult<ProductPhotoResult>> {
      const lineage: ExactStudioLineage = {
        projectId,
        sourceAssetId: request.expected_asset_id,
        sourceDesignVersion: request.expected_design_version,
      };
      const started = await startJob('present', request.created_by, 1, lineage);
      if (started.error !== null) return started;
      const result = await callTracked(
        started.data,
        () => client.createProductPhoto(projectId, {
          ...request,
          ...(started.data === null ? {} : { studio_job_id: started.data.jobId }),
        }) as Promise<ApiResult<ProductPhotoResult>>,
      );
      if (result.error !== null) return result;
      if (result.data.status !== 'review_required') {
        await failJob(started.data, 'PRESENTATION_REVIEW_BYPASSED', 0.95);
        return gatewayError(
          'PRESENTATION_REVIEW_BYPASSED',
          'A Client presentation must remain temporary until the designer reviews it.',
          'invalid_response',
          result.status,
        );
      }
      if (
        result.data.project_id !== projectId
        || result.data.presentation.source_asset_id !== request.expected_asset_id
        || result.data.presentation.design_version !== request.expected_design_version
      ) {
        await failJob(started.data, 'INVALID_PRESENTATION_LINEAGE', 0.95);
        return gatewayError(
          'INVALID_PRESENTATION_LINEAGE',
          'The product-photo response did not match the requested immutable revision.',
          'invalid_response',
          result.status,
        );
      }
      const candidateId = result.data.warning_candidate.candidate_id;
      const runId = result.data.warning_candidate.run_id;
      if (candidateId === null || !registerPresentationCandidates(
        started.data,
        lineage,
        [{ runId, candidateId, capability: 'CLIENT_PRODUCT_PHOTO' }],
      )) {
        await failJob(started.data, 'INVALID_PRESENTATION_CANDIDATE', 0.95);
        return gatewayError(
          'INVALID_PRESENTATION_CANDIDATE',
          'The presentation preview could not be bound to this saved revision.',
          'invalid_response',
          result.status,
        );
      }
      return result;
    },

    async createMarketingPresentation(
      projectId: string,
      request: MarketingPackRequest,
    ): Promise<StudioGatewayResult<MarketingPackResult>> {
      const lineage: ExactStudioLineage = {
        projectId,
        sourceAssetId: request.expected_asset_id,
        sourceDesignVersion: request.expected_design_version,
      };
      const started = await startJob(
        'present', request.created_by, request.presets.length, lineage,
      );
      if (started.error !== null) return started;
      const result = await callTracked(
        started.data, () => client.createMarketingPack(projectId, {
          ...request,
          ...(started.data === null ? {} : { studio_job_id: started.data.jobId }),
        }),
      );
      if (result.error !== null) return result;
      if (
        result.data.project_id !== projectId
        || result.data.source_asset_id !== request.expected_asset_id
        || result.data.design_version !== request.expected_design_version
        || result.data.requested_count !== request.presets.length
      ) {
        await failJob(started.data, 'INVALID_PRESENTATION_LINEAGE', 0.95);
        return gatewayError(
          'INVALID_PRESENTATION_LINEAGE',
          'The marketing response did not match the requested immutable revision and output count.',
          'invalid_response',
          result.status,
        );
      }
      if (result.data.candidate_count > 0 && !registerPresentationCandidates(
        started.data,
        lineage,
        result.data.candidates.map((candidate) => ({
          runId: candidate.image_run_id,
          candidateId: candidate.candidate_id,
          capability: 'MARKETING_IMAGE' as const,
        })),
      )) {
        await failJob(started.data, 'INVALID_PRESENTATION_CANDIDATE', 0.95);
        return gatewayError(
          'INVALID_PRESENTATION_CANDIDATE',
          'The presentation previews could not be bound to this saved revision.',
          'invalid_response',
          result.status,
        );
      }
      const activity = result.data.status === 'failed' || result.data.candidate_count === 0
        ? await transitionJob(started.data, 'failed', 0.9, undefined, 'NO_PRESENTATION_OUTPUTS')
        : { data: null, error: null, status: result.status } as const;
      if (activity.error !== null) return activity;
      return result;
    },

    async acceptPresentationCandidate(
      request: StudioCandidateDecisionRequest,
    ): Promise<StudioGatewayResult<StudioPresentationDecisionResult>> {
      const stored = presentationCandidates.get(request.candidateId);
      if (stored === undefined) return gatewayError(
        'PRESENTATION_NOT_FOUND', 'This presentation preview is no longer available.',
        'validation', 404,
      );
      if (stored.group.decisions.get(stored.candidateId) !== 'pending_review') {
        return gatewayError(
          'PRESENTATION_NOT_REVIEWABLE', 'This presentation preview already has a final decision.',
          'conflict', 409,
        );
      }
      const before = await client.getProject(stored.group.lineage.projectId);
      if (before.error !== null) {
        return { data: null, error: mapError(before.error), status: before.status };
      }
      const beforeLineage = exactLineage(before.data);
      if (beforeLineage === null
        || beforeLineage.sourceAssetId !== stored.group.lineage.sourceAssetId
        || beforeLineage.sourceDesignVersion !== stored.group.lineage.sourceDesignVersion) {
        await failJob(stored.group.studioJob, 'STALE_PRESENTATION_SOURCE', 0.95);
        return gatewayError(
          'STALE_PRESENTATION_SOURCE',
          'The selected design changed while this presentation was awaiting review.',
          'conflict', 409,
        );
      }
      const accepted = await client.acceptPresentationCandidate(
        stored.runId,
        stored.candidateId,
        {
          created_by: request.createdBy,
          expected_project_id: stored.group.lineage.projectId,
          expected_source_asset_id: stored.group.lineage.sourceAssetId,
          expected_design_version: stored.group.lineage.sourceDesignVersion,
        },
      );
      if (accepted.error !== null) {
        return { data: null, error: mapError(accepted.error), status: accepted.status };
      }
      const acceptedLineage = exactLineage(accepted.data.project);
      const savedAsset = accepted.data.project.derived_assets.find((asset) => (
        asset.asset_id === accepted.data.asset_id
        && asset.parent_asset_id === stored.group.lineage.sourceAssetId
        && asset.design_version === stored.group.lineage.sourceDesignVersion
        && asset.capability === stored.capability
      ));
      if (accepted.data.project_id !== stored.group.lineage.projectId
        || accepted.data.source_asset_id !== stored.group.lineage.sourceAssetId
        || accepted.data.source_design_version !== stored.group.lineage.sourceDesignVersion
        || accepted.data.capability !== stored.capability
        || acceptedLineage === null
        || acceptedLineage.sourceAssetId !== stored.group.lineage.sourceAssetId
        || acceptedLineage.sourceDesignVersion !== stored.group.lineage.sourceDesignVersion
        || savedAsset === undefined) {
        return gatewayError(
          'INVALID_PRESENTATION_ACCEPT_LINEAGE',
          'Saving the presentation did not preserve the selected design revision.',
          'invalid_response', accepted.status,
        );
      }
      stored.group.decisions.set(stored.candidateId, 'accepted');
      const finished = await finishPresentationGroup(stored.group);
      if (finished.error !== null) return finished;
      return {
        data: { candidateId: stored.candidateId, project: accepted.data.project },
        error: null,
        status: accepted.status,
      };
    },

    async discardPresentationCandidate(
      request: StudioCandidateDecisionRequest,
    ): Promise<StudioGatewayResult<StudioPresentationDecisionResult>> {
      const stored = presentationCandidates.get(request.candidateId);
      if (stored === undefined) return gatewayError(
        'PRESENTATION_NOT_FOUND', 'This presentation preview is no longer available.',
        'validation', 404,
      );
      if (stored.group.decisions.get(stored.candidateId) !== 'pending_review') {
        return gatewayError(
          'PRESENTATION_NOT_REVIEWABLE', 'This presentation preview already has a final decision.',
          'conflict', 409,
        );
      }
      const before = await client.getProject(stored.group.lineage.projectId);
      if (before.error !== null) {
        return { data: null, error: mapError(before.error), status: before.status };
      }
      const discarded = await client.discardPresentationCandidate(
        stored.runId, stored.candidateId, {
          created_by: request.createdBy,
          expected_project_id: stored.group.lineage.projectId,
          expected_source_asset_id: stored.group.lineage.sourceAssetId,
          expected_design_version: stored.group.lineage.sourceDesignVersion,
        },
      );
      if (discarded.error !== null) {
        return { data: null, error: mapError(discarded.error), status: discarded.status };
      }
      if (discarded.data.project_id !== stored.group.lineage.projectId
        || discarded.data.source_asset_id !== stored.group.lineage.sourceAssetId
        || discarded.data.source_design_version !== stored.group.lineage.sourceDesignVersion
        || discarded.data.candidate_id !== stored.candidateId) {
        return gatewayError(
          'INVALID_PRESENTATION_DISCARD_LINEAGE',
          'Discarding the presentation could not be confirmed for the selected design revision.',
          'invalid_response', discarded.status,
        );
      }
      stored.group.decisions.set(stored.candidateId, 'discarded');
      const finished = await finishPresentationGroup(stored.group);
      if (finished.error !== null) return finished;
      return {
        data: { candidateId: stored.candidateId, project: before.data },
        error: null,
        status: discarded.status,
      };
    },

    getFactoryEligibility,

    async getFactoryEntitlement(): Promise<StudioGatewayResult<boolean>> {
      if (client.getStudioCapabilities === undefined) return gatewayError(
        'FACTORY_ENTITLEMENT_UNAVAILABLE',
        'Facetta could not verify Factory access.',
        'unavailable', 0, true,
      );
      const result = await client.getStudioCapabilities();
      if (result.error !== null) return {
        data: null, error: mapError(result.error), status: result.status,
      };
      return { data: result.data.factory_review.enabled, error: null, status: result.status };
    },

    async getEligibleFactoryPack(projectId: string): Promise<StudioGatewayResult<FactoryPackManifest>> {
      const eligibility = await getFactoryEligibility(projectId);
      if (eligibility.error !== null) return eligibility;
      if (!eligibility.data.eligible) return gatewayError(
        'FACTORY_NOT_ELIGIBLE',
        eligibility.data.blockers.join(' '),
        'validation',
        422,
      );
      return mapResult(await client.getFactoryPack(projectId));
    },
  };
}

export function createStudioGatewayFromOptions(
  clientOptions: TrustedApiClientOptions,
  gatewayOptions: StudioGatewayOptions = {},
) {
  return createStudioGateway(createTrustedApiClient(clientOptions), gatewayOptions);
}

export type StudioGateway = ReturnType<typeof createStudioGateway>;
