/**
 * Stable application contracts for the trusted Facetta workspace.
 *
 * The API client is the only module that knows about legacy response aliases.
 * Everything above it consumes these types, so the redesign can change its
 * presentation without coupling itself to provider or database details.
 */

import type { AnnotationCanvasSnapshot } from './AnnotationCanvas';

export type JsonPrimitive = string | number | boolean | null;
export type JsonValue = JsonPrimitive | JsonObject | JsonValue[];
export interface JsonObject {
  [key: string]: JsonValue;
}

export type ProjectState =
  | 'refining'
  | 'approval_required'
  | 'approved'
  | 'factory_ready';

export type WorkflowPhase = 'create' | 'refine' | 'approve' | 'factory';

export type ImageOperation =
  | 'CREATIVE_GENERATE'
  | 'CONCEPT_GENERATE'
  | 'REFERENCE_RENDER'
  | 'SPEC_RENDER'
  | 'LOCAL_EDIT'
  | 'VISUAL_ONLY_EDIT';

export type ImageQualityVerdict = 'pass' | 'warn' | 'fail';

export interface ImageQualityCheck {
  key: string;
  label: string;
  verdict: ImageQualityVerdict;
  severity: 'hard' | 'advisory';
  message: string;
}

export interface ImageQualityReport {
  verdict: ImageQualityVerdict;
  accepted: boolean;
  review_required: boolean;
  score: number | null;
  summary: string;
  failed_checks: string[];
  warnings: string[];
  checks: ImageQualityCheck[];
}

export interface ImageAgentPlan {
  operation: ImageOperation;
  normalized_intent: string;
  prompt_contract_version: string;
  source_hash: string | null;
  spec_visual_hash: string | null;
  source_spec_visual_hash: string | null;
  frozen_elements: string[];
  style_constraints: string[];
  expected_output: string;
  variant: number;
}

export interface ImageAttemptSummary {
  attempt_id: string | null;
  attempt: number;
  engine_role: 'primary' | 'primary_retry' | 'fallback';
  provider: string | null;
  model: string | null;
  latency_ms: number | null;
  cache_hit: boolean;
  provider_request_id: string | null;
  verdict: ImageQualityVerdict | null;
  failed_checks: string[];
  correction: string | null;
  fallback_reason: string | null;
  output_hash: string | null;
  prompt_hash: string | null;
  cache_key: string | null;
  usage: JsonObject | null;
  cost: number | null;
  error_category: string | null;
  created_at: string | null;
}

export interface ImageRunSummary {
  run_id: string;
  project_id: string | null;
  source_asset_id: string | null;
  accepted_asset_id: string | null;
  operation: ImageOperation;
  normalized_intent: string;
  prompt_contract_version: string;
  variant: number;
  status: 'running' | 'review_required' | 'accepted' | 'failed';
  stored_status: 'running' | 'review_required' | 'accepted' | 'failed';
  verdict: ImageQualityVerdict | null;
  accepted: boolean;
  review_required: boolean;
  source_hash: string | null;
  input_hash: string | null;
  mask_hash: string | null;
  spec_visual_hash: string | null;
  source_spec_visual_hash: string | null;
  output_hash: string | null;
  selected_attempt: number | null;
  error_category: string | null;
  review_decision: 'accepted' | 'rejected' | null;
  reviewed_by: string | null;
  reviewed_at: string | null;
  created_by: string | null;
  attempts: ImageAttemptSummary[];
  created_at: string | null;
  completed_at: string | null;
}

export interface AssetSummary {
  asset_id: string;
  root_id: string;
  parent_asset_id: string | null;
  capability: string;
  provenance: string;
  revision: number | null;
  design_id: string | null;
  design_version: number | null;
  region: string | null;
  instruction: string | null;
  drift: number | null;
  pinned: boolean;
  media_type: string;
  sha256?: string | null;
  image_url: string | null;
  created_by: string | null;
  created_at: string | null;
  legacy_provenance: boolean;
}

export interface SpecChange {
  path: string;
  before: JsonValue;
  after: JsonValue;
  label: string | null;
}

export interface ImageRoutingSummary {
  attempt_count: number;
  used_retry: boolean;
  used_fallback: boolean;
  cache_hit: boolean;
  run_id: string | null;
}

export interface ProjectRevision {
  revision: number;
  asset: AssetSummary;
  spec_version: number | null;
  spec_change: SpecChange[];
  ignored_fields: string[];
  qa: ImageQualityReport | null;
  routing: ImageRoutingSummary | null;
  created_at: string | null;
}

export interface FactoryReadinessBlocker {
  code: string;
  subject_kind: 'design_form' | 'source_component' | 'chain';
  subject_id: string;
  element_id: string | null;
  component_id: string | null;
  role: string;
  label: string;
  detail: string;
  required_resolution: string;
}

export interface ApprovalItem {
  key: string;
  label: string;
  fact: string;
  section: string;
  ref: string | null;
  index: number | null;
  target_element_id: string | null;
}

export interface ApprovalAnswer {
  item_key: string;
  approved: boolean;
  note: string | null;
  understood_as: string | null;
  created_by: string | null;
  created_at: string | null;
}

export interface ApprovalSummary {
  checklist_id: string;
  asset_id: string;
  design_id: string | null;
  design_version: number | null;
  mode: 'auto_pin' | 'explicit_pin' | 'optional';
  items: ApprovalItem[];
  answers: Record<string, ApprovalAnswer>;
  outstanding: string[];
  approved_count: number;
  total: number;
  completed: boolean;
  all_approved: boolean;
  pinned: boolean;
}

export interface ProjectDetail {
  id: string;
  root_id: string;
  title: string;
  collection: string | null;
  tags: string[];
  owner: string;
  state: ProjectState;
  design_id: string | null;
  /** Present on canonical project payloads; optional only for legacy snapshots. */
  spec?: JsonObject | null;
  active_asset_id: string | null;
  selected_candidate_asset_id?: string | null;
  active_design_version: number | null;
  active_revision: AssetSummary | null;
  pinned_revision: AssetSummary | null;
  revisions: ProjectRevision[];
  assets: AssetSummary[];
  derived_assets: AssetSummary[];
  approval: ApprovalSummary | null;
  factory_ready: boolean;
  factory_blockers: FactoryReadinessBlocker[];
  primary_revision_count: number;
  has_factory_drawing: boolean;
  cover_asset_id: string | null;
  created_at: string | null;
  updated_at: string | null;
}

/**
 * Fork the exact active revision into an independent sibling variation.
 * The expected values make the branch fail safely if the project changes while
 * the designer is naming the variation.
 */
export interface SaveAsVariationRequest {
  created_by: string;
  expected_active_asset_id: string;
  expected_design_version?: number | null;
  label: string;
}

/** The canonical Studio response after an immutable variation branch is made. */
export interface SaveAsVariationResult {
  status: 'variation_created';
  family_id: string;
  variation_index: number;
  source_project_id: string;
  source_asset_id: string;
  project: ProjectDetail;
}

export type StudioRevisionAction = 'created' | 'edit' | 'restore';

/** One append-only entry in a Variation's immutable Studio history. */
export interface StudioHistoryRevision {
  revision: number;
  asset_id: string;
  parent_asset_id: string | null;
  design_version: number | null;
  capability: string;
  image_url: string;
  pinned: boolean;
  action: StudioRevisionAction;
  /** Exact designer input or catalog action that caused this revision. */
  raw_intent: JsonObject;
  /** Structured AI understanding kept separate from designer intent. */
  interpretation: JsonObject;
  change_summary: string;
  restored_from_asset_id: string | null;
  created_by: string | null;
  created_at: string;
}

export interface StudioProjectHistory {
  project_id: string;
  family_id: string | null;
  variation_index: number;
  variation_label: string | null;
  active_asset_id: string | null;
  revisions: StudioHistoryRevision[];
}

export interface DesignFamilyVariation {
  root_id: string;
  title: string;
  collection: string;
  tags: string[];
  owner: string;
  counts: Record<string, number>;
  item_count: number;
  primary_revision_count: number;
  has_factory_drawing: boolean;
  cover_asset_id: string | null;
  created_at: string;
  updated_at: string;
  variation_index: number;
  variation_label: string | null;
  branched_from_project_root_id: string | null;
  branched_from_asset_id: string | null;
}

export interface DesignFamilyDetail {
  family_id: string;
  owner: string;
  title: string;
  created_at: string;
  updated_at: string;
  variations: DesignFamilyVariation[];
}

export interface DesignFamilyList {
  families: DesignFamilyDetail[];
}

export type StudioJobStatus =
  | 'queued'
  | 'running'
  | 'reviewing'
  | 'succeeded'
  | 'failed'
  | 'canceled';

export type StudioJobAction =
  | 'create'
  | 'vary'
  | 'refine'
  | 'views'
  | 'present'
  | 'factory';

export type StudioJobLane = 'instant' | 'fast_visual' | 'trusted_structural';

export interface StudioJobBilling {
  requested_outputs: number;
  credits_per_output: number;
  estimated_credits: number;
  completed_outputs: number;
  charged_outputs: number;
  charged_credits: number;
  policy: string;
}

/** Designer-facing Activity record. Provider and retry details are excluded. */
export interface StudioJobRecord {
  job_id: string;
  owner: string;
  action_id: StudioJobAction;
  lane: StudioJobLane;
  status: StudioJobStatus;
  progress: number;
  active_design_id: string | null;
  source_revision_id: string | null;
  error_code: string | null;
  created_at: string;
  updated_at: string;
  billing: StudioJobBilling;
}

export interface StudioJobList {
  jobs: StudioJobRecord[];
}

export interface CreateStudioJobRequest {
  owner: string;
  action_id: StudioJobAction;
  lane: StudioJobLane;
  active_design_id?: string | null;
  source_revision_id?: string | null;
  requested_outputs: number;
  credits_per_output: number;
}

export interface TransitionStudioJobRequest {
  owner: string;
  status: StudioJobStatus;
  progress: number;
  completed_outputs?: number | null;
  error_code?: string | null;
  /** Late-bound once for jobs that begin before a Project exists. */
  active_design_id?: string | null;
  /** Late-bound once when a designer selects the exact accepted direction. */
  source_revision_id?: string | null;
}

export interface RestoreStudioRevisionRequest {
  created_by: string;
  expected_active_asset_id: string;
  expected_design_version?: number | null;
}

/** Restore is append-only: the selected bytes become a new active revision. */
export interface RestoreStudioRevisionResult {
  status: 'restored_as_new_revision';
  restored_from_asset_id: string;
  new_asset_id: string;
  new_design_version: number | null;
  spec_change: SpecChange[];
  project: ProjectDetail;
}

export interface ProjectComment {
  id: string;
  design_id: string;
  version: number | null;
  author: string;
  author_label: string | null;
  body: string;
  created_at: string | null;
}

export interface CreateProjectFromBriefRequest {
  brief: string;
  owner: string;
  title?: string;
  collection?: string;
  tags?: string[];
  variant?: number;
}

export interface CreateProjectFromImageRequest {
  image_base64: string;
  media_type?: string;
  confirmed_spec: JsonObject;
  owner: string;
  title: string;
  collection?: string;
  tags?: string[];
}

export interface CreateProjectFromDrawingRequest {
  image_base64: string;
  media_type?: 'image/png' | 'image/jpeg' | 'image/webp';
  instruction?: string;
  variation_count?: 1 | 2 | 3 | 4;
  starting_variant?: number;
  owner: string;
  title: string;
  collection?: string;
  tags?: string[];
  /** Exact view isolated from a multi-view plate; the full source is retained. */
  source_region_description?: string;
  source_region?: NormalizedSourceRegion;
  references?: CreativeRoleReferenceRequest[];
}

export interface CreativeRoleReferenceRequest {
  role: 'material_style' | 'construction_detail' | 'brand_direction';
  image_base64: string;
  media_type: 'image/png' | 'image/jpeg' | 'image/webp';
}

export interface CreateProjectFromPromptRequest {
  prompt: string;
  variation_count?: 1 | 2 | 3 | 4;
  starting_variant?: number;
  owner: string;
  title: string;
  collection?: string;
  tags?: string[];
}

/**
 * A visual-only refinement can exist before a project has a confirmed design
 * specification. The active asset id is therefore the optimistic concurrency
 * token; a nullable design version must never be invented for this route.
 */
interface CreateVisualPreviewRequestBase {
  created_by: string;
  expected_active_asset_id: string;
  instruction: string;
  variant?: number;
}

export type CreateVisualPreviewRequest = CreateVisualPreviewRequestBase & (
  | { scope: 'appearance'; mask_base64?: never; markup_asset_id?: never }
  | { scope: 'marked_region'; mask_base64: string; markup_asset_id?: never }
  | { scope: 'marked_region'; markup_asset_id: string; mask_base64?: never }
);

export interface VisualPreviewCandidate {
  candidate_id: string;
  preview_url: string;
  save_as_variation_url: string;
  verdict: ImageQualityVerdict;
  qa: ImageQualityReport;
}

/** A temporary candidate. Creating it does not append project history. */
export interface VisualPreviewResult {
  project_id: string;
  source_asset_id: string;
  image_run_id: string;
  candidate: VisualPreviewCandidate;
}

export interface VisualPreviewListItem {
  candidate_id: string;
  image_run_id: string;
  source_asset_id: string;
  preview_url: string;
  save_as_variation_url: string;
  verdict: 'pass' | 'warn';
  requested_change: string;
  scope: 'appearance' | 'marked_region';
  qa: ImageQualityReport;
  expires_at: string;
}

export interface VisualPreviewListResult {
  candidates: VisualPreviewListItem[];
}

export interface VisualPreviewDecisionRequest {
  created_by: string;
  expected_active_asset_id: string;
}

/** Applying a pre-spec preview appends an image revision, never a fake spec. */
export interface VisualPreviewApplyResult {
  status: 'applied';
  project_id: string;
  source_asset_id: string;
  new_asset_id: string;
  design_version: null;
  project: ProjectDetail;
}

export interface VisualPreviewDiscardResult {
  status: 'discarded';
  project_id: string;
  candidate_id: string;
}

export interface PreviewVariationRequest {
  created_by: string;
  label: string;
}

/** A preview fork is a new sibling project; it never advances the source project. */
export interface PreviewVariationResult {
  status: 'saved_as_variation';
  family_id: string;
  variation_index: number;
  design_id?: string;
  design_version?: number;
  project: ProjectDetail;
}

export type StudioFactPath =
  | 'metal.material' | 'metal.color' | 'metal.finish' | 'metal.karat'
  | 'stone.species' | 'stone.cut' | 'stone.color.trade' | 'stone.color.gia'
  | 'stone.carat' | 'stone.dimensions_mm.length' | 'stone.dimensions_mm.width'
  | 'stone.dimensions_mm.depth' | 'setting.style' | 'setting.prong_count'
  | 'band.profile' | 'band.width_mm' | 'band.thickness_mm'
  | 'ring_size.system' | 'ring_size.value';

export interface StudioFactChangeRequest {
  path: StudioFactPath;
  value: JsonValue;
}

export interface ReviseStudioFactsRequest {
  expected_active_asset_id: string;
  expected_design_version: number;
  created_by: string;
  changes: StudioFactChangeRequest[];
}

export interface ReviseStudioFactsResult {
  status: 'applied' | 'no_change';
  project_root_id: string;
  source_asset_id: string;
  asset_id: string;
  design_id: string;
  previous_design_version: number;
  design_version: number;
  spec_change: SpecChange[];
  project_detail: ProjectDetail;
}

export type PresentationAssetCapability =
  | 'CLIENT_BEAUTY_RENDER'
  | 'CLIENT_PRODUCT_PHOTO'
  | 'MARKETING_IMAGE';

/** Exact optimistic-concurrency tokens required to resolve a presentation preview. */
export interface PresentationCandidateDecisionRequest {
  created_by: string;
  expected_project_id: string;
  expected_source_asset_id: string;
  expected_design_version: number;
}

/** Saving presentation imagery never replaces the active canonical revision. */
export interface PresentationCandidateAcceptResult {
  status: 'accepted';
  project_id: string;
  source_asset_id: string;
  source_design_version: number;
  asset_id: string;
  capability: PresentationAssetCapability;
  project: ProjectDetail;
}

export interface PresentationCandidateDiscardResult {
  status: 'discarded';
  project_id: string;
  source_asset_id: string;
  source_design_version: number;
  candidate_id: string;
}

export interface PreSpecPresentationRequest {
  created_by: string;
  expected_active_asset_id: string;
  destination: 'client' | 'marketing';
  client_format?: 'beauty' | 'product';
  preset: ProductPhotoPreset;
  framing?: ProductPhotoFraming;
  custom_instruction?: string;
  variant?: number;
  /** Server-created Activity job bound to this exact requested output. */
  studio_job_id?: string;
}

export interface PreSpecPresentationCandidate {
  candidate_id: string;
  image_run_id: string;
  preview_url: string;
  studio_job_id: string | null;
  capability: PresentationAssetCapability;
  preset: ProductPhotoPreset;
  framing: ProductPhotoFraming;
  qa: ImageQualityReport;
}

export interface PreSpecPresentationResumeCandidate extends PreSpecPresentationCandidate {
  project_id: string;
  source_asset_id: string;
  source_sha256: string;
  /** Null for a pre-spec visual; exact Present candidates carry their immutable spec version. */
  design_version: number | null;
  destination: 'client' | 'marketing';
  status: 'reviewing';
  accepted_asset_id: null;
  expires_at: string;
}

export interface PreSpecPresentationListResult {
  candidates: PreSpecPresentationResumeCandidate[];
}

/** Review-only output from an exact visual which has no confirmed spec. */
export interface PreSpecPresentationResult {
  status: 'review_required';
  project_id: string;
  source_asset_id: string;
  source_sha256: string;
  design_version: null;
  destination: 'client' | 'marketing';
  client_format: 'beauty' | 'product';
  candidate: PreSpecPresentationCandidate;
}

export interface PreSpecPresentationDecisionRequest {
  created_by: string;
  expected_active_asset_id: string;
  expected_source_sha256: string;
}

export interface PreSpecPresentationAcceptResult {
  status: 'accepted';
  project_id: string;
  source_asset_id: string;
  source_sha256: string;
  design_version: null;
  asset_id: string;
  capability: PresentationAssetCapability;
  project: ProjectDetail;
}

export interface PreSpecPresentationDiscardResult {
  status: 'discarded';
  project_id: string;
  source_asset_id: string;
  source_sha256: string;
  design_version: null;
  candidate_id: string;
}

export interface PromoteCreativeCandidateRequest {
  created_by: string;
  confirmation_token: string;
}

export interface ExtractCreativeCandidateDraftRequest {
  notes?: string;
  created_by: string;
  run_independent_audit?: boolean;
}

export type StudioConfirmFactAuthority = 'suggested' | 'estimated' | 'designer_supplied';

export interface StudioConfirmFact {
  key: string;
  label: string;
  value: string;
  authority: StudioConfirmFactAuthority;
}

export interface StudioConfirmFactGroup {
  key: 'design' | 'center_stone' | 'setting' | 'metal' | 'ring_fit' | 'accents';
  label: string;
  facts: StudioConfirmFact[];
}

export interface StudioConfirmDesignResponse {
  confirmation_token: string;
  expires_at: string;
  candidate_id: string;
  candidate_sha256: string;
  spec_visual_hash: string;
  fact_groups: StudioConfirmFactGroup[];
  unresolved_source_questions: string[];
  audit_eligibility: {
    eligible: boolean;
    state: 'not_ready' | 'ready' | 'complete';
    reason: string;
  };
}

export interface BeautyRenderRequest {
  created_by: string;
  expected_asset_id: string;
  source_asset_id?: string;
  expected_design_version: number;
  instruction?: string;
  variant?: number;
  presentation_only?: boolean;
  studio_job_id?: string;
}

export interface BeautyRenderAccepted {
  status: 'accepted';
  project: ProjectDetail;
  source_asset_id: string;
  asset_id: string;
  image_run_id: string;
  qa: ImageQualityReport;
}

export interface BeautyRenderWarning {
  status: 'review_required';
  project_id: string;
  source_asset_id: string;
  image_run_id: string;
  quality_report: ImageQualityReport;
  routing: ImageRoutingSummary;
  warning_candidate: ImageWarningCandidate;
}

export type BeautyRenderResult = BeautyRenderAccepted | BeautyRenderWarning;

export interface ExtractImageDraftRequest {
  image_base64: string;
  media_type: 'image/png' | 'image/jpeg' | 'image/webp';
  notes?: string;
  created_by: string;
  run_independent_audit?: boolean;
}

export interface ExtractPlateDraftRequest {
  image_base64: string;
  scale_anchor?: string;
  notes?: string;
  created_by: string;
  run_independent_audit?: boolean;
}

export type SourceCoverageAuditStatus =
  | 'not_requested'
  | 'pass'
  | 'review_required'
  | 'unavailable'
  | 'invalid'
  | 'legacy_provenance';

export type SourceComponentView =
  | 'plate_composite'
  | 'front'
  | 'top'
  | 'side'
  | 'three_quarter'
  | 'detail'
  | 'unspecified';

export interface SourceComponentIndependentAudit {
  kind: 'independent_component_audit';
  verdict: 'pass' | 'fail' | 'inconclusive';
  auditor: string;
  source_view: SourceComponentView;
  observed_description: string;
  evidence_sha256: string | null;
}

export interface DesignerComponentConfirmation {
  kind: 'designer_component_confirmation';
  basis: 'visible_source' | 'designer_defined_target';
  reviewer: string;
  source_view: SourceComponentView;
  confirmed_description: string;
  evidence_sha256: string;
  spec_visual_hash: string;
}

export interface SourceCoverageComponent {
  component_id: string;
  source_view: SourceComponentView;
  source_description: string;
  source_confidence: number;
  canonical_spec_paths: string[];
  unresolved_reason: string | null;
  independent_audit: SourceComponentIndependentAudit | null;
  designer_confirmation?: DesignerComponentConfirmation | null;
}

export interface SourceCoverageBlocker {
  code:
    | 'source_component_unresolved'
    | 'source_component_not_independently_audited'
    | 'source_component_audit_failed'
    | 'source_component_audit_inconclusive'
    | 'source_component_path_missing'
    | 'source_component_spec_audit_missing'
    | 'source_component_spec_audit_stale'
    | 'source_component_confirmation_stale';
  component_id: string;
  message: string;
  required_resolution: string;
}

export interface SourceComponentResolution {
  component_id: string;
  canonical_spec_paths?: string[];
  unresolved_reason?: string | null;
}

export interface ResolveSourceCoverageRequest {
  spec: JsonObject;
  source_image_base64?: string | null;
  resolutions: SourceComponentResolution[];
  created_by: string;
  run_independent_audit: boolean;
}

export interface SourceComponentConfirmationInput {
  component_id: string;
  basis: 'visible_source' | 'designer_defined_target';
  confirmed_description: string;
}

export interface ConfirmSourceCoverageRequest {
  spec: JsonObject;
  source_image_base64: string;
  confirmations: SourceComponentConfirmationInput[];
  created_by: string;
}

export interface ConfirmSourceCoverageResult {
  spec: JsonObject;
  confirmed_component_ids: string[];
  blockers: SourceCoverageBlocker[];
  factory_ready: boolean;
  confirmed_by: string;
}

export interface DimensionedProfilePoint {
  x_mm: number;
  y_mm: number;
}

export interface DimensionedProfilePath {
  path_id: string;
  purpose: 'outline' | 'centerline' | 'stone_seat' | 'attachment';
  closed: boolean;
  points: DimensionedProfilePoint[];
  nominal_width_mm: number | null;
}

export interface DimensionedProfileGeometryInput {
  view: string;
  paths: DimensionedProfilePath[];
  profile_thickness_mm: number;
  dimension_status: 'designer_supplied' | 'designer_confirmed_estimate';
  manufacturing_notes: string;
}

export interface DimensionedProfileDefinition extends DimensionedProfileGeometryInput {
  kind: 'dimensioned_profile';
  scope: 'full_assembly';
  coordinate_system: 'x_right_y_up';
  source_asset_id: string;
  source_asset_sha256: string;
  confirmed_by: string;
  confirmed_at: string;
}

export interface ConfirmCreativeCandidateProfileRequest {
  spec: JsonObject;
  element_id: string;
  profile: DimensionedProfileGeometryInput;
  created_by: string;
}

export interface DimensionedProfileBlocker {
  code: string;
  detail: string;
}

export interface ConfirmCreativeCandidateProfileResult {
  spec: JsonObject;
  element_id: string;
  candidate_asset_id: string;
  candidate_sha256: string;
  previous_definition_kind: string;
  definition: DimensionedProfileDefinition;
  source_reaudit_required: boolean;
  factory_ready: boolean;
  sheet_authority: 'factory_profile' | 'preliminary_not_for_production';
  blockers: DimensionedProfileBlocker[];
}

export interface DraftFactorySheetPreview {
  svg: string;
  authority: 'spec_derived_preview' | 'preliminary_not_for_production';
}

export interface SourceCoverageResolutionAudit {
  requested: boolean;
  status: SourceCoverageAuditStatus;
  audited_component_ids: string[];
  blocker_count: number;
}

export interface SourceCoverageResolutionResult {
  spec: JsonObject;
  source_kind: string | null;
  components: SourceCoverageComponent[];
  valid_spec_paths: string[];
  changed_component_ids: string[];
  invalidated_audit_component_ids: string[];
  blockers: SourceCoverageBlocker[];
  factory_ready: boolean;
  legacy_provenance: boolean;
  resolved_by: string | null;
  audit: SourceCoverageResolutionAudit;
}

export interface PhotoDraftResult {
  spec: JsonObject;
  source_coverage: SourceCoverageResolutionResult;
}

export interface SourceCoverageAuditSummary {
  status: Exclude<SourceCoverageAuditStatus, 'legacy_provenance'>;
  blocker_count: number;
}

export interface PlateDraftResult {
  spec: JsonObject;
  read: JsonObject;
  uncertainties: string[];
  provenance: 'grok_vision_hand_plate_draft';
  requires_designer_confirmation: true;
  source_coverage_audit: SourceCoverageAuditSummary;
  source_coverage: SourceCoverageResolutionResult;
}

export type ProductPhotoPreset =
  | 'catalog_white'
  | 'luxury_studio'
  | 'dark_editorial'
  | 'macro_detail';

export type ProductPhotoFraming = 'source' | 'square' | 'portrait';

export interface ProductPhotoRequest {
  created_by: string;
  expected_asset_id: string;
  expected_design_version: number;
  preset: ProductPhotoPreset;
  framing?: ProductPhotoFraming;
  custom_instruction?: string;
  variant?: number;
  presentation_only?: boolean;
  studio_job_id?: string;
}

export interface MarketingPackRequest {
  created_by: string;
  expected_asset_id: string;
  expected_design_version: number;
  presets: ProductPhotoPreset[];
  framing?: ProductPhotoFraming;
  custom_instruction?: string;
  starting_variant?: number;
  studio_job_id?: string;
}

export interface MarketingPackCandidate {
  preset: ProductPhotoPreset;
  framing: ProductPhotoFraming;
  image_run_id: string;
  candidate_id: string;
  preview_url: string;
  qa: ImageQualityReport;
  routing: ImageRoutingSummary;
}

export interface MarketingPackFailure {
  preset: ProductPhotoPreset;
  image_run_id: string | null;
  error_category: string;
  code: string;
  detail: string;
}

export interface MarketingPackResult {
  status: 'review_required' | 'failed';
  project_id: string;
  source_asset_id: string;
  design_version: number;
  requested_count: number;
  candidate_count: number;
  failed_count: number;
  maximum_provider_attempts: number;
  actual_attempts: number;
  candidates: MarketingPackCandidate[];
  failures: MarketingPackFailure[];
}

export interface ProductPhotoPresentation {
  preset: ProductPhotoPreset;
  framing: ProductPhotoFraming;
  source_asset_id: string;
  design_version: number;
}

export interface ProductPhotoAccepted {
  status: 'accepted';
  project: ProjectDetail;
  asset_id: string;
  image_run_id: string;
  qa: ImageQualityReport;
  routing: ImageRoutingSummary;
  presentation: ProductPhotoPresentation;
}

export interface ProductPhotoWarning {
  status: 'review_required';
  project_id: string;
  image_run_id: string;
  quality_report: ImageQualityReport;
  routing: ImageRoutingSummary;
  presentation: ProductPhotoPresentation;
  warning_candidate: ImageWarningCandidate;
}

export type ProductPhotoResult = ProductPhotoAccepted | ProductPhotoWarning;

/**
 * Catalog paths are deliberately closed. Adding a new backend catalog does
 * not make it designer-selectable until the client knows how to place it in
 * the applicable jewelry workflow.
 */
export type ComponentCatalogPath =
  | 'chain.style'
  | 'stone.color'
  | 'stone.cut'
  | 'metal.material'
  | 'metal.color'
  | 'setting.style';

export type CatalogImageAgentStatus =
  | 'catalog_ready'
  | 'catalog_ready_category_pending';

export interface ComponentCatalogOption {
  id: string;
  display: string;
  visual_geometry: string[];
  isolation_target: string;
  frozen_facts: string[];
  factory_fields: JsonObject;
  derived_factory_fields: string[];
  selection_requirements: string[];
}

export interface ComponentCatalog {
  component_path: ComponentCatalogPath;
  display: string;
  applicable_jewelry_types: string[];
  image_agent_status: CatalogImageAgentStatus;
  options: ComponentCatalogOption[];
}

export interface DraftCatalogSelectionRequest {
  spec: JsonObject;
  component_path: ComponentCatalogPath;
  option_id: string;
}

export interface DraftCatalogSelectionResult {
  spec: JsonObject;
  spec_change: SpecChange[];
  isolation_target: string;
  frozen_facts: string[];
}

export interface StoneVocabularyEntry {
  id: string;
  display: string;
  parameter_set: string;
}

export interface StoneTradeColorOption {
  term: string;
  gia: string;
}

export interface StoneCutOption {
  id: string;
  name: string;
}

export interface StoneVocabularyOptions {
  stone: string;
  display: string;
  parameter_set: 'gemstone';
  colors: StoneTradeColorOption[];
  cuts: StoneCutOption[];
}

export interface DraftStoneSelectionRequest {
  spec: JsonObject;
  species: string;
  trade_color: string;
}

export interface ChainLinkDimensions {
  role: 'standard' | 'long';
  length_mm: number;
  inside_length_mm: number;
  inside_width_mm: number;
}

export interface OpenLinkChainGeometry {
  construction: 'open_link';
  chain_width_mm: number;
  profile_thickness_mm: number;
  end_ring_outer_diameter_mm: number;
  link_thickness_mm: number;
  links_soldered: boolean;
  links: ChainLinkDimensions[];
}

export interface StrandedChainGeometry {
  construction: 'stranded';
  chain_width_mm: number;
  profile_thickness_mm: number;
  end_ring_outer_diameter_mm: number;
  strand_wire_diameter_mm: number;
  strand_count: number;
}

export interface SmoothChainGeometry {
  construction: 'smooth_plate';
  chain_width_mm: number;
  profile_thickness_mm: number;
  end_ring_outer_diameter_mm: number;
  plate_thickness_mm: number;
}

export type ChainGeometry =
  | OpenLinkChainGeometry
  | StrandedChainGeometry
  | SmoothChainGeometry;

export type ChainProduction =
  | {
      mode: 'stock';
      reference_kind: 'supplier_sku' | 'approved_sample';
      reference: string;
    }
  | {
      mode: 'custom';
      reference_kind: 'dimensioned_drawing' | 'cad_asset';
      reference: string;
    };

export interface CatalogApplyRequest {
  component_path: ComponentCatalogPath;
  option_id: string;
  expected_design_version: number;
  created_by: string;
  variant?: number;
  /** Applies only to the species-scoped stone.color palette. */
  stone_species?: string;
  chain_geometry?: ChainGeometry;
  chain_production?: ChainProduction;
}

/**
 * A provider-evaluated catalog edit that has not yet changed project history.
 * The three URLs are short-lived capability URLs and are normalized by the
 * trusted API client before they reach UI code.
 */
export interface CatalogPreviewCandidate {
  run_id: string;
  candidate_id: string;
  preview_url: string;
  accept_url: string;
  discard_url: string;
  save_as_variation_url: string;
  verdict: 'pass' | 'warn';
  expires_in_seconds: number;
}

export interface CatalogPreviewResult {
  status: 'preview_ready' | 'review_required';
  component_path: ComponentCatalogPath;
  option_id: string;
  isolation_target: string;
  source_asset_id: string;
  design_version: number;
  image_run_id: string;
  spec_change: SpecChange[];
  next_spec: JsonObject;
  qa: ImageQualityReport;
  routing: ImageRoutingSummary;
  project: ProjectDetail;
  candidate: CatalogPreviewCandidate;
}

export interface CatalogPreviewListItem {
  candidate: CatalogPreviewCandidate;
  source_asset_id: string;
  component_path: ComponentCatalogPath;
  option_id: string;
  requested_change: string;
  next_spec: JsonObject;
  spec_change: SpecChange[];
  qa: ImageQualityReport;
  routing: ImageRoutingSummary;
  expires_at: string;
}

export interface CatalogPreviewListResult {
  candidates: CatalogPreviewListItem[];
}

export interface CatalogPreviewAcceptRequest {
  expected_design_version: number;
  created_by: string;
}

export interface CatalogPreviewAcceptResult {
  status: 'accepted';
  asset_id: string;
  design_version: number;
  image_run_id: string;
  spec_change: SpecChange[];
  project: ProjectDetail;
}

export interface CatalogPreviewDiscardResult {
  status: 'discarded';
}

export interface CatalogWarningCandidate {
  run_id: string;
  candidate_id: string;
  preview_url: string;
  operation: 'LOCAL_EDIT';
  requested_change: string;
}

interface CatalogApplyBase {
  component_path: ComponentCatalogPath;
  option_id: string;
  isolation_target: string;
  design_version: number;
  image_run_id: string;
  spec_change: SpecChange[];
  qa: ImageQualityReport;
  routing: ImageRoutingSummary;
  project: ProjectDetail;
}

export interface CatalogApplyAccepted extends CatalogApplyBase {
  status: 'accepted';
  asset_id: string;
}

export interface CatalogApplyReviewRequired extends CatalogApplyBase {
  status: 'review_required';
  next_spec: JsonObject;
  warning_candidate: CatalogWarningCandidate;
}

export type CatalogApplyResult =
  | CatalogApplyAccepted
  | CatalogApplyReviewRequired;

/**
 * Error responses remain ApiResult-compatible while exposing the states the
 * catalog UI must handle without interpreting prose or provider details.
 */
export type CatalogApplyFailureStatus =
  | 'warning'
  | 'stale'
  | 'category_pending'
  | 'error';

export interface CatalogApplyFailure extends ApiError {
  catalog_status: CatalogApplyFailureStatus;
  component_path: ComponentCatalogPath | null;
  option_id: string | null;
  image_run_id: string | null;
  applicable_jewelry_types: string[];
  current_asset_id: string | null;
  current_design_version: number | null;
}

export type CatalogApplyCallResult =
  | { data: CatalogApplyResult; error: null; status: number }
  | { data: null; error: CatalogApplyFailure; status: number };

export type MarkupImpact = 'specification' | 'visual_only';

export interface MarkupInterpretation {
  target_region: string;
  requested_change: string;
  impact: MarkupImpact;
  target_spec_reference: string | null;
  target_section: string | null;
  target_index: number | null;
  target_element_id: string | null;
  frozen_elements: string[];
  confidence: number | null;
  clarification_question: string | null;
  understood_as: string;
}

interface MarkupReadRequestBase {
  created_by: string;
  assistant_name?: string;
}

export type MarkupReadRequest = MarkupReadRequestBase & (
  | {
      marked_image_base64: string;
      markup_snapshot?: never;
    }
  | {
      markup_snapshot: AnnotationCanvasSnapshot;
      marked_image_base64?: never;
    }
);

export interface MarkupReadResponse {
  markup_asset_id: string | null;
  assistant_name: string | null;
  interpretation: MarkupInterpretation;
  design_id: string | null;
  expected_design_version: number | null;
}

export interface ConfirmedMarkupAnnotation {
  region_description: string;
  change_instruction: string;
  impact: MarkupImpact;
  target_section: string | null;
  target_ref: string | null;
  index: number | null;
  target_element_id: string | null;
  form_view: 'front' | 'side' | 'top' | 'three_quarter';
  mask_base64: string | null;
}

/** One request intentionally contains exactly one confirmed annotation. */
export interface MarkupApplyRequest {
  annotation: ConfirmedMarkupAnnotation;
  markup_asset_id: string | null;
  expected_design_version: number;
  created_by: string;
  variant?: number;
  preview_only?: boolean;
}

export interface ImageWarningCandidate {
  run_id: string;
  candidate_id: string | null;
  preview_url: string | null;
  qa: ImageQualityReport;
  operation: ImageOperation | null;
  requested_change: string;
  asset_capability: string | null;
}

export type LineArtView = 'front' | 'three_quarter' | 'side';

/** A source-image rectangle expressed as fractions of the full image. */
export interface NormalizedSourceRegion {
  x: number;
  y: number;
  width: number;
  height: number;
}

/** Optional source isolation carried through initial generation and retries. */
export interface LineArtSourceSelection {
  source_region_description?: string;
  source_region?: NormalizedSourceRegion;
}

export interface CreateLineArtRequest {
  created_by: string;
  expected_asset_id: string;
  expected_design_version: number;
  view: LineArtView;
  source_region_description?: string;
  source_region?: NormalizedSourceRegion;
  variant?: number;
  studio_job_id?: string;
}

/** Durable exact-revision View awaiting an explicit Save or Discard decision. */
export interface StudioViewResumeCandidate {
  candidate_id: string;
  image_run_id: string;
  studio_job_id: string | null;
  project_id: string;
  source_asset_id: string;
  design_version: number;
  view: LineArtView;
  qa: ImageQualityReport;
  status: 'reviewing';
  accepted_asset_id: null;
  expires_at: string;
  preview_url: string;
}

export interface StudioViewCandidateListResult {
  candidates: StudioViewResumeCandidate[];
}

export interface StudioViewCandidateDecisionRequest {
  created_by: string;
  expected_project_id: string;
  expected_source_asset_id: string;
  expected_design_version: number;
}

export interface StudioViewCandidateAcceptResult {
  status: 'accepted';
  project_id: string;
  source_asset_id: string;
  design_version: number;
  asset_id: string;
  project: ProjectDetail;
}

export interface StudioViewCandidateDiscardResult {
  status: 'discarded';
  project_id: string;
  source_asset_id: string;
  design_version: number;
  candidate_id: string;
}

export interface DrawingConfirmationResult {
  status: 'confirmation_required';
  project_id: string;
  image_run_id: string;
  quality_report: ImageQualityReport;
  routing: ImageRoutingSummary;
  view: LineArtView;
  candidate: ImageWarningCandidate;
  next: string;
}

export interface ColorizeLineArtRequest {
  created_by: string;
  expected_asset_id: string;
  expected_design_version: number;
  variant?: number;
}

export type ColorizeLineArtResult =
  | {
      status: 'accepted';
      project: ProjectDetail;
      asset_id: string;
      image_run_id: string;
      qa: ImageQualityReport;
      routing: ImageRoutingSummary;
    }
  | {
      status: 'review_required';
      project_id: string;
      image_run_id: string;
      quality_report: ImageQualityReport;
      routing: ImageRoutingSummary;
      candidate: ImageWarningCandidate;
    };

export interface ProjectCreationWarning {
  status: 'review_required';
  project: null;
  image_run_id: string;
  warning_candidate: ImageWarningCandidate;
  quality_report: JsonObject;
}

export type ProjectCreationResult = ProjectDetail | ProjectCreationWarning;

export interface MarkupApplyResponse {
  revision: ProjectRevision | null;
  spec_version: number | null;
  spec_change: SpecChange[];
  ignored_fields: string[];
  qa: ImageQualityReport;
  routing: ImageRoutingSummary;
  image_run_id: string | null;
  warning_candidate: ImageWarningCandidate | null;
}

export interface ChecklistCreateRequest {
  created_by: string;
  mode?: 'auto_pin' | 'explicit_pin' | 'optional';
}

export interface ChecklistResponseRequest {
  item_key: string;
  approved: boolean;
  note?: string;
  created_by: string;
  interpret?: boolean;
}

export interface FactoryPackArtifact {
  name: string;
  media_type: string;
  sha256: string;
  url: string;
  authoritative: boolean;
}

export interface FactoryDimensionEstimate {
  field_path: string;
  value: JsonValue;
  unit: string;
  status: 'estimated_from_reference';
  method: string;
  source: string;
  confidence: number | null;
  note: string | null;
}

export interface FactoryDimensionSummary {
  has_estimates: boolean;
  estimated_fields: FactoryDimensionEstimate[];
  disclaimer: string | null;
}

export type FactoryFactStatus =
  | 'designer_confirmed'
  | 'estimated_from_reference'
  | 'pending_confirmation';

export interface FactoryDimensionFact {
  field_path: string;
  section: string;
  value: number;
  unit: string;
  status: FactoryFactStatus;
  method: string | null;
  source: string | null;
  confidence: number | null;
  note: string | null;
}

export interface FactoryStoneScheduleRow {
  ref: string;
  section: string;
  role: string;
  species: string;
  cut: string;
  visible_color: string | null;
  count: number;
  carat_each: number;
  carat_total: number;
  fact_status: FactoryFactStatus;
  dimension_paths: string[];
}

export interface FactoryMaterialScheduleRow {
  section: 'metal';
  material: string;
  karat: number | null;
  color: string | null;
  finish: string | null;
  fact_status: FactoryFactStatus;
}

export interface FactorySettingScheduleRow {
  section: 'setting';
  style: string;
  prong_count: number | null;
  fact_status: FactoryFactStatus;
  dimension_paths: string[];
}

export interface FactoryRecordedFact {
  field_path: string;
  section: string;
  label: string;
  value: string;
  fact_status: FactoryFactStatus;
}

export interface FactorySheetFactPlan {
  schema_version: 'facetta.factory-sheet-plan.v1';
  jewelry_type: string;
  template: string;
  materials: FactoryMaterialScheduleRow[];
  stones: FactoryStoneScheduleRow[];
  settings: FactorySettingScheduleRow[];
  recorded_facts: FactoryRecordedFact[];
  dimensions: FactoryDimensionFact[];
  confirmed_fact_count: number;
  estimated_fact_count: number;
  pending_confirmation_count: number;
  has_estimates: boolean;
  estimate_disclaimer: string | null;
}

export interface FactoryPackManifest {
  project_id: string;
  design_id: string;
  design_version: number;
  pinned_asset_id: string;
  approver: string;
  approved_at: string;
  checklist_id: string;
  qa: ImageQualityReport | null;
  dimensions: FactoryDimensionSummary;
  factory_sheet_fact_plan: FactorySheetFactPlan;
  artifacts: FactoryPackArtifact[];
  bundle_url: string;
  manifest_sha256: string | null;
}

export type ApiErrorCategory =
  | 'network'
  | 'validation'
  | 'stale_version'
  | 'quality'
  | 'provider'
  | 'conflict'
  | 'not_found'
  | 'decode'
  | 'authentication'
  | 'authorization'
  | 'unknown';

export interface ApiError {
  code: string;
  message: string;
  category: ApiErrorCategory;
  status: number;
  details?: JsonValue;
  retryable: boolean;
}

export type ApiResult<T> =
  | { data: T; error: null; status: number }
  | { data: null; error: ApiError; status: number };
