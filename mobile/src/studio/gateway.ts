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
  CreateProjectFromPromptRequest,
  DrawingConfirmationResult,
  FactoryPackManifest,
  MarketingPackRequest,
  MarketingPackResult,
  ProductPhotoRequest,
  ProductPhotoResult,
  ProjectCreationResult,
  ProjectDetail,
  SaveAsVariationResult,
} from '../trusted/types';
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

export interface StudioCatalogPreview {
  candidate: PreviewCandidate;
  lineage: ExactStudioLineage;
  componentPath: CatalogApplyRequest['component_path'];
  optionId: string;
}

export interface StudioVariationRequest extends ExactStudioLineage {
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
  | 'createProjectFromPrompt'
  | 'saveAsVariation'
  | 'previewCatalogSelection'
  | 'acceptCatalogPreview'
  | 'discardCatalogPreview'
  | 'createLineArt'
  | 'createBeautyRender'
  | 'createProductPhoto'
  | 'createMarketingPack'
  | 'getProject'
  | 'getFactoryPack'
>;

export interface StudioGatewayOptions {
  factoryEnabled?: boolean;
  now?: () => Date;
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
  return result.qa.checks.map((check) => ({
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
  const now = options.now ?? (() => new Date());
  const catalogCandidates = new Map<string, {
    trusted: CatalogPreviewCandidate;
    preview: PreviewCandidate;
    lineage: ExactStudioLineage;
  }>();

  const requireCandidate = (candidateId: string) => catalogCandidates.get(candidateId) ?? null;

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

    createFromPrompt(request: CreateProjectFromPromptRequest): Promise<StudioGatewayResult<ProjectDetail>> {
      return client.createProjectFromPrompt(request).then(mapResult);
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

    async previewCatalogRefine(
      request: StudioCatalogPreviewRequest,
    ): Promise<StudioGatewayResult<StudioCatalogPreview>> {
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
      const result = await client.previewCatalogSelection(request.sourceAssetId, trustedRequest);
      if (result.error !== null) return { data: null, error: mapError(result.error), status: result.status };
      if (
        result.data.source_asset_id !== request.sourceAssetId
        || result.data.design_version !== request.sourceDesignVersion
        || result.data.project.root_id !== request.projectId
      ) {
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
      const lineage: ExactStudioLineage = {
        projectId: request.projectId,
        sourceAssetId: request.sourceAssetId,
        sourceDesignVersion: request.sourceDesignVersion,
      };
      catalogCandidates.set(candidate.id, {
        trusted: result.data.candidate,
        preview: candidate,
        lineage,
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
      const result = await client.acceptCatalogPreview(stored.trusted, {
        expected_design_version: stored.lineage.sourceDesignVersion,
        created_by: request.createdBy,
      });
      if (result.error !== null) return { data: null, error: mapError(result.error), status: result.status };
      const projectLineage = exactLineage(result.data.project);
      if (
        result.data.image_run_id !== stored.preview.jobId
        || result.data.design_version !== stored.lineage.sourceDesignVersion + 1
        || projectLineage === null
        || projectLineage.sourceAssetId !== result.data.asset_id
      ) return gatewayError(
        'INVALID_ACCEPT_LINEAGE',
        'The accepted preview did not produce the expected canonical revision.',
        'invalid_response',
        result.status,
      );
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
      if (result.error !== null) return { data: null, error: mapError(result.error), status: result.status };
      const candidate = decidePreviewCandidate(stored.preview, 'discard', now().toISOString());
      stored.preview = candidate;
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

    async createBeautyPresentation(
      projectId: string,
      request: BeautyRenderRequest,
    ): Promise<StudioGatewayResult<BeautyRenderResult>> {
      const result = await client.createBeautyRender(projectId, request) as ApiResult<BeautyRenderResult>;
      return mapResult(result);
    },

    async createProductPresentation(
      projectId: string,
      request: ProductPhotoRequest,
    ): Promise<StudioGatewayResult<ProductPhotoResult>> {
      const result = await client.createProductPhoto(projectId, request) as ApiResult<ProductPhotoResult>;
      return mapResult(result);
    },

    createMarketingPresentation(
      projectId: string,
      request: MarketingPackRequest,
    ): Promise<StudioGatewayResult<MarketingPackResult>> {
      return client.createMarketingPack(projectId, request).then(mapResult);
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
