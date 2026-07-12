import type {
  ApiError,
  ApiErrorCategory,
  ApiResult,
  ApprovalAnswer,
  ApprovalItem,
  ApprovalSummary,
  AssetSummary,
  BeautyRenderRequest,
  BeautyRenderResult,
  CatalogApplyCallResult,
  CatalogApplyFailure,
  CatalogApplyFailureStatus,
  CatalogApplyRequest,
  CatalogApplyResult,
  CatalogPreviewAcceptRequest,
  CatalogPreviewAcceptResult,
  CatalogPreviewCandidate,
  CatalogPreviewDiscardResult,
  CatalogPreviewResult,
  CatalogWarningCandidate,
  ChecklistCreateRequest,
  ChecklistResponseRequest,
  ColorizeLineArtRequest,
  ColorizeLineArtResult,
  ConfirmSourceCoverageRequest,
  ConfirmSourceCoverageResult,
  ConfirmCreativeCandidateProfileRequest,
  ConfirmCreativeCandidateProfileResult,
  ComponentCatalog,
  ComponentCatalogOption,
  ComponentCatalogPath,
  CreateLineArtRequest,
  CreateProjectFromBriefRequest,
  CreateProjectFromDrawingRequest,
  CreateProjectFromImageRequest,
  CreateProjectFromPromptRequest,
  ExtractImageDraftRequest,
  ExtractCreativeCandidateDraftRequest,
  ExtractPlateDraftRequest,
  FactoryPackArtifact,
  FactoryPackManifest,
  FactoryDimensionEstimate,
  FactoryReadinessBlocker,
  FactorySheetFactPlan,
  ImageAttemptSummary,
  ImageOperation,
  ImageQualityCheck,
  ImageQualityReport,
  ImageRoutingSummary,
  ImageRunSummary,
  ImageWarningCandidate,
  JsonObject,
  JsonValue,
  LineArtView,
  MarkupApplyRequest,
  MarkupApplyResponse,
  MarkupImpact,
  MarkupInterpretation,
  MarkupReadRequest,
  MarkupReadResponse,
  MarketingPackRequest,
  MarketingPackResult,
  DrawingConfirmationResult,
  DesignFamilyDetail,
  DesignFamilyList,
  DesignFamilyVariation,
  DraftFactorySheetPreview,
  DraftCatalogSelectionRequest,
  DraftCatalogSelectionResult,
  DraftStoneSelectionRequest,
  DimensionedProfileDefinition,
  DimensionedProfilePath,
  DesignerComponentConfirmation,
  ProjectDetail,
  ProjectCreationResult,
  ProjectCreationWarning,
  ProjectComment,
  ProjectRevision,
  ProjectState,
  PlateDraftResult,
  PhotoDraftResult,
  ProductPhotoFraming,
  ProductPhotoPresentation,
  ProductPhotoPreset,
  ProductPhotoRequest,
  ProductPhotoResult,
  PromoteCreativeCandidateRequest,
  ResolveSourceCoverageRequest,
  SaveAsVariationRequest,
  SaveAsVariationResult,
  RestoreStudioRevisionRequest,
  RestoreStudioRevisionResult,
  SourceComponentIndependentAudit,
  SourceComponentView,
  SourceCoverageAuditStatus,
  SourceCoverageBlocker,
  SourceCoverageComponent,
  SourceCoverageResolutionResult,
  SpecChange,
  StoneVocabularyEntry,
  StoneVocabularyOptions,
  StudioHistoryRevision,
  StudioProjectHistory,
} from './types';

type UnknownRecord = Record<string, unknown>;
type Decoder<T> = (value: unknown) => T | null;

export interface TrustedApiClientOptions {
  baseUrl: string;
  fetcher?: typeof fetch;
  getAccessToken?: () => string | null | Promise<string | null>;
}

const isRecord = (value: unknown): value is UnknownRecord =>
  typeof value === 'object' && value !== null && !Array.isArray(value);

const decodeJsonObject: Decoder<JsonObject> = (value) => {
  const converted = jsonValue(value);
  return converted !== undefined && isRecord(converted) ? converted : null;
};

const pick = (record: UnknownRecord, ...keys: string[]): unknown => {
  for (const key of keys) {
    if (record[key] !== undefined) return record[key];
  }
  return undefined;
};

const text = (value: unknown, fallback = ''): string =>
  typeof value === 'string' ? value : fallback;

const nullableText = (value: unknown): string | null =>
  typeof value === 'string' && value.length > 0 ? value : null;

const number = (value: unknown): number | null =>
  typeof value === 'number' && Number.isFinite(value) ? value : null;

const boolean = (value: unknown, fallback = false): boolean =>
  typeof value === 'boolean' ? value : fallback;

const stringList = (value: unknown): string[] =>
  Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : [];

const recordList = (value: unknown): UnknownRecord[] =>
  Array.isArray(value) ? value.filter(isRecord) : [];

const normalizedIntent = (value: unknown): string => {
  if (typeof value === 'string') return value;
  if (isRecord(value)) {
    const direct = nullableText(pick(value, 'instruction', 'requested_change', 'brief', 'description'));
    if (direct !== null) return direct;
  }
  const converted = jsonValue(value);
  return converted === undefined ? '' : JSON.stringify(converted);
};

function jsonValue(value: unknown): JsonValue | undefined {
  if (value === null || typeof value === 'string' || typeof value === 'boolean') return value;
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (Array.isArray(value)) {
    const converted: JsonValue[] = [];
    for (const item of value) {
      const entry = jsonValue(item);
      if (entry !== undefined) converted.push(entry);
    }
    return converted;
  }
  if (isRecord(value)) {
    const converted: JsonObject = {};
    for (const [key, item] of Object.entries(value)) {
      const entry = jsonValue(item);
      if (entry !== undefined) converted[key] = entry;
    }
    return converted;
  }
  return undefined;
}

const knownProjectState = (value: unknown): ProjectState | null => {
  if (
    value === 'refining' ||
    value === 'approval_required' ||
    value === 'approved' ||
    value === 'factory_ready'
  ) {
    return value;
  }
  return null;
};

const knownOperation = (value: unknown): ImageOperation | null => {
  if (
    value === 'CREATIVE_GENERATE' ||
    value === 'CONCEPT_GENERATE' ||
    value === 'REFERENCE_RENDER' ||
    value === 'SPEC_RENDER' ||
    value === 'LOCAL_EDIT' ||
    value === 'VISUAL_ONLY_EDIT'
  ) {
    return value;
  }
  return null;
};

const knownComponentCatalogPath = (value: unknown): ComponentCatalogPath | null => {
  if (
    value === 'chain.style'
    || value === 'stone.color'
    || value === 'stone.cut'
    || value === 'metal.material'
    || value === 'metal.color'
    || value === 'setting.style'
  ) return value;
  return null;
};

const strictStringList = (
  value: unknown,
  options: { nonEmpty?: boolean } = {},
): string[] | null => {
  if (!Array.isArray(value)) return null;
  if (options.nonEmpty && value.length === 0) return null;
  if (value.some((item) => typeof item !== 'string' || item.trim().length === 0)) {
    return null;
  }
  return value as string[];
};

const knownProductPhotoPreset = (value: unknown): ProductPhotoPreset | null => {
  if (
    value === 'catalog_white' || value === 'luxury_studio'
    || value === 'dark_editorial' || value === 'macro_detail'
  ) return value;
  return null;
};

const knownProductPhotoFraming = (value: unknown): ProductPhotoFraming | null => {
  if (value === 'source' || value === 'square' || value === 'portrait') return value;
  return null;
};

const knownLineArtView = (value: unknown): LineArtView | null => {
  if (value === 'front' || value === 'three_quarter' || value === 'side') return value;
  return null;
};

const knownSourceComponentView = (value: unknown): SourceComponentView | null => {
  if (
    value === 'plate_composite' || value === 'front' || value === 'top'
    || value === 'side' || value === 'three_quarter' || value === 'detail'
    || value === 'unspecified'
  ) return value;
  return null;
};

const knownSourceCoverageAuditStatus = (value: unknown): SourceCoverageAuditStatus | null => {
  if (
    value === 'not_requested' || value === 'pass' || value === 'review_required'
    || value === 'unavailable' || value === 'invalid' || value === 'legacy_provenance'
  ) return value;
  return null;
};

const CANONICAL_SPEC_PATH = /^(?:(?:jewelry_type|template|stone|setting|metal|band|ring_size|bracelet|pendant|chain|brooch|drop|composition|side_stones\[(?:0|[1-9][0-9]*)\])(?:\.[a-z][a-z0-9_]*)*|design_form\.elements\[[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*\])$/;

const canonicalPathList = (value: unknown): string[] | null => {
  if (!Array.isArray(value)) return null;
  const paths = value.filter((item): item is string => typeof item === 'string');
  if (paths.length !== value.length || paths.some((path) => !CANONICAL_SPEC_PATH.test(path))) {
    return null;
  }
  return [...new Set(paths)];
};

const jsonValueIsEmpty = (value: JsonValue): boolean => value === null
  || (Array.isArray(value) && value.length === 0)
  || (isRecord(value) && Object.keys(value).length === 0);

function presentJsonPaths(prefix: string, value: JsonObject): string[] {
  const paths = [prefix];
  for (const [key, child] of Object.entries(value)) {
    if (!/^[a-z][a-z0-9_]*$/.test(key) || jsonValueIsEmpty(child)) continue;
    const childPath = `${prefix}.${key}`;
    paths.push(childPath);
    if (isRecord(child)) paths.push(...presentJsonPaths(childPath, child as JsonObject).slice(1));
  }
  return paths;
}

function validSourcePathsFromSpec(spec: JsonObject): string[] {
  const raw: string[] = [];
  if (typeof spec.jewelry_type === 'string') raw.push('jewelry_type');
  if (typeof spec.template === 'string') raw.push('template');
  for (const root of [
    'stone', 'setting', 'metal', 'band', 'ring_size', 'bracelet', 'pendant',
    'chain', 'brooch', 'drop', 'composition',
  ]) {
    const value = spec[root];
    if (isRecord(value)) raw.push(...presentJsonPaths(root, value as JsonObject));
  }
  if (Array.isArray(spec.side_stones)) {
    spec.side_stones.forEach((value, index) => {
      if (isRecord(value)) {
        raw.push(...presentJsonPaths(`side_stones[${index}]`, value as JsonObject));
      }
    });
  }
  const designForm = spec.design_form;
  const elements = isRecord(designForm) && Array.isArray(designForm.elements)
    ? designForm.elements
    : [];
  for (const element of elements) {
    const elementId = isRecord(element) ? nullableText(element.element_id) : null;
    if (elementId !== null) raw.push(`design_form.elements[${elementId}]`);
  }
  return [...new Set(raw.filter((path) => CANONICAL_SPEC_PATH.test(path)))];
}

const knownVerdict = (value: unknown): 'pass' | 'warn' | 'fail' | null => {
  if (value === 'pass' || value === 'warn' || value === 'fail') return value;
  return null;
};

const normalizeImpact = (value: unknown, hasSpecTarget = false): MarkupImpact => {
  if (value === 'visual_only' || value === 'image_only' || value === 'presentation') {
    return 'visual_only';
  }
  if (
    value === 'specification' ||
    value === 'spec' ||
    value === 'image_and_spec' ||
    value === 'factory_specification'
  ) {
    return 'specification';
  }
  return hasSpecTarget ? 'specification' : 'visual_only';
};

const decodeQualityCheck: Decoder<ImageQualityCheck> = (value) => {
  if (!isRecord(value)) return null;
  const verdict = knownVerdict(value.verdict) ?? (boolean(value.passed, false) ? 'pass' : 'fail');
  return {
    key: text(pick(value, 'key', 'code'), 'quality_check'),
    label: text(pick(value, 'label', 'name'), 'Quality check'),
    verdict,
    severity: value.severity === 'advisory' || value.severity === 'warning' || value.hard === false
      ? 'advisory'
      : 'hard',
    message: text(pick(value, 'message', 'detail', 'reason')),
  };
};

export const decodeImageQualityReport: Decoder<ImageQualityReport> = (value) => {
  if (!isRecord(value)) return null;
  const verdict = knownVerdict(pick(value, 'verdict', 'status'));
  if (verdict === null) return null;
  const checks = (Array.isArray(value.checks) ? value.checks : [])
    .map(decodeQualityCheck)
    .filter((check): check is ImageQualityCheck => check !== null);
  const failedChecks = stringList(pick(value, 'failed_checks', 'failures'));
  const warnings = stringList(pick(value, 'warnings', 'notes'));
  return {
    verdict,
    accepted: boolean(value.accepted, verdict === 'pass'),
    review_required: boolean(value.review_required, verdict === 'warn'),
    score: number(pick(value, 'score', 'conformance_score', 'fidelity_score')),
    summary: text(pick(value, 'summary', 'message'),
      verdict === 'pass' ? 'Image checks passed.' : 'Image needs review.'),
    failed_checks: failedChecks.length > 0
      ? failedChecks
      : checks.filter((check) => check.verdict === 'fail').map((check) => check.key),
    warnings,
    checks,
  };
};

export const decodeAssetSummary: Decoder<AssetSummary> = (value) => {
  if (!isRecord(value)) return null;
  const assetId = nullableText(pick(value, 'asset_id', 'id'));
  if (assetId === null) return null;
  const capability = text(value.capability, 'UNKNOWN');
  return {
    asset_id: assetId,
    root_id: text(pick(value, 'root_id', 'project_id'), assetId),
    parent_asset_id: nullableText(value.parent_asset_id),
    capability,
    provenance: text(value.provenance, capability.toLowerCase()),
    revision: number(pick(value, 'revision', 'version')),
    design_id: nullableText(value.design_id),
    design_version: number(pick(value, 'design_version', 'spec_version')),
    region: nullableText(value.region),
    instruction: nullableText(value.instruction),
    drift: number(value.drift),
    pinned: boolean(value.pinned),
    media_type: text(value.media_type, 'image/png'),
    image_url: nullableText(pick(value, 'image_url', 'url')),
    created_by: nullableText(value.created_by),
    created_at: nullableText(value.created_at),
    legacy_provenance: boolean(
      value.legacy_provenance,
      isRecord(value.provenance) ? boolean(value.provenance.legacy) : false,
    ),
  };
};

const decodeSpecChange: Decoder<SpecChange> = (value) => {
  if (!isRecord(value)) return null;
  const path = nullableText(pick(value, 'path', 'field'));
  const before = jsonValue(pick(value, 'before', 'old'));
  const after = jsonValue(pick(value, 'after', 'new'));
  if (path === null || before === undefined || after === undefined) return null;
  return { path, before, after, label: nullableText(value.label) };
};

const decodeRouting: Decoder<ImageRoutingSummary> = (value) => {
  if (!isRecord(value)) return null;
  const attemptCount = number(pick(value, 'attempt_count', 'attempts'));
  return {
    attempt_count: attemptCount ?? 1,
    used_retry: boolean(pick(value, 'used_retry', 'retried'), (attemptCount ?? 1) > 1),
    used_fallback: boolean(pick(value, 'used_fallback', 'fallback_used')),
    cache_hit: boolean(pick(value, 'cache_hit', 'cached')),
    run_id: nullableText(pick(value, 'run_id', 'image_run_id')),
  };
};

export const decodeProjectRevision: Decoder<ProjectRevision> = (value) => {
  if (!isRecord(value)) return null;
  const asset = decodeAssetSummary(isRecord(value.asset) ? value.asset : value);
  if (asset === null) return null;
  const revision = number(value.revision) ?? asset.revision;
  if (revision === null) return null;
  return {
    revision,
    asset: { ...asset, revision },
    spec_version: number(pick(value, 'spec_version', 'design_version')) ?? asset.design_version,
    spec_change: (Array.isArray(pick(value, 'spec_change', 'changes'))
      ? (pick(value, 'spec_change', 'changes') as unknown[])
      : [])
      .map(decodeSpecChange)
      .filter((change): change is SpecChange => change !== null),
    ignored_fields: stringList(value.ignored_fields),
    qa: decodeImageQualityReport(pick(value, 'qa', 'quality')),
    routing: decodeRouting(pick(value, 'routing', 'route')),
    created_at: nullableText(value.created_at) ?? asset.created_at,
  };
};

const decodeApprovalItem: Decoder<ApprovalItem> = (value) => {
  if (!isRecord(value)) return null;
  const key = nullableText(value.key);
  if (key === null) return null;
  return {
    key,
    label: text(value.label, key),
    fact: text(value.fact),
    section: text(value.section),
    ref: nullableText(value.ref),
    index: number(value.index),
    target_element_id: nullableText(value.target_element_id),
  };
};

const decodeApprovalAnswer = (itemKey: string, value: unknown): ApprovalAnswer | null => {
  if (!isRecord(value) || typeof value.approved !== 'boolean') return null;
  return {
    item_key: itemKey,
    approved: value.approved,
    note: nullableText(value.note),
    understood_as: nullableText(value.understood_as),
    created_by: nullableText(value.created_by),
    created_at: nullableText(value.created_at),
  };
};

export const decodeApprovalSummary: Decoder<ApprovalSummary> = (value) => {
  if (!isRecord(value)) return null;
  const checklistId = nullableText(value.checklist_id);
  const assetId = nullableText(value.asset_id);
  if (checklistId === null || assetId === null) return null;
  const status = isRecord(value.status) ? value.status : value;
  const answers: Record<string, ApprovalAnswer> = {};
  if (isRecord(value.answers)) {
    for (const [itemKey, raw] of Object.entries(value.answers)) {
      const answer = decodeApprovalAnswer(itemKey, raw);
      if (answer !== null) answers[itemKey] = answer;
    }
  }
  const items = (Array.isArray(value.items) ? value.items : [])
    .map(decodeApprovalItem)
    .filter((item): item is ApprovalItem => item !== null);
  const total = number(status.total) ?? items.length;
  const approvedCount = number(pick(status, 'approved_count', 'approved'))
    ?? Object.values(answers).filter((answer) => answer.approved).length;
  const allApproved = boolean(status.all_approved, total > 0 && approvedCount === total);
  const mode = value.mode === 'explicit_pin' || value.mode === 'optional'
    ? value.mode
    : 'auto_pin';
  const pinState = isRecord(value.pin_state) ? value.pin_state : value;
  return {
    checklist_id: checklistId,
    asset_id: assetId,
    design_id: nullableText(value.design_id),
    design_version: number(value.design_version),
    mode,
    items,
    answers,
    outstanding: stringList(status.outstanding),
    approved_count: approvedCount,
    total,
    completed: boolean(status.completed, allApproved),
    all_approved: allApproved,
    pinned: boolean(pick(pinState, 'pinned', 'is_pinned')),
  };
};

const revisionFromAsset = (asset: AssetSummary, fallbackRevision: number): ProjectRevision => {
  const revision = asset.revision ?? fallbackRevision;
  return {
    revision,
    asset: { ...asset, revision },
    spec_version: asset.design_version,
    spec_change: [],
    ignored_fields: [],
    qa: null,
    routing: null,
    created_at: asset.created_at,
  };
};

const decodeFactoryReadinessBlocker: Decoder<FactoryReadinessBlocker> = (value) => {
  if (!isRecord(value)) return null;
  const code = nullableText(value.code);
  const elementId = nullableText(value.element_id);
  const componentId = nullableText(value.component_id);
  const subjectId = nullableText(value.subject_id) ?? elementId ?? componentId;
  const detail = nullableText(pick(value, 'detail', 'message'));
  const requiredResolution = nullableText(value.required_resolution);
  if (code === null || subjectId === null || detail === null || requiredResolution === null) {
    return null;
  }
  const subjectKind = value.subject_kind === 'source_component'
    ? 'source_component'
    : value.subject_kind === 'chain' ? 'chain' : 'design_form';
  return {
    code,
    subject_kind: subjectKind,
    subject_id: subjectId,
    element_id: elementId,
    component_id: componentId,
    role: text(value.role, 'other'),
    label: text(value.label, subjectId),
    detail,
    required_resolution: requiredResolution,
  };
};

export const decodeProjectDetail: Decoder<ProjectDetail> = (value) => {
  if (!isRecord(value)) return null;
  const rootId = nullableText(pick(value, 'root_id', 'id', 'project_id'));
  if (rootId === null) return null;

  const rawAssets = Array.isArray(value.assets)
    ? value.assets
    : Array.isArray(value.items) ? value.items : [];
  const assets = rawAssets
    .map(decodeAssetSummary)
    .filter((asset): asset is AssetSummary => asset !== null);

  const rawRevisions = Array.isArray(value.revisions) ? value.revisions : [];
  let revisions = rawRevisions
    .map(decodeProjectRevision)
    .filter((revision): revision is ProjectRevision => revision !== null);
  if (revisions.length === 0) {
    const primary = assets.filter((asset) => asset.revision !== null);
    revisions = primary.map((asset, index) => revisionFromAsset(asset, index + 1));
  }
  revisions.sort((left, right) => left.revision - right.revision);

  const rawDerived = Array.isArray(value.derived_assets) ? value.derived_assets : [];
  const derivedAssets = rawDerived
    .map(decodeAssetSummary)
    .filter((asset): asset is AssetSummary => asset !== null);
  const allAssets = assets.length > 0
    ? assets
    : [...revisions.map((revision) => revision.asset), ...derivedAssets];

  const activeRaw = decodeAssetSummary(value.active_revision);
  const pinnedRaw = decodeAssetSummary(value.pinned_revision);
  const activeAssetId = nullableText(value.active_asset_id) ?? activeRaw?.asset_id
    ?? revisions.at(-1)?.asset.asset_id ?? null;
  const pinnedAssetId = pinnedRaw?.asset_id
    ?? allAssets.find((asset) => asset.pinned)?.asset_id ?? null;
  const activeRevision = activeRaw
    ?? revisions.find((revision) => revision.asset.asset_id === activeAssetId)?.asset
    ?? null;
  const pinnedRevision = pinnedRaw
    ?? allAssets.find((asset) => asset.asset_id === pinnedAssetId)
    ?? null;

  const approval = decodeApprovalSummary(value.approval);
  const factoryReady = boolean(value.factory_ready)
    || knownProjectState(value.state) === 'factory_ready';
  const state = knownProjectState(value.state)
    ?? (factoryReady
      ? 'factory_ready'
      : approval?.all_approved
        ? approval.pinned ? 'factory_ready' : 'approved'
        : approval ? 'approval_required' : 'refining');

  return {
    id: text(value.id, rootId),
    root_id: rootId,
    title: text(value.title, 'Untitled ring'),
    collection: nullableText(value.collection),
    tags: stringList(value.tags),
    owner: text(value.owner),
    state,
    design_id: nullableText(value.design_id) ?? activeRevision?.design_id ?? null,
    spec: decodeJsonObject(value.spec),
    active_asset_id: activeAssetId,
    selected_candidate_asset_id: nullableText(value.selected_candidate_asset_id),
    active_design_version: number(pick(value, 'active_design_version', 'latest_design_version'))
      ?? activeRevision?.design_version ?? null,
    active_revision: activeRevision,
    pinned_revision: pinnedRevision,
    revisions,
    assets: allAssets,
    derived_assets: derivedAssets,
    approval,
    factory_ready: factoryReady || state === 'factory_ready',
    factory_blockers: recordList(value.factory_blockers)
      .map(decodeFactoryReadinessBlocker)
      .filter((blocker): blocker is FactoryReadinessBlocker => blocker !== null),
    primary_revision_count: number(value.primary_revision_count) ?? revisions.length,
    has_factory_drawing: boolean(value.has_factory_drawing),
    cover_asset_id: nullableText(value.cover_asset_id) ?? activeAssetId,
    created_at: nullableText(value.created_at),
    updated_at: nullableText(value.updated_at),
  };
};

export const decodeSaveAsVariationResult: Decoder<SaveAsVariationResult> = (value) => {
  if (!isRecord(value) || value.status !== 'variation_created') return null;
  const familyId = nullableText(value.family_id);
  const variationIndex = number(value.variation_index);
  const sourceProjectId = nullableText(value.source_project_id);
  const sourceAssetId = nullableText(value.source_asset_id);
  const project = decodeProjectDetail(value.project);
  if (
    familyId === null || variationIndex === null || variationIndex < 1
    || sourceProjectId === null || sourceAssetId === null || project === null
  ) return null;
  return {
    status: 'variation_created',
    family_id: familyId,
    variation_index: variationIndex,
    source_project_id: sourceProjectId,
    source_asset_id: sourceAssetId,
    project,
  };
};

const decodeNumberRecord: Decoder<Record<string, number>> = (value) => {
  if (!isRecord(value)) return null;
  const decoded: Record<string, number> = {};
  for (const [key, raw] of Object.entries(value)) {
    const count = number(raw);
    if (count === null || count < 0) return null;
    decoded[key] = count;
  }
  return decoded;
};

export const decodeStudioHistoryRevision: Decoder<StudioHistoryRevision> = (value) => {
  if (!isRecord(value)) return null;
  const revision = number(value.revision);
  const assetId = nullableText(value.asset_id);
  const imageUrl = nullableText(value.image_url);
  const capability = nullableText(value.capability);
  const action = value.action === 'created' || value.action === 'edit' || value.action === 'restore'
    ? value.action
    : null;
  const rawIntent = decodeJsonObject(value.raw_intent);
  const interpretation = decodeJsonObject(value.interpretation);
  const changeSummary = nullableText(value.change_summary);
  const createdAt = nullableText(value.created_at);
  if (
    revision === null || revision < 1 || assetId === null || imageUrl === null
    || capability === null || action === null || rawIntent === null
    || interpretation === null || changeSummary === null || createdAt === null
  ) return null;
  return {
    revision,
    asset_id: assetId,
    parent_asset_id: nullableText(value.parent_asset_id),
    design_version: number(value.design_version),
    capability,
    image_url: imageUrl,
    pinned: boolean(value.pinned),
    action,
    raw_intent: rawIntent,
    interpretation,
    change_summary: changeSummary,
    restored_from_asset_id: nullableText(value.restored_from_asset_id),
    created_by: nullableText(value.created_by),
    created_at: createdAt,
  };
};

export const decodeStudioProjectHistory: Decoder<StudioProjectHistory> = (value) => {
  if (!isRecord(value)) return null;
  const projectId = nullableText(value.project_id);
  const variationIndex = number(value.variation_index);
  const rawRevisions = Array.isArray(value.revisions) ? value.revisions : null;
  if (projectId === null || variationIndex === null || variationIndex < 1 || rawRevisions === null) {
    return null;
  }
  const revisions = rawRevisions.map(decodeStudioHistoryRevision);
  if (revisions.some((revision) => revision === null)) return null;
  return {
    project_id: projectId,
    family_id: nullableText(value.family_id),
    variation_index: variationIndex,
    variation_label: nullableText(value.variation_label),
    active_asset_id: nullableText(value.active_asset_id),
    revisions: revisions as StudioHistoryRevision[],
  };
};

const decodeDesignFamilyVariation: Decoder<DesignFamilyVariation> = (value) => {
  if (!isRecord(value)) return null;
  const rootId = nullableText(value.root_id);
  const title = nullableText(value.title);
  const collection = nullableText(value.collection);
  const owner = nullableText(value.owner);
  const counts = decodeNumberRecord(value.counts);
  const itemCount = number(value.item_count);
  const primaryRevisionCount = number(value.primary_revision_count);
  const createdAt = nullableText(value.created_at);
  const updatedAt = nullableText(value.updated_at);
  const variationIndex = number(value.variation_index);
  if (
    rootId === null || title === null || collection === null || owner === null || counts === null
    || itemCount === null || itemCount < 0
    || primaryRevisionCount === null || primaryRevisionCount < 0
    || createdAt === null || updatedAt === null
    || variationIndex === null || variationIndex < 1
  ) return null;
  return {
    root_id: rootId,
    title,
    collection,
    tags: stringList(value.tags),
    owner,
    counts,
    item_count: itemCount,
    primary_revision_count: primaryRevisionCount,
    has_factory_drawing: boolean(value.has_factory_drawing),
    cover_asset_id: nullableText(value.cover_asset_id),
    created_at: createdAt,
    updated_at: updatedAt,
    variation_index: variationIndex,
    variation_label: nullableText(value.variation_label),
    branched_from_project_root_id: nullableText(value.branched_from_project_root_id),
    branched_from_asset_id: nullableText(value.branched_from_asset_id),
  };
};

export const decodeDesignFamilyDetail: Decoder<DesignFamilyDetail> = (value) => {
  if (!isRecord(value)) return null;
  const familyId = nullableText(value.family_id);
  const owner = nullableText(value.owner);
  const title = nullableText(value.title);
  const createdAt = nullableText(value.created_at);
  const updatedAt = nullableText(value.updated_at);
  const rawVariations = Array.isArray(value.variations) ? value.variations : null;
  if (
    familyId === null || owner === null || title === null || createdAt === null
    || updatedAt === null || rawVariations === null
  ) return null;
  const variations = rawVariations.map(decodeDesignFamilyVariation);
  if (variations.some((variation) => variation === null)) return null;
  return {
    family_id: familyId,
    owner,
    title,
    created_at: createdAt,
    updated_at: updatedAt,
    variations: variations as DesignFamilyVariation[],
  };
};

export const decodeDesignFamilyList: Decoder<DesignFamilyList> = (value) => {
  if (!isRecord(value) || !Array.isArray(value.families)) return null;
  const families = value.families.map(decodeDesignFamilyDetail);
  if (families.some((family) => family === null)) return null;
  return { families: families as DesignFamilyDetail[] };
};

export const decodeRestoreStudioRevisionResult: Decoder<RestoreStudioRevisionResult> = (value) => {
  if (!isRecord(value) || value.status !== 'restored_as_new_revision') return null;
  const restoredFromAssetId = nullableText(value.restored_from_asset_id);
  const newAssetId = nullableText(value.new_asset_id);
  const project = decodeProjectDetail(value.project);
  const rawChanges = Array.isArray(value.spec_change) ? value.spec_change : null;
  if (restoredFromAssetId === null || newAssetId === null || project === null || rawChanges === null) {
    return null;
  }
  const specChange = rawChanges.map(decodeSpecChange);
  if (specChange.some((change) => change === null)) return null;
  return {
    status: 'restored_as_new_revision',
    restored_from_asset_id: restoredFromAssetId,
    new_asset_id: newAssetId,
    new_design_version: number(value.new_design_version),
    spec_change: specChange as SpecChange[],
    project,
  };
};

export const decodeMarkupInterpretation: Decoder<MarkupInterpretation> = (value) => {
  if (!isRecord(value)) return null;
  const targetRegion = nullableText(pick(value, 'target_region', 'region_description'));
  const requestedChange = nullableText(pick(value, 'requested_change', 'change_instruction'));
  if (targetRegion === null || requestedChange === null) return null;
  const targetReference = nullableText(pick(value, 'target_spec_reference', 'target_ref', 'ref'));
  const targetSection = nullableText(pick(value, 'target_section', 'section'));
  const targetElementId = nullableText(value.target_element_id);
  return {
    target_region: targetRegion,
    requested_change: requestedChange,
    impact: normalizeImpact(
      value.impact,
      targetReference !== null || targetSection !== null || targetElementId !== null,
    ),
    target_spec_reference: targetReference,
    target_section: targetSection,
    target_index: number(pick(value, 'target_index', 'index')),
    target_element_id: targetElementId,
    frozen_elements: stringList(pick(value, 'frozen_elements', 'frozen')),
    confidence: number(value.confidence),
    clarification_question: nullableText(pick(value, 'clarification_question', 'clarification')),
    understood_as: text(value.understood_as, `${requestedChange} in ${targetRegion}`),
  };
};

export const decodeMarkupReadResponse: Decoder<MarkupReadResponse> = (value) => {
  if (!isRecord(value)) return null;
  let interpretation = decodeMarkupInterpretation(value.interpretation);
  if (interpretation === null && Array.isArray(value.annotations)) {
    interpretation = decodeMarkupInterpretation(value.annotations[0]);
  }
  if (interpretation === null) interpretation = decodeMarkupInterpretation(value);
  if (interpretation === null) return null;
  if (interpretation.understood_as.length === 0) {
    interpretation = { ...interpretation, understood_as: text(value.understood_as) };
  }
  return {
    markup_asset_id: nullableText(value.markup_asset_id),
    assistant_name: nullableText(value.assistant_name),
    interpretation,
    design_id: nullableText(value.design_id),
    expected_design_version: number(pick(value, 'expected_design_version', 'design_version')),
  };
};

const defaultQualityReport = (verdict: 'pass' | 'warn' | 'fail'): ImageQualityReport => ({
  verdict,
  accepted: verdict === 'pass',
  review_required: verdict === 'warn',
  score: null,
  summary: verdict === 'pass' ? 'Image checks passed.' : 'Image needs review.',
  failed_checks: [],
  warnings: [],
  checks: [],
});

const decodeWarningCandidate: Decoder<ImageWarningCandidate> = (value) => {
  if (!isRecord(value)) return null;
  const qa = decodeImageQualityReport(pick(value, 'qa', 'quality'));
  const runId = nullableText(pick(value, 'run_id', 'image_run_id'));
  if (qa === null || runId === null || qa.verdict === 'fail') return null;
  return {
    run_id: runId,
    candidate_id: nullableText(value.candidate_id),
    preview_url: nullableText(pick(value, 'preview_url', 'image_url')),
    qa,
    operation: knownOperation(value.operation),
    requested_change: text(pick(value, 'requested_change', 'normalized_intent')),
    asset_capability: nullableText(value.asset_capability),
  };
};

export const decodeProjectCreationResult: Decoder<ProjectCreationResult> = (value) => {
  const project = decodeProjectDetail(value);
  if (project !== null) return project;
  if (!isRecord(value) || value.status !== 'review_required') return null;
  const warningCandidate = decodeWarningCandidate(value.warning_candidate);
  const imageRunId = nullableText(pick(value, 'image_run_id', 'run_id'));
  const quality = jsonValue(value.quality_report);
  if (
    warningCandidate === null || imageRunId === null
    || quality === undefined || !isRecord(quality)
  ) return null;
  return {
    status: 'review_required',
    project: null,
    image_run_id: imageRunId,
    warning_candidate: warningCandidate,
    quality_report: quality,
  };
};

export const decodeBeautyRenderResult: Decoder<BeautyRenderResult> = (value) => {
  if (!isRecord(value)) return null;
  const imageRunId = nullableText(pick(value, 'image_run_id', 'run_id'));
  const sourceAssetId = nullableText(value.source_asset_id);
  if (imageRunId === null || sourceAssetId === null) return null;
  if (value.status === 'accepted') {
    const project = decodeProjectDetail(value.project);
    const assetId = nullableText(value.asset_id);
    const qa = decodeImageQualityReport(value.qa);
    if (project === null || assetId === null || qa === null) return null;
    return {
      status: 'accepted',
      project,
      source_asset_id: sourceAssetId,
      asset_id: assetId,
      image_run_id: imageRunId,
      qa,
    };
  }
  if (value.status !== 'review_required') return null;
  const projectId = nullableText(value.project_id);
  const qa = decodeImageQualityReport(value.quality_report);
  const routing = decodeRouting(value.routing);
  const storedWarning = decodeWarningCandidate(value.warning_candidate);
  if (projectId !== null && qa !== null && routing !== null && storedWarning !== null) {
    return {
      status: 'review_required',
      project_id: projectId,
      source_asset_id: sourceAssetId,
      image_run_id: imageRunId,
      quality_report: qa,
      routing,
      warning_candidate: storedWarning,
    };
  }
  const candidate = isRecord(value.candidate) ? value.candidate : null;
  const imageBase64 = candidate === null
    ? null
    : nullableText(pick(candidate, 'image_b64', 'image_base64'));
  if (projectId === null || qa === null || routing === null || qa.verdict === 'fail'
    || candidate === null || imageBase64 === null) {
    return null;
  }
  const mediaType = text(candidate.media_type, 'image/png');
  return {
    status: 'review_required',
    project_id: projectId,
    source_asset_id: sourceAssetId,
    image_run_id: imageRunId,
    quality_report: qa,
    routing,
    warning_candidate: {
      run_id: imageRunId,
      candidate_id: null,
      preview_url: `data:${mediaType};base64,${imageBase64}`,
      qa,
      operation: 'SPEC_RENDER',
      requested_change: 'Create a beauty render from the confirmed design.',
      asset_capability: 'SPEC_RENDER',
    },
  };
};

const decodeProductPhotoPresentation: Decoder<ProductPhotoPresentation> = (value) => {
  if (!isRecord(value)) return null;
  const preset = knownProductPhotoPreset(value.preset);
  const framing = knownProductPhotoFraming(value.framing);
  const sourceAssetId = nullableText(value.source_asset_id);
  const designVersion = number(value.design_version);
  if (
    preset === null || framing === null || sourceAssetId === null
    || designVersion === null
  ) return null;
  return {
    preset,
    framing,
    source_asset_id: sourceAssetId,
    design_version: designVersion,
  };
};

export const decodeProductPhotoResult: Decoder<ProductPhotoResult> = (value) => {
  if (!isRecord(value)) return null;
  const presentation = decodeProductPhotoPresentation(value.presentation);
  const imageRunId = nullableText(pick(value, 'image_run_id', 'run_id'));
  const routing = decodeRouting(value.routing);
  if (presentation === null || imageRunId === null || routing === null) return null;
  if (value.status === 'accepted') {
    const project = decodeProjectDetail(value.project);
    const assetId = nullableText(value.asset_id);
    const qa = decodeImageQualityReport(value.qa);
    if (project === null || assetId === null || qa === null) return null;
    return {
      status: 'accepted',
      project,
      asset_id: assetId,
      image_run_id: imageRunId,
      qa,
      routing,
      presentation,
    };
  }
  if (value.status === 'review_required') {
    const projectId = nullableText(value.project_id);
    const quality = decodeImageQualityReport(value.quality_report);
    const warning = decodeWarningCandidate(value.warning_candidate);
    if (projectId === null || quality === null || warning === null) return null;
    return {
      status: 'review_required',
      project_id: projectId,
      image_run_id: imageRunId,
      quality_report: quality,
      routing,
      presentation,
      warning_candidate: warning,
    };
  }
  return null;
};

export const decodeMarketingPackResult: Decoder<MarketingPackResult> = (value) => {
  if (!isRecord(value)
      || (value.status !== 'review_required' && value.status !== 'failed')) return null;
  const projectId = nullableText(value.project_id);
  const sourceAssetId = nullableText(value.source_asset_id);
  const designVersion = number(value.design_version);
  const requestedCount = number(value.requested_count);
  const candidateCount = number(value.candidate_count);
  const failedCount = number(value.failed_count);
  const maximumProviderAttempts = number(value.maximum_provider_attempts);
  const actualAttempts = number(value.actual_attempts);
  if (
    projectId === null || sourceAssetId === null || designVersion === null
    || requestedCount === null || candidateCount === null || failedCount === null
    || maximumProviderAttempts === null || actualAttempts === null
  ) return null;
  const candidates = recordList(value.candidates).flatMap((item) => {
    const preset = knownProductPhotoPreset(item.preset);
    const framing = knownProductPhotoFraming(item.framing);
    const runId = nullableText(item.image_run_id);
    const candidateId = nullableText(item.candidate_id);
    const previewUrl = nullableText(item.preview_url);
    const qa = decodeImageQualityReport(item.qa);
    const routing = decodeRouting(item.routing);
    if (
      preset === null || framing === null || runId === null
      || candidateId === null || previewUrl === null || qa === null || routing === null
    ) return [];
    return [{
      preset, framing, image_run_id: runId, candidate_id: candidateId,
      preview_url: previewUrl, qa, routing,
    }];
  });
  const failures = recordList(value.failures).flatMap((item) => {
    const preset = knownProductPhotoPreset(item.preset);
    const code = nullableText(item.code);
    const detail = nullableText(item.detail);
    if (preset === null || code === null || detail === null) return [];
    return [{
      preset,
      image_run_id: nullableText(item.image_run_id),
      error_category: text(item.error_category, 'unknown'),
      code,
      detail,
    }];
  });
  if (candidates.length !== candidateCount || failures.length !== failedCount) return null;
  return {
    status: value.status,
    project_id: projectId,
    source_asset_id: sourceAssetId,
    design_version: designVersion,
    requested_count: requestedCount,
    candidate_count: candidateCount,
    failed_count: failedCount,
    maximum_provider_attempts: maximumProviderAttempts,
    actual_attempts: actualAttempts,
    candidates,
    failures,
  };
};

const FACTORY_FIELD_PATH = /^[a-z][a-z0-9_]*(?:(?:\.[a-z][a-z0-9_]*)|(?:\[[0-9]+\]))+$/;

function catalogSpecValue(spec: JsonObject, path: string): JsonValue | undefined {
  let current: JsonValue = spec;
  const segments = path.replace(/\[([0-9]+)\]/g, '.$1').split('.');
  for (const segment of segments) {
    const next: JsonValue | undefined = Array.isArray(current)
      ? (/^[0-9]+$/.test(segment) ? current[Number(segment)] : undefined)
      : (isRecord(current) ? current[segment] : undefined);
    if (next === undefined) return undefined;
    current = next;
  }
  return current;
}

const sameCatalogValue = (left: JsonValue | undefined, right: JsonValue): boolean =>
  (right === null && left === undefined)
  || (left !== undefined && JSON.stringify(left) === JSON.stringify(right));

export const decodeComponentCatalogOption: Decoder<ComponentCatalogOption> = (value) => {
  if (!isRecord(value)) return null;
  const id = nullableText(value.id);
  const display = nullableText(value.display);
  const geometry = strictStringList(value.visual_geometry, { nonEmpty: true });
  const isolationTarget = nullableText(value.isolation_target);
  const frozenFacts = strictStringList(value.frozen_facts, { nonEmpty: true });
  const factoryFields = decodeJsonObject(value.factory_fields);
  const derivedFields = strictStringList(value.derived_factory_fields);
  const requirements = strictStringList(value.selection_requirements);
  if (
    id === null || display === null || geometry === null || isolationTarget === null
    || frozenFacts === null || factoryFields === null || derivedFields === null
    || requirements === null || Object.keys(factoryFields).length === 0
    || Object.keys(factoryFields).some((path) => !FACTORY_FIELD_PATH.test(path))
    || derivedFields.some((path) => !FACTORY_FIELD_PATH.test(path))
    || new Set(frozenFacts).size !== frozenFacts.length
    || new Set(derivedFields).size !== derivedFields.length
  ) return null;
  return {
    id,
    display,
    visual_geometry: geometry,
    isolation_target: isolationTarget,
    frozen_facts: frozenFacts,
    factory_fields: factoryFields,
    derived_factory_fields: derivedFields,
    selection_requirements: requirements,
  };
};

export const decodeComponentCatalog: Decoder<ComponentCatalog> = (value) => {
  if (!isRecord(value)) return null;
  const componentPath = knownComponentCatalogPath(value.component_path);
  const display = nullableText(value.display);
  const jewelryTypes = strictStringList(value.applicable_jewelry_types, { nonEmpty: true });
  const imageAgentStatus = value.image_agent_status === 'catalog_ready'
    || value.image_agent_status === 'catalog_ready_category_pending'
    ? value.image_agent_status
    : null;
  const rawOptions = Array.isArray(value.options) ? value.options : null;
  const options = rawOptions?.map(decodeComponentCatalogOption) ?? [];
  if (
    componentPath === null || display === null || jewelryTypes === null
    || imageAgentStatus === null || rawOptions === null || rawOptions.length === 0
    || options.some((option) => option === null)
    || jewelryTypes.some((kind) => kind !== 'ring' && kind !== 'necklace')
  ) return null;
  const decodedOptions = options as ComponentCatalogOption[];
  if (new Set(decodedOptions.map((option) => option.id)).size !== decodedOptions.length) {
    return null;
  }
  return {
    component_path: componentPath,
    display,
    applicable_jewelry_types: jewelryTypes,
    image_agent_status: imageAgentStatus,
    options: decodedOptions,
  };
};

export const decodeStoneVocabulary: Decoder<StoneVocabularyEntry[]> = (value) => {
  if (!isRecord(value) || !Array.isArray(value.stones)) return null;
  const entries = value.stones.map((item): StoneVocabularyEntry | null => {
    if (!isRecord(item)) return null;
    const id = nullableText(item.id);
    const display = nullableText(item.display);
    const parameterSet = nullableText(item.parameter_set);
    return id === null || display === null || parameterSet === null
      ? null : { id, display, parameter_set: parameterSet };
  });
  if (entries.some((entry) => entry === null)) return null;
  const decoded = entries as StoneVocabularyEntry[];
  return new Set(decoded.map((entry) => entry.id)).size === decoded.length
    ? decoded : null;
};

export const decodeStoneVocabularyOptions: Decoder<StoneVocabularyOptions> = (value) => {
  if (!isRecord(value) || value.parameter_set !== 'gemstone') return null;
  const stone = nullableText(value.stone);
  const display = nullableText(value.display);
  if (!Array.isArray(value.colors) || !Array.isArray(value.cuts)) return null;
  const colors = value.colors.map((item) => {
    if (!isRecord(item)) return null;
    const term = nullableText(item.term);
    const gia = nullableText(item.gia);
    return term === null || gia === null ? null : { term, gia };
  });
  const cuts = value.cuts.map((item) => {
    if (!isRecord(item)) return null;
    const id = nullableText(item.id);
    const name = nullableText(item.name);
    return id === null || name === null ? null : { id, name };
  });
  if (
    stone === null || display === null || colors.length === 0 || cuts.length === 0
    || colors.some((item) => item === null) || cuts.some((item) => item === null)
  ) return null;
  return {
    stone,
    display,
    parameter_set: 'gemstone',
    colors: colors as StoneVocabularyOptions['colors'],
    cuts: cuts as StoneVocabularyOptions['cuts'],
  };
};

const decodeCatalogWarningCandidate: Decoder<CatalogWarningCandidate> = (value) => {
  if (!isRecord(value) || value.operation !== 'LOCAL_EDIT') return null;
  const runId = nullableText(value.run_id);
  const candidateId = nullableText(value.candidate_id);
  const previewUrl = nullableText(value.preview_url);
  const requestedChange = nullableText(value.requested_change);
  if (
    runId === null || candidateId === null || previewUrl === null
    || requestedChange === null
  ) return null;
  return {
    run_id: runId,
    candidate_id: candidateId,
    preview_url: previewUrl,
    operation: 'LOCAL_EDIT',
    requested_change: requestedChange,
  };
};

const decodeCatalogSpecChanges = (value: unknown): SpecChange[] | null => {
  if (!Array.isArray(value) || value.length === 0) return null;
  const changes = value.map(decodeSpecChange);
  if (changes.some((change) => change === null)) return null;
  const decoded = changes as SpecChange[];
  if (
    decoded.some((change) => !FACTORY_FIELD_PATH.test(change.path)
      || change.label === null || change.label.trim().length === 0)
    || new Set(decoded.map((change) => change.path)).size !== decoded.length
  ) return null;
  return decoded;
};

export const decodeDraftCatalogSelectionResult: Decoder<
DraftCatalogSelectionResult
> = (value) => {
  if (!isRecord(value)) return null;
  const spec = decodeJsonObject(value.spec);
  const changes = decodeCatalogSpecChanges(value.spec_change);
  const isolationTarget = nullableText(value.isolation_target);
  const frozenFacts = strictStringList(value.frozen_facts, { nonEmpty: true });
  if (
    spec === null || changes === null || isolationTarget === null
    || frozenFacts === null || new Set(frozenFacts).size !== frozenFacts.length
  ) return null;
  return {
    spec,
    spec_change: changes,
    isolation_target: isolationTarget,
    frozen_facts: frozenFacts,
  };
};

export const decodeCatalogApplyResult: Decoder<CatalogApplyResult> = (value) => {
  if (!isRecord(value)) return null;
  const componentPath = knownComponentCatalogPath(value.component_path);
  const optionId = nullableText(value.option_id);
  const isolationTarget = nullableText(value.isolation_target);
  const designVersion = number(value.design_version);
  const imageRunId = nullableText(value.image_run_id);
  const specChange = decodeCatalogSpecChanges(value.spec_change);
  const qa = decodeImageQualityReport(value.qa);
  const routing = decodeRouting(value.routing);
  const project = decodeProjectDetail(value.project);
  const projectSpec = project?.spec ?? null;
  if (
    componentPath === null || optionId === null || isolationTarget === null
    || designVersion === null || !Number.isInteger(designVersion) || designVersion < 1
    || imageRunId === null || specChange === null || qa === null || routing === null
    || routing.attempt_count < 1 || routing.run_id !== imageRunId || project === null
    || projectSpec === null
  ) return null;

  if (value.status === 'accepted') {
    const assetId = nullableText(value.asset_id);
    if (
      assetId === null || qa.verdict !== 'pass' || !qa.accepted || qa.review_required
      || project.active_asset_id !== assetId
      || project.active_design_version !== designVersion
      || !specChange.every((change) => sameCatalogValue(
        catalogSpecValue(projectSpec, change.path), change.after,
      ))
      || value.next_spec !== undefined || value.warning_candidate !== undefined
    ) return null;
    return {
      status: 'accepted',
      component_path: componentPath,
      option_id: optionId,
      isolation_target: isolationTarget,
      asset_id: assetId,
      design_version: designVersion,
      image_run_id: imageRunId,
      spec_change: specChange,
      qa,
      routing,
      project,
    };
  }

  if (value.status !== 'review_required' || value.asset_id !== undefined) return null;
  const nextSpec = decodeJsonObject(value.next_spec);
  const warningCandidate = decodeCatalogWarningCandidate(value.warning_candidate);
  if (
    nextSpec === null || warningCandidate === null
    || qa.verdict !== 'warn' || qa.accepted || !qa.review_required
    || warningCandidate.run_id !== imageRunId
    || project.active_design_version !== designVersion
    || !specChange.every((change) => sameCatalogValue(
      catalogSpecValue(projectSpec, change.path), change.before,
    ) && sameCatalogValue(catalogSpecValue(nextSpec, change.path), change.after))
  ) return null;
  return {
    status: 'review_required',
    component_path: componentPath,
    option_id: optionId,
    isolation_target: isolationTarget,
    design_version: designVersion,
    image_run_id: imageRunId,
    spec_change: specChange,
    next_spec: nextSpec,
    qa,
    routing,
    project,
    warning_candidate: warningCandidate,
  };
};

const catalogCandidatePath = (
  runId: string,
  candidateId: string,
  suffix = '',
): string => `/image-runs/${encodeURIComponent(runId)}/catalog-candidates/${encodeURIComponent(candidateId)}${suffix}`;

const endpointPath = (value: unknown): string | null => {
  const raw = nullableText(value);
  if (raw === null) return null;
  try {
    const parsed = new URL(raw, 'https://facetta.invalid');
    if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') return null;
    if (parsed.search.length > 0 || parsed.hash.length > 0) return null;
    return parsed.pathname;
  } catch {
    return null;
  }
};

const decodeCatalogPreviewCandidate: Decoder<CatalogPreviewCandidate> = (value) => {
  if (!isRecord(value)) return null;
  const runId = nullableText(value.run_id);
  const candidateId = nullableText(value.candidate_id);
  const previewUrl = nullableText(value.preview_url);
  const acceptUrl = nullableText(value.accept_url);
  const discardUrl = nullableText(value.discard_url);
  const expiresInSeconds = number(value.expires_in_seconds);
  if (
    runId === null || candidateId === null || previewUrl === null
    || acceptUrl === null || discardUrl === null
    || (value.verdict !== 'pass' && value.verdict !== 'warn')
    || expiresInSeconds === null || !Number.isInteger(expiresInSeconds)
    || expiresInSeconds < 1
  ) return null;
  const root = catalogCandidatePath(runId, candidateId);
  if (
    endpointPath(previewUrl) !== `${root}/image`
    || endpointPath(acceptUrl) !== `${root}/accept`
    || endpointPath(discardUrl) !== root
  ) return null;
  return {
    run_id: runId,
    candidate_id: candidateId,
    preview_url: previewUrl,
    accept_url: acceptUrl,
    discard_url: discardUrl,
    verdict: value.verdict,
    expires_in_seconds: expiresInSeconds,
  };
};

/** Decode a temporary catalog preview without weakening its lineage checks. */
export const decodeCatalogPreviewResult: Decoder<CatalogPreviewResult> = (value) => {
  if (!isRecord(value)) return null;
  const componentPath = knownComponentCatalogPath(value.component_path);
  const optionId = nullableText(value.option_id);
  const isolationTarget = nullableText(value.isolation_target);
  const sourceAssetId = nullableText(value.source_asset_id);
  const designVersion = number(value.design_version);
  const imageRunId = nullableText(value.image_run_id);
  const specChange = decodeCatalogSpecChanges(value.spec_change);
  const nextSpec = decodeJsonObject(value.next_spec);
  const qa = decodeImageQualityReport(value.qa);
  const routing = decodeRouting(value.routing);
  const project = decodeProjectDetail(value.project);
  const candidate = decodeCatalogPreviewCandidate(value.candidate);
  if (
    componentPath === null || optionId === null || isolationTarget === null
    || sourceAssetId === null || designVersion === null
    || !Number.isInteger(designVersion) || designVersion < 1
    || imageRunId === null || specChange === null || nextSpec === null
    || qa === null || routing === null || routing.attempt_count < 1
    || routing.run_id !== imageRunId || project === null || project.spec === null
    || candidate === null || candidate.run_id !== imageRunId
    || project.active_asset_id !== sourceAssetId
    || project.active_design_version !== designVersion
    || !specChange.every((change) => sameCatalogValue(
      catalogSpecValue(project.spec as JsonObject, change.path), change.before,
    ) && sameCatalogValue(catalogSpecValue(nextSpec, change.path), change.after))
  ) return null;

  const pass = value.status === 'preview_ready';
  const warn = value.status === 'review_required';
  if (
    (!pass && !warn)
    || (pass && (
      candidate.verdict !== 'pass' || qa.verdict !== 'pass'
      || !qa.accepted || qa.review_required
    ))
    || (warn && (
      candidate.verdict !== 'warn' || qa.verdict !== 'warn'
      || qa.accepted || !qa.review_required
    ))
  ) return null;

  return {
    status: pass ? 'preview_ready' : 'review_required',
    component_path: componentPath,
    option_id: optionId,
    isolation_target: isolationTarget,
    source_asset_id: sourceAssetId,
    design_version: designVersion,
    image_run_id: imageRunId,
    spec_change: specChange,
    next_spec: nextSpec,
    qa,
    routing,
    project,
    candidate,
  };
};

export const decodeCatalogPreviewAcceptResult: Decoder<
CatalogPreviewAcceptResult
> = (value) => {
  if (!isRecord(value) || value.status !== 'accepted') return null;
  const assetId = nullableText(value.asset_id);
  const designVersion = number(value.design_version);
  const imageRunId = nullableText(value.image_run_id);
  const specChange = decodeCatalogSpecChanges(value.spec_change);
  const project = decodeProjectDetail(value.project);
  if (
    assetId === null || designVersion === null || !Number.isInteger(designVersion)
    || designVersion < 2 || imageRunId === null || specChange === null
    || project === null || project.spec === null
    || project.active_asset_id !== assetId
    || project.active_design_version !== designVersion
    || !specChange.every((change) => sameCatalogValue(
      catalogSpecValue(project.spec as JsonObject, change.path), change.after,
    ))
  ) return null;
  return {
    status: 'accepted',
    asset_id: assetId,
    design_version: designVersion,
    image_run_id: imageRunId,
    spec_change: specChange,
    project,
  };
};

const decodeSourceComponentIndependentAudit: Decoder<SourceComponentIndependentAudit> = (
  value,
) => {
  if (!isRecord(value) || value.kind !== 'independent_component_audit') return null;
  const verdict = value.verdict === 'pass' || value.verdict === 'fail'
    || value.verdict === 'inconclusive'
    ? value.verdict
    : null;
  const sourceView = knownSourceComponentView(value.source_view);
  const auditor = nullableText(value.auditor);
  const observedDescription = nullableText(value.observed_description);
  if (verdict === null || sourceView === null || auditor === null
    || observedDescription === null) return null;
  return {
    kind: 'independent_component_audit',
    verdict,
    auditor,
    source_view: sourceView,
    observed_description: observedDescription,
    evidence_sha256: nullableText(value.evidence_sha256),
  };
};

const decodeDesignerComponentConfirmation: Decoder<DesignerComponentConfirmation> = (
  value,
) => {
  if (!isRecord(value) || value.kind !== 'designer_component_confirmation') return null;
  const basis = value.basis === 'visible_source' || value.basis === 'designer_defined_target'
    ? value.basis
    : null;
  const reviewer = nullableText(value.reviewer);
  const sourceView = knownSourceComponentView(value.source_view);
  const confirmedDescription = nullableText(value.confirmed_description);
  const evidenceSha256 = nullableText(value.evidence_sha256);
  const specVisualHash = nullableText(value.spec_visual_hash);
  if (basis === null || reviewer === null || sourceView === null
    || confirmedDescription === null || evidenceSha256 === null
    || specVisualHash === null) return null;
  return {
    kind: 'designer_component_confirmation',
    basis,
    reviewer,
    source_view: sourceView,
    confirmed_description: confirmedDescription,
    evidence_sha256: evidenceSha256,
    spec_visual_hash: specVisualHash,
  };
};

const decodeSourceCoverageComponent: Decoder<SourceCoverageComponent> = (value) => {
  if (!isRecord(value)) return null;
  const componentId = nullableText(value.component_id);
  const sourceView = knownSourceComponentView(value.source_view);
  const sourceDescription = nullableText(value.source_description);
  const confidence = number(value.source_confidence);
  const paths = canonicalPathList(value.canonical_spec_paths);
  const unresolvedReason = nullableText(value.unresolved_reason);
  const audit = value.independent_audit === null || value.independent_audit === undefined
    ? null
    : decodeSourceComponentIndependentAudit(value.independent_audit);
  const confirmation = value.designer_confirmation === null
    || value.designer_confirmation === undefined
    ? null
    : decodeDesignerComponentConfirmation(value.designer_confirmation);
  if (
    componentId === null || sourceView === null || sourceDescription === null
    || confidence === null || confidence < 0 || confidence > 1 || paths === null
    || (paths.length > 0) === (unresolvedReason !== null)
    || (value.independent_audit !== null && value.independent_audit !== undefined && audit === null)
    || (value.designer_confirmation !== null && value.designer_confirmation !== undefined
      && confirmation === null)
  ) return null;
  return {
    component_id: componentId,
    source_view: sourceView,
    source_description: sourceDescription,
    source_confidence: confidence,
    canonical_spec_paths: paths,
    unresolved_reason: unresolvedReason,
    independent_audit: audit,
    designer_confirmation: confirmation,
  };
};

const knownSourceCoverageBlockerCode = (
  value: unknown,
): SourceCoverageBlocker['code'] | null => {
  if (
    value === 'source_component_unresolved'
    || value === 'source_component_not_independently_audited'
    || value === 'source_component_audit_failed'
    || value === 'source_component_audit_inconclusive'
    || value === 'source_component_path_missing'
    || value === 'source_component_spec_audit_missing'
    || value === 'source_component_spec_audit_stale'
    || value === 'source_component_confirmation_stale'
  ) return value;
  return null;
};

const decodeSourceCoverageBlocker: Decoder<SourceCoverageBlocker> = (value) => {
  if (!isRecord(value)) return null;
  const code = knownSourceCoverageBlockerCode(value.code);
  const componentId = nullableText(value.component_id);
  const message = nullableText(value.message);
  const requiredResolution = nullableText(value.required_resolution);
  if (code === null || componentId === null || message === null || requiredResolution === null) {
    return null;
  }
  return {
    code,
    component_id: componentId,
    message,
    required_resolution: requiredResolution,
  };
};

function sourceCoverageBlockersFromComponents(
  components: SourceCoverageComponent[],
  validSpecPaths?: string[],
): SourceCoverageBlocker[] {
  const blockers: SourceCoverageBlocker[] = [];
  const validPaths = validSpecPaths === undefined ? null : new Set(validSpecPaths);
  for (const component of components) {
    if (validPaths !== null) {
      const missing = component.canonical_spec_paths.filter(
        (path) => !validPaths.has(path),
      );
      if (missing.length > 0) {
        blockers.push({
          code: 'source_component_path_missing',
          component_id: component.component_id,
          message: `${component.component_id} maps to paths absent from this draft: ${missing.join(', ')}`,
          required_resolution: 'Map this component to paths that exist in the current specification before re-running the audit.',
        });
      }
    }
    if (component.unresolved_reason !== null) {
      blockers.push({
        code: 'source_component_unresolved',
        component_id: component.component_id,
        message: `${component.component_id} remains unresolved: ${component.unresolved_reason}`,
        required_resolution: 'Map this component to existing specification paths or retain an explicit unresolved note.',
      });
    }
    if (component.independent_audit === null) {
      blockers.push({
        code: 'source_component_not_independently_audited',
        component_id: component.component_id,
        message: `${component.component_id} has not been independently audited against the source.`,
        required_resolution: 'Run the independent component-coverage audit.',
      });
    } else if (component.independent_audit.verdict === 'fail') {
      blockers.push({
        code: 'source_component_audit_failed',
        component_id: component.component_id,
        message: component.independent_audit.observed_description,
        required_resolution: 'Correct the mapping and repeat the independent audit.',
      });
    } else if (component.independent_audit.verdict === 'inconclusive'
      && (component.designer_confirmation ?? null) === null) {
      blockers.push({
        code: 'source_component_audit_inconclusive',
        component_id: component.component_id,
        message: component.independent_audit.observed_description,
        required_resolution: 'Provide a clearer source view and repeat the independent audit.',
      });
    }
  }
  return blockers;
}

function sourceCoverageSnapshotFromSpec(
  spec: JsonObject,
  options: {
    requested: boolean;
    status?: SourceCoverageAuditStatus;
    blocker_count?: number;
  },
): SourceCoverageResolutionResult | null {
  const coverage = isRecord(spec.source_component_coverage)
    ? spec.source_component_coverage
    : null;
  const rawComponents = coverage !== null && Array.isArray(coverage.components)
    ? coverage.components
    : [];
  const components = rawComponents
    .map(decodeSourceCoverageComponent)
    .filter((item): item is SourceCoverageComponent => item !== null);
  if (coverage === null || components.length !== rawComponents.length) return null;
  const validSpecPaths = validSourcePathsFromSpec(spec);
  const blockers = sourceCoverageBlockersFromComponents(
    components,
    validSpecPaths,
  );
  const status = options.status
    ?? (blockers.length === 0 && components.length > 0 ? 'pass' : 'review_required');
  const blockerCount = options.blocker_count ?? blockers.length;
  return {
    spec,
    source_kind: nullableText(coverage.source_kind),
    components,
    valid_spec_paths: validSpecPaths,
    changed_component_ids: [],
    invalidated_audit_component_ids: [],
    blockers,
    factory_ready: status === 'pass' && blockerCount === 0 && blockers.length === 0,
    legacy_provenance: false,
    resolved_by: null,
    audit: {
      requested: options.requested,
      status,
      audited_component_ids: components
        .filter((component) => component.independent_audit !== null)
        .map((component) => component.component_id),
      blocker_count: blockerCount,
    },
  };
}

export const decodePhotoDraftResult: Decoder<PhotoDraftResult> = (value) => {
  const spec = decodeJsonObject(value);
  if (spec === null) return null;
  const sourceCoverage = sourceCoverageSnapshotFromSpec(spec, { requested: true });
  if (sourceCoverage === null) return null;
  return { spec, source_coverage: sourceCoverage };
};

export const decodeSourceCoverageResolutionResult: Decoder<
SourceCoverageResolutionResult
> = (value) => {
  if (!isRecord(value)) return null;
  const spec = decodeJsonObject(value.spec);
  const components = (Array.isArray(value.components) ? value.components : [])
    .map(decodeSourceCoverageComponent)
    .filter((item): item is SourceCoverageComponent => item !== null);
  const validPaths = canonicalPathList(value.valid_spec_paths);
  const blockers = (Array.isArray(value.blockers) ? value.blockers : [])
    .map(decodeSourceCoverageBlocker)
    .filter((item): item is SourceCoverageBlocker => item !== null);
  const audit = isRecord(value.audit) ? value.audit : null;
  const auditStatus = audit === null ? null : knownSourceCoverageAuditStatus(audit.status);
  const blockerCount = audit === null ? null : number(audit.blocker_count);
  if (
    spec === null || validPaths === null || audit === null || auditStatus === null
    || blockerCount === null
    || components.length !== (Array.isArray(value.components) ? value.components.length : 0)
    || blockers.length !== (Array.isArray(value.blockers) ? value.blockers.length : 0)
  ) return null;
  return {
    spec,
    source_kind: nullableText(value.source_kind),
    components,
    valid_spec_paths: validPaths,
    changed_component_ids: stringList(value.changed_component_ids),
    invalidated_audit_component_ids: stringList(value.invalidated_audit_component_ids),
    blockers,
    factory_ready: boolean(value.factory_ready),
    legacy_provenance: boolean(value.legacy_provenance),
    resolved_by: nullableText(value.resolved_by),
    audit: {
      requested: boolean(audit.requested),
      status: auditStatus,
      audited_component_ids: stringList(audit.audited_component_ids),
      blocker_count: blockerCount,
    },
  };
};

export const decodeConfirmSourceCoverageResult: Decoder<
ConfirmSourceCoverageResult
> = (value) => {
  if (!isRecord(value)) return null;
  const spec = decodeJsonObject(value.spec);
  const blockers = (Array.isArray(value.blockers) ? value.blockers : [])
    .map(decodeSourceCoverageBlocker)
    .filter((item): item is SourceCoverageBlocker => item !== null);
  const confirmedBy = nullableText(value.confirmed_by);
  if (spec === null || confirmedBy === null
    || blockers.length !== (Array.isArray(value.blockers) ? value.blockers.length : 0)) {
    return null;
  }
  return {
    spec,
    confirmed_component_ids: stringList(value.confirmed_component_ids),
    blockers,
    factory_ready: boolean(value.factory_ready),
    confirmed_by: confirmedBy,
  };
};

const decodeDimensionedProfilePath: Decoder<DimensionedProfilePath> = (value) => {
  if (!isRecord(value) || !Array.isArray(value.points)) return null;
  const pathId = nullableText(value.path_id);
  const purpose = value.purpose === 'outline' || value.purpose === 'centerline'
    || value.purpose === 'stone_seat' || value.purpose === 'attachment'
    ? value.purpose : null;
  const points = value.points.map((point) => {
    if (!isRecord(point)) return null;
    const x = number(point.x_mm);
    const y = number(point.y_mm);
    return x === null || y === null ? null : { x_mm: x, y_mm: y };
  });
  const nominalWidth = value.nominal_width_mm === null
    ? null : number(value.nominal_width_mm);
  if (
    pathId === null || purpose === null || typeof value.closed !== 'boolean'
    || points.length < 2 || points.some((point) => point === null)
    || (value.nominal_width_mm !== null && nominalWidth === null)
  ) return null;
  return {
    path_id: pathId,
    purpose,
    closed: value.closed,
    points: points as DimensionedProfilePath['points'],
    nominal_width_mm: nominalWidth,
  };
};

const decodeDimensionedProfileDefinition: Decoder<
DimensionedProfileDefinition
> = (value) => {
  if (!isRecord(value) || !Array.isArray(value.paths)) return null;
  const paths = value.paths.map(decodeDimensionedProfilePath);
  const view = nullableText(value.view);
  const thickness = number(value.profile_thickness_mm);
  const notes = nullableText(value.manufacturing_notes);
  const sourceAssetId = nullableText(value.source_asset_id);
  const sourceHash = nullableText(value.source_asset_sha256);
  const confirmedBy = nullableText(value.confirmed_by);
  const confirmedAt = nullableText(value.confirmed_at);
  const status = value.dimension_status === 'designer_supplied'
    || value.dimension_status === 'designer_confirmed_estimate'
    ? value.dimension_status : null;
  if (
    value.kind !== 'dimensioned_profile' || value.scope !== 'full_assembly'
    || value.coordinate_system !== 'x_right_y_up' || view === null
    || thickness === null || thickness <= 0 || status === null || notes === null
    || sourceAssetId === null || sourceHash === null
    || !/^[0-9a-f]{64}$/.test(sourceHash)
    || confirmedBy === null || confirmedAt === null || paths.length === 0
    || paths.some((path) => path === null)
  ) return null;
  return {
    kind: 'dimensioned_profile',
    scope: 'full_assembly',
    coordinate_system: 'x_right_y_up',
    view,
    paths: paths as DimensionedProfilePath[],
    profile_thickness_mm: thickness,
    dimension_status: status,
    manufacturing_notes: notes,
    source_asset_id: sourceAssetId,
    source_asset_sha256: sourceHash,
    confirmed_by: confirmedBy,
    confirmed_at: confirmedAt,
  };
};

export const decodeConfirmCreativeCandidateProfileResult: Decoder<
ConfirmCreativeCandidateProfileResult
> = (value) => {
  if (!isRecord(value) || !Array.isArray(value.blockers)) return null;
  const spec = decodeJsonObject(value.spec);
  const elementId = nullableText(value.element_id);
  const candidateId = nullableText(value.candidate_asset_id);
  const candidateHash = nullableText(value.candidate_sha256);
  const previousKind = nullableText(value.previous_definition_kind);
  const definition = decodeDimensionedProfileDefinition(value.definition);
  const authority = value.sheet_authority === 'factory_profile'
    || value.sheet_authority === 'preliminary_not_for_production'
    ? value.sheet_authority : null;
  const blockers = value.blockers.map((item) => {
    if (!isRecord(item)) return null;
    const code = nullableText(item.code);
    const detail = nullableText(item.detail);
    return code === null || detail === null ? null : { code, detail };
  });
  if (
    spec === null || elementId === null || candidateId === null
    || candidateHash === null || !/^[0-9a-f]{64}$/.test(candidateHash)
    || previousKind === null || definition === null || authority === null
    || typeof value.source_reaudit_required !== 'boolean'
    || typeof value.factory_ready !== 'boolean'
    || blockers.some((item) => item === null)
  ) return null;
  return {
    spec,
    element_id: elementId,
    candidate_asset_id: candidateId,
    candidate_sha256: candidateHash,
    previous_definition_kind: previousKind,
    definition,
    source_reaudit_required: value.source_reaudit_required,
    factory_ready: value.factory_ready,
    sheet_authority: authority,
    blockers: blockers as ConfirmCreativeCandidateProfileResult['blockers'],
  };
};

export const decodePlateDraftResult: Decoder<PlateDraftResult> = (value) => {
  if (!isRecord(value)) return null;
  const spec = decodeJsonObject(value.spec);
  const read = decodeJsonObject(value.read);
  if (
    spec === null || read === null
    || value.provenance !== 'grok_vision_hand_plate_draft'
    || value.requires_designer_confirmation !== true
  ) return null;
  const audit = isRecord(value.source_coverage_audit)
    ? value.source_coverage_audit
    : {};
  const auditStatus = audit.status === 'pass'
    || audit.status === 'review_required'
    || audit.status === 'unavailable'
    || audit.status === 'invalid'
    || audit.status === 'not_requested'
    ? audit.status
    : 'not_requested';
  const reportedBlockerCount = number(audit.blocker_count);
  const sourceCoverage = sourceCoverageSnapshotFromSpec(spec, {
    requested: auditStatus !== 'not_requested',
    status: auditStatus,
    ...(reportedBlockerCount === null ? {} : { blocker_count: reportedBlockerCount }),
  });
  if (sourceCoverage === null) return null;
  return {
    spec,
    read,
    uncertainties: stringList(value.uncertainties),
    provenance: 'grok_vision_hand_plate_draft',
    requires_designer_confirmation: true,
    source_coverage_audit: {
      status: auditStatus,
      blocker_count: sourceCoverage.audit.blocker_count,
    },
    source_coverage: sourceCoverage,
  };
};

export const decodeDrawingConfirmationResult: Decoder<DrawingConfirmationResult> = (value) => {
  if (!isRecord(value) || value.status !== 'confirmation_required') return null;
  const projectId = nullableText(value.project_id);
  const imageRunId = nullableText(value.image_run_id);
  const qa = decodeImageQualityReport(value.quality_report);
  const routing = decodeRouting(value.routing);
  const view = knownLineArtView(value.view);
  const candidate = decodeWarningCandidate(value.candidate);
  if (
    projectId === null || imageRunId === null || qa === null
    || routing === null || view === null || candidate === null
  ) return null;
  return {
    status: 'confirmation_required',
    project_id: projectId,
    image_run_id: imageRunId,
    quality_report: qa,
    routing,
    view,
    candidate,
    next: text(value.next),
  };
};

export const decodeColorizeLineArtResult: Decoder<ColorizeLineArtResult> = (value) => {
  if (!isRecord(value)) return null;
  const imageRunId = nullableText(value.image_run_id);
  const routing = decodeRouting(value.routing);
  if (imageRunId === null || routing === null) return null;
  if (value.status === 'accepted') {
    const project = decodeProjectDetail(value.project);
    const assetId = nullableText(value.asset_id);
    const qa = decodeImageQualityReport(value.qa);
    if (project === null || assetId === null || qa === null) return null;
    return {
      status: 'accepted', project, asset_id: assetId,
      image_run_id: imageRunId, qa, routing,
    };
  }
  if (value.status === 'review_required') {
    const projectId = nullableText(value.project_id);
    const qa = decodeImageQualityReport(value.quality_report);
    const candidate = decodeWarningCandidate(value.candidate);
    if (projectId === null || qa === null || candidate === null) return null;
    return {
      status: 'review_required', project_id: projectId,
      image_run_id: imageRunId, quality_report: qa, routing, candidate,
    };
  }
  return null;
};

const decodeProjectComment: Decoder<ProjectComment> = (value) => {
  if (!isRecord(value)) return null;
  const id = nullableText(value.id);
  const designId = nullableText(value.design_id);
  const body = nullableText(value.body);
  const author = nullableText(value.author);
  if (id === null || designId === null || body === null || author === null) return null;
  return {
    id,
    design_id: designId,
    version: number(value.version),
    author,
    author_label: nullableText(value.author_label),
    body,
    created_at: nullableText(value.created_at),
  };
};

const decodeProjectComments: Decoder<ProjectComment[]> = (value) => {
  if (!isRecord(value) || !Array.isArray(value.messages)) return null;
  return value.messages
    .map(decodeProjectComment)
    .filter((comment): comment is ProjectComment => comment !== null);
};

export const decodeMarkupApplyResponse: Decoder<MarkupApplyResponse> = (value) => {
  if (!isRecord(value)) return null;
  let revision = decodeProjectRevision(value.revision);
  let lastApplied: UnknownRecord | null = null;
  if (revision === null && Array.isArray(value.steps)) {
    const applied = recordList(value.steps).filter((step) => nullableText(step.asset_id) !== null);
    lastApplied = applied.at(-1) ?? null;
    if (lastApplied !== null) {
      revision = decodeProjectRevision({
        ...lastApplied,
        root_id: value.root_id,
        design_id: value.design_id,
        capability: 'LOCALIZED_EDIT',
      });
    }
  }
  const qa = decodeImageQualityReport(
    pick(value, 'qa', 'quality')
      ?? (lastApplied === null ? undefined : pick(lastApplied, 'qa', 'qa_report')),
  )
    ?? (isRecord(value.consistency) && value.consistency.consistent === false
      ? defaultQualityReport('warn')
      : defaultQualityReport('pass'));
  const routing = decodeRouting(
    value.routing
      ?? (lastApplied === null ? undefined : pick(lastApplied, 'routing', 'model_routing')),
  ) ?? {
    attempt_count: 1,
    used_retry: false,
    used_fallback: false,
    cache_hit: false,
    run_id: nullableText(pick(value, 'image_run_id', 'run_id')),
  };
  let warningCandidate = decodeWarningCandidate(value.warning_candidate);
  if (warningCandidate === null && qa.verdict === 'warn' && routing.run_id !== null) {
    warningCandidate = {
      run_id: routing.run_id,
      candidate_id: null,
      preview_url: null,
      qa,
      operation: 'LOCAL_EDIT',
      requested_change: '',
      asset_capability: 'LOCALIZED_EDIT',
    };
  }
  return {
    revision: qa.verdict === 'warn' ? null : revision,
    spec_version: number(pick(value, 'spec_version', 'new_spec_version', 'design_version'))
      ?? (lastApplied === null
        ? null
        : number(pick(lastApplied, 'spec_version', 'new_spec_version', 'design_version')))
      ?? revision?.spec_version ?? null,
    spec_change: (Array.isArray(
      pick(value, 'spec_change', 'changes')
        ?? (lastApplied === null ? undefined : pick(lastApplied, 'spec_change', 'changes')),
    )
      ? (pick(value, 'spec_change', 'changes')
          ?? (lastApplied === null ? [] : pick(lastApplied, 'spec_change', 'changes'))) as unknown[]
      : [])
      .map(decodeSpecChange)
      .filter((change): change is SpecChange => change !== null),
    ignored_fields: stringList(
      value.ignored_fields ?? (lastApplied === null ? undefined : lastApplied.ignored_fields),
    ),
    qa,
    routing,
    image_run_id: nullableText(pick(value, 'image_run_id', 'run_id')) ?? routing.run_id,
    warning_candidate: warningCandidate,
  };
};

const decodeAttempt: Decoder<ImageAttemptSummary> = (value) => {
  if (!isRecord(value)) return null;
  const attempt = number(pick(value, 'attempt', 'attempt_number'));
  const verdict = knownVerdict(pick(value, 'verdict', 'qa_verdict'));
  if (attempt === null) return null;
  const route = text(value.route).toLowerCase();
  const role = value.engine_role === 'fallback' || value.fallback === true
    || route.includes('fallback') || route.includes('flux')
    ? 'fallback'
    : attempt === 1 ? 'primary' : 'primary_retry';
  const qaChecks = recordList(value.qa_checks);
  const failedChecks = stringList(value.failed_checks);
  const rawUsage = jsonValue(value.usage);
  return {
    attempt_id: nullableText(value.attempt_id),
    attempt,
    engine_role: role,
    provider: nullableText(value.provider),
    model: nullableText(value.model),
    latency_ms: number(value.latency_ms),
    cache_hit: boolean(pick(value, 'cache_hit', 'cached')),
    provider_request_id: nullableText(value.provider_request_id),
    verdict,
    failed_checks: failedChecks.length > 0
      ? failedChecks
      : qaChecks
        .filter((check) => check.passed === false)
        .map((check) => text(pick(check, 'code', 'key')))
        .filter(Boolean),
    correction: nullableText(pick(value, 'correction', 'corrective_instruction')),
    fallback_reason: nullableText(value.fallback_reason),
    output_hash: nullableText(value.output_hash),
    prompt_hash: nullableText(value.prompt_hash),
    cache_key: nullableText(value.cache_key),
    usage: isRecord(rawUsage) ? rawUsage : null,
    cost: number(value.cost),
    error_category: nullableText(value.error_category)
      ?? (isRecord(value.error) ? nullableText(value.error.category) : null),
    created_at: nullableText(value.created_at),
  };
};

export const decodeImageRunSummary: Decoder<ImageRunSummary> = (value) => {
  if (!isRecord(value)) return null;
  const runId = nullableText(pick(value, 'run_id', 'id'));
  const operation = knownOperation(value.operation);
  if (runId === null || operation === null) return null;
  const attempts = (Array.isArray(value.attempts) ? value.attempts : [])
    .map(decodeAttempt)
    .filter((attempt): attempt is ImageAttemptSummary => attempt !== null);
  const verdict = knownVerdict(value.verdict) ?? attempts.at(-1)?.verdict ?? null;
  const rawStatus = value.status;
  const acceptedAssetId = nullableText(value.accepted_asset_id);
  const accepted = boolean(value.accepted, rawStatus === 'accepted' || acceptedAssetId !== null);
  const reviewRequired = boolean(
    value.review_required,
    verdict === 'warn' || rawStatus === 'review_required',
  );
  const status = rawStatus === 'running' || rawStatus === 'review_required'
    || rawStatus === 'accepted' || rawStatus === 'failed'
    ? rawStatus
    : accepted ? 'accepted' : reviewRequired ? 'review_required' : verdict === 'fail' ? 'failed' : 'running';
  return {
    run_id: runId,
    project_id: nullableText(value.project_id),
    source_asset_id: nullableText(value.source_asset_id),
    accepted_asset_id: acceptedAssetId,
    operation,
    normalized_intent: normalizedIntent(value.normalized_intent),
    prompt_contract_version: text(pick(value, 'prompt_contract_version', 'prompt_version')),
    variant: number(value.variant) ?? 0,
    status,
    stored_status: value.stored_status === 'running'
      || value.stored_status === 'review_required'
      || value.stored_status === 'accepted'
      || value.stored_status === 'failed'
      ? value.stored_status
      : status,
    verdict,
    accepted,
    review_required: reviewRequired,
    source_hash: nullableText(value.source_hash),
    input_hash: nullableText(value.input_hash),
    mask_hash: nullableText(value.mask_hash),
    spec_visual_hash: nullableText(value.spec_visual_hash),
    source_spec_visual_hash: nullableText(value.source_spec_visual_hash),
    output_hash: nullableText(value.output_hash) ?? attempts.at(-1)?.output_hash ?? null,
    selected_attempt: number(value.selected_attempt),
    error_category: nullableText(value.error_category),
    review_decision: value.review_decision === 'accepted' || value.review_decision === 'rejected'
      ? value.review_decision
      : null,
    reviewed_by: nullableText(value.reviewed_by),
    reviewed_at: nullableText(value.reviewed_at),
    created_by: nullableText(value.created_by),
    attempts,
    created_at: nullableText(value.created_at),
    completed_at: nullableText(value.completed_at),
  };
};

const decodeArtifact: Decoder<FactoryPackArtifact> = (value) => {
  if (!isRecord(value)) return null;
  const name = nullableText(value.name);
  if (name === null) return null;
  const lowerName = name.toLowerCase();
  const inferredMediaType = lowerName.endsWith('.json')
    ? 'application/json'
    : lowerName.endsWith('.svg')
      ? 'image/svg+xml'
      : lowerName.endsWith('.dxf')
        ? 'application/dxf'
        : lowerName.endsWith('.png')
          ? 'image/png'
          : lowerName.endsWith('.jpg') || lowerName.endsWith('.jpeg')
            ? 'image/jpeg'
            : 'application/octet-stream';
  return {
    name,
    media_type: text(value.media_type, inferredMediaType),
    sha256: text(value.sha256),
    url: text(value.url),
    authoritative: boolean(value.authoritative, name !== 'discussion-drawing'),
  };
};

const decodeFactoryDimensionEstimate: Decoder<FactoryDimensionEstimate> = (value) => {
  if (!isRecord(value)) return null;
  const fieldPath = nullableText(value.field_path);
  if (fieldPath === null || value.status !== 'estimated_from_reference') return null;
  return {
    field_path: fieldPath,
    value: (value.value ?? null) as JsonValue,
    unit: text(value.unit, 'mm'),
    status: 'estimated_from_reference',
    method: text(value.method, 'reference_vision'),
    source: text(value.source, 'reference'),
    confidence: number(value.confidence),
    note: nullableText(value.note),
  };
};

const factoryFactStatus = (
  value: unknown,
): 'designer_confirmed' | 'estimated_from_reference' | 'pending_confirmation' | null => (
  value === 'designer_confirmed' || value === 'estimated_from_reference'
    || value === 'pending_confirmation' ? value : null
);

const decodeFactorySheetFactPlan: Decoder<FactorySheetFactPlan> = (value) => {
  if (!isRecord(value) || value.schema_version !== 'facetta.factory-sheet-plan.v1') return null;
  const dimensions = recordList(value.dimensions).flatMap((item) => {
    const status = factoryFactStatus(item.status);
    const fieldPath = nullableText(item.field_path);
    const dimensionValue = number(item.value);
    if (status === null || fieldPath === null || dimensionValue === null) return [];
    return [{
      field_path: fieldPath,
      section: text(item.section),
      value: dimensionValue,
      unit: text(item.unit, 'mm'),
      status,
      method: nullableText(item.method),
      source: nullableText(item.source),
      confidence: number(item.confidence),
      note: nullableText(item.note),
    }];
  });
  const stones = recordList(value.stones).flatMap((item) => {
    const status = factoryFactStatus(item.fact_status);
    const count = number(item.count);
    const caratEach = number(item.carat_each);
    const caratTotal = number(item.carat_total);
    if (status === null || count === null || caratEach === null || caratTotal === null) return [];
    return [{
      ref: text(item.ref), section: text(item.section), role: text(item.role),
      species: text(item.species), cut: text(item.cut),
      visible_color: nullableText(item.visible_color), count,
      carat_each: caratEach, carat_total: caratTotal, fact_status: status,
      dimension_paths: stringList(item.dimension_paths),
    }];
  });
  const materials = recordList(value.materials).flatMap((item) => {
    const status = factoryFactStatus(item.fact_status);
    if (status === null || item.section !== 'metal') return [];
    return [{
      section: 'metal' as const,
      material: text(item.material), karat: number(item.karat),
      color: nullableText(item.color), finish: nullableText(item.finish),
      fact_status: status,
    }];
  });
  const settings = recordList(value.settings).flatMap((item) => {
    const status = factoryFactStatus(item.fact_status);
    if (status === null || item.section !== 'setting') return [];
    return [{
      section: 'setting' as const,
      style: text(item.style), prong_count: number(item.prong_count),
      fact_status: status, dimension_paths: stringList(item.dimension_paths),
    }];
  });
  const recordedFacts = recordList(value.recorded_facts).flatMap((item) => {
    const status = factoryFactStatus(item.fact_status);
    const fieldPath = nullableText(item.field_path);
    const label = nullableText(item.label);
    const recordedValue = nullableText(item.value);
    if (
      status === null || fieldPath === null || label === null
      || recordedValue === null
    ) return [];
    return [{
      field_path: fieldPath,
      section: text(item.section),
      label,
      value: recordedValue,
      fact_status: status,
    }];
  });
  return {
    schema_version: 'facetta.factory-sheet-plan.v1',
    jewelry_type: text(value.jewelry_type), template: text(value.template),
    materials, stones, settings, recorded_facts: recordedFacts, dimensions,
    confirmed_fact_count: number(value.confirmed_fact_count) ?? 0,
    estimated_fact_count: number(value.estimated_fact_count) ?? 0,
    pending_confirmation_count: number(value.pending_confirmation_count) ?? 0,
    has_estimates: boolean(value.has_estimates),
    estimate_disclaimer: nullableText(value.estimate_disclaimer),
  };
};

export const decodeFactoryPackManifest: Decoder<FactoryPackManifest> = (value) => {
  if (!isRecord(value)) return null;
  const manifest = isRecord(value.manifest) ? value.manifest : value;
  const projectId = nullableText(pick(manifest, 'project_id', 'root_id'));
  const designId = nullableText(manifest.design_id);
  const designVersion = number(manifest.design_version);
  const pinnedAssetId = nullableText(pick(manifest, 'pinned_asset_id', 'asset_id'));
  const checklist = isRecord(manifest.checklist) ? manifest.checklist : manifest;
  const checklistId = nullableText(pick(manifest, 'checklist_id'))
    ?? nullableText(checklist.id);
  if (
    projectId === null || designId === null || designVersion === null
    || pinnedAssetId === null || checklistId === null
  ) return null;
  const dimensions = isRecord(manifest.dimensions) ? manifest.dimensions : {};
  const estimatedFields = Array.isArray(dimensions.estimated_fields)
    ? dimensions.estimated_fields
      .map(decodeFactoryDimensionEstimate)
      .filter((item): item is FactoryDimensionEstimate => item !== null)
    : [];
  const factPlan = decodeFactorySheetFactPlan(manifest.factory_sheet_fact_plan);
  if (factPlan === null) return null;
  return {
    project_id: projectId,
    design_id: designId,
    design_version: designVersion,
    pinned_asset_id: pinnedAssetId,
    approver: text(manifest.approver, text(checklist.approver)),
    approved_at: text(manifest.approved_at, text(checklist.approved_at)),
    checklist_id: checklistId,
    qa: decodeImageQualityReport(pick(manifest, 'qa', 'qa_summary')),
    dimensions: {
      has_estimates: boolean(dimensions.has_estimates, estimatedFields.length > 0),
      estimated_fields: estimatedFields,
      disclaimer: nullableText(dimensions.disclaimer),
    },
    factory_sheet_fact_plan: factPlan,
    artifacts: (Array.isArray(manifest.artifacts)
      ? manifest.artifacts
      : Array.isArray(manifest.files) ? manifest.files : [])
      .map(decodeArtifact)
      .filter((artifact): artifact is FactoryPackArtifact => artifact !== null),
    bundle_url: text(pick(value, 'bundle_url', 'download_url'), text(manifest.bundle_url)),
    manifest_sha256: nullableText(manifest.manifest_sha256),
  };
};

function errorCategory(status: number, code: string, message: string): ApiErrorCategory {
  const normalized = `${code} ${message}`.toLowerCase();
  if (status === 0) return 'network';
  if (status === 404) return 'not_found';
  if (normalized.includes('stale') || normalized.includes('expected_design_version')) {
    return 'stale_version';
  }
  if (normalized.includes('quality') || normalized.includes('qa_failed')) return 'quality';
  if (status === 422) return 'validation';
  if (status === 409) return 'conflict';
  if (status === 502 || status === 503 || normalized.includes('provider')) return 'provider';
  return 'unknown';
}

function apiError(status: number, value: unknown, fallback: string): ApiError {
  const record = isRecord(value) ? value : {};
  const nested = isRecord(record.error) ? record.error : record;
  const code = text(
    pick(nested, 'code', 'error_category'),
    status === 0 ? 'NETWORK_ERROR' : `HTTP_${status}`,
  );
  const detail = pick(nested, 'message', 'detail', 'error');
  const message = typeof detail === 'string'
    ? detail
    : Array.isArray(detail)
      ? detail.map((entry) => isRecord(entry) ? text(pick(entry, 'message', 'msg')) : text(entry)).filter(Boolean).join('\n')
      : fallback;
  const rawCategory = text(pick(nested, 'category', 'error_category')).toLowerCase();
  const categoryValue = rawCategory.includes('stale')
    ? 'stale_version'
    : rawCategory.includes('quality')
      ? 'quality'
      : rawCategory.includes('provider')
        ? 'provider'
        : rawCategory.includes('validation')
          ? 'validation'
          : rawCategory || null;
  const category = categoryValue === 'network' || categoryValue === 'validation'
    || categoryValue === 'stale_version' || categoryValue === 'quality'
    || categoryValue === 'provider' || categoryValue === 'conflict'
    || categoryValue === 'not_found' || categoryValue === 'decode'
    || categoryValue === 'unknown'
    ? categoryValue
    : errorCategory(status, code, message);
  const details = jsonValue(nested.details ?? nested);
  return {
    code,
    message,
    category,
    status,
    details,
    retryable: boolean(nested.retryable, status === 0 || status === 502 || status === 503),
  };
}

export function classifyCatalogApplyFailure(error: ApiError): CatalogApplyFailure {
  const details = isRecord(error.details) ? error.details : {};
  let catalogStatus: CatalogApplyFailureStatus = 'error';
  if (error.code === 'catalog_category_pending') {
    catalogStatus = 'category_pending';
  } else if (
    error.category === 'stale_version'
    || error.code === 'stale_asset_revision'
    || error.code === 'stale_design_version'
  ) {
    catalogStatus = 'stale';
  } else if (error.category === 'quality' || error.code === 'image_quality_failed') {
    catalogStatus = 'warning';
  }
  return {
    ...error,
    catalog_status: catalogStatus,
    component_path: knownComponentCatalogPath(details.component_path),
    option_id: nullableText(details.option_id),
    image_run_id: nullableText(details.image_run_id),
    applicable_jewelry_types: stringList(details.applicable_jewelry_types),
    current_asset_id: nullableText(details.current_asset_id),
    current_design_version: number(details.current_design_version),
  };
}

const encodeBody = (body: JsonObject): string => JSON.stringify(body);

function resolveUrl(url: string, baseUrl: string): string {
  return /^https?:\/\//i.test(url) || url.startsWith('data:')
    ? url
    : `${baseUrl}${url.startsWith('/') ? '' : '/'}${url}`;
}

function catalogApplyBody(request: CatalogApplyRequest): JsonObject {
  return {
    component_path: request.component_path,
    option_id: request.option_id,
    expected_design_version: request.expected_design_version,
    created_by: request.created_by,
    variant: request.variant ?? 0,
    ...(request.stone_species === undefined
      ? {}
      : { stone_species: request.stone_species }),
    ...(request.chain_geometry === undefined
      ? {}
      : { chain_geometry: request.chain_geometry as unknown as JsonObject }),
    ...(request.chain_production === undefined
      ? {}
      : { chain_production: request.chain_production as unknown as JsonObject }),
  };
}

function normalizedCatalogPreviewCandidate(
  candidate: CatalogPreviewCandidate,
  baseUrl: string,
): CatalogPreviewCandidate | null {
  const root = catalogCandidatePath(candidate.run_id, candidate.candidate_id);
  const base = new URL(baseUrl);
  const normalize = (raw: string, expectedPath: string): string | null => {
    try {
      const resolved = new URL(raw, `${baseUrl}/`);
      if (
        resolved.protocol !== 'http:' && resolved.protocol !== 'https:'
        || resolved.origin !== base.origin
        || resolved.username.length > 0 || resolved.password.length > 0
        || resolved.search.length > 0 || resolved.hash.length > 0
        || resolved.pathname !== expectedPath
      ) return null;
      return resolved.toString();
    } catch {
      return null;
    }
  };
  const previewUrl = normalize(candidate.preview_url, `${root}/image`);
  const acceptUrl = normalize(candidate.accept_url, `${root}/accept`);
  const discardUrl = normalize(candidate.discard_url, root);
  return previewUrl === null || acceptUrl === null || discardUrl === null
    ? null
    : {
        ...candidate,
        preview_url: previewUrl,
        accept_url: acceptUrl,
        discard_url: discardUrl,
      };
}

function projectWithUrls(project: ProjectDetail, baseUrl: string): ProjectDetail {
  const addUrl = (asset: AssetSummary): AssetSummary => {
    const rawUrl = asset.image_url;
    const imageUrl = rawUrl === null
      ? `${baseUrl}/assets/${encodeURIComponent(asset.asset_id)}/image`
      : resolveUrl(rawUrl, baseUrl);
    return { ...asset, image_url: imageUrl };
  };
  const revisions = project.revisions.map((revision) => ({
    ...revision,
    asset: addUrl(revision.asset),
  }));
  const assets = project.assets.map(addUrl);
  const derivedAssets = project.derived_assets.map(addUrl);
  const active = project.active_revision === null ? null : addUrl(project.active_revision);
  const pinned = project.pinned_revision === null ? null : addUrl(project.pinned_revision);
  return {
    ...project,
    revisions,
    assets,
    derived_assets: derivedAssets,
    active_revision: active,
    pinned_revision: pinned,
  };
}

export function createTrustedApiClient(options: TrustedApiClientOptions) {
  const baseUrl = options.baseUrl.replace(/\/$/, '');
  const fetcher = options.fetcher ?? fetch;

  async function call<T>(
    path: string,
    decoder: Decoder<T>,
    init?: RequestInit,
  ): Promise<ApiResult<T>> {
    let token: string | null = null;
    try {
      token = await options.getAccessToken?.() ?? null;
      const response = await fetcher(`${baseUrl}${path}`, {
        ...init,
        headers: {
          Accept: 'application/json',
          ...(init?.body === undefined ? {} : { 'Content-Type': 'application/json' }),
          ...(token === null ? {} : { Authorization: `Bearer ${token}` }),
          ...init?.headers,
        },
      });
      const responseText = await response.text();
      let parsed: unknown = responseText;
      if (responseText.length > 0) {
        try {
          parsed = JSON.parse(responseText) as unknown;
        } catch {
          parsed = responseText;
        }
      }
      if (!response.ok) {
        return {
          data: null,
          error: apiError(response.status, parsed, `Request failed (${response.status}).`),
          status: response.status,
        };
      }

      const envelope = isRecord(parsed) && 'data' in parsed && 'error' in parsed ? parsed : null;
      if (envelope !== null && envelope.error !== null && envelope.error !== undefined) {
        return {
          data: null,
          error: apiError(response.status, envelope.error, 'The request could not be completed.'),
          status: response.status,
        };
      }
      const payload = envelope === null ? parsed : envelope.data;
      const decoded = decoder(payload);
      if (decoded === null) {
        return {
          data: null,
          error: {
            code: 'INVALID_RESPONSE',
            message: 'The server returned an incomplete trusted-workflow response.',
            category: 'decode',
            status: response.status,
            details: jsonValue(payload),
            retryable: false,
          },
          status: response.status,
        };
      }
      return { data: decoded, error: null, status: response.status };
    } catch (cause: unknown) {
      const message = cause instanceof Error ? cause.message : String(cause);
      return {
        data: null,
        error: {
          code: 'NETWORK_ERROR',
          message,
          category: 'network',
          status: 0,
          retryable: true,
        },
        status: 0,
      };
    }
  }

  const jsonCall = <T>(path: string, method: 'POST' | 'PATCH', body: JsonObject, decoder: Decoder<T>) =>
    call(path, decoder, { method, body: encodeBody(body) });

  const svgCall = async (
    path: string,
    body: JsonObject,
  ): Promise<ApiResult<DraftFactorySheetPreview>> => {
    let token: string | null = null;
    try {
      token = await options.getAccessToken?.() ?? null;
      const response = await fetcher(`${baseUrl}${path}`, {
        method: 'POST',
        headers: {
          Accept: 'image/svg+xml',
          'Content-Type': 'application/json',
          ...(token === null ? {} : { Authorization: `Bearer ${token}` }),
        },
        body: encodeBody(body),
      });
      const responseText = await response.text();
      if (!response.ok) {
        let parsed: unknown = responseText;
        try {
          parsed = JSON.parse(responseText) as unknown;
        } catch {
          // Preserve a plain-text server failure for structured client mapping.
        }
        return {
          data: null,
          error: apiError(
            response.status,
            parsed,
            `Factory-sheet preview failed (${response.status}).`,
          ),
          status: response.status,
        };
      }
      if (!responseText.trimStart().startsWith('<svg')) {
        return {
          data: null,
          error: {
            code: 'INVALID_RESPONSE',
            message: 'The server returned an invalid factory-sheet preview.',
            category: 'decode',
            status: response.status,
            retryable: false,
          },
          status: response.status,
        };
      }
      const header = response.headers?.get?.('X-Facetta-Sheet-Authority');
      const authority = header === 'preliminary_not_for_production'
        ? 'preliminary_not_for_production' as const
        : 'spec_derived_preview' as const;
      return {
        data: { svg: responseText, authority },
        error: null,
        status: response.status,
      };
    } catch (cause: unknown) {
      const message = cause instanceof Error ? cause.message : String(cause);
      return {
        data: null,
        error: {
          code: 'NETWORK_ERROR',
          message,
          category: 'network',
          status: 0,
          retryable: true,
        },
        status: 0,
      };
    }
  };

  const projectCall = async (path: string, init?: RequestInit): Promise<ApiResult<ProjectDetail>> => {
    const result = await call(path, decodeProjectDetail, init);
    return result.error === null
      ? { ...result, data: projectWithUrls(result.data, baseUrl) }
      : result;
  };

  const projectCreationCall = async (
    path: string,
    init: RequestInit,
  ): Promise<ApiResult<ProjectCreationResult>> => {
    const result = await call(path, decodeProjectCreationResult, init);
    if (result.error !== null) return result;
    if ('warning_candidate' in result.data) {
      const preview = result.data.warning_candidate.preview_url;
      const warning: ProjectCreationWarning = {
        ...result.data,
        warning_candidate: {
          ...result.data.warning_candidate,
          preview_url: preview === null
            || /^https?:\/\//i.test(preview) || preview.startsWith('data:')
            ? preview
            : `${baseUrl}${preview.startsWith('/') ? '' : '/'}${preview}`,
        },
      };
      return { ...result, data: warning };
    }
    return { ...result, data: projectWithUrls(result.data, baseUrl) };
  };

  return {
    previewDraftFactorySheet(spec: JsonObject) {
      return svgCall('/specs/sheet.svg', spec);
    },

    baseUrl,

    createProjectFromBrief(request: CreateProjectFromBriefRequest) {
      return projectCreationCall('/projects/from-brief', {
        method: 'POST',
        body: encodeBody({
          brief: request.brief,
          owner: request.owner,
          ...(request.title === undefined ? {} : { title: request.title }),
          ...(request.collection === undefined ? {} : { collection: request.collection }),
          ...(request.tags === undefined ? {} : { tags: request.tags }),
          ...(request.variant === undefined ? {} : { variant: request.variant }),
        }),
      });
    },

    acceptBriefWarningCandidate(candidateId: string, createdBy: string) {
      return projectCreationCall(
        `/projects/from-brief/candidates/${encodeURIComponent(candidateId)}/accept`,
        {
          method: 'POST',
          body: encodeBody({ created_by: createdBy }),
        },
      );
    },

    createProjectFromImage(request: CreateProjectFromImageRequest) {
      return projectCall('/projects/from-image', {
        method: 'POST',
        body: encodeBody({
          image_base64: request.image_base64,
          media_type: request.media_type ?? 'image/png',
          spec: request.confirmed_spec,
          owner: request.owner,
          title: request.title,
          ...(request.collection === undefined ? {} : { collection: request.collection }),
          ...(request.tags === undefined ? {} : { tags: request.tags }),
        }),
      });
    },

    createProjectFromDrawing(request: CreateProjectFromDrawingRequest) {
      return projectCall('/projects/from-drawing', {
        method: 'POST',
        body: encodeBody({
          image_base64: request.image_base64,
          media_type: request.media_type ?? 'image/png',
          instruction: request.instruction
            ?? 'Create a polished fine-jewelry beauty render faithful to every visible design element in this source.',
          variation_count: request.variation_count ?? 1,
          starting_variant: request.starting_variant ?? 0,
          owner: request.owner,
          title: request.title,
          ...(request.source_region_description === undefined
            ? {}
            : { source_region_description: request.source_region_description }),
          ...(request.source_region === undefined
            ? {}
            : {
                source_region: {
                  x: request.source_region.x,
                  y: request.source_region.y,
                  width: request.source_region.width,
                  height: request.source_region.height,
                },
              }),
          ...(request.collection === undefined ? {} : { collection: request.collection }),
          ...(request.tags === undefined ? {} : { tags: request.tags }),
        }),
      });
    },

    createProjectFromPrompt(request: CreateProjectFromPromptRequest) {
      return projectCall('/projects/from-prompt', {
        method: 'POST',
        body: encodeBody({
          prompt: request.prompt,
          variation_count: request.variation_count ?? 1,
          starting_variant: request.starting_variant ?? 0,
          owner: request.owner,
          title: request.title,
          ...(request.collection === undefined ? {} : { collection: request.collection }),
          ...(request.tags === undefined ? {} : { tags: request.tags }),
        }),
      });
    },

    selectCreativeCandidate(projectId: string, candidateId: string, createdBy: string) {
      return projectCall(
        `/projects/${encodeURIComponent(projectId)}/creative-candidates/${encodeURIComponent(candidateId)}/select`,
        { method: 'POST', body: encodeBody({ created_by: createdBy }) },
      );
    },

    promoteCreativeCandidate(
      projectId: string,
      candidateId: string,
      request: PromoteCreativeCandidateRequest,
    ) {
      return projectCall(
        `/projects/${encodeURIComponent(projectId)}/creative-candidates/${encodeURIComponent(candidateId)}/promote`,
        {
          method: 'POST',
          body: encodeBody({
            spec: request.confirmed_spec,
            created_by: request.created_by,
          }),
        },
      );
    },

    extractCreativeCandidateDraft(
      projectId: string,
      candidateId: string,
      request: ExtractCreativeCandidateDraftRequest,
    ) {
      return jsonCall(
        `/projects/${encodeURIComponent(projectId)}/creative-candidates/${encodeURIComponent(candidateId)}/draft`,
        'POST',
        {
          notes: request.notes ?? '',
          created_by: request.created_by,
          run_independent_audit: request.run_independent_audit ?? true,
        },
        decodePhotoDraftResult,
      );
    },

    extractImageDraft(request: ExtractImageDraftRequest) {
      return jsonCall('/specs/from-photo', 'POST', {
        image_base64: request.image_base64,
        media_type: request.media_type,
        notes: request.notes ?? '',
        created_by: request.created_by,
        run_independent_audit: request.run_independent_audit ?? true,
      }, decodePhotoDraftResult);
    },

    extractPlateDraft(request: ExtractPlateDraftRequest) {
      return jsonCall('/specs/from-plate', 'POST', {
        image_base64: request.image_base64,
        scale_anchor: request.scale_anchor ?? null,
        notes: request.notes ?? '',
        created_by: request.created_by,
        run_independent_audit: request.run_independent_audit ?? true,
      }, decodePlateDraftResult);
    },

    resolveSourceCoverage(request: ResolveSourceCoverageRequest) {
      return jsonCall('/specs/source-coverage/resolve', 'POST', {
        spec: request.spec,
        source_image_base64: request.source_image_base64 ?? null,
        resolutions: request.resolutions.map((resolution) => ({
          component_id: resolution.component_id,
          ...(resolution.canonical_spec_paths === undefined
            ? {} : { canonical_spec_paths: resolution.canonical_spec_paths }),
          ...(resolution.unresolved_reason === undefined
            ? {} : { unresolved_reason: resolution.unresolved_reason }),
        })),
        created_by: request.created_by,
        run_independent_audit: request.run_independent_audit,
      }, decodeSourceCoverageResolutionResult);
    },

    confirmSourceCoverage(request: ConfirmSourceCoverageRequest) {
      return jsonCall('/specs/source-coverage/confirm', 'POST', {
        spec: request.spec,
        source_image_base64: request.source_image_base64,
        confirmations: request.confirmations.map((confirmation) => ({
          component_id: confirmation.component_id,
          basis: confirmation.basis,
          confirmed_description: confirmation.confirmed_description,
        })),
        created_by: request.created_by,
      }, decodeConfirmSourceCoverageResult);
    },

    resolveCreativeCandidateCoverage(
      projectId: string,
      candidateId: string,
      request: Omit<ResolveSourceCoverageRequest, 'source_image_base64'>,
    ) {
      return jsonCall(
        `/projects/${encodeURIComponent(projectId)}/creative-candidates/${encodeURIComponent(candidateId)}/source-coverage/resolve`,
        'POST',
        {
          spec: request.spec,
          resolutions: request.resolutions.map((resolution) => ({
            component_id: resolution.component_id,
            ...(resolution.canonical_spec_paths === undefined
              ? {} : { canonical_spec_paths: resolution.canonical_spec_paths }),
            ...(resolution.unresolved_reason === undefined
              ? {} : { unresolved_reason: resolution.unresolved_reason }),
          })),
          created_by: request.created_by,
          run_independent_audit: request.run_independent_audit,
        },
        decodeSourceCoverageResolutionResult,
      );
    },

    confirmCreativeCandidateCoverage(
      projectId: string,
      candidateId: string,
      request: Omit<ConfirmSourceCoverageRequest, 'source_image_base64'>,
    ) {
      return jsonCall(
        `/projects/${encodeURIComponent(projectId)}/creative-candidates/${encodeURIComponent(candidateId)}/source-coverage/confirm`,
        'POST',
        {
          spec: request.spec,
          confirmations: request.confirmations.map((confirmation) => ({
            component_id: confirmation.component_id,
            basis: confirmation.basis,
            confirmed_description: confirmation.confirmed_description,
          })),
          created_by: request.created_by,
        },
        decodeSourceCoverageResolutionResult,
      );
    },

    confirmCreativeCandidateProfile(
      projectId: string,
      candidateId: string,
      request: ConfirmCreativeCandidateProfileRequest,
    ) {
      return jsonCall(
        `/projects/${encodeURIComponent(projectId)}/creative-candidates/${encodeURIComponent(candidateId)}/dimensioned-profile/confirm`,
        'POST',
        {
          spec: request.spec,
          element_id: request.element_id,
          profile: {
            view: request.profile.view,
            paths: request.profile.paths.map((path) => ({
              path_id: path.path_id,
              purpose: path.purpose,
              closed: path.closed,
              points: path.points.map((point) => ({
                x_mm: point.x_mm,
                y_mm: point.y_mm,
              })),
              nominal_width_mm: path.nominal_width_mm,
            })),
            profile_thickness_mm: request.profile.profile_thickness_mm,
            dimension_status: request.profile.dimension_status,
            manufacturing_notes: request.profile.manufacturing_notes,
          },
          created_by: request.created_by,
        },
        decodeConfirmCreativeCandidateProfileResult,
      );
    },

    async getComponentCatalog(
      componentPath: ComponentCatalogPath,
      options?: { stoneSpecies?: string },
    ) {
      const stoneSpecies = options?.stoneSpecies?.trim();
      const query = componentPath === 'stone.color' && stoneSpecies
        ? `?stone_species=${encodeURIComponent(stoneSpecies)}`
        : '';
      const result = await call(
        `/vocabulary/components/${encodeURIComponent(componentPath)}${query}`,
        (value) => {
          const catalog = decodeComponentCatalog(value);
          return catalog?.component_path === componentPath ? catalog : null;
        },
      );
      if (result.error !== null || result.status === 200) return result;
      return {
        data: null,
        error: {
          code: 'INVALID_RESPONSE',
          message: 'The catalog endpoint returned an unexpected success status.',
          category: 'decode',
          status: result.status,
          retryable: false,
        },
        status: result.status,
      };
    },

    getStoneVocabulary() {
      return call('/vocabulary/stones', decodeStoneVocabulary);
    },

    getStoneVocabularyOptions(species: string) {
      return call(
        `/vocabulary/stones/${encodeURIComponent(species)}/options`,
        decodeStoneVocabularyOptions,
      );
    },

    selectDraftCatalogOption(request: DraftCatalogSelectionRequest) {
      return jsonCall(
        '/specs/catalog/select',
        'POST',
        {
          spec: request.spec,
          component_path: request.component_path,
          option_id: request.option_id,
        },
        decodeDraftCatalogSelectionResult,
      );
    },

    selectDraftStone(request: DraftStoneSelectionRequest) {
      return jsonCall(
        '/specs/stone/select',
        'POST',
        {
          spec: request.spec,
          species: request.species,
          trade_color: request.trade_color,
        },
        decodeDraftCatalogSelectionResult,
      );
    },

    async applyCatalogSelection(
      activeAssetId: string,
      request: CatalogApplyRequest,
    ): Promise<CatalogApplyCallResult> {
      const result = await jsonCall(
        `/assets/${encodeURIComponent(activeAssetId)}/catalog/apply`,
        'POST',
        catalogApplyBody(request),
        decodeCatalogApplyResult,
      );
      if (result.error !== null) {
        return {
          data: null,
          error: classifyCatalogApplyFailure(result.error),
          status: result.status,
        };
      }
      const expectedStatus = result.data.status === 'accepted' ? 201 : 202;
      if (result.status !== expectedStatus) {
        return {
          data: null,
          error: classifyCatalogApplyFailure({
            code: 'INVALID_RESPONSE',
            message: 'The catalog revision returned an inconsistent success status.',
            category: 'decode',
            status: result.status,
            retryable: false,
          }),
          status: result.status,
        };
      }
      const project = projectWithUrls(result.data.project, baseUrl);
      if (result.data.status === 'accepted') {
        return {
          ...result,
          data: { ...result.data, project },
        };
      }
      const preview = result.data.warning_candidate.preview_url;
      return {
        ...result,
        data: {
          ...result.data,
          project,
          warning_candidate: {
            ...result.data.warning_candidate,
            preview_url: /^https?:\/\//i.test(preview) || preview.startsWith('data:')
              ? preview
              : `${baseUrl}${preview.startsWith('/') ? '' : '/'}${preview}`,
          },
        },
      };
    },

    async previewCatalogSelection(
      activeAssetId: string,
      request: CatalogApplyRequest,
    ): Promise<ApiResult<CatalogPreviewResult>> {
      const result = await jsonCall(
        `/assets/${encodeURIComponent(activeAssetId)}/catalog/preview`,
        'POST',
        catalogApplyBody(request),
        decodeCatalogPreviewResult,
      );
      if (result.error !== null) return result;
      const expectedStatus = result.data.status === 'preview_ready' ? 201 : 202;
      const candidate = normalizedCatalogPreviewCandidate(result.data.candidate, baseUrl);
      if (
        result.status !== expectedStatus || candidate === null
        || result.data.source_asset_id !== activeAssetId
        || result.data.component_path !== request.component_path
        || result.data.option_id !== request.option_id
        || result.data.design_version !== request.expected_design_version
      ) {
        return {
          data: null,
          error: {
            code: 'INVALID_RESPONSE',
            message: 'The catalog preview returned inconsistent lineage or candidate URLs.',
            category: 'decode',
            status: result.status,
            retryable: false,
          },
          status: result.status,
        };
      }
      return {
        ...result,
        data: {
          ...result.data,
          project: projectWithUrls(result.data.project, baseUrl),
          candidate,
        },
      };
    },

    async acceptCatalogPreview(
      candidate: CatalogPreviewCandidate,
      request: CatalogPreviewAcceptRequest,
    ): Promise<ApiResult<CatalogPreviewAcceptResult>> {
      const normalized = normalizedCatalogPreviewCandidate(candidate, baseUrl);
      if (normalized === null) {
        return {
          data: null,
          error: {
            code: 'INVALID_CANDIDATE_URL',
            message: 'The catalog preview candidate does not belong to this API.',
            category: 'validation',
            status: 0,
            retryable: false,
          },
          status: 0,
        };
      }
      const path = catalogCandidatePath(candidate.run_id, candidate.candidate_id, '/accept');
      const result = await jsonCall(path, 'POST', {
        expected_design_version: request.expected_design_version,
        created_by: request.created_by,
      }, decodeCatalogPreviewAcceptResult);
      if (result.error !== null) return result;
      if (
        result.status !== 201 || result.data.image_run_id !== candidate.run_id
        || result.data.design_version !== request.expected_design_version + 1
      ) {
        return {
          data: null,
          error: {
            code: 'INVALID_RESPONSE',
            message: 'The accepted catalog preview returned inconsistent revision lineage.',
            category: 'decode',
            status: result.status,
            retryable: false,
          },
          status: result.status,
        };
      }
      return {
        ...result,
        data: {
          ...result.data,
          project: projectWithUrls(result.data.project, baseUrl),
        },
      };
    },

    async discardCatalogPreview(
      candidate: CatalogPreviewCandidate,
    ): Promise<ApiResult<CatalogPreviewDiscardResult>> {
      const normalized = normalizedCatalogPreviewCandidate(candidate, baseUrl);
      if (normalized === null) {
        return {
          data: null,
          error: {
            code: 'INVALID_CANDIDATE_URL',
            message: 'The catalog preview candidate does not belong to this API.',
            category: 'validation',
            status: 0,
            retryable: false,
          },
          status: 0,
        };
      }
      let token: string | null = null;
      try {
        token = await options.getAccessToken?.() ?? null;
        const path = catalogCandidatePath(candidate.run_id, candidate.candidate_id);
        const response = await fetcher(`${baseUrl}${path}`, {
          method: 'DELETE',
          headers: {
            Accept: 'application/json',
            ...(token === null ? {} : { Authorization: `Bearer ${token}` }),
          },
        });
        if (response.status === 204) {
          return { data: { status: 'discarded' }, error: null, status: 204 };
        }
        const responseText = await response.text();
        let parsed: unknown = responseText;
        try {
          parsed = responseText.length === 0 ? {} : JSON.parse(responseText) as unknown;
        } catch {
          // Preserve plain-text response for the shared structured error mapper.
        }
        return {
          data: null,
          error: apiError(response.status, parsed, `Request failed (${response.status}).`),
          status: response.status,
        };
      } catch (cause: unknown) {
        return {
          data: null,
          error: {
            code: 'NETWORK_ERROR',
            message: cause instanceof Error ? cause.message : String(cause),
            category: 'network',
            status: 0,
            retryable: true,
          },
          status: 0,
        };
      }
    },

    getProject(projectId: string) {
      return projectCall(`/projects/${encodeURIComponent(projectId)}`);
    },

    async saveAsVariation(
      projectRootId: string,
      request: SaveAsVariationRequest,
    ): Promise<ApiResult<SaveAsVariationResult>> {
      const result = await call(
        `/studio/projects/${encodeURIComponent(projectRootId)}/variations`,
        decodeSaveAsVariationResult,
        {
          method: 'POST',
          body: encodeBody({
            created_by: request.created_by,
            expected_active_asset_id: request.expected_active_asset_id,
            expected_design_version: request.expected_design_version ?? null,
            label: request.label,
          }),
        },
      );
      if (result.error !== null) return result;
      return {
        ...result,
        data: {
          ...result.data,
          project: projectWithUrls(result.data.project, baseUrl),
        },
      };
    },

    getDesignFamily(familyId: string): Promise<ApiResult<DesignFamilyDetail>> {
      return call(
        `/studio/families/${encodeURIComponent(familyId)}`,
        decodeDesignFamilyDetail,
      );
    },

    listDesignFamilies(owner?: string): Promise<ApiResult<DesignFamilyList>> {
      const query = owner?.trim()
        ? `?owner=${encodeURIComponent(owner.trim())}`
        : '';
      return call('/studio/families' + query, decodeDesignFamilyList);
    },

    async getStudioProjectHistory(
      projectRootId: string,
    ): Promise<ApiResult<StudioProjectHistory>> {
      const result = await call(
        `/studio/projects/${encodeURIComponent(projectRootId)}/history`,
        decodeStudioProjectHistory,
      );
      if (result.error !== null) return result;
      return {
        ...result,
        data: {
          ...result.data,
          revisions: result.data.revisions.map((revision) => ({
            ...revision,
            image_url: resolveUrl(revision.image_url, baseUrl),
          })),
        },
      };
    },

    async restoreStudioRevision(
      projectRootId: string,
      assetId: string,
      request: RestoreStudioRevisionRequest,
    ): Promise<ApiResult<RestoreStudioRevisionResult>> {
      const result = await call(
        `/studio/projects/${encodeURIComponent(projectRootId)}/revisions/${encodeURIComponent(assetId)}/restore`,
        decodeRestoreStudioRevisionResult,
        {
          method: 'POST',
          body: encodeBody({
            created_by: request.created_by,
            expected_active_asset_id: request.expected_active_asset_id,
            expected_design_version: request.expected_design_version ?? null,
          }),
        },
      );
      if (result.error !== null) return result;
      return {
        ...result,
        data: {
          ...result.data,
          project: projectWithUrls(result.data.project, baseUrl),
        },
      };
    },

    async createBeautyRender(projectId: string, request: BeautyRenderRequest) {
      const result = await jsonCall(
        `/projects/${encodeURIComponent(projectId)}/render`,
        'POST',
        {
          created_by: request.created_by,
          expected_asset_id: request.expected_asset_id,
          source_asset_id: request.source_asset_id ?? request.expected_asset_id,
          expected_design_version: request.expected_design_version,
          instruction: request.instruction
            ?? 'Create a beauty render faithful to the current designer-confirmed specification and preserve the imported design identity.',
          variant: request.variant ?? 0,
        },
        decodeBeautyRenderResult,
      );
      if (result.error !== null) return result;
      if (result.data.status === 'review_required') {
        const preview = result.data.warning_candidate.preview_url;
        return {
          ...result,
          data: {
            ...result.data,
            warning_candidate: {
              ...result.data.warning_candidate,
              preview_url: preview === null
                || /^https?:\/\//i.test(preview) || preview.startsWith('data:')
                ? preview
                : `${baseUrl}${preview.startsWith('/') ? '' : '/'}${preview}`,
            },
          },
        };
      }
      return {
        ...result,
        data: {
          ...result.data,
          project: projectWithUrls(result.data.project, baseUrl),
        },
      };
    },

    async createProductPhoto(projectId: string, request: ProductPhotoRequest) {
      const result = await jsonCall(
        `/projects/${encodeURIComponent(projectId)}/product-photo`,
        'POST',
        {
          created_by: request.created_by,
          expected_asset_id: request.expected_asset_id,
          expected_design_version: request.expected_design_version,
          preset: request.preset,
          framing: request.framing ?? 'portrait',
          custom_instruction: request.custom_instruction ?? '',
          variant: request.variant ?? 0,
        },
        decodeProductPhotoResult,
      );
      if (result.error !== null) return result;
      if (result.data.status === 'accepted') {
        return {
          ...result,
          data: {
            ...result.data,
            project: projectWithUrls(result.data.project, baseUrl),
          },
        };
      }
      const preview = result.data.warning_candidate.preview_url;
      return {
        ...result,
        data: {
          ...result.data,
          warning_candidate: {
            ...result.data.warning_candidate,
            preview_url: preview === null
              || /^https?:\/\//i.test(preview) || preview.startsWith('data:')
              ? preview
              : `${baseUrl}${preview.startsWith('/') ? '' : '/'}${preview}`,
          },
        },
      };
    },

    async createMarketingPack(projectId: string, request: MarketingPackRequest) {
      const result = await jsonCall(
        `/projects/${encodeURIComponent(projectId)}/marketing-pack`,
        'POST',
        {
          created_by: request.created_by,
          expected_asset_id: request.expected_asset_id,
          expected_design_version: request.expected_design_version,
          presets: request.presets,
          framing: request.framing ?? 'portrait',
          custom_instruction: request.custom_instruction ?? '',
          starting_variant: request.starting_variant ?? 0,
        },
        decodeMarketingPackResult,
      );
      if (result.error !== null) return result;
      return {
        ...result,
        data: {
          ...result.data,
          candidates: result.data.candidates.map((candidate) => ({
            ...candidate,
            preview_url: /^https?:\/\//i.test(candidate.preview_url)
              || candidate.preview_url.startsWith('data:')
              ? candidate.preview_url
              : `${baseUrl}${candidate.preview_url.startsWith('/') ? '' : '/'}${candidate.preview_url}`,
          })),
        },
      };
    },

    async createLineArt(projectId: string, request: CreateLineArtRequest) {
      const result = await jsonCall(
        `/projects/${encodeURIComponent(projectId)}/line-art`,
        'POST',
        {
          created_by: request.created_by,
          expected_asset_id: request.expected_asset_id,
          expected_design_version: request.expected_design_version,
          view: request.view,
          ...(request.source_region_description === undefined
            ? {}
            : { source_region_description: request.source_region_description }),
          ...(request.source_region === undefined
            ? {}
            : {
                source_region: {
                  x: request.source_region.x,
                  y: request.source_region.y,
                  width: request.source_region.width,
                  height: request.source_region.height,
                },
              }),
          variant: request.variant ?? 0,
        },
        decodeDrawingConfirmationResult,
      );
      if (result.error !== null || result.data.candidate.preview_url === null) return result;
      const preview = result.data.candidate.preview_url;
      return {
        ...result,
        data: {
          ...result.data,
          candidate: {
            ...result.data.candidate,
            preview_url: /^https?:\/\//i.test(preview) || preview.startsWith('data:')
              ? preview
              : `${baseUrl}${preview.startsWith('/') ? '' : '/'}${preview}`,
          },
        },
      };
    },

    async colorizeLineArt(
      projectId: string,
      lineArtAssetId: string,
      request: ColorizeLineArtRequest,
    ) {
      const result = await jsonCall(
        `/projects/${encodeURIComponent(projectId)}/line-art/`
          + `${encodeURIComponent(lineArtAssetId)}/colorize`,
        'POST',
        {
          created_by: request.created_by,
          expected_asset_id: request.expected_asset_id,
          expected_design_version: request.expected_design_version,
          variant: request.variant ?? 0,
        },
        decodeColorizeLineArtResult,
      );
      if (result.error !== null) return result;
      if (result.data.status === 'accepted') {
        return {
          ...result,
          data: { ...result.data, project: projectWithUrls(result.data.project, baseUrl) },
        };
      }
      const preview = result.data.candidate.preview_url;
      if (preview === null) return result;
      return {
        ...result,
        data: {
          ...result.data,
          candidate: {
            ...result.data.candidate,
            preview_url: /^https?:\/\//i.test(preview) || preview.startsWith('data:')
              ? preview
              : `${baseUrl}${preview.startsWith('/') ? '' : '/'}${preview}`,
          },
        },
      };
    },

    listProjectComments(designId: string) {
      return call(
        `/designs/${encodeURIComponent(designId)}/messages`,
        decodeProjectComments,
      );
    },

    postProjectComment(
      designId: string,
      request: { author: string; body: string; version: number | null },
    ) {
      return jsonCall(
        `/designs/${encodeURIComponent(designId)}/messages`,
        'POST',
        {
          author: request.author,
          body: request.body,
          version: request.version,
        },
        decodeProjectComment,
      );
    },

    readMarkup(assetId: string, request: MarkupReadRequest) {
      return jsonCall(`/assets/${encodeURIComponent(assetId)}/markup/read`, 'POST', {
        ...(request.marked_image_base64 !== undefined
          ? { marked_image_base64: request.marked_image_base64 }
          : {
              // AnnotationCanvasSnapshot is a closed, JSON-only contract. The
              // cast bridges its precise named fields to the API client's
              // recursive JsonObject boundary without weakening either type.
              markup_snapshot: request.markup_snapshot as unknown as JsonObject,
            }),
        created_by: request.created_by,
        ...(request.assistant_name === undefined ? {} : { assistant_name: request.assistant_name }),
      }, decodeMarkupReadResponse);
    },

    async applyMarkup(assetId: string, request: MarkupApplyRequest) {
      const annotation = request.annotation;
      const updateSpec = annotation.impact === 'specification';
      const result = await jsonCall(`/assets/${encodeURIComponent(assetId)}/markup/apply`, 'POST', {
        annotations: [{
          region_description: annotation.region_description,
          change_instruction: annotation.change_instruction,
          target_section: annotation.target_section,
          target_ref: annotation.target_ref,
          index: annotation.index,
          target_element_id: annotation.target_element_id,
          form_view: annotation.form_view,
          mask_base64: annotation.mask_base64,
        }],
        markup_asset_id: request.markup_asset_id,
        kind: 'render',
        update_spec: updateSpec,
        expected_design_version: request.expected_design_version,
        created_by: request.created_by,
        variant: request.variant ?? 0,
      }, decodeMarkupApplyResponse);
      if (result.error !== null) {
        return result;
      }
      const warning = result.data.warning_candidate;
      if (warning === null || warning.preview_url === null) return result;
      const preview = warning.preview_url;
      return {
        ...result,
        data: {
          ...result.data,
          warning_candidate: {
            ...warning,
            preview_url: /^https?:\/\//i.test(preview) || preview.startsWith('data:')
              ? preview
              : `${baseUrl}${preview.startsWith('/') ? '' : '/'}${preview}`,
          },
        },
      };
    },

    getImageRun(runId: string) {
      return call(`/image-runs/${encodeURIComponent(runId)}`, decodeImageRunSummary);
    },

    recordImageRunFeedback(
      runId: string,
      action: 'accepted' | 'regenerated' | 'rejected',
      createdBy: string,
      note?: string,
    ) {
      return jsonCall(
        `/image-runs/${encodeURIComponent(runId)}/feedback`,
        'POST',
        {
          action,
          created_by: createdBy,
          ...(note === undefined ? {} : { note }),
        },
        decodeJsonObject,
      );
    },

    acceptWarningCandidate(
      runId: string,
      candidateId: string,
      expectedDesignVersion: number,
      createdBy: string,
    ) {
      return projectCall(
        `/image-runs/${encodeURIComponent(runId)}/candidates/${encodeURIComponent(candidateId)}/accept`,
        {
          method: 'POST',
          body: encodeBody({
            expected_design_version: expectedDesignVersion,
            created_by: createdBy,
          }),
        },
      );
    },

    createChecklist(assetId: string, request: ChecklistCreateRequest) {
      return jsonCall(`/assets/${encodeURIComponent(assetId)}/checklist`, 'POST', {
        created_by: request.created_by,
        mode: request.mode ?? 'auto_pin',
      }, decodeApprovalSummary);
    },

    getChecklist(assetId: string) {
      return call(`/assets/${encodeURIComponent(assetId)}/checklist`, decodeApprovalSummary);
    },

    respondChecklist(assetId: string, request: ChecklistResponseRequest) {
      return jsonCall(`/assets/${encodeURIComponent(assetId)}/checklist/respond`, 'POST', {
        item_key: request.item_key,
        approved: request.approved,
        note: request.note ?? '',
        created_by: request.created_by,
        interpret: request.interpret ?? !request.approved,
      }, (value) => {
        if (!isRecord(value)) return null;
        const nested = isRecord(value.approval)
          ? value.approval
          : isRecord(value.status_summary) ? value.status_summary : value;
        return decodeApprovalSummary({
          ...nested,
          checklist_id: pick(nested, 'checklist_id') ?? value.checklist_id,
          asset_id: pick(nested, 'asset_id') ?? assetId,
          status: isRecord(value.status) ? value.status : nested.status,
          pinned: pick(value, 'pinned', 'is_pinned') ?? nested.pinned,
          items: Array.isArray(nested.items) ? nested.items : [],
        });
      });
    },

    async getFactoryPack(projectId: string): Promise<ApiResult<FactoryPackManifest>> {
      const result = await call(`/projects/${encodeURIComponent(projectId)}/factory-pack`,
        decodeFactoryPackManifest);
      if (result.error !== null) return result;
      const bundleUrl = result.data.bundle_url
        || `${baseUrl}/projects/${encodeURIComponent(projectId)}/factory-pack.zip`;
      return {
        ...result,
        data: {
          ...result.data,
          bundle_url: bundleUrl,
          artifacts: result.data.artifacts.map((artifact) => ({
            ...artifact,
            url: artifact.url || bundleUrl,
          })),
        },
      };
    },

    factoryPackZipUrl(projectId: string) {
      return `${baseUrl}/projects/${encodeURIComponent(projectId)}/factory-pack.zip`;
    },

    assetImageUrl(assetId: string) {
      return `${baseUrl}/assets/${encodeURIComponent(assetId)}/image`;
    },
  };
}

export type TrustedApiClient = ReturnType<typeof createTrustedApiClient>;
