/// <reference types="jest" />

import {
  createTrustedApiClient,
  decodeBeautyRenderResult,
  decodeDesignFamilyDetail,
  decodeDesignFamilyList,
  decodeFactoryPackManifest,
  decodeDrawingConfirmationResult,
  decodeImageRunSummary,
  decodeMarkupApplyResponse,
  decodeMarketingPackResult,
  decodePhotoDraftResult,
  decodePlateDraftResult,
  decodeProductPhotoResult,
  decodePreviewVariationResult,
  decodeProjectCreationResult,
  decodeProjectDetail,
  decodeSaveAsVariationResult,
  decodeStudioJobList,
  decodeStudioJobRecord,
  decodeStudioComponentTargeting,
  decodeStudioProjectHistory,
  decodeSourceCoverageResolutionResult,
} from './client';

function assert(condition: boolean, message: string): void {
  if (!condition) throw new Error(`Trusted client decoder: ${message}`);
}

export function runTrustedClientDecoderTests(): void {
  const project = decodeProjectDetail({
    id: 'ast_root',
    root_id: 'ast_root',
    title: 'Ring project',
    owner: 'usr_test',
    state: 'refining',
    design_id: 'dsn_test',
    latest_design_version: 1,
    active_asset_id: 'ast_root',
    active_design_version: 1,
    active_revision: {
      asset_id: 'ast_root',
      root_id: 'ast_root',
      capability: 'SPEC_RENDER',
      provenance: 'generated_spec_aligned',
      revision: 1,
      design_version: 1,
      image_url: '/assets/ast_root/image',
    },
    revisions: [{
      asset_id: 'ast_root',
      root_id: 'ast_root',
      capability: 'SPEC_RENDER',
      provenance: 'generated_spec_aligned',
      revision: 1,
      design_version: 1,
      image_url: '/assets/ast_root/image',
    }],
    creative_candidates: [{
      asset_id: 'ast_direction', root_id: 'ast_root', capability: 'CREATIVE_RENDER',
      provenance: 'pre_spec_creative_candidate', revision: null, design_version: null,
      image_url: '/assets/ast_direction/image',
    }],
    assets: [],
    derived_assets: [],
    factory_ready: false,
    factory_blockers: [{
      code: 'visual_reference_not_dimensioned',
      element_id: 'shoulder_form',
      role: 'shoulder',
      label: 'Shoulder form',
      detail: 'The contour is confirmed only by a visual reference.',
      required_resolution: 'Confirm a dimensioned profile or CAD definition.',
    }, {
      code: 'source_component_unresolved',
      subject_kind: 'source_component',
      subject_id: 'stone.assembly_hint.shoulder',
      component_id: 'stone.assembly_hint.shoulder',
      role: 'source_component',
      label: 'Shoulder stones',
      detail: 'The visible shoulder stones were not mapped.',
      required_resolution: 'Map or explicitly resolve the source component.',
    }, {
      code: 'factory_category_not_released',
      subject_kind: 'category',
      subject_id: 'necklace',
      role: 'factory_release_scope',
      label: 'Necklace Factory review',
      detail: 'Factory review is currently released for rings only.',
      required_resolution: 'Keep the design in Studio.',
    }],
  });
  assert(project !== null, 'canonical ProjectDetail should decode');
  assert(project?.revisions[0]?.asset.provenance === 'generated_spec_aligned',
    'primary revision provenance should survive normalization');
  assert(project?.active_design_version === 1, 'latest spec version alias should decode');
  assert(project?.factory_blockers[0]?.element_id === 'shoulder_form',
    'factory-readiness blockers should survive project normalization');
  assert(project?.factory_blockers[1]?.component_id === 'stone.assembly_hint.shoulder',
    'source-component blockers should survive project normalization');
  assert(project?.factory_blockers[2]?.subject_kind === 'category'
    && project.factory_blockers[2]?.subject_id === 'necklace',
  'category-release blockers should survive project normalization');
  assert(project?.creative_candidates?.[0]?.asset_id === 'ast_direction'
    && project.creative_candidates[0]?.revision === null,
  'pre-spec directions should decode separately from canonical revisions');

  const variation = decodeSaveAsVariationResult({
    status: 'variation_created',
    family_id: 'fam_ring',
    variation_index: 2,
    source_project_id: 'ast_root',
    source_asset_id: 'ast_root',
    project: {
      id: 'ast_variation_2', root_id: 'ast_variation_2', title: 'Rose gold direction',
      owner: 'usr_test', state: 'refining', design_id: 'dsn_test',
      active_asset_id: 'ast_variation_2', active_design_version: 1,
      active_revision: {
        asset_id: 'ast_variation_2', root_id: 'ast_variation_2',
        capability: 'SPEC_RENDER', provenance: 'studio_variation_branch',
        revision: 1, design_version: 1, image_url: '/assets/ast_variation_2/image',
      },
      revisions: [], assets: [], derived_assets: [], factory_ready: false,
      factory_blockers: [], primary_revision_count: 1, has_factory_drawing: false,
    },
  });
  assert(variation?.project.root_id === 'ast_variation_2'
    && variation.source_asset_id === 'ast_root',
  'save-as-variation responses must decode their sibling project and source provenance');

  const reviewedVariation = decodePreviewVariationResult({
    status: 'saved_as_variation',
    family_id: 'fam_ring',
    variation_index: 3,
    source_project_id: 'ast_root',
    source_asset_id: 'ast_root',
    design_id: 'dsn_preview',
    design_version: 1,
    project: variation?.project,
  });
  assert(reviewedVariation?.source_asset_id === 'ast_root',
    'reviewed preview variations must preserve exact source provenance');
  assert(decodePreviewVariationResult({
    status: 'saved_as_variation',
    family_id: 'fam_ring',
    variation_index: 3,
    project: variation?.project,
  }) === null, 'reviewed preview variation provenance must fail closed when absent');

  const creationWarning = decodeProjectCreationResult({
    status: 'review_required',
    project: null,
    image_run_id: 'run_concept_warning',
    quality_report: { verdict: 'warn', stage: 'concept' },
    warning_candidate: {
      run_id: 'run_concept_warning',
      candidate_id: 'cand_concept',
      preview_url: '/projects/from-brief/candidates/cand_concept/image',
      qa: { verdict: 'warn', checks: [] },
      operation: 'CONCEPT_GENERATE',
      requested_change: 'oval sapphire solitaire',
    },
  });
  assert(
    creationWarning !== null && 'warning_candidate' in creationWarning,
    'project creation warnings should remain reviewable without a partial project',
  );

  const edit = decodeMarkupApplyResponse({
    final_asset_id: 'ast_2',
    root_id: 'ast_root',
    design_id: 'dsn_test',
    design_version: 2,
    steps: [{
      asset_id: 'ast_2',
      version: 2,
      design_version: 2,
      spec_change: [{ path: 'band.width_mm', before: 1.8, after: 2.2 }],
      ignored_fields: ['lighting'],
      qa_report: {
        verdict: 'pass',
        score: 96,
        checks: [{ code: 'change_applied', passed: true, severity: 'hard', message: 'Applied' }],
      },
      model_routing: { attempts: 2, fallback_used: false },
    }],
  });
  assert(edit?.revision?.asset.asset_id === 'ast_2', 'legacy step response should become a revision');
  assert(edit?.revision?.revision === 2, 'visual revision should decode from version');
  assert(edit?.spec_version === 2, 'linked design version should decode');
  assert(edit?.spec_change[0]?.path === 'band.width_mm', 'structural diff should decode');
  assert(edit?.routing.attempt_count === 2, 'routing aliases should decode');

  const run = decodeImageRunSummary({
    run_id: 'run_1',
    project_id: 'ast_root',
    operation: 'LOCAL_EDIT',
    normalized_intent: { instruction: 'widen band', region: 'lower band' },
    prompt_version: 'local-edit.v1',
    source_hash: 'source',
    spec_visual_hash: 'spec',
    variant: 0,
    status: 'accepted',
    accepted_asset_id: 'ast_2',
    attempts: [{
      attempt_number: 1,
      provider: 'hidden-in-ui',
      model: 'hidden-in-ui',
      latency_ms: 100,
      cached: false,
      qa_verdict: 'pass',
      qa_checks: [],
      corrective_instruction: null,
      fallback_reason: null,
      output_hash: 'output',
      error_category: null,
    }],
  });
  assert(run?.normalized_intent === 'widen band', 'normalized intent object should get a safe label');
  assert(run?.prompt_contract_version === 'local-edit.v1', 'prompt_version alias should decode');
  assert(run?.accepted === true, 'accepted asset should mark the run accepted');

  const pack = decodeFactoryPackManifest({
    schema_version: '1',
    project_id: 'ast_root',
    design_id: 'dsn_test',
    design_version: 2,
    asset_id: 'ast_2',
    visual_revision: 2,
    approver: 'usr_test',
    approved_at: '2026-07-10T00:00:00Z',
    pinned_at: '2026-07-10T00:00:00Z',
    checklist: { id: 'chk_1', mode: 'auto_pin', status: {}, results: [] },
    qa_summary: {},
    dimensions: {
      has_estimates: true,
      estimated_fields: [{
        field_path: 'band.width_mm', value: 2, unit: 'mm',
        status: 'estimated_from_reference', method: 'reference_vision',
        source: 'uploaded reference', confidence: 0.4, note: null,
      }],
      disclaimer: 'ESTIMATED values are not measurements.',
    },
    factory_sheet_fact_plan: {
      schema_version: 'facetta.factory-sheet-plan.v1',
      jewelry_type: 'ring', template: 'solitaire_prong',
      materials: [{
        section: 'metal', material: 'gold', karat: 18, color: 'yellow',
        finish: 'high_polish', fact_status: 'designer_confirmed',
      }],
      stones: [{
        ref: 'A', section: 'stone', role: 'center', species: 'diamond',
        cut: 'round_brilliant', visible_color: 'D', count: 1,
        carat_each: 1, carat_total: 1, fact_status: 'designer_confirmed',
        dimension_paths: ['stone.dimensions_mm.length'],
      }],
      settings: [],
      recorded_facts: [{
        field_path: 'band.profile', section: 'band', label: 'Band profile',
        value: 'half round', fact_status: 'designer_confirmed',
      }],
      dimensions: [{
        field_path: 'band.width_mm', section: 'band', value: 2, unit: 'mm',
        status: 'estimated_from_reference', method: 'reference_vision',
        source: 'uploaded reference', confidence: 0.4, note: null,
      }],
      confirmed_fact_count: 2, estimated_fact_count: 1,
      pending_confirmation_count: 0, has_estimates: true,
      estimate_disclaimer: 'ESTIMATED values are not measurements.',
    },
    authority: { factory_truth: [], visual_reference_only: [], note: '' },
    files: [
      { name: 'validated-spec.json', sha256: 'abc', bytes: 10, authoritative: true },
      { name: 'facetta-sheet.svg', sha256: 'def', bytes: 20, authoritative: true },
    ],
  });
  assert(pack?.pinned_asset_id === 'ast_2', 'asset_id should normalize to pinned asset');
  assert(pack?.checklist_id === 'chk_1', 'nested checklist id should normalize');
  assert(pack?.artifacts[1]?.media_type === 'image/svg+xml', 'file media type should be inferred');
  assert(pack?.dimensions.estimated_fields[0]?.field_path === 'band.width_mm',
    'factory estimate provenance should decode');
  assert(pack?.factory_sheet_fact_plan.estimated_fact_count === 1,
    'factory fact-plan status counts should decode');
  assert(pack?.factory_sheet_fact_plan.recorded_facts[0]?.value === 'half round',
    'non-dimensional factory facts should decode');

  const productPhoto = decodeProductPhotoResult({
    status: 'review_required',
    project_id: 'ast_root',
    image_run_id: 'run_product',
    quality_report: { verdict: 'warn', checks: [] },
    routing: { attempt_count: 2, used_retry: true, used_fallback: false },
    presentation: {
      preset: 'catalog_white',
      framing: 'portrait',
      source_asset_id: 'ast_root',
      design_version: 1,
    },
    warning_candidate: {
      run_id: 'run_product',
      candidate_id: 'cand_product',
      preview_url: '/image-runs/run_product/candidates/cand_product/image',
      qa: { verdict: 'warn', checks: [] },
      operation: 'VISUAL_ONLY_EDIT',
      requested_change: 'clean catalog presentation',
    },
  });
  assert(productPhoto?.status === 'review_required',
    'product-photo warning must remain a temporary review candidate');
  assert(productPhoto?.presentation.design_version === 1,
    'visual-only presentation must inherit the exact spec version');

  const plateDraft = decodePlateDraftResult({
    spec: {
      jewelry_type: 'ring',
      template: 'leaf_shoulder_prong',
      stone: { cut: 'emerald', species: 'emerald' },
      side_stones: [{ cut: 'marquise' }],
      source_component_coverage: {
        source_kind: 'designer_plate',
        components: [{
          component_id: 'stone.center',
          source_view: 'plate_composite',
          source_description: 'Emerald-cut green center stone.',
          source_confidence: 0.94,
          canonical_spec_paths: ['stone'],
          unresolved_reason: null,
          independent_audit: {
            kind: 'independent_component_audit',
            verdict: 'pass',
            auditor: 'skeptical-source-component-audit.v2',
            source_view: 'plate_composite',
            observed_description: 'The visible center stone is represented by the stone record.',
            evidence_sha256: 'a'.repeat(64),
          },
        }, {
          component_id: 'assembly.shoulder',
          source_view: 'detail',
          source_description: 'Mirrored sculpted shoulder leaves.',
          source_confidence: 0.76,
          canonical_spec_paths: [],
          unresolved_reason: 'No existing form path captures the shoulder contour.',
          independent_audit: null,
        }],
      },
    },
    read: { assembly: 'emerald center with leaf shoulders', hand_written: ['2 mm'] },
    uncertainties: ['ring size requires confirmation'],
    provenance: 'grok_vision_hand_plate_draft',
    requires_designer_confirmation: true,
    source_coverage_audit: { status: 'review_required', blocker_count: 2 },
  });
  assert(plateDraft?.uncertainties.length === 1,
    'hand-plate uncertainties must stay visible before project creation');
  assert(Array.isArray(plateDraft?.spec.side_stones),
    'hand-plate stone groups must survive client normalization');
  assert(plateDraft?.source_coverage_audit.blocker_count === 2,
    'independent source-coverage blockers must remain visible');
  assert(plateDraft?.source_coverage.components[1]?.component_id === 'assembly.shoulder',
    'stable source components must be exposed for designer correction');
  assert(plateDraft?.source_coverage.valid_spec_paths.includes('side_stones[0]') ?? false,
    'the plate client should offer only mapping targets present in the draft');

  const photoDraft = decodePhotoDraftResult({
    jewelry_type: 'ring',
    template: 'solitaire_prong',
    stone: { cut: 'oval', species: 'sapphire' },
    source_component_coverage: {
      source_kind: 'imported_reference',
      components: [{
        component_id: 'stone.center',
        source_view: 'three_quarter',
        source_description: 'Oval blue center stone.',
        source_confidence: 0.9,
        canonical_spec_paths: ['stone'],
        unresolved_reason: null,
        independent_audit: {
          kind: 'independent_component_audit',
          verdict: 'pass',
          auditor: 'skeptical-source-component-audit.v2',
          source_view: 'three_quarter',
          observed_description: 'The visible center stone is represented by the stone record.',
          evidence_sha256: 'b'.repeat(64),
        },
      }],
    },
  });
  assert(photoDraft?.source_coverage.source_kind === 'imported_reference',
    'finished-photo drafts must expose the same structured component accounting');
  assert(photoDraft?.source_coverage.audit.status === 'pass',
    'a finished-photo draft with independently passed components can clear its source gate');

  const resolvedCoverage = decodeSourceCoverageResolutionResult({
    spec: plateDraft?.spec,
    source_kind: 'designer_plate',
    components: [plateDraft?.source_coverage.components[0]],
    valid_spec_paths: ['jewelry_type', 'template', 'stone', 'stone.cut'],
    changed_component_ids: ['stone.center'],
    invalidated_audit_component_ids: ['stone.center'],
    blockers: [],
    factory_ready: true,
    legacy_provenance: false,
    resolved_by: 'usr_designer',
    audit: {
      requested: true,
      status: 'pass',
      audited_component_ids: ['stone.center'],
      blocker_count: 0,
    },
  });
  assert(resolvedCoverage?.audit.status === 'pass',
    'resolved source coverage must retain its explicit independent-audit state');
  assert(resolvedCoverage?.invalidated_audit_component_ids[0] === 'stone.center',
    'changed mappings must expose which prior audit evidence was invalidated');

  const stalePathCoverage = decodeSourceCoverageResolutionResult({
    spec: plateDraft?.spec,
    source_kind: 'designer_plate',
    components: [plateDraft?.source_coverage.components[0]],
    valid_spec_paths: ['jewelry_type', 'template', 'stone'],
    changed_component_ids: [],
    invalidated_audit_component_ids: [],
    blockers: [{
      code: 'source_component_path_missing',
      component_id: 'stone.center',
      message: 'stone.center maps to stone.cut, which is absent from this draft.',
      required_resolution: 'Map it to a path present in the current specification.',
    }],
    factory_ready: false,
    legacy_provenance: false,
    resolved_by: 'usr_designer',
    audit: {
      requested: true,
      status: 'invalid',
      audited_component_ids: [],
      blocker_count: 1,
    },
  });
  assert(stalePathCoverage?.blockers[0]?.code === 'source_component_path_missing',
    'stale canonical paths must remain typed creation/factory blockers');
  assert(stalePathCoverage?.factory_ready === false,
    'a stale mapping cannot pass source readiness');

  const lineArt = decodeDrawingConfirmationResult({
    status: 'confirmation_required',
    project_id: 'ast_root',
    image_run_id: 'run_line',
    quality_report: { verdict: 'pass', checks: [] },
    routing: { attempt_count: 1 },
    view: 'three_quarter',
    next: 'confirm geometry',
    candidate: {
      run_id: 'run_line',
      candidate_id: 'cand_line',
      preview_url: '/image-runs/run_line/candidates/cand_line/image',
      qa: { verdict: 'pass', checks: [] },
      operation: 'VISUAL_ONLY_EDIT',
      asset_capability: 'LINE_ART',
      requested_change: 'make line art',
    },
  });
  assert(lineArt?.candidate.asset_capability === 'LINE_ART',
    'QA-pass line art must still decode as an explicit geometry confirmation');

  const beautyRender = decodeBeautyRenderResult({
    status: 'review_required',
    project_id: 'project_imported',
    source_asset_id: 'asset_colored_line_art',
    image_run_id: 'run_beauty',
    routing: { attempt_count: 2, used_retry: true, used_fallback: false },
    quality_report: {
      verdict: 'warn',
      summary: 'Check the shoulder silhouette.',
      checks: [],
    },
    candidate: {
      media_type: 'image/png',
      image_b64: 'cG5nLWJ5dGVz',
    },
  });
  assert(beautyRender?.status === 'review_required',
    'beauty-render warning must remain temporary');
  assert(beautyRender?.status === 'review_required'
    && beautyRender.warning_candidate.preview_url === 'data:image/png;base64,cG5nLWJ5dGVz',
  'beauty-render candidate bytes should become a local review preview');
  assert(beautyRender?.status === 'review_required'
    && beautyRender.warning_candidate.candidate_id === null,
  'unbound beauty-render warnings must not become promotable revisions');

  const storedBeautyWarning = decodeBeautyRenderResult({
    status: 'review_required',
    project_id: 'project_imported',
    source_asset_id: 'asset_colored_line_art',
    image_run_id: 'run_beauty_stored',
    routing: { attempt_count: 1, used_retry: false, used_fallback: false },
    quality_report: { verdict: 'warn', checks: [] },
    warning_candidate: {
      run_id: 'run_beauty_stored',
      candidate_id: 'candidate_beauty',
      preview_url: '/image-runs/run_beauty_stored/candidates/candidate_beauty/image',
      qa: { verdict: 'warn', checks: [] },
      operation: 'SPEC_RENDER',
      requested_change: 'Render from confirmed colored line art.',
      asset_capability: 'SPEC_RENDER',
    },
  });
  assert(storedBeautyWarning?.status === 'review_required'
    && storedBeautyWarning.warning_candidate.candidate_id === 'candidate_beauty',
  'stored beauty warnings must remain explicitly promotable after designer review');
}

describe('trusted API decoders', () => {
  test('normalize canonical and compatibility payloads', () => {
    runTrustedClientDecoderTests();
  });

  test('posts neutral drawing variations and explicit candidate promotion', async () => {
    const fetcher = jest.fn(async (
      _input: RequestInfo | URL,
      _init?: RequestInit,
    ) => ({
      ok: true,
      status: 201,
      text: async () => JSON.stringify({
        id: 'ast_root', root_id: 'ast_root', title: 'Concept', owner: 'usr_designer',
        state: 'refining', active_asset_id: 'ast_candidate',
        active_design_version: null, revisions: [], assets: [], derived_assets: [],
        factory_ready: false, factory_blockers: [], primary_revision_count: 1,
        has_factory_drawing: false,
      }),
    } as unknown as Response));
    const api = createTrustedApiClient({ baseUrl: 'https://facetta.test', fetcher });

    await api.createProjectFromDrawing({
      image_base64: 'c291cmNl',
      source_kind: 'photograph',
      media_type: 'image/png',
      instruction: 'Preserve every visible element and render in platinum.',
      variation_count: 3,
      starting_variant: 10,
      studio_job_id: 'studio job drawing',
      owner: 'usr_designer',
      title: 'Concept',
      source_region_description: 'Front necklace elevation',
      source_region: { x: 0.2, y: 0.1, width: 0.6, height: 0.5 },
      references: [{
        role: 'material_style',
        image_base64: 'bWF0ZXJpYWw=',
        media_type: 'image/jpeg',
      }],
    });
    await api.promoteCreativeCandidate('project one', 'candidate one', {
      created_by: 'usr_designer',
      confirmation_token: 'confirmation-token-1234567890123456',
    });

    expect(fetcher).toHaveBeenCalledTimes(2);
    expect(fetcher.mock.calls[0]?.[0]).toBe(
      'https://facetta.test/projects/from-drawing');
    expect(JSON.parse(String(fetcher.mock.calls[0]?.[1]?.body))).toMatchObject({
      source_kind: 'photograph',
      variation_count: 3,
      starting_variant: 10,
      studio_job_id: 'studio job drawing',
      instruction: 'Preserve every visible element and render in platinum.',
      source_region_description: 'Front necklace elevation',
      source_region: { x: 0.2, y: 0.1, width: 0.6, height: 0.5 },
      references: [{
        role: 'material_style',
        image_base64: 'bWF0ZXJpYWw=',
        media_type: 'image/jpeg',
      }],
    });
    expect(fetcher.mock.calls[1]?.[0]).toBe(
      'https://facetta.test/projects/project%20one/creative-candidates/candidate%20one/promote');
    expect(JSON.parse(String(fetcher.mock.calls[1]?.[1]?.body))).toEqual({
      created_by: 'usr_designer',
      confirmation_token: 'confirmation-token-1234567890123456',
    });
  });

  test('posts confirmed exact references only to the canonical Studio import route', async () => {
    const fetcher = jest.fn(async (
      _input: RequestInfo | URL,
      _init?: RequestInit,
    ) => ({
      ok: true,
      status: 201,
      text: async () => JSON.stringify({
        id: 'ast_import', root_id: 'ast_import', title: 'Confirmed ring',
        owner: 'usr_designer', state: 'refining', active_asset_id: 'ast_import',
        active_design_version: 1, revisions: [], assets: [], derived_assets: [],
        factory_ready: false, factory_blockers: [], primary_revision_count: 1,
        has_factory_drawing: false,
      }),
    } as unknown as Response));
    const api = createTrustedApiClient({ baseUrl: 'https://facetta.test', fetcher });

    await api.createProjectFromImage({
      image_base64: 'c291cmNl',
      media_type: 'image/png',
      confirmed_spec: {},
      owner: 'usr_designer',
      title: 'Confirmed ring',
      collection: 'Exact references',
      tags: ['confirmed'],
    });

    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(fetcher.mock.calls[0]?.[0]).toBe(
      'https://facetta.test/studio/projects/import-confirmed',
    );
    expect(JSON.parse(String(fetcher.mock.calls[0]?.[1]?.body))).toMatchObject({
      image_base64: 'c291cmNl',
      media_type: 'image/png',
      owner: 'usr_designer',
      title: 'Confirmed ring',
      collection: 'Exact references',
      tags: ['confirmed'],
    });
  });

  test('posts a category-neutral multi-candidate prompt project', async () => {
    const fetcher = jest.fn(async (
      _input: RequestInfo | URL,
      _init?: RequestInit,
    ) => ({
      ok: true,
      status: 201,
      text: async () => JSON.stringify({
        id: 'ast_prompt', root_id: 'ast_prompt', title: 'Lariat', owner: 'usr_designer',
        state: 'refining', active_asset_id: 'ast_prompt',
        active_design_version: null, revisions: [], assets: [], derived_assets: [],
        factory_ready: false, factory_blockers: [], primary_revision_count: 3,
        has_factory_drawing: false,
      }),
    } as unknown as Response));
    const api = createTrustedApiClient({ baseUrl: 'https://facetta.test', fetcher });

    await api.createProjectFromPrompt({
      prompt: 'A platinum floral lariat necklace with emerald leaves.',
      variation_count: 3,
      starting_variant: 8,
      studio_job_id: 'studio job prompt',
      owner: 'usr_designer',
      title: 'Lariat',
      collection: 'Exploration',
      references: [{
        role: 'material_style',
        image_base64: 'cmVmZXJlbmNl',
        media_type: 'image/jpeg',
      }],
    });
    await api.selectCreativeCandidate('ast prompt', 'candidate two', 'usr_designer');
    await api.selectCreativeCandidate(
      'ast prompt', 'candidate three', 'usr_designer', 'studio job create',
    );

    expect(fetcher).toHaveBeenCalledTimes(3);
    expect(fetcher.mock.calls[0]?.[0]).toBe(
      'https://facetta.test/projects/from-prompt');
    expect(JSON.parse(String(fetcher.mock.calls[0]?.[1]?.body))).toEqual({
      prompt: 'A platinum floral lariat necklace with emerald leaves.',
      variation_count: 3,
      starting_variant: 8,
      studio_job_id: 'studio job prompt',
      owner: 'usr_designer',
      title: 'Lariat',
      collection: 'Exploration',
      references: [{
        role: 'material_style',
        image_base64: 'cmVmZXJlbmNl',
        media_type: 'image/jpeg',
      }],
    });
    expect(fetcher.mock.calls[1]?.[0]).toBe(
      'https://facetta.test/projects/ast%20prompt/creative-candidates/candidate%20two/select');
    expect(JSON.parse(String(fetcher.mock.calls[1]?.[1]?.body))).toEqual({
      created_by: 'usr_designer',
    });
    expect(fetcher.mock.calls[2]?.[0]).toBe(
      'https://facetta.test/projects/ast%20prompt/creative-candidates/candidate%20three/select');
    expect(JSON.parse(String(fetcher.mock.calls[2]?.[1]?.body))).toEqual({
      created_by: 'usr_designer',
      studio_job_id: 'studio job create',
    });
  });

  test('commits the selected Original and retained Create directions in one request', async () => {
    const responseProject = {
      id: 'project original', root_id: 'project original', title: 'Lariat',
      owner: 'usr_designer', state: 'refining', design_id: null,
      selected_candidate_asset_id: 'candidate primary',
      active_asset_id: 'candidate primary', active_design_version: null,
      revisions: [], creative_candidates: [], assets: [], derived_assets: [],
      factory_ready: false, factory_blockers: [], primary_revision_count: 1,
      has_factory_drawing: false,
    };
    const fetcher = jest.fn(async (
      _input: RequestInfo | URL,
      _init?: RequestInit,
    ) => ({
      ok: true,
      status: 200,
      text: async () => JSON.stringify({
        project: responseProject,
        retained_variations: [{
          status: 'variation_created', family_id: 'fam_create', variation_index: 2,
          source_project_id: 'project original', source_asset_id: 'candidate kept',
          project: {
            ...responseProject,
            id: 'variation kept', root_id: 'variation kept', title: 'Direction 2',
            selected_candidate_asset_id: null, active_asset_id: 'variation kept',
            active_revision: {
              asset_id: 'variation kept', root_id: 'variation kept',
              capability: 'VARIATION_BRANCH', provenance: 'studio_variation_branch',
              revision: 1, design_version: null,
              image_url: '/assets/variation kept/image',
            },
          },
        }],
      }),
    } as unknown as Response));
    const api = createTrustedApiClient({ baseUrl: 'https://facetta.test', fetcher });

    const result = await api.commitCreativeDirections('project original', {
      created_by: 'usr_designer',
      selected_candidate_id: 'candidate primary',
      retained: [{ candidate_id: 'candidate kept', label: 'Direction 2' }],
      studio_job_id: 'studio job create',
    });

    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(fetcher.mock.calls[0]?.[0]).toBe(
      'https://facetta.test/projects/project%20original/creative-directions/commit',
    );
    expect(JSON.parse(String(fetcher.mock.calls[0]?.[1]?.body))).toEqual({
      created_by: 'usr_designer',
      selected_candidate_id: 'candidate primary',
      retained: [{ candidate_id: 'candidate kept', label: 'Direction 2' }],
      studio_job_id: 'studio job create',
    });
    expect(result.data?.project.selected_candidate_asset_id).toBe('candidate primary');
    expect(result.data?.retained_variations[0]?.source_asset_id).toBe('candidate kept');
    expect(result.data?.retained_variations[0]?.project.active_revision?.image_url).toBe(
      'https://facetta.test/assets/variation kept/image',
    );
  });

  test('saves an exact active revision as a sibling variation and resolves its project URLs', async () => {
    const fetcher = jest.fn(async (
      _input: RequestInfo | URL,
      _init?: RequestInit,
    ) => ({
      ok: true,
      status: 201,
      text: async () => JSON.stringify({
        status: 'variation_created',
        family_id: 'fam_ring',
        variation_index: 2,
        source_project_id: 'ast root',
        source_asset_id: 'ast source',
        project: {
          id: 'ast variation', root_id: 'ast variation', title: 'Rose gold direction',
          owner: 'usr_designer', state: 'refining', design_id: 'dsn_ring',
          active_asset_id: 'ast variation', active_design_version: 4,
          active_revision: {
            asset_id: 'ast variation', root_id: 'ast variation',
            capability: 'SPEC_RENDER', provenance: 'studio_variation_branch',
            revision: 1, design_version: 4, image_url: '/assets/ast variation/image',
          },
          revisions: [], assets: [], derived_assets: [], factory_ready: false,
          factory_blockers: [], primary_revision_count: 1, has_factory_drawing: false,
        },
      }),
    } as unknown as Response));
    const api = createTrustedApiClient({ baseUrl: 'https://facetta.test/', fetcher });

    const result = await api.saveAsVariation('ast root', {
      created_by: 'usr_designer',
      expected_active_asset_id: 'ast source',
      expected_design_version: 4,
      label: 'Rose gold direction',
    });

    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(fetcher.mock.calls[0]?.[0]).toBe(
      'https://facetta.test/studio/projects/ast%20root/variations');
    expect(JSON.parse(String(fetcher.mock.calls[0]?.[1]?.body))).toEqual({
      created_by: 'usr_designer',
      expected_active_asset_id: 'ast source',
      expected_design_version: 4,
      label: 'Rose gold direction',
    });
    expect(result).toMatchObject({
      data: {
        status: 'variation_created',
        family_id: 'fam_ring',
        variation_index: 2,
        source_project_id: 'ast root',
        source_asset_id: 'ast source',
        project: {
          root_id: 'ast variation',
          active_revision: {
            image_url: 'https://facetta.test/assets/ast variation/image',
          },
        },
      },
      error: null,
      status: 201,
    });
  });

  test('keeps an unselected Create candidate through the dedicated variation route', async () => {
    const fetcher = jest.fn(async (
      _input: RequestInfo | URL,
      _init?: RequestInit,
    ) => ({
      ok: true,
      status: 201,
      text: async () => JSON.stringify({
        status: 'variation_created', family_id: 'fam_create', variation_index: 2,
        source_project_id: 'project original', source_asset_id: 'candidate kept',
        project: {
          id: 'variation kept', root_id: 'variation kept', title: 'Direction 2',
          owner: 'usr_designer', state: 'refining', design_id: null,
          active_asset_id: 'variation kept', active_design_version: null,
          active_revision: {
            asset_id: 'variation kept', root_id: 'variation kept',
            capability: 'VARIATION_BRANCH', provenance: 'studio_variation_branch',
            revision: 1, design_version: null,
            image_url: '/assets/variation kept/image',
          },
          revisions: [], creative_candidates: [], assets: [], derived_assets: [],
          factory_ready: false, factory_blockers: [], primary_revision_count: 1,
          has_factory_drawing: false,
        },
      }),
    } as unknown as Response));
    const api = createTrustedApiClient({ baseUrl: 'https://facetta.test', fetcher });

    const result = await api.saveCreativeCandidateAsVariation(
      'project original', 'candidate kept', {
        created_by: 'usr_designer', expected_active_asset_id: 'candidate original',
        expected_design_version: null, label: 'Direction 2',
      },
    );

    expect(fetcher.mock.calls[0]?.[0]).toBe(
      'https://facetta.test/studio/projects/project%20original/creative-candidates/candidate%20kept/variations',
    );
    expect(JSON.parse(String(fetcher.mock.calls[0]?.[1]?.body))).toEqual({
      created_by: 'usr_designer', expected_active_asset_id: 'candidate original',
      expected_design_version: null, label: 'Direction 2',
    });
    expect(result.data?.source_asset_id).toBe('candidate kept');
    expect(result.data?.project.active_revision?.image_url).toBe(
      'https://facetta.test/assets/variation kept/image',
    );
  });

  test('preserves structured stale-version errors when variation branching is rejected', async () => {
    const fetcher = jest.fn(async (
      _input: RequestInfo | URL,
      _init?: RequestInit,
    ) => ({
      ok: false,
      status: 409,
      text: async () => JSON.stringify({
        code: 'stale_active_asset',
        category: 'stale_version',
        detail: 'The active revision changed before this variation could be saved.',
      }),
    } as unknown as Response));
    const api = createTrustedApiClient({ baseUrl: 'https://facetta.test', fetcher });

    const result = await api.saveAsVariation('ast_root', {
      created_by: 'usr_designer',
      expected_active_asset_id: 'ast_old',
      label: 'Do not overwrite newer work',
    });

    expect(result).toEqual({
      data: null,
      error: expect.objectContaining({
        code: 'stale_active_asset',
        category: 'stale_version',
        status: 409,
        retryable: false,
      }),
      status: 409,
    });
  });

  test('loads a design family without losing variation branch provenance', async () => {
    const payload = {
      family_id: 'fam ring',
      owner: 'usr_designer',
      title: 'Sapphire ring directions',
      created_at: '2026-07-12T01:00:00Z',
      updated_at: '2026-07-12T02:00:00Z',
      variations: [{
        root_id: 'ast variation',
        title: 'Rose gold direction',
        collection: 'Client A',
        tags: ['sapphire', 'halo'],
        owner: 'usr_designer',
        counts: { SPEC_RENDER: 2, PRODUCT_PHOTO: 1 },
        item_count: 3,
        primary_revision_count: 2,
        has_factory_drawing: false,
        cover_asset_id: 'ast current',
        created_at: '2026-07-12T01:30:00Z',
        updated_at: '2026-07-12T02:00:00Z',
        variation_index: 2,
        variation_label: 'Rose gold direction',
        branched_from_project_root_id: 'ast source project',
        branched_from_asset_id: 'ast source revision',
      }],
    };
    expect(decodeDesignFamilyDetail(payload)?.variations[0]).toMatchObject({
      variation_index: 2,
      branched_from_project_root_id: 'ast source project',
      branched_from_asset_id: 'ast source revision',
      counts: { SPEC_RENDER: 2, PRODUCT_PHOTO: 1 },
    });
    const fetcher = jest.fn(async (
      _input: RequestInfo | URL,
      _init?: RequestInit,
    ) => ({
      ok: true,
      status: 200,
      text: async () => JSON.stringify(payload),
    } as unknown as Response));
    const api = createTrustedApiClient({ baseUrl: 'https://facetta.test', fetcher });

    const result = await api.getDesignFamily('fam ring');

    expect(fetcher.mock.calls[0]?.[0]).toBe('https://facetta.test/studio/families/fam%20ring');
    expect(result.data?.variations[0]?.variation_label).toBe('Rose gold direction');
  });

  test('lists owner families as nested variation groups', async () => {
    const payload = {
      families: [{
        family_id: 'fam ring',
        owner: 'usr_designer',
        title: 'Sapphire ring directions',
        created_at: '2026-07-12T01:00:00Z',
        updated_at: '2026-07-12T02:00:00Z',
        variations: [{
          root_id: 'ast variation',
          title: 'Rose gold direction',
          collection: 'Client A',
          tags: ['sapphire'],
          owner: 'usr_designer',
          counts: { SPEC_RENDER: 1 },
          item_count: 1,
          primary_revision_count: 1,
          has_factory_drawing: false,
          cover_asset_id: 'ast current',
          created_at: '2026-07-12T01:30:00Z',
          updated_at: '2026-07-12T02:00:00Z',
          variation_index: 1,
          variation_label: 'Original',
          branched_from_project_root_id: null,
          branched_from_asset_id: null,
        }],
      }],
    };
    expect(decodeDesignFamilyList(payload)?.families[0]?.family_id).toBe('fam ring');
    const fetcher = jest.fn<Promise<Response>, [RequestInfo | URL, RequestInit?]>(async () => ({
      ok: true,
      status: 200,
      text: async () => JSON.stringify(payload),
    } as unknown as Response));
    const api = createTrustedApiClient({ baseUrl: 'https://facetta.test', fetcher });

    const result = await api.listDesignFamilies('usr_designer');

    expect(fetcher.mock.calls[0]?.[0]).toBe(
      'https://facetta.test/studio/families?owner=usr_designer',
    );
    expect(result.data?.families[0]?.variations[0]?.variation_label).toBe('Original');
  });

  test('loads immutable Studio history with raw intent, interpretation, and restore evidence', async () => {
    const payload = {
      project_id: 'ast project',
      family_id: 'fam_ring',
      variation_index: 1,
      variation_label: 'Original direction',
      active_asset_id: 'ast_3',
      revisions: [{
        revision: 3,
        asset_id: 'ast_3',
        parent_asset_id: 'ast_2',
        design_version: 3,
        capability: 'RESTORED_REVISION',
        image_url: '/assets/ast_3/image',
        pinned: false,
        action: 'restore',
        raw_intent: { kind: 'restore_revision', selected_asset_id: 'ast_1' },
        interpretation: {
          operation: 'append_historical_copy',
          history_deleted: false,
          visual_bytes_restored_exactly: true,
        },
        change_summary: 'Restored the original sapphire direction.',
        restored_from_asset_id: 'ast_1',
        created_by: 'usr_designer',
        created_at: '2026-07-12T03:00:00Z',
      }],
    };
    expect(decodeStudioProjectHistory(payload)?.revisions[0]).toMatchObject({
      action: 'restore',
      raw_intent: { kind: 'restore_revision', selected_asset_id: 'ast_1' },
      interpretation: { history_deleted: false, visual_bytes_restored_exactly: true },
      restored_from_asset_id: 'ast_1',
    });
    expect(decodeStudioProjectHistory({ ...payload, revisions: [{
      ...payload.revisions[0], raw_intent: null,
    }] })).toBeNull();
    const fetcher = jest.fn(async (
      _input: RequestInfo | URL,
      _init?: RequestInit,
    ) => ({
      ok: true,
      status: 200,
      text: async () => JSON.stringify(payload),
    } as unknown as Response));
    const api = createTrustedApiClient({ baseUrl: 'https://facetta.test', fetcher });

    const result = await api.getStudioProjectHistory('ast project');

    expect(fetcher.mock.calls[0]?.[0]).toBe(
      'https://facetta.test/studio/projects/ast%20project/history');
    expect(result.data?.revisions[0]?.image_url).toBe(
      'https://facetta.test/assets/ast_3/image');
    expect(result.data?.revisions[0]?.change_summary).toBe(
      'Restored the original sapphire direction.');
  });

  test('restores a historical revision by appending a new revision with its exact evidence', async () => {
    const fetcher = jest.fn(async (
      _input: RequestInfo | URL,
      _init?: RequestInit,
    ) => ({
      ok: true,
      status: 201,
      text: async () => JSON.stringify({
        status: 'restored_as_new_revision',
        restored_from_asset_id: 'ast old',
        new_asset_id: 'ast new',
        new_design_version: 5,
        spec_change: [{
          path: 'metal.color', before: 'rose', after: 'white', label: 'Metal color',
        }],
        project: {
          id: 'ast project', root_id: 'ast project', title: 'Sapphire ring',
          owner: 'usr_designer', state: 'refining', design_id: 'dsn_ring',
          active_asset_id: 'ast new', active_design_version: 5,
          active_revision: {
            asset_id: 'ast new', root_id: 'ast project', parent_asset_id: 'ast current',
            capability: 'RESTORED_REVISION', provenance: 'restored_revision',
            revision: 5, design_version: 5, image_url: '/assets/ast new/image',
          },
          revisions: [], assets: [], derived_assets: [], factory_ready: false,
          factory_blockers: [], primary_revision_count: 5, has_factory_drawing: false,
        },
      }),
    } as unknown as Response));
    const api = createTrustedApiClient({ baseUrl: 'https://facetta.test', fetcher });

    const result = await api.restoreStudioRevision('ast project', 'ast old', {
      created_by: 'usr_designer',
      expected_active_asset_id: 'ast current',
      expected_design_version: 4,
    });

    expect(fetcher.mock.calls[0]?.[0]).toBe(
      'https://facetta.test/studio/projects/ast%20project/revisions/ast%20old/restore');
    expect(JSON.parse(String(fetcher.mock.calls[0]?.[1]?.body))).toEqual({
      created_by: 'usr_designer',
      expected_active_asset_id: 'ast current',
      expected_design_version: 4,
    });
    expect(result).toMatchObject({
      status: 201,
      error: null,
      data: {
        restored_from_asset_id: 'ast old',
        new_asset_id: 'ast new',
        new_design_version: 5,
        spec_change: [{ path: 'metal.color', before: 'rose', after: 'white' }],
        project: { active_revision: { image_url: 'https://facetta.test/assets/ast new/image' } },
      },
    });
  });

  test('preserves structured stale-version errors when a restore races newer work', async () => {
    const fetcher = jest.fn<Promise<Response>, [RequestInfo | URL, RequestInit?]>(async () => ({
      ok: false,
      status: 409,
      text: async () => JSON.stringify({
        code: 'stale_design_version',
        category: 'stale_version',
        detail: 'The specification changed before the restore could be saved.',
      }),
    } as unknown as Response));
    const api = createTrustedApiClient({ baseUrl: 'https://facetta.test', fetcher });

    const result = await api.restoreStudioRevision('ast_root', 'ast_old', {
      created_by: 'usr_designer',
      expected_active_asset_id: 'ast_current',
      expected_design_version: 3,
    });

    expect(result).toEqual({
      data: null,
      error: expect.objectContaining({
        code: 'stale_design_version',
        category: 'stale_version',
        status: 409,
        retryable: false,
      }),
      status: 409,
    });
  });

  test('posts a review-only marketing pack and resolves preview URLs', async () => {
    const payload = {
      status: 'review_required',
      project_id: 'ast root',
      source_asset_id: 'ast_source',
      design_version: 3,
      requested_count: 2,
      candidate_count: 1,
      failed_count: 1,
      maximum_provider_attempts: 6,
      actual_attempts: 3,
      candidates: [{
        preset: 'catalog_white', framing: 'portrait', image_run_id: 'run_1',
        candidate_id: 'cand_1',
        preview_url: '/image-runs/run_1/candidates/cand_1/image',
        qa: { verdict: 'pass', checks: [] },
        routing: { attempt_count: 1, used_retry: false, used_fallback: false },
      }],
      failures: [{
        preset: 'dark_editorial', image_run_id: 'run_2',
        error_category: 'quality', code: 'image_quality_failed',
        detail: 'Jewelry geometry changed.',
      }],
    };
    assert(decodeMarketingPackResult(payload)?.failed_count === 1,
      'mixed marketing-pack evidence should decode');
    const fetcher = jest.fn(async (
      _input: RequestInfo | URL,
      _init?: RequestInit,
    ) => ({
      ok: true, status: 202, text: async () => JSON.stringify(payload),
    } as unknown as Response));
    const api = createTrustedApiClient({ baseUrl: 'https://facetta.test', fetcher });
    const result = await api.createMarketingPack('ast root', {
      created_by: 'usr_designer', expected_asset_id: 'ast_source',
      expected_design_version: 3,
      presets: ['catalog_white', 'dark_editorial'],
      framing: 'portrait', starting_variant: 4,
    });
    expect(result.error).toBeNull();
    expect(fetcher.mock.calls[0]?.[0]).toBe(
      'https://facetta.test/projects/ast%20root/marketing-pack');
    expect(JSON.parse(String(fetcher.mock.calls[0]?.[1]?.body))).toMatchObject({
      presets: ['catalog_white', 'dark_editorial'], starting_variant: 4,
    });
    expect(result.data?.candidates[0]?.preview_url).toBe(
      'https://facetta.test/image-runs/run_1/candidates/cand_1/image');
  });

  test('posts an exact confirmed version to the Studio beauty-render route', async () => {
    const fetcher = jest.fn(async (
      _input: RequestInfo | URL,
      _init?: RequestInit,
    ) => ({
      ok: true,
      status: 202,
      text: async () => JSON.stringify({
        status: 'review_required',
        project_id: 'project imported',
        source_asset_id: 'asset_colored_line_art',
        image_run_id: 'run_beauty',
        routing: { attempt_count: 1, used_retry: false, used_fallback: false },
        quality_report: { verdict: 'warn', checks: [] },
        warning_candidate: {
          run_id: 'run_beauty',
          candidate_id: 'candidate_beauty',
          preview_url: '/image-runs/run_beauty/candidates/candidate_beauty/image',
          qa: { verdict: 'warn', checks: [] },
          operation: 'SPEC_RENDER',
          requested_change: 'Use the confirmed drawing.',
          asset_capability: 'SPEC_RENDER',
        },
      }),
    } as unknown as Response));
    const api = createTrustedApiClient({ baseUrl: 'https://facetta.test', fetcher });

    const result = await api.createStudioBeautyRender('project imported', {
      created_by: 'usr_designer',
      expected_asset_id: 'asset_active_primary',
      source_asset_id: 'asset_colored_line_art',
      expected_design_version: 4,
      instruction: 'Use a neutral studio presentation and preserve the confirmed design.',
      variant: 2,
      presentation_only: true,
      studio_job_id: 'job_present_beauty',
    });

    expect(result.error).toBeNull();
    expect(fetcher).toHaveBeenCalledTimes(1);
    const [url, init] = fetcher.mock.calls[0]!;
    expect(url).toBe(
      'https://facetta.test/studio/projects/project%20imported/beauty-render',
    );
    expect(init?.method).toBe('POST');
    expect(JSON.parse(String(init?.body))).toEqual({
      created_by: 'usr_designer',
      expected_asset_id: 'asset_active_primary',
      source_asset_id: 'asset_colored_line_art',
      expected_design_version: 4,
      instruction: 'Use a neutral studio presentation and preserve the confirmed design.',
      variant: 2,
      presentation_only: true,
      studio_job_id: 'job_present_beauty',
    });
    expect(result.data?.status === 'review_required'
      ? result.data.warning_candidate.preview_url
      : null).toBe(
      'https://facetta.test/image-runs/run_beauty/candidates/candidate_beauty/image',
    );
  });

  test('posts an accounted exact version to the Studio product-photo route', async () => {
    const fetcher = jest.fn(async (
      _input: RequestInfo | URL,
      _init?: RequestInit,
    ) => ({
      ok: true,
      status: 202,
      text: async () => JSON.stringify({
        status: 'review_required',
        project_id: 'project imported',
        image_run_id: 'run_product',
        quality_report: { verdict: 'warn', checks: [] },
        routing: { attempt_count: 1, used_retry: false, used_fallback: false },
        presentation: {
          preset: 'catalog_white',
          framing: 'square',
          source_asset_id: 'asset_active_primary',
          design_version: 4,
        },
        warning_candidate: {
          run_id: 'run_product',
          candidate_id: 'candidate_product',
          preview_url: '/studio/image-runs/run_product/presentation-candidates/candidate_product/image',
          qa: { verdict: 'warn', checks: [] },
          operation: 'VISUAL_ONLY_EDIT',
          requested_change: 'Clean catalog presentation.',
          studio_job_id: 'job_present_product',
        },
      }),
    } as unknown as Response));
    const api = createTrustedApiClient({ baseUrl: 'https://facetta.test', fetcher });

    const result = await api.createStudioProductPhoto('project imported', {
      created_by: 'usr_designer',
      expected_asset_id: 'asset_active_primary',
      expected_design_version: 4,
      preset: 'catalog_white',
      framing: 'square',
      presentation_only: true,
      studio_job_id: 'job_present_product',
    });

    expect(result.error).toBeNull();
    const [url, init] = fetcher.mock.calls[0]!;
    expect(url).toBe(
      'https://facetta.test/studio/projects/project%20imported/product-photo',
    );
    expect(JSON.parse(String(init?.body))).toEqual({
      created_by: 'usr_designer',
      expected_asset_id: 'asset_active_primary',
      expected_design_version: 4,
      preset: 'catalog_white',
      framing: 'square',
      custom_instruction: '',
      variant: 0,
      presentation_only: true,
      studio_job_id: 'job_present_product',
    });
    expect(result.data?.status).toBe('review_required');
  });

  test('canonical Studio presentation methods fail closed on Studio routes', async () => {
    const fetcher = jest.fn(async (
      _input: RequestInfo | URL,
      _init?: RequestInit,
    ) => ({
      ok: false,
      status: 422,
      text: async () => JSON.stringify({ detail: 'Studio accounting is required.' }),
    } as unknown as Response));
    const api = createTrustedApiClient({ baseUrl: 'https://facetta.test', fetcher });

    await api.createStudioBeautyRender('project legacy shape', {
      created_by: 'usr_designer',
      expected_asset_id: 'asset_active_primary',
      expected_design_version: 4,
    });
    await api.createStudioProductPhoto('project legacy shape', {
      created_by: 'usr_designer',
      expected_asset_id: 'asset_active_primary',
      expected_design_version: 4,
      preset: 'catalog_white',
    });

    expect(fetcher.mock.calls.map(([url]) => url)).toEqual([
      'https://facetta.test/studio/projects/project%20legacy%20shape/beauty-render',
      'https://facetta.test/studio/projects/project%20legacy%20shape/product-photo',
    ]);
    expect(fetcher.mock.calls.map(([, init]) => (
      JSON.parse(String(init?.body)) as { presentation_only?: boolean }
    ).presentation_only)).toEqual([true, true]);
    expect(fetcher.mock.calls.every(([url]) => !String(url).includes('/projects/project%20legacy%20shape/render')))
      .toBe(true);
  });

  test('posts an isolated normalized source region to the line-art route', async () => {
    const fetcher = jest.fn(async (
      _input: RequestInfo | URL,
      _init?: RequestInit,
    ) => ({
      ok: true,
      status: 202,
      text: async () => JSON.stringify({
        status: 'confirmation_required',
        project_id: 'project imported',
        image_run_id: 'run_line',
        quality_report: { verdict: 'pass', checks: [] },
        routing: { attempt_count: 1, used_retry: false, used_fallback: false },
        view: 'front',
        next: 'Confirm the selected-view geometry.',
        candidate: {
          run_id: 'run_line',
          candidate_id: 'candidate_line',
          preview_url: '/image-runs/run_line/candidates/candidate_line/image',
          qa: { verdict: 'pass', checks: [] },
          operation: 'VISUAL_ONLY_EDIT',
          requested_change: 'Create isolated line art.',
          asset_capability: 'LINE_ART',
        },
      }),
    } as unknown as Response));
    const api = createTrustedApiClient({ baseUrl: 'https://facetta.test', fetcher });

    const result = await api.createLineArt('project imported', {
      created_by: 'usr_designer',
      expected_asset_id: 'asset_reference',
      expected_design_version: 4,
      view: 'front',
      source_region_description: 'Front elevation in the upper-left reference panel.',
      source_region: { x: 0.08, y: 0.12, width: 0.55, height: 0.38 },
      variant: 2,
    });

    expect(result.error).toBeNull();
    const [url, init] = fetcher.mock.calls[0]!;
    expect(url).toBe('https://facetta.test/projects/project%20imported/line-art');
    expect(JSON.parse(String(init?.body))).toEqual({
      created_by: 'usr_designer',
      expected_asset_id: 'asset_reference',
      expected_design_version: 4,
      view: 'front',
      source_region_description: 'Front elevation in the upper-left reference panel.',
      source_region: { x: 0.08, y: 0.12, width: 0.55, height: 0.38 },
      variant: 2,
    });
    expect(result.data?.candidate.preview_url).toBe(
      'https://facetta.test/image-runs/run_line/candidates/candidate_line/image',
    );
  });

  test('opts finished-reference drafts into independent source accounting', async () => {
    const fetcher = jest.fn(async (
      _input: RequestInfo | URL,
      _init?: RequestInit,
    ) => ({
      ok: true,
      status: 200,
      text: async () => JSON.stringify({
        jewelry_type: 'ring',
        template: 'solitaire_prong',
        stone: { cut: 'oval', species: 'sapphire' },
        source_component_coverage: {
          source_kind: 'imported_reference',
          components: [{
            component_id: 'stone.center',
            source_view: 'three_quarter',
            source_description: 'Oval blue center stone.',
            source_confidence: 0.9,
            canonical_spec_paths: ['stone'],
            unresolved_reason: null,
            independent_audit: null,
          }],
        },
      }),
    } as unknown as Response));
    const api = createTrustedApiClient({ baseUrl: 'https://facetta.test', fetcher });

    const result = await api.extractImageDraft({
      image_base64: 'cGhvdG8=',
      media_type: 'image/jpeg',
      notes: 'Keep the shoulder motif.',
      created_by: 'usr_designer',
    });

    expect(result.error).toBeNull();
    const [url, init] = fetcher.mock.calls[0]!;
    expect(url).toBe('https://facetta.test/specs/from-photo');
    expect(JSON.parse(String(init?.body))).toEqual({
      image_base64: 'cGhvdG8=',
      media_type: 'image/jpeg',
      notes: 'Keep the shoulder motif.',
      created_by: 'usr_designer',
      run_independent_audit: true,
    });
    expect(result.data?.source_coverage.audit.status).toBe('review_required');
  });

  test('posts only structured source-component decisions and an explicit audit request', async () => {
    const component = {
      component_id: 'assembly.shoulder',
      source_view: 'detail',
      source_description: 'Mirrored sculpted shoulder leaves.',
      source_confidence: 0.76,
      canonical_spec_paths: ['side_stones[0]'],
      unresolved_reason: null,
      independent_audit: null,
    };
    const fetcher = jest.fn(async (
      _input: RequestInfo | URL,
      _init?: RequestInit,
    ) => ({
      ok: true,
      status: 200,
      text: async () => JSON.stringify({
        spec: { jewelry_type: 'ring', template: 'solitaire_prong' },
        source_kind: 'designer_plate',
        components: [component],
        valid_spec_paths: ['jewelry_type', 'template', 'side_stones[0]'],
        changed_component_ids: ['assembly.shoulder'],
        invalidated_audit_component_ids: [],
        blockers: [{
          code: 'source_component_not_independently_audited',
          component_id: 'assembly.shoulder',
          message: 'The changed mapping has not been independently audited.',
          required_resolution: 'Run the independent component-coverage audit.',
        }],
        factory_ready: false,
        legacy_provenance: false,
        resolved_by: 'usr_designer',
        audit: {
          requested: false,
          status: 'not_requested',
          audited_component_ids: [],
          blocker_count: 1,
        },
      }),
    } as unknown as Response));
    const api = createTrustedApiClient({ baseUrl: 'https://facetta.test', fetcher });

    const result = await api.resolveSourceCoverage({
      spec: { jewelry_type: 'ring', template: 'solitaire_prong' },
      source_image_base64: null,
      resolutions: [{
        component_id: 'assembly.shoulder',
        canonical_spec_paths: ['side_stones[0]'],
        unresolved_reason: null,
      }],
      created_by: 'usr_designer',
      run_independent_audit: false,
    });

    expect(result.error).toBeNull();
    const [url, init] = fetcher.mock.calls[0]!;
    expect(url).toBe('https://facetta.test/specs/source-coverage/resolve');
    expect(JSON.parse(String(init?.body))).toEqual({
      spec: { jewelry_type: 'ring', template: 'solitaire_prong' },
      source_image_base64: null,
      resolutions: [{
        component_id: 'assembly.shoulder',
        canonical_spec_paths: ['side_stones[0]'],
        unresolved_reason: null,
      }],
      created_by: 'usr_designer',
      run_independent_audit: false,
    });
    expect(result.data?.blockers[0]?.component_id).toBe('assembly.shoulder');
  });

  test('binds designer confirmation to an inconclusive source component', async () => {
    const fetcher = jest.fn(async (
      _input: RequestInfo | URL,
      _init?: RequestInit,
    ) => ({
      ok: true,
      status: 200,
      text: async () => JSON.stringify({
        spec: { jewelry_type: 'ring', template: 'solitaire_prong' },
        confirmed_component_ids: ['setting.primary'],
        blockers: [],
        factory_ready: true,
        confirmed_by: 'usr_designer',
      }),
    } as unknown as Response));
    const api = createTrustedApiClient({ baseUrl: 'https://facetta.test', fetcher });

    const result = await api.confirmSourceCoverage({
      spec: { jewelry_type: 'ring', template: 'solitaire_prong' },
      source_image_base64: 'cGhvdG8=',
      confirmations: [{
        component_id: 'setting.primary',
        basis: 'visible_source',
        confirmed_description: 'Exactly four center-stone prongs are visible.',
      }],
      created_by: 'usr_designer',
    });

    expect(result.error).toBeNull();
    const [url, init] = fetcher.mock.calls[0]!;
    expect(url).toBe('https://facetta.test/specs/source-coverage/confirm');
    expect(JSON.parse(String(init?.body))).toEqual({
      spec: { jewelry_type: 'ring', template: 'solitaire_prong' },
      source_image_base64: 'cGhvdG8=',
      confirmations: [{
        component_id: 'setting.primary',
        basis: 'visible_source',
        confirmed_description: 'Exactly four center-stone prongs are visible.',
      }],
      created_by: 'usr_designer',
    });
    expect(result.data?.factory_ready).toBe(true);
  });

  test('reads a selected creative candidate into an audited draft', async () => {
    const fetcher = jest.fn(async (
      _input: RequestInfo | URL,
      _init?: RequestInit,
    ) => ({
      ok: true,
      status: 200,
      text: async () => JSON.stringify({
        jewelry_type: 'ring',
        template: 'solitaire_prong',
        source_component_coverage: {
          source_kind: 'imported_reference',
          components: [{
            component_id: 'stone.center',
            source_view: 'three_quarter',
            source_description: 'Oval green center stone.',
            source_confidence: 0.9,
            canonical_spec_paths: ['stone'],
            unresolved_reason: null,
            independent_audit: null,
          }],
        },
      }),
    } as unknown as Response));
    const api = createTrustedApiClient({ baseUrl: 'https://facetta.test', fetcher });

    const result = await api.extractCreativeCandidateDraft(
      'project one',
      'candidate one',
      {
        notes: 'Keep the shoulder motif.',
        created_by: 'usr_designer',
      },
    );

    expect(result.error).toBeNull();
    const [url, init] = fetcher.mock.calls[0]!;
    expect(url).toBe(
      'https://facetta.test/projects/project%20one/creative-candidates/candidate%20one/draft',
    );
    expect(JSON.parse(String(init?.body))).toEqual({
      notes: 'Keep the shoulder motif.',
      created_by: 'usr_designer',
      run_independent_audit: true,
    });
    expect(result.data?.source_coverage.components[0]?.component_id).toBe('stone.center');
  });

  test('confirms candidate evidence without resending candidate bytes', async () => {
    const component = {
      component_id: 'setting.primary',
      source_view: 'three_quarter',
      source_description: 'Four center prongs.',
      source_confidence: 0.8,
      canonical_spec_paths: ['setting'],
      unresolved_reason: null,
      independent_audit: {
        kind: 'independent_component_audit',
        verdict: 'inconclusive',
        auditor: 'grok_vision',
        source_view: 'three_quarter',
        observed_description: 'Prong count needs designer review.',
        evidence_sha256: 'a'.repeat(64),
      },
      designer_confirmation: {
        kind: 'designer_component_confirmation',
        basis: 'visible_source',
        reviewer: 'usr_designer',
        source_view: 'three_quarter',
        confirmed_description: 'Exactly four center prongs are visible.',
        evidence_sha256: 'a'.repeat(64),
        spec_visual_hash: 'b'.repeat(16),
      },
    };
    const fetcher = jest.fn(async (
      _input: RequestInfo | URL,
      _init?: RequestInit,
    ) => ({
      ok: true,
      status: 200,
      text: async () => JSON.stringify({
        spec: { jewelry_type: 'ring', template: 'solitaire_prong' },
        source_kind: 'imported_reference',
        components: [component],
        valid_spec_paths: ['jewelry_type', 'template', 'setting'],
        changed_component_ids: ['setting.primary'],
        invalidated_audit_component_ids: [],
        blockers: [],
        factory_ready: true,
        legacy_provenance: false,
        resolved_by: 'usr_designer',
        audit: {
          requested: false,
          status: 'pass',
          audited_component_ids: ['setting.primary'],
          blocker_count: 0,
        },
      }),
    } as unknown as Response));
    const api = createTrustedApiClient({ baseUrl: 'https://facetta.test', fetcher });

    const result = await api.confirmCreativeCandidateCoverage(
      'project one',
      'candidate one',
      {
        spec: { jewelry_type: 'ring', template: 'solitaire_prong' },
        confirmations: [{
          component_id: 'setting.primary',
          basis: 'visible_source',
          confirmed_description: 'Exactly four center prongs are visible.',
        }],
        created_by: 'usr_designer',
      },
    );

    expect(result.error).toBeNull();
    const [url, init] = fetcher.mock.calls[0]!;
    expect(url).toContain('/source-coverage/confirm');
    expect(JSON.parse(String(init?.body))).not.toHaveProperty('source_image_base64');
    expect(result.data?.factory_ready).toBe(true);
  });

  test('binds designer profile geometry to server-held candidate evidence', async () => {
    const path = {
      path_id: 'assembly.outline',
      purpose: 'outline' as const,
      closed: true,
      points: [
        { x_mm: -10, y_mm: -20 },
        { x_mm: 10, y_mm: -20 },
        { x_mm: 8, y_mm: 20 },
        { x_mm: -8, y_mm: 20 },
      ],
      nominal_width_mm: null,
    };
    const definition = {
      kind: 'dimensioned_profile',
      scope: 'full_assembly',
      coordinate_system: 'x_right_y_up',
      view: 'front',
      paths: [path],
      profile_thickness_mm: 1.5,
      dimension_status: 'designer_confirmed_estimate',
      manufacturing_notes: 'Prototype profile; verify at bench.',
      source_asset_id: 'candidate one',
      source_asset_sha256: 'a'.repeat(64),
      confirmed_by: 'usr_designer',
      confirmed_at: '2026-07-12T10:30:00Z',
    };
    const fetcher = jest.fn(async (
      _input: RequestInfo | URL,
      _init?: RequestInit,
    ) => ({
      ok: true,
      status: 200,
      text: async () => JSON.stringify({
        spec: {
          jewelry_type: 'necklace',
          design_form: { elements: [{ definition }] },
        },
        element_id: 'assembly.full',
        candidate_asset_id: 'candidate one',
        candidate_sha256: 'a'.repeat(64),
        previous_definition_kind: 'visual_reference_only',
        definition,
        source_reaudit_required: true,
        factory_ready: false,
        sheet_authority: 'preliminary_not_for_production',
        blockers: [{
          code: 'source_component_spec_audit_stale',
          detail: 'Source coverage must be re-audited.',
        }],
      }),
    } as unknown as Response));
    const api = createTrustedApiClient({ baseUrl: 'https://facetta.test', fetcher });

    const result = await api.confirmCreativeCandidateProfile(
      'project one',
      'candidate one',
      {
        spec: { jewelry_type: 'necklace' },
        element_id: 'assembly.full',
        profile: {
          view: 'front',
          paths: [path],
          profile_thickness_mm: 1.5,
          dimension_status: 'designer_confirmed_estimate',
          manufacturing_notes: 'Prototype profile; verify at bench.',
        },
        created_by: 'usr_designer',
      },
    );

    expect(result.error).toBeNull();
    expect(result.data?.definition.source_asset_id).toBe('candidate one');
    expect(result.data?.source_reaudit_required).toBe(true);
    const [url, init] = fetcher.mock.calls[0]!;
    expect(url).toContain('/dimensioned-profile/confirm');
    const body = JSON.parse(String(init?.body));
    expect(body.profile).not.toHaveProperty('source_asset_id');
    expect(body.profile).not.toHaveProperty('confirmed_by');
  });

  test('reads SVG factory previews with explicit authority metadata', async () => {
    const fetcher = jest.fn(async (
      _input: RequestInfo | URL,
      _init?: RequestInit,
    ) => ({
      ok: true,
      status: 200,
      headers: {
        get: (name: string) => name.toLowerCase() === 'x-facetta-sheet-authority'
          ? 'preliminary_not_for_production' : null,
      },
      text: async () => '<svg data-facetta-authority="preliminary_not_for_production"></svg>',
    } as unknown as Response));
    const api = createTrustedApiClient({ baseUrl: 'https://facetta.test', fetcher });
    const spec = { jewelry_type: 'ring', template: 'solitaire_prong' };

    const result = await api.previewDraftFactorySheet(spec);

    expect(result.error).toBeNull();
    expect(result.data?.authority).toBe('preliminary_not_for_production');
    expect(result.data?.svg).toContain('<svg');
    const [url, init] = fetcher.mock.calls[0]!;
    expect(url).toBe('https://facetta.test/specs/sheet.svg');
    expect(init?.method).toBe('POST');
    expect(JSON.parse(String(init?.body))).toEqual(spec);
  });

  test('decodes server-authoritative Studio billing and rejects inconsistent charges', () => {
    const payload = {
      job_id: 'job_create', owner: 'usr_designer', action_id: 'create',
      lane: 'fast_visual', status: 'succeeded', progress: 1,
      active_design_id: 'design_ring', source_revision_id: 'asset_source',
      error_code: null, created_at: '2026-07-12T01:00:00Z',
      updated_at: '2026-07-12T01:01:00Z',
      billing: {
        requested_outputs: 4, credits_per_output: 7, estimated_credits: 28,
        completed_outputs: 3, charged_outputs: 3, charged_credits: 21,
        policy: 'Only requested completed outputs are charged.',
      },
    };
    expect(decodeStudioJobRecord(payload)?.billing.charged_credits).toBe(21);
    expect(decodeStudioJobList({ jobs: [payload] })?.jobs).toHaveLength(1);
    expect(decodeStudioJobRecord({
      ...payload,
      billing: {
        ...payload.billing,
        completed_outputs: 2,
        charged_outputs: 0,
        charged_credits: 0,
      },
    })?.billing).toMatchObject({
      completed_outputs: 2,
      charged_outputs: 0,
      charged_credits: 0,
    });
    expect(decodeStudioJobRecord({
      ...payload,
      billing: {
        ...payload.billing,
        completed_outputs: 2,
        charged_outputs: 1,
        charged_credits: 7,
      },
    })).toBeNull();
    expect(decodeStudioJobRecord({
      ...payload,
      billing: {
        ...payload.billing,
        completed_outputs: 2,
        charged_outputs: 3,
        charged_credits: 21,
      },
    })).toBeNull();
    expect(decodeStudioJobRecord({
      ...payload,
      status: 'reviewing',
      progress: 0.8,
      billing: {
        ...payload.billing,
        completed_outputs: 1,
        charged_outputs: 0,
        charged_credits: 0,
      },
    })).toBeNull();
    expect(decodeStudioJobRecord({
      ...payload,
      billing: { ...payload.billing, charged_credits: 28 },
    })).toBeNull();
  });

  test('uses owner-scoped Studio Activity routes and cancel command', async () => {
    const job = {
      job_id: 'job one', owner: 'usr_designer', action_id: 'refine',
      lane: 'trusted_structural', status: 'running', progress: 0.4,
      active_design_id: 'design_ring', source_revision_id: 'asset_source',
      error_code: null, created_at: '2026-07-12T01:00:00Z',
      updated_at: '2026-07-12T01:01:00Z',
      billing: {
        requested_outputs: 1, credits_per_output: 9, estimated_credits: 9,
        completed_outputs: 0, charged_outputs: 0, charged_credits: 0,
        policy: 'Internal retries are included.',
      },
    };
    const fetcher = jest.fn<Promise<Response>, [RequestInfo | URL, RequestInit?]>(async (input, init) => {
      const body = init?.body === undefined ? null : JSON.parse(String(init.body));
      const payload = init?.method === 'PATCH'
        ? {
            ...job, status: body.status, progress: body.progress,
            active_design_id: body.active_design_id,
            source_revision_id: body.source_revision_id,
          }
        : String(input).includes('/cancel')
          ? { ...job, status: 'canceled' }
          : { jobs: [job] };
      return {
        ok: true, status: 200, text: async () => JSON.stringify(payload),
      } as unknown as Response;
    });
    const api = createTrustedApiClient({ baseUrl: 'https://facetta.test', fetcher });

    const listed = await api.listStudioJobs('usr_designer', 'running');
    expect(listed.data?.jobs[0]?.job_id).toBe('job one');
    expect(fetcher.mock.calls[0]?.[0]).toBe(
      'https://facetta.test/studio/jobs?owner=usr_designer&status=running',
    );

    const canceled = await api.cancelStudioJob('job one', 'usr_designer');
    expect(canceled.data?.status).toBe('canceled');
    expect(fetcher.mock.calls[1]?.[0]).toBe(
      'https://facetta.test/studio/jobs/job%20one/cancel',
    );
    expect(JSON.parse(String(fetcher.mock.calls[1]?.[1]?.body))).toEqual({
      owner: 'usr_designer',
    });

    const bound = await api.transitionStudioJob('job one', {
      owner: 'usr_designer', status: 'reviewing', progress: 0.9,
      active_design_id: 'project one', source_revision_id: 'candidate one',
    });
    expect(bound.data?.active_design_id).toBe('project one');
    expect(JSON.parse(String(fetcher.mock.calls[2]?.[1]?.body))).toMatchObject({
      active_design_id: 'project one', source_revision_id: 'candidate one',
    });
  });

  test('binds pre-spec presentation preview and discard to exact asset hash', async () => {
    const sourceHash = 'f'.repeat(64);
    const fetcher = jest.fn<Promise<Response>, [RequestInfo | URL, RequestInit?]>(async (input) => {
      const url = String(input);
      const payload = url.endsWith('/discard') ? {
        status: 'discarded', project_id: 'project visual',
        source_asset_id: 'asset visual', source_sha256: sourceHash,
        design_version: null, candidate_id: 'candidate visual',
      } : {
        status: 'review_required', project_id: 'project visual',
        source_asset_id: 'asset visual', source_sha256: sourceHash,
        design_version: null, destination: 'marketing', client_format: 'product',
        candidate: {
          candidate_id: 'candidate visual', image_run_id: 'run visual',
          preview_url: '/studio/image-runs/run%20visual/presentation-candidates/candidate%20visual/image',
          capability: 'MARKETING_IMAGE', preset: 'dark_editorial', framing: 'square',
          qa: { verdict: 'pass', accepted: true, review_required: false, checks: [] },
        },
      };
      return {
        ok: true, status: url.endsWith('/discard') ? 200 : 201,
        text: async () => JSON.stringify(payload),
      } as unknown as Response;
    });
    const api = createTrustedApiClient({ baseUrl: 'https://facetta.test', fetcher });

    const preview = await api.createPreSpecPresentation('project visual', {
      created_by: 'designer', expected_active_asset_id: 'asset visual',
      destination: 'marketing', preset: 'dark_editorial', framing: 'square',
    });
    expect(preview.error).toBeNull();
    expect(preview.data?.source_sha256).toBe(sourceHash);
    expect(preview.data?.candidate.preview_url).toBe(
      'https://facetta.test/studio/image-runs/run%20visual/presentation-candidates/candidate%20visual/image',
    );
    expect(JSON.parse(String(fetcher.mock.calls[0]?.[1]?.body))).toEqual({
      created_by: 'designer', expected_active_asset_id: 'asset visual',
      destination: 'marketing', client_format: 'product', preset: 'dark_editorial',
      framing: 'square', custom_instruction: '', variant: 0,
    });

    const discarded = await api.discardPreSpecPresentation(
      'run visual', 'candidate visual', {
        created_by: 'designer', expected_active_asset_id: 'asset visual',
        expected_source_sha256: sourceHash,
      },
    );
    expect(discarded.error).toBeNull();
    expect(discarded.data?.design_version).toBeNull();
    expect(fetcher.mock.calls[1]?.[0]).toBe(
      'https://facetta.test/studio/image-runs/run%20visual/presentation-candidates/candidate%20visual/discard',
    );
    expect(JSON.parse(String(fetcher.mock.calls[1]?.[1]?.body))).toEqual({
      created_by: 'designer', expected_active_asset_id: 'asset visual',
      expected_source_sha256: sourceHash,
    });
  });

  test('decodes owner-scoped durable presentation reviews for resume', async () => {
    const sourceHash = 'e'.repeat(64);
    const fetcher = jest.fn<Promise<Response>, [RequestInfo | URL, RequestInit?]>(async () => ({
      ok: true,
      status: 200,
      text: async () => JSON.stringify({ candidates: [{
        candidate_id: 'candidate resume', image_run_id: 'run resume',
        project_id: 'project visual', source_asset_id: 'asset visual',
        source_sha256: sourceHash, design_version: null, destination: 'client',
        capability: 'CLIENT_PRODUCT_PHOTO', preset: 'catalog_white',
        framing: 'square', qa: { verdict: 'pass', accepted: true,
          review_required: false, checks: [] }, status: 'reviewing',
        studio_job_id: 'job resume', accepted_asset_id: null,
        expires_at: '2026-07-13T12:00:00Z',
        preview_url: '/studio/image-runs/run%20resume/presentation-candidates/candidate%20resume/image?owner=designer',
      }] }),
    } as unknown as Response));
    const api = createTrustedApiClient({ baseUrl: 'https://facetta.test', fetcher });

    const resumed = await api.listPreSpecPresentations('designer', 'project visual');
    expect(resumed.error).toBeNull();
    expect(resumed.data?.candidates[0]).toMatchObject({
      candidate_id: 'candidate resume', source_sha256: sourceHash,
      studio_job_id: 'job resume', status: 'reviewing',
      preview_url: 'https://facetta.test/studio/image-runs/run%20resume/presentation-candidates/candidate%20resume/image?owner=designer',
    });
    expect(String(fetcher.mock.calls[0]?.[0])).toBe(
      'https://facetta.test/studio/presentation-candidates?owner=designer&project_id=project+visual&status=reviewing',
    );
  });

  test('decodes durable exact View reviews and sends CAS decision fields', async () => {
    const fetcher = jest.fn<Promise<Response>, [RequestInfo | URL, RequestInit?]>(async (input) => {
      const url = String(input);
      const payload = url.includes('/accept') ? {
        status: 'accepted', project_id: 'project 1', source_asset_id: 'asset 1',
        design_version: 3, asset_id: 'view asset', project: {
          id: 'project 1', root_id: 'project 1', title: 'Ring', owner: 'designer',
          state: 'refining', design_id: 'design 1', spec: {}, active_asset_id: 'asset 1',
          active_design_version: 3, active_revision: {
            asset_id: 'asset 1', root_id: 'project 1', capability: 'SPEC_RENDER',
            provenance: 'studio', revision: 3, design_id: 'design 1', design_version: 3,
            image_url: '/source.png',
          }, revisions: [], assets: [], derived_assets: [], factory_ready: false,
          factory_blockers: [], primary_revision_count: 1, has_factory_drawing: false,
        },
      } : { candidates: [{
        candidate_id: 'candidate view', image_run_id: 'run view', studio_job_id: 'job view',
        project_id: 'project 1', source_asset_id: 'asset 1', design_version: 3,
        view: 'front', status: 'reviewing', accepted_asset_id: null,
        expires_at: '2026-07-14T00:00:00Z', preview_url: '/view-preview.png',
        qa: { verdict: 'pass', accepted: true, review_required: false, checks: [] },
      }] };
      return { ok: true, status: url.includes('/accept') ? 201 : 200,
        text: async () => JSON.stringify(payload) } as unknown as Response;
    });
    const api = createTrustedApiClient({ baseUrl: 'https://facetta.test', fetcher });
    const listed = await api.listStudioViewCandidates('designer', 'project 1');
    expect(listed.error).toBeNull();
    expect(listed.data?.candidates[0]).toMatchObject({
      candidate_id: 'candidate view', studio_job_id: 'job view', design_version: 3,
      preview_url: 'https://facetta.test/view-preview.png',
    });
    const accepted = await api.acceptStudioViewCandidate('run view', 'candidate view', {
      created_by: 'designer', expected_project_id: 'project 1',
      expected_source_asset_id: 'asset 1', expected_design_version: 3,
    });
    expect(accepted.error).toBeNull();
    expect(String(fetcher.mock.calls[1]?.[0])).toBe(
      'https://facetta.test/studio/view-candidates/run%20view/candidate%20view/accept',
    );
    expect(JSON.parse(String(fetcher.mock.calls[1]?.[1]?.body))).toEqual({
      created_by: 'designer', expected_project_id: 'project 1',
      expected_source_asset_id: 'asset 1', expected_design_version: 3,
    });
  });

  test('decodes durable markup reviews and sends exact accept lineage', async () => {
    const candidatePayload = {
      candidate_id: 'candidate markup', image_run_id: 'run markup',
      project_root_id: 'project 1', source_asset_id: 'asset 1',
      expected_active_asset_id: 'asset 1', design_version: 3,
      operation: 'LOCAL_EDIT', requested_change: 'soften halo',
      region_description: 'halo', status: 'reviewing', studio_job_id: 'job refine',
      expires_at: '2026-07-14T00:00:00Z',
      qa: { verdict: 'pass', accepted: true, review_required: false, checks: [] },
      preview_url: '/studio/markup-candidates/run%20markup/candidate%20markup/image',
      accept_url: '/studio/markup-candidates/run%20markup/candidate%20markup/accept',
      discard_url: '/studio/markup-candidates/run%20markup/candidate%20markup/discard',
      save_as_variation_url: '/studio/markup-candidates/run%20markup/candidate%20markup/save-as-variation',
    };
    const fetcher = jest.fn<Promise<Response>, [RequestInfo | URL, RequestInit?]>(async (input) => {
      const url = String(input);
      const payload = url.endsWith('/accept') ? {
        status: 'applied', candidate_id: 'candidate markup', asset_id: 'asset 2',
        project: {
          id: 'project 1', root_id: 'project 1', title: 'Ring', owner: 'designer',
          state: 'refining', design_id: 'design 1', spec: {}, active_asset_id: 'asset 2',
          active_design_version: 4, active_revision: {
            asset_id: 'asset 2', root_id: 'project 1', capability: 'LOCALIZED_EDIT',
            provenance: 'studio', revision: 4, design_id: 'design 1', design_version: 4,
            image_url: '/asset-2.png',
          }, revisions: [], assets: [], derived_assets: [], factory_ready: false,
          factory_blockers: [], primary_revision_count: 2, has_factory_drawing: false,
        },
      } : { candidates: [candidatePayload] };
      return { ok: true, status: url.endsWith('/accept') ? 201 : 200,
        text: async () => JSON.stringify(payload) } as unknown as Response;
    });
    const api = createTrustedApiClient({ baseUrl: 'https://facetta.test', fetcher });
    const listed = await api.listStudioMarkupCandidates('project 1');
    expect(listed.error).toBeNull();
    expect(listed.data?.candidates[0]).toMatchObject({
      candidate_id: 'candidate markup', studio_job_id: 'job refine',
      preview_url: 'https://facetta.test/studio/markup-candidates/run%20markup/candidate%20markup/image',
    });
    const accepted = await api.acceptStudioMarkupCandidate(
      listed.data!.candidates[0], {
        expected_active_asset_id: 'asset 1', expected_design_version: 3,
        created_by: 'designer',
      },
    );
    expect(accepted.error).toBeNull();
    expect(accepted.data?.project.active_asset_id).toBe('asset 2');
    expect(String(fetcher.mock.calls[1]?.[0])).toBe(
      'https://facetta.test/studio/markup-candidates/run%20markup/candidate%20markup/accept',
    );
    expect(JSON.parse(String(fetcher.mock.calls[1]?.[1]?.body))).toEqual({
      expected_active_asset_id: 'asset 1', expected_design_version: 3,
      created_by: 'designer',
    });
  });
});

test('markup preserves an exact revision component identity from read through apply', async () => {
  const fetcher = jest.fn<Promise<Response>, [RequestInfo | URL, RequestInit?]>(
    async (input) => {
      const url = String(input);
      if (url.endsWith('/markup/read')) {
        return {
          ok: true,
          status: 200,
          text: async () => JSON.stringify({
            markup_asset_id: 'markup_1',
            assistant_name: 'Facetta',
            design_id: 'design_1',
            expected_design_version: 3,
            interpretation: {
              target_region: 'left shoulder',
              requested_change: 'soften this shoulder',
              impact: 'specification',
              target_spec_reference: 'setting.shoulder_profile',
              target_section: 'setting',
              target_index: null,
              target_component_id: 'shoulders.left',
              target_element_id: null,
              frozen_elements: ['everything outside the left shoulder'],
              confidence: 0.97,
              clarification_question: null,
              understood_as: 'Soften only the mapped left shoulder.',
            },
          }),
        } as unknown as Response;
      }
      return {
        ok: false,
        status: 422,
        text: async () => JSON.stringify({ detail: 'test stop after request capture' }),
      } as unknown as Response;
    },
  );
  const api = createTrustedApiClient({ baseUrl: 'https://facetta.test', fetcher });

  const reading = await api.readMarkup('asset 1', {
    markup_snapshot: {
      schema_version: 1,
      coordinate_space: 'normalized_image',
      source_uri: 'https://facetta.test/assets/asset%201/image',
      annotations: [],
    },
    created_by: 'designer',
  });
  expect(reading.error).toBeNull();
  expect(reading.data?.interpretation.target_component_id).toBe('shoulders.left');

  await api.applyMarkup('asset 1', {
    annotation: {
      region_description: reading.data!.interpretation.target_region,
      change_instruction: reading.data!.interpretation.requested_change,
      impact: reading.data!.interpretation.impact,
      target_section: reading.data!.interpretation.target_section,
      target_ref: reading.data!.interpretation.target_spec_reference,
      index: reading.data!.interpretation.target_index,
      target_component_id: reading.data!.interpretation.target_component_id,
      target_element_id: reading.data!.interpretation.target_element_id,
      form_view: 'three_quarter',
      mask_base64: null,
    },
    markup_asset_id: 'markup_1',
    expected_design_version: 3,
    created_by: 'designer',
  });

  const body = JSON.parse(String(fetcher.mock.calls[1]?.[1]?.body));
  expect(body.annotations[0].target_component_id).toBe('shoulders.left');
});

test('decodes only the designer-safe exact component targeting contract', () => {
  const targeting = decodeStudioComponentTargeting({
    schema_version: 'facetta.studio-component-targeting.v1',
    asset_id: 'asset_1',
    asset_sha256: 'a'.repeat(64),
    jewelry_type: 'ring',
    component_map: {
      state: 'unresolved', scope: 'ring_v1', map_sha256: 'b'.repeat(64),
      mapper_contract: 'calibrated.mapper.v1', raster_width: 1024, raster_height: 1024,
    },
    catalog_paths: [{
      component_path: 'setting.style', status: 'unresolved',
      required_component_kinds: ['prongs', 'setting'],
      component_ids: ['prongs', 'setting'],
      reason_code: 'structural_child_mapping_unavailable',
    }],
    authority: 'exact_revision_image_editing_only',
  });

  expect(targeting?.catalog_paths[0]).toMatchObject({
    component_path: 'setting.style', status: 'unresolved',
    reason_code: 'structural_child_mapping_unavailable',
  });
  expect((targeting as any)?.catalog_paths[0].polygons).toBeUndefined();
});

test('prepares an exact revision component map through the trusted seam', async () => {
  const payload = {
    schema_version: 'facetta.studio-component-targeting.v1',
    asset_id: 'asset 1',
    asset_sha256: 'a'.repeat(64),
    jewelry_type: 'ring',
    component_map: {
      state: 'ready', scope: 'ring_v1', map_sha256: 'b'.repeat(64),
      mapper_contract: 'facetta.grok-ring-component-map.v1',
      raster_width: 1024, raster_height: 1024,
    },
    catalog_paths: [{
      component_path: 'stone.cut', status: 'ready',
      required_component_kinds: ['center_stone', 'prongs', 'setting'],
      component_ids: ['center_stone', 'prongs', 'setting'], reason_code: null,
    }],
    authority: 'exact_revision_image_editing_only',
  };
  const fetcher = jest.fn<Promise<Response>, [RequestInfo | URL, RequestInit?]>(
    async () => ({
      ok: true, status: 200, text: async () => JSON.stringify(payload),
    } as unknown as Response),
  );
  const api = createTrustedApiClient({ baseUrl: 'https://facetta.test', fetcher });

  const result = await api.prepareStudioComponentMap('asset 1');

  expect(result.error).toBeNull();
  expect(result.data?.catalog_paths[0]?.component_ids).toEqual([
    'center_stone', 'prongs', 'setting',
  ]);
  expect(String(fetcher.mock.calls[0]?.[0])).toBe(
    'https://facetta.test/assets/asset%201/studio-component-map',
  );
  expect(fetcher.mock.calls[0]?.[1]?.method).toBe('POST');
  expect(JSON.parse(String(fetcher.mock.calls[0]?.[1]?.body))).toEqual({});
});
