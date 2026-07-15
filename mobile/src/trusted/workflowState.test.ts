/// <reference types="jest" />

import type {
  ApiError,
  AssetSummary,
  ImageQualityReport,
  ImageWarningCandidate,
  MarkupApplyResponse,
  MarkupReadResponse,
  ProjectDetail,
  ProjectRevision,
} from './types';
import {
  canSelectPhase,
  initialTrustedWorkflowState,
  trustedWorkflowReducer,
  type TrustedWorkflowState,
} from './workflowState';
import { selectBeautyRenderSource } from './useTrustedWorkflow';

function assert(condition: boolean, message: string): void {
  if (!condition) throw new Error(`Trusted workflow reducer: ${message}`);
}

const quality = (verdict: 'pass' | 'warn' | 'fail'): ImageQualityReport => ({
  verdict,
  accepted: verdict === 'pass',
  review_required: verdict === 'warn',
  score: verdict === 'pass' ? 96 : 74,
  summary: verdict === 'pass' ? 'passed' : 'review',
  failed_checks: verdict === 'fail' ? ['metal'] : [],
  warnings: verdict === 'warn' ? ['band edge needs review'] : [],
  checks: [],
});

const asset = (revision: number, designVersion = revision): AssetSummary => ({
  asset_id: `ast_${revision}`,
  root_id: 'ast_1',
  parent_asset_id: revision === 1 ? null : `ast_${revision - 1}`,
  capability: revision === 1 ? 'SPEC_RENDER' : 'LOCAL_EDIT',
  provenance: revision === 1 ? 'spec_aligned' : 'confirmed_edit',
  revision,
  design_id: 'dsn_1',
  design_version: designVersion,
  region: null,
  instruction: null,
  drift: 0,
  pinned: false,
  media_type: 'image/png',
  image_url: `http://localhost:8000/assets/ast_${revision}/image`,
  created_by: 'usr_test',
  created_at: `2026-07-10T00:00:0${revision}Z`,
  legacy_provenance: false,
});

const revision = (value: number): ProjectRevision => ({
  revision: value,
  asset: asset(value),
  spec_version: value,
  spec_change: value === 1 ? [] : [{
    path: 'band.width_mm',
    before: 1.8,
    after: 2.2,
    label: 'Band width',
  }],
  ignored_fields: [],
  qa: quality('pass'),
  routing: {
    attempt_count: 1,
    used_retry: false,
    used_fallback: false,
    cache_hit: false,
    run_id: `run_${value}`,
  },
  created_at: `2026-07-10T00:00:0${value}Z`,
});

function project(overrides: Partial<ProjectDetail> = {}): ProjectDetail {
  const first = revision(1);
  return {
    id: 'ast_1',
    root_id: 'ast_1',
    title: 'Trusted ring',
    collection: null,
    tags: [],
    owner: 'usr_test',
    state: 'refining',
    design_id: 'dsn_1',
    active_asset_id: first.asset.asset_id,
    active_design_version: 1,
    active_revision: first.asset,
    pinned_revision: null,
    revisions: [first],
    assets: [first.asset],
    derived_assets: [],
    approval: null,
    factory_ready: false,
    factory_blockers: [],
    primary_revision_count: 1,
    has_factory_drawing: false,
    cover_asset_id: first.asset.asset_id,
    created_at: '2026-07-10T00:00:01Z',
    updated_at: '2026-07-10T00:00:01Z',
    ...overrides,
  };
}

const reading: MarkupReadResponse = {
  interpretation_id: 'interpretation_1',
  interpretation_status: 'awaiting_confirmation',
  expires_at: '2099-01-01T00:00:00Z',
  markup_asset_id: 'ast_markup',
  assistant_name: 'Facetta',
  interpretation: {
    target_region: 'the lower band',
    requested_change: 'widen the band to 2.2 mm',
    impact: 'specification',
    target_spec_reference: null,
    target_section: 'band',
    target_index: null,
    target_component_id: 'shank',
    target_element_id: null,
    frozen_elements: ['center stone', 'setting', 'metal', 'camera'],
    confidence: 0.96,
    clarification_question: null,
    understood_as: 'Widen only the lower band to 2.2 mm.',
  },
  design_id: 'dsn_1',
  expected_design_version: 1,
};

const confirmed = {
  region_description: 'the lower band',
  change_instruction: 'widen the band to 2.2 mm',
  impact: 'specification' as const,
  target_section: 'band',
  target_ref: null,
  index: null,
  target_component_id: 'shank',
  target_element_id: null,
  form_view: 'three_quarter' as const,
  mask_base64: null,
};

const staleError: ApiError = {
  code: 'STALE_DESIGN_VERSION',
  message: 'Expected version 1, current version is 2.',
  category: 'stale_version',
  status: 409,
  retryable: false,
};

const warningCandidate: ImageWarningCandidate = {
  run_id: 'run_warn',
  candidate_id: 'candidate_1',
  preview_url: 'http://localhost/warning.png',
  qa: quality('warn'),
  operation: 'LOCAL_EDIT',
  requested_change: 'widen the band',
  asset_capability: 'LOCALIZED_EDIT',
};

function interpretedState(): TrustedWorkflowState {
  let state = trustedWorkflowReducer(initialTrustedWorkflowState, {
    type: 'project_loaded',
    project: project(),
    source: 'open',
  });
  state = trustedWorkflowReducer(state, {
    type: 'markup_interpreted',
    base_asset_id: 'ast_1',
    response: reading,
  });
  return trustedWorkflowReducer(state, {
    type: 'markup_confirmed',
    annotation: confirmed,
    confirmed_interpretation_id: 'interpretation_1',
    expected_design_version: 1,
  });
}

export function runTrustedWorkflowReducerTests(): void {
  const creationWarning = trustedWorkflowReducer(initialTrustedWorkflowState, {
    type: 'creation_warning_received',
    warning: {
      ...warningCandidate,
      operation: 'CONCEPT_GENERATE',
    },
  });
  assert(creationWarning.project === null, 'creation WARN must not create a partial project');
  assert(creationWarning.phase === 'create', 'creation WARN should remain in Create review');

  const loaded = trustedWorkflowReducer(initialTrustedWorkflowState, {
    type: 'project_loaded',
    project: project(),
    source: 'open',
  });
  assert(loaded.phase === 'refine', 'opening a project should enter Refine');
  assert(loaded.project?.active_asset_id === 'ast_1', 'opening should retain the active image');

  const imported = project({
    active_revision: { ...asset(1), capability: 'IMPORTED_REFERENCE' },
    assets: [{ ...asset(1), capability: 'IMPORTED_REFERENCE' }],
    derived_assets: [{
      ...asset(2, 1), asset_id: 'line_unconfirmed', capability: 'LINE_ART', revision: null,
    }, {
      ...asset(2, 0), asset_id: 'colored_stale', capability: 'COLORED_LINE_ART', revision: null,
    }, {
      ...asset(2, 1), asset_id: 'colored_confirmed', capability: 'COLORED_LINE_ART', revision: null,
    }],
  });
  assert(selectBeautyRenderSource(imported)?.asset_id === 'colored_confirmed',
    'beauty rendering should prefer exact-version confirmed colored line art');
  assert(selectBeautyRenderSource({
    ...imported,
    derived_assets: imported.derived_assets.filter(
      (item) => item.asset_id !== 'colored_confirmed',
    ),
  })?.asset_id === 'ast_1',
  'stale colored or unconfirmed line art must fall back to the confirmed imported reference');
  assert(selectBeautyRenderSource({
    ...imported,
    derived_assets: imported.derived_assets
      .filter((item) => item.asset_id === 'colored_confirmed')
      .map((item) => ({ ...item, root_id: 'foreign_project' })),
  })?.asset_id === 'ast_1',
  'foreign colored line art must never be selected over the in-project confirmed reference');
  const validBranchSource: AssetSummary = {
    ...asset(2, 1),
    asset_id: 'colored_valid_branch',
    parent_asset_id: 'ast_1',
    capability: 'COLORED_LINE_ART',
    revision: null,
  };
  const abandonedSibling: AssetSummary = {
    ...asset(2, 1),
    asset_id: 'colored_abandoned_sibling',
    parent_asset_id: 'ast_1',
    capability: 'COLORED_LINE_ART',
    revision: null,
  };
  const activeBranch: AssetSummary = {
    ...asset(3, 1),
    asset_id: 'active_branch_render',
    parent_asset_id: validBranchSource.asset_id,
    capability: 'SPEC_RENDER',
  };
  const branchedProject = project({
    active_asset_id: activeBranch.asset_id,
    active_revision: activeBranch,
    active_design_version: 1,
    assets: [asset(1), validBranchSource, abandonedSibling, activeBranch],
    derived_assets: [validBranchSource, abandonedSibling],
  });
  assert(selectBeautyRenderSource(branchedProject)?.asset_id === 'colored_valid_branch',
    'the newest sibling candidate must be skipped in favor of an older active-lineage source');
  assert(selectBeautyRenderSource({
    ...branchedProject,
    derived_assets: [abandonedSibling],
  }) === null,
  'an abandoned sibling cannot source a generated primary when no valid lineage candidate remains');
  assert(selectBeautyRenderSource(project()) === null,
    'a generated primary without exact confirmed colored line art is not an eligible drawing source');

  const rendering = trustedWorkflowReducer(loaded, {
    type: 'operation_started',
    operation: 'beauty_render',
  });
  assert(rendering.busy === 'beauty_render',
    'beauty-render progress should have a dedicated task state');
  assert(rendering.project?.active_asset_id === 'ast_1',
    'starting a beauty render must keep the confirmed reference on the canvas');
  const renderFailure = trustedWorkflowReducer(rendering, {
    type: 'operation_failed',
    operation: 'beauty_render',
    error: {
      code: 'IMAGE_PROVIDER_UNAVAILABLE',
      message: 'The render could not be completed.',
      category: 'provider',
      status: 503,
      retryable: true,
    },
  });
  assert(renderFailure.project?.active_asset_id === 'ast_1',
    'beauty-render failure must preserve the confirmed active revision');
  assert(renderFailure.error?.category === 'provider',
    'beauty-render failure should retain its actionable error category');
  const beautyWarning = trustedWorkflowReducer(loaded, {
    type: 'beauty_render_warning_received',
    warning: {
      ...warningCandidate,
      operation: 'SPEC_RENDER',
      asset_capability: 'SPEC_RENDER',
      requested_change: 'Create a beauty render from the confirmed reference.',
    },
  });
  assert(beautyWarning.project?.active_asset_id === 'ast_1',
    'beauty-render warning must not replace the confirmed reference');
  assert(beautyWarning.notice?.includes('confirmed reference remains') ?? false,
    'beauty-render warning should explain which revision remains authoritative');

  const productWarning = trustedWorkflowReducer(loaded, {
    type: 'product_photo_warning_received',
    warning: {
      ...warningCandidate,
      operation: 'VISUAL_ONLY_EDIT',
      requested_change: 'catalog white restage',
    },
  });
  assert(productWarning.project?.active_asset_id === 'ast_1',
    'product-photo WARN must keep the current project and canvas');
  assert(productWarning.warning_candidate?.operation === 'VISUAL_ONLY_EDIT',
    'product-photo WARN must enter explicit visual-only review');
  const lineConfirmation = trustedWorkflowReducer(loaded, {
    type: 'drawing_confirmation_received',
    candidate: {
      ...warningCandidate,
      qa: quality('pass'),
      operation: 'VISUAL_ONLY_EDIT',
      asset_capability: 'LINE_ART',
      requested_change: 'make line art',
    },
  });
  assert(lineConfirmation.project?.active_asset_id === 'ast_1',
    'line-art confirmation must not replace the active visual revision');
  assert(lineConfirmation.notice?.includes('Confirm the line geometry') ?? false,
    'line-art pass still requires explicit designer geometry confirmation');
  const acceptedProduct = trustedWorkflowReducer(productWarning, {
    type: 'project_loaded',
    project: project({
      active_asset_id: 'ast_2',
      active_revision: asset(2, 1),
      active_design_version: 1,
    }),
    source: 'refresh',
  });
  assert(acceptedProduct.warning_candidate === null,
    'loading a new active revision must close its temporary warning candidate');

  const confirmedState = interpretedState();
  assert(confirmedState.pending_markup?.confirmed !== null, 'one interpretation can be confirmed');
  assert(
    confirmedState.pending_markup?.confirmed?.impact === 'specification',
    'spec-impact confirmation must stay spec-impacting',
  );

  const stale = trustedWorkflowReducer(confirmedState, {
    type: 'operation_failed',
    operation: 'apply_markup',
    error: staleError,
  });
  assert(stale.project?.active_asset_id === 'ast_1', 'stale failure must preserve the current canvas');
  assert(stale.pending_markup?.interpretation.requested_change.includes('2.2') ?? false,
    'stale failure must preserve the interpretation');
  assert(stale.pending_markup?.confirmed === null,
    'stale failure must invalidate only the confirmation');
  assert(stale.pending_markup?.requires_reconfirmation === true,
    'stale failure must require reconfirmation');

  const refreshed = trustedWorkflowReducer(stale, {
    type: 'project_loaded',
    project: project({ active_design_version: 2 }),
    source: 'refresh',
  });
  assert(refreshed.pending_markup !== null, 'refresh must recover the pending interpretation');
  assert(refreshed.error?.category === 'stale_version',
    'silent stale recovery should preserve the actionable error');

  const warningResponse: MarkupApplyResponse = {
    revision: null,
    spec_version: null,
    spec_change: [],
    ignored_fields: [],
    qa: quality('warn'),
    routing: {
      attempt_count: 3,
      used_retry: true,
      used_fallback: true,
      cache_hit: false,
      run_id: 'run_warn',
    },
    image_run_id: 'run_warn',
    warning_candidate: warningCandidate,
  };
  const warned = trustedWorkflowReducer(confirmedState, {
    type: 'markup_applied',
    response: warningResponse,
  });
  assert(warned.warning_candidate?.run_id === 'run_warn', 'WARN should enter explicit review');
  assert(warned.project?.active_asset_id === 'ast_1', 'WARN must never become active automatically');
  assert(warned.project?.revisions.length === 1, 'WARN must not enter revision history');

  const passResponse: MarkupApplyResponse = {
    ...warningResponse,
    revision: revision(2),
    spec_version: 2,
    spec_change: revision(2).spec_change,
    qa: quality('pass'),
    warning_candidate: null,
  };
  const applied = trustedWorkflowReducer(confirmedState, {
    type: 'markup_applied',
    response: passResponse,
  });
  assert(applied.project?.active_asset_id === 'ast_2', 'PASS should advance the active revision');
  assert(applied.project?.active_design_version === 2, 'PASS should advance the linked spec');
  assert(applied.project?.approval === null, 'a new revision should structurally invalidate approval');
  assert(applied.pending_markup === null, 'accepted revision should close the one-item annotation');

  const factoryBlocked = trustedWorkflowReducer(loaded, {
    type: 'phase_selected',
    phase: 'factory',
  });
  assert(factoryBlocked.phase === 'factory',
    'Factory readiness must stay inspectable before approval and pinning');
  assert(factoryBlocked.project?.factory_ready === false,
    'Opening readiness must not unlock the factory pack');

  const creative = project({
    design_id: null,
    spec: null,
    active_design_version: null,
    approval: null,
  });
  const creativeState = trustedWorkflowReducer(initialTrustedWorkflowState, {
    type: 'project_loaded',
    project: creative,
    source: 'create',
  });
  assert(canSelectPhase(creativeState, 'refine'),
    'creative candidates must remain reviewable');
  assert(!canSelectPhase(creativeState, 'approve')
    && !canSelectPhase(creativeState, 'factory'),
  'pre-spec creative candidates must not enter approval or factory phases');
}

describe('trusted workflow reducer', () => {
  test('preserves revision, warning, stale, and factory invariants', () => {
    runTrustedWorkflowReducerTests();
  });
});
