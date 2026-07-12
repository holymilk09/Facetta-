import { createTrustedApiClient, TrustedApiClient, TrustedApiClientOptions } from '../trusted/client';
import type {
  ApiError,
  ApiResult,
  BeautyRenderRequest,
  BeautyRenderResult,
  CatalogApplyRequest,
  CatalogPreviewAcceptResult,
  CatalogPreviewCandidate,
  CatalogPreviewResult,
  CreateLineArtRequest,
  CreateProjectFromBriefRequest,
  CreateProjectFromDrawingRequest,
  CreateProjectFromPromptRequest,
  CreateVisualPreviewRequest,
  DrawingConfirmationResult,
  FactoryPackManifest,
  ImageQualityReport,
  MarketingPackRequest,
  MarketingPackResult,
  MarkupApplyRequest,
  ProductPhotoRequest,
  ProductPhotoResult,
  ProjectCreationResult,
  ProjectDetail,
  SaveAsVariationResult,
  StudioJobAction,
  StudioJobRecord,
} from '../trusted/types';
import { getStudioAction } from './actions';
import {
  decidePreviewCandidate,
  PreviewCandidate,
  PreviewCheck,
} from './contracts';

export type StudioGatewayErrorCategory =
  | 'network'
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
  componentPath: CatalogApplyRequest['component_path'];
  optionId: string;
}

export interface StudioMarkupPreview {
  candidate: PreviewCandidate;
  lineage: ExactStudioLineage;
  annotation: MarkupApplyRequest['annotation'];
}

export interface StudioVariationRequest extends StudioVisualLineage {
  sourceDesignVersion: number | null;
  createdBy: string;
  label: string;
}

export interface StudioCatalogPreviewRequest extends ExactStudioLineage {
  createdBy: string;
  componentPath: CatalogApplyRequest['component_path'];
  optionId: string;
  variant?: number;
  stoneSpecies?: string;
  chainGeometry?: CatalogApplyRequest['chain_geometry'];
  chainProduction?: CatalogApplyRequest['chain_production'];
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

export interface StudioPresentationDecisionResult {
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
  | 'saveAsVariation'
  | 'previewCatalogSelection'
  | 'acceptCatalogPreview'
  | 'discardCatalogPreview'
  | 'applyMarkup'
  | 'acceptWarningCandidate'
  | 'discardWarningCandidate'
  | 'acceptPresentationCandidate'
  | 'discardPresentationCandidate'
  | 'createLineArt'
  | 'createBeautyRender'
  | 'createProductPhoto'
  | 'createMarketingPack'
  | 'recordImageRunFeedback'
  | 'getProject'
  | 'getFactoryPack'
  | 'createStudioJob'
  | 'transitionStudioJob'
  | 'cancelStudioJob'
  | 'createVisualPreview'
  | 'acceptVisualPreview'
  | 'discardVisualPreview'
>;

export interface StudioGatewayOptions {
  factoryEnabled?: boolean;
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

export function createStudioGateway(
  client: GatewayTrustedClient,
  options: StudioGatewayOptions = {},
) {
  const factoryEnabled = options.factoryEnabled ?? false;
  const trackJobs = options.trackJobs ?? false;
  const now = options.now ?? (() => new Date());
  const creativeJobs = new Map<string, ActiveStudioJob & { completedOutputs: number }>();
  const catalogCandidates = new Map<string, {
    trusted: CatalogPreviewCandidate;
    preview: PreviewCandidate;
    lineage: ExactStudioLineage;
    studioJob: ActiveStudioJob | null;
  }>();
  const markupCandidates = new Map<string, {
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
  const visualCandidates = new Map<string, {
    runId: string;
    preview: StudioVisualPreview;
    studioJob: ActiveStudioJob | null;
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
    progress = 0.1,
  ): Promise<void> => {
    // Preserve the action's original error. Activity repair is retryable, but
    // it must never disguise why generation itself failed.
    await transitionJob(job, 'failed', progress, undefined, code);
  };

  const cancelJob = async (
    job: ActiveStudioJob | null,
  ): Promise<StudioGatewayResult<StudioJobRecord | null>> => {
    if (job === null) return { data: null, error: null, status: 0 };
    try {
      const result = await client.cancelStudioJob(job.jobId, job.owner);
      return result.error === null
        ? result
        : { data: null, error: mapError(result.error), status: result.status };
    } catch (error) {
      return trackingError(error);
    }
  };

  const finishPresentationGroup = async (
    group: PresentationGroup,
  ): Promise<StudioGatewayResult<StudioJobRecord | null>> => {
    const decisions = [...group.decisions.values()];
    if (decisions.some((decision) => decision === 'pending_review')) {
      return { data: null, error: null, status: 0 };
    }
    const accepted = decisions.filter((decision) => decision === 'accepted').length;
    return accepted === 0
      ? cancelJob(group.studioJob)
      : transitionJob(group.studioJob, 'succeeded', 1, accepted);
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
    const outputs = project.revisions.filter(
      (revision) => revision.asset.capability === 'CREATIVE_RENDER',
    ).length;
    return Math.min(requested, Math.max(outputs, project.active_revision === null ? 0 : 1));
  };

  const getFactoryEligibility = async (
    projectId: string,
  ): Promise<StudioGatewayResult<StudioFactoryEligibility>> => {
    if (!factoryEnabled) return {
      data: {
        enabled: false,
        eligible: false,
        projectId,
        pinnedAssetId: null,
        designVersion: null,
        blockers: ['Factory destination is not enabled for this workspace.'],
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
        creativeJobs.set(result.data.root_id, { ...started.data, completedOutputs });
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
        creativeJobs.set(result.data.root_id, { ...started.data, completedOutputs });
      }
      return result;
    },

    async selectCreativeDirection(
      projectId: string,
      candidateId: string,
      createdBy: string,
    ): Promise<StudioGatewayResult<ProjectDetail>> {
      const tracked = creativeJobs.get(projectId) ?? null;
      const result = await callTracked(
        tracked,
        () => client.selectCreativeCandidate(projectId, candidateId, createdBy),
      );
      if (result.error !== null) return result;
      const succeeded = await transitionJob(
        tracked, 'succeeded', 1, tracked?.completedOutputs ?? 1, undefined,
        { activeDesignId: result.data.root_id, sourceRevisionId: candidateId },
      );
      if (succeeded.error !== null) return succeeded;
      creativeJobs.delete(projectId);
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
            ...(request.variant === undefined ? {} : { variant: request.variant }),
          }
        : typeof request.maskBase64 === 'string'
          ? {
            created_by: request.createdBy,
            expected_active_asset_id: request.sourceAssetId,
            instruction,
            scope: 'marked_region',
            mask_base64: request.maskBase64,
            ...(request.variant === undefined ? {} : { variant: request.variant }),
          }
          : {
            created_by: request.createdBy,
            expected_active_asset_id: request.sourceAssetId,
            instruction,
            scope: 'marked_region',
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
        preview,
        studioJob: started.data,
      });
      const reviewing = await transitionJob(started.data, 'reviewing', 0.9);
      if (reviewing.error !== null) return reviewing;
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
      const succeeded = await transitionJob(stored.studioJob, 'succeeded', 1, 1);
      if (succeeded.error !== null) return succeeded;
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
      const dismissed = await cancelJob(stored.studioJob);
      if (dismissed.error !== null) return dismissed;
      return { data: { candidate, project: null }, error: null, status: result.status };
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
      const trustedRequest: CatalogApplyRequest = {
        component_path: request.componentPath,
        option_id: request.optionId,
        expected_design_version: request.sourceDesignVersion,
        created_by: request.createdBy,
        ...(request.variant === undefined ? {} : { variant: request.variant }),
        ...(request.stoneSpecies === undefined ? {} : { stone_species: request.stoneSpecies }),
        ...(request.chainGeometry === undefined ? {} : { chain_geometry: request.chainGeometry }),
        ...(request.chainProduction === undefined ? {} : { chain_production: request.chainProduction }),
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
        studioJob: started.data,
      });
      const reviewing = await transitionJob(started.data, 'reviewing', 0.9);
      if (reviewing.error !== null) return reviewing;
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
      const result = await callTracked(stored.studioJob, () => client.acceptCatalogPreview(
        stored.trusted,
        {
          expected_design_version: stored.lineage.sourceDesignVersion,
          created_by: request.createdBy,
        },
      ));
      if (result.error !== null) return result;
      const projectLineage = exactLineage(result.data.project);
      if (
        result.data.image_run_id !== stored.preview.jobId
        || result.data.design_version !== stored.lineage.sourceDesignVersion + 1
        || projectLineage === null
        || projectLineage.sourceAssetId !== result.data.asset_id
      ) {
        await failJob(stored.studioJob, 'INVALID_ACCEPT_LINEAGE', 0.95);
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
      const succeeded = await transitionJob(stored.studioJob, 'succeeded', 1, 1);
      if (succeeded.error !== null) return succeeded;
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
      const result = await callTracked(
        stored.studioJob, () => client.discardCatalogPreview(stored.trusted),
      );
      if (result.error !== null) return result;
      const candidate = decidePreviewCandidate(stored.preview, 'discard', now().toISOString());
      stored.preview = candidate;
      const dismissed = await cancelJob(stored.studioJob);
      if (dismissed.error !== null) return dismissed;
      return { data: { candidate, project: null }, error: null, status: result.status };
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
      const result = await callTracked(started.data, () => client.applyMarkup(
        request.sourceAssetId,
        {
          annotation: request.annotation,
          markup_asset_id: request.markupAssetId ?? null,
          expected_design_version: request.sourceDesignVersion,
          created_by: request.createdBy,
          ...(request.variant === undefined ? {} : { variant: request.variant }),
          preview_only: true,
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
        await failJob(started.data, 'INVALID_MARKUP_PREVIEW', 0.9);
        return gatewayError(
          'INVALID_MARKUP_PREVIEW',
          'The refinement response did not remain a temporary candidate on the requested revision.',
          'invalid_response',
          result.status,
        );
      }
      const candidate: PreviewCandidate = {
        id: warning.candidate_id,
        jobId: warning.run_id,
        sourceRevisionId: request.sourceAssetId,
        assetUrl: warning.preview_url,
        verdict: warning.qa.verdict === 'fail' ? 'reject' : warning.qa.verdict,
        status: 'pending_review',
        checks: qualityPreviewChecks(warning.qa),
        temporary: true,
        expiresAt: null,
        decision: null,
        decidedAt: null,
        canonicalRevisionId: null,
      };
      markupCandidates.set(candidate.id, {
        runId: warning.run_id,
        candidateId: warning.candidate_id,
        preview: candidate,
        lineage,
        studioJob: started.data,
      });
      const reviewing = await transitionJob(started.data, 'reviewing', 0.9);
      if (reviewing.error !== null) return reviewing;
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
      const result = await callTracked(stored.studioJob, () => client.acceptWarningCandidate(
        stored.runId, stored.candidateId, stored.lineage.sourceDesignVersion, request.createdBy,
      ));
      if (result.error !== null) return result;
      const lineage = exactLineage(result.data);
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
      const succeeded = await transitionJob(stored.studioJob, 'succeeded', 1, 1);
      if (succeeded.error !== null) return succeeded;
      return { data: { candidate, project: result.data }, error: null, status: result.status };
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
      const result = await callTracked(stored.studioJob, () => client.discardWarningCandidate(
        stored.runId, stored.candidateId, request.createdBy,
      ));
      if (result.error !== null) return result;
      const candidate = decidePreviewCandidate(stored.preview, 'discard', now().toISOString());
      stored.preview = candidate;
      const dismissed = await cancelJob(stored.studioJob);
      if (dismissed.error !== null) return dismissed;
      return { data: { candidate, project: null }, error: null, status: result.status };
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
      const reviewing = await transitionJob(started.data, 'reviewing', 0.9);
      if (reviewing.error !== null) return reviewing;
      return { data: preview, error: null, status: result.status };
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
      const result = await callTracked(stored.studioJob, () => client.acceptWarningCandidate(
        stored.preview.runId,
        stored.preview.candidateId,
        lineage.sourceDesignVersion,
        request.createdBy,
      ));
      if (result.error !== null) return result;
      const acceptedLineage = exactLineage(result.data);
      if (
        result.data.root_id !== lineage.projectId
        || acceptedLineage === null
        || acceptedLineage.sourceAssetId !== lineage.sourceAssetId
        || acceptedLineage.sourceDesignVersion !== lineage.sourceDesignVersion
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
      void client.recordImageRunFeedback(stored.preview.runId, 'accepted', request.createdBy);
      const succeeded = await transitionJob(stored.studioJob, 'succeeded', 1, 1);
      if (succeeded.error !== null) return succeeded;
      return { data: { preview: stored.preview, project: result.data }, error: null, status: result.status };
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
      const feedback = await callTracked(stored.studioJob, () => client.recordImageRunFeedback(
        stored.preview.runId, 'rejected', request.createdBy,
      ));
      if (feedback.error !== null) return feedback;
      stored.status = 'discarded';
      const dismissed = await cancelJob(stored.studioJob);
      if (dismissed.error !== null) return dismissed;
      return { data: { preview: stored.preview, project: null }, error: null, status: feedback.status };
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
        () => client.createBeautyRender(projectId, request) as Promise<ApiResult<BeautyRenderResult>>,
      );
      if (result.error !== null) return result;
      const accepted = result.data.status === 'accepted' ? result.data : null;
      const responseProjectId = result.data.status === 'accepted'
        ? result.data.project.root_id : result.data.project_id;
      if (
        responseProjectId !== projectId
        || result.data.source_asset_id !== request.expected_asset_id
        || (accepted !== null
          && (accepted.project.active_design_version !== request.expected_design_version
            || (request.presentation_only === true
              && (accepted.project.active_asset_id !== request.expected_asset_id
                || !accepted.project.derived_assets.some((asset) => asset.asset_id === accepted.asset_id)))))
      ) {
        await failJob(started.data, 'INVALID_PRESENTATION_LINEAGE', 0.95);
        return gatewayError(
          'INVALID_PRESENTATION_LINEAGE',
          'The beauty-render response did not match the requested immutable revision.',
          'invalid_response',
          result.status,
        );
      }
      if (result.data.status === 'review_required') {
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
      }
      const activity = result.data.status === 'accepted'
        ? await transitionJob(started.data, 'succeeded', 1, 1)
        : await transitionJob(started.data, 'reviewing', 0.9);
      if (activity.error !== null) return activity;
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
        () => client.createProductPhoto(projectId, request) as Promise<ApiResult<ProductPhotoResult>>,
      );
      if (result.error !== null) return result;
      const accepted = result.data.status === 'accepted' ? result.data : null;
      const responseProjectId = result.data.status === 'accepted'
        ? result.data.project.root_id : result.data.project_id;
      if (
        responseProjectId !== projectId
        || result.data.presentation.source_asset_id !== request.expected_asset_id
        || result.data.presentation.design_version !== request.expected_design_version
        || (accepted !== null && request.presentation_only === true
          && (accepted.project.active_asset_id !== request.expected_asset_id
            || !accepted.project.derived_assets.some((asset) => asset.asset_id === accepted.asset_id)))
      ) {
        await failJob(started.data, 'INVALID_PRESENTATION_LINEAGE', 0.95);
        return gatewayError(
          'INVALID_PRESENTATION_LINEAGE',
          'The product-photo response did not match the requested immutable revision.',
          'invalid_response',
          result.status,
        );
      }
      if (result.data.status === 'review_required') {
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
      }
      const activity = result.data.status === 'accepted'
        ? await transitionJob(started.data, 'succeeded', 1, 1)
        : await transitionJob(started.data, 'reviewing', 0.9);
      if (activity.error !== null) return activity;
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
        started.data, () => client.createMarketingPack(projectId, request),
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
        : await transitionJob(started.data, 'reviewing', 0.9);
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
        await failJob(stored.group.studioJob, accepted.error.code, 0.95);
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
        await failJob(stored.group.studioJob, 'INVALID_PRESENTATION_ACCEPT_LINEAGE', 0.95);
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
        await failJob(stored.group.studioJob, 'INVALID_PRESENTATION_DISCARD_LINEAGE', 0.95);
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
