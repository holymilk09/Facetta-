/// <reference types="jest" />

import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react-native';

import type { TrustedApiClient } from './client';
import { TrustedWorkflowScreen } from './TrustedWorkflowScreen';
import type { TrustedWorkflowController } from './useTrustedWorkflow';
import * as trustedWorkflowModule from './useTrustedWorkflow';
import type { ProjectDetail, SourceCoverageResolutionResult } from './types';
import { initialTrustedWorkflowState } from './workflowState';

describe('TrustedWorkflowScreen', () => {
  test('keeps the workspace dark until its feature flag is enabled', async () => {
    const api = {} as TrustedApiClient;
    await render(React.createElement(TrustedWorkflowScreen, {
      api,
      designer: 'usr_test',
      enabled: false,
    }));

    expect(await screen.findByText('Trusted workspace')).toBeTruthy();
    expect(await screen.findByText(/EXPO_PUBLIC_TRUSTED_WORKSPACE=true/)).toBeTruthy();
  });

  test.each([
    ['phone', 390, false],
    ['tablet', 768, true],
    ['desktop', 1440, true],
  ] as const)('uses the supported controls on %s at %ipx', async (
    _surface,
    width,
    canCreate,
  ) => {
    const api = {} as TrustedApiClient;
    await render(React.createElement(TrustedWorkflowScreen, {
      api,
      designer: 'usr_test',
      enabled: true,
      viewportWidth: width,
    }));

    const creation = screen.queryByText('Create a jewelry project');
    expect(creation === null).toBe(!canCreate);
    if (!canCreate) {
      expect(screen.getByText(/Mobile is review-only/)).toBeTruthy();
    }
  });

  test('creates a multi-candidate visual study before any factory spec', async () => {
    const creativeAsset = {
      asset_id: 'candidate_1',
      root_id: 'creative_project',
      parent_asset_id: 'creative_project',
      capability: 'CREATIVE_RENDER',
      provenance: 'creative_render_review_only',
      revision: 1,
      design_id: null,
      design_version: null,
      region: null,
      instruction: 'Preserve the exact drawing.',
      drift: null,
      pinned: false,
      media_type: 'image/png',
      image_url: 'https://facetta.test/assets/candidate_1/image',
      created_by: 'usr_test',
      created_at: null,
      legacy_provenance: false,
    };
    const creativeProject: ProjectDetail = {
      id: 'creative_project',
      root_id: 'creative_project',
      title: 'Creative jewelry study',
      collection: null,
      tags: [],
      owner: 'usr_test',
      state: 'refining',
      design_id: null,
      spec: null,
      active_asset_id: 'candidate_1',
      active_design_version: null,
      active_revision: creativeAsset,
      pinned_revision: null,
      revisions: [{
        revision: 1,
        asset: creativeAsset,
        spec_version: null,
        spec_change: [],
        ignored_fields: [],
        qa: null,
        routing: null,
        created_at: null,
      }],
      assets: [creativeAsset],
      derived_assets: [],
      approval: null,
      factory_ready: false,
      factory_blockers: [],
      primary_revision_count: 1,
      has_factory_drawing: false,
      cover_asset_id: 'candidate_1',
      created_at: null,
      updated_at: null,
    };
    const createProjectFromDrawing = jest.fn(async () => ({
      data: creativeProject,
      error: null,
      status: 201,
    }));
    const api = { createProjectFromDrawing } as unknown as TrustedApiClient;

    await render(React.createElement(TrustedWorkflowScreen, {
      api,
      designer: 'usr_test',
      enabled: true,
      viewportWidth: 768,
    }));
    await fireEvent.press(screen.getByText('Drawing / image first').parent!);
    await fireEvent.changeText(
      screen.getByPlaceholderText('Add the uploaded source image bytes.'),
      'c291cmNl',
    );
    await fireEvent.press(screen.getByText('3 candidates').parent!);
    await fireEvent.press(screen.getByText('Create project'));

    expect(createProjectFromDrawing).toHaveBeenCalledWith(expect.objectContaining({
      image_base64: 'c291cmNl',
      variation_count: 3,
      owner: 'usr_test',
    }));
    expect(await screen.findByText('Choose a creative candidate')).toBeTruthy();
    expect(screen.getByText('Direction 1')).toBeTruthy();
    expect(screen.getByText(/not factory records/)).toBeTruthy();
    expect(screen.getByText(/Every concept is already saved in your Studio library/)).toBeTruthy();
    expect(screen.queryByText('Optional destination · Factory')).toBeNull();
    expect(screen.queryByText('Factory handoff')).toBeNull();
    expect(screen.getByText('Review').parent?.props.accessibilityState.disabled).toBe(true);
    await fireEvent.press(screen.getByText('Close project'));
  });

  test('starts with category-neutral prompt directions instead of forcing a ring spec', async () => {
    const creativeAsset = {
      asset_id: 'prompt_candidate', root_id: 'prompt_candidate', parent_asset_id: null,
      capability: 'CREATIVE_RENDER', provenance: 'pre_spec_creative_candidate',
      revision: 1, design_id: null, design_version: null, region: null,
      instruction: 'A platinum floral lariat necklace.', drift: null, pinned: false,
      media_type: 'image/png', image_url: 'https://facetta.test/assets/prompt_candidate/image',
      created_by: 'usr_test', created_at: null, legacy_provenance: false,
    };
    const promptProject: ProjectDetail = {
      id: 'prompt_candidate', root_id: 'prompt_candidate', title: 'Lariat study',
      collection: null, tags: [], owner: 'usr_test', state: 'refining', design_id: null,
      spec: null, active_asset_id: 'prompt_candidate', active_design_version: null,
      active_revision: creativeAsset, pinned_revision: null,
      revisions: [{
        revision: 1, asset: creativeAsset, spec_version: null, spec_change: [],
        ignored_fields: [], qa: null, routing: null, created_at: null,
      }],
      assets: [creativeAsset], derived_assets: [], approval: null, factory_ready: false,
      factory_blockers: [], primary_revision_count: 1, has_factory_drawing: false,
      cover_asset_id: 'prompt_candidate', created_at: null, updated_at: null,
    };
    const createProjectFromPrompt = jest.fn(async () => ({
      data: promptProject, error: null, status: 201,
    }));
    const api = { createProjectFromPrompt } as unknown as TrustedApiClient;

    await render(React.createElement(TrustedWorkflowScreen, {
      api, designer: 'usr_test', enabled: true, viewportWidth: 768,
    }));
    expect(screen.getByText('Describe an idea')).toBeTruthy();
    expect(screen.getByText('Structured ring brief')).toBeTruthy();
    await fireEvent.changeText(
      screen.getByPlaceholderText(/platinum floral lariat necklace/),
      'A platinum floral lariat necklace with emerald leaves.',
    );
    await fireEvent.press(screen.getByText('2 candidates').parent!);
    await fireEvent.press(screen.getByText('Create project'));

    expect(createProjectFromPrompt).toHaveBeenCalledWith(expect.objectContaining({
      prompt: 'A platinum floral lariat necklace with emerald leaves.',
      variation_count: 2,
      owner: 'usr_test',
    }));
    expect(await screen.findByText('Choose a creative candidate')).toBeTruthy();
    await fireEvent.press(screen.getByText('Close project'));
  });

  test('keeps revision mutation off a phone while allowing interpretation review', async () => {
    const workflow = {
      state: {
        ...initialTrustedWorkflowState,
        phase: 'refine' as const,
        project_id: 'project_phone_review',
        project: {
          id: 'project_phone_review',
          root_id: 'asset_root',
          title: 'Phone review ring',
          collection: null,
          tags: [],
          owner: 'usr_test',
          state: 'refining' as const,
          design_id: 'design_ring',
          active_asset_id: null,
          active_design_version: 2,
          active_revision: null,
          pinned_revision: null,
          revisions: [],
          assets: [],
          derived_assets: [],
          approval: null,
          factory_ready: false,
          factory_blockers: [],
          primary_revision_count: 1,
          has_factory_drawing: false,
          cover_asset_id: null,
          created_at: null,
          updated_at: null,
        },
        pending_markup: {
          base_asset_id: 'asset_root',
          markup_asset_id: 'asset_markup',
          interpretation: {
            target_region: 'band',
            requested_change: 'Widen the band',
            impact: 'specification' as const,
            target_spec_reference: 'shank.width_mm',
            target_section: 'shank',
            target_index: null,
            target_component_id: 'shank',
            target_element_id: null,
            frozen_elements: ['center stone', 'setting'],
            confidence: 0.96,
            clarification_question: null,
            understood_as: 'Widen only the band and preserve the setting.',
          },
          expected_design_version: 2,
          confirmed: {
            region_description: 'band',
            change_instruction: 'Widen the band',
            impact: 'specification' as const,
            target_section: 'shank',
            target_ref: 'shank.width_mm',
            index: null,
            target_component_id: 'shank',
            target_element_id: null,
            form_view: 'three_quarter' as const,
            mask_base64: null,
          },
          requires_reconfirmation: false,
        },
      },
      createFromBrief: jest.fn(),
      createFromPrompt: jest.fn(),
      createFromDrawing: jest.fn(),
      createFromImage: jest.fn(),
      promoteCreativeCandidate: jest.fn(),
      openProject: jest.fn(),
      refreshProject: jest.fn(),
      selectPhase: jest.fn(),
      readMarkup: jest.fn(),
      confirmMarkup: jest.fn(),
      applyConfirmedMarkup: jest.fn(),
      createBeautyRender: jest.fn(),
      createProductPhoto: jest.fn(),
      createLineArt: jest.fn(),
      colorizeLineArt: jest.fn(),
      regenerateWarningCandidate: jest.fn(),
      acceptWarningCandidate: jest.fn(),
      discardWarningCandidate: jest.fn(),
      discardMarkup: jest.fn(),
      startApproval: jest.fn(),
      loadApproval: jest.fn(),
      respondToApproval: jest.fn(),
      loadFactoryPack: jest.fn(),
      clearError: jest.fn(),
      clearWorkspace: jest.fn(),
      canAcceptWarningCandidate: false,
    } as TrustedWorkflowController;
    const hook = jest.spyOn(trustedWorkflowModule, 'useTrustedWorkflow')
      .mockReturnValue(workflow);
    const api = {} as TrustedApiClient;

    const rendered = await render(React.createElement(TrustedWorkflowScreen, {
      api,
      designer: 'usr_test',
      enabled: true,
      viewportWidth: 390,
    }));

    expect(screen.getByText('Confirmed change')).toBeTruthy();
    expect(screen.getByText('Project comments')).toBeTruthy();
    expect(screen.getByText(/ready for review/)).toBeTruthy();
    expect(screen.queryByText('Apply one confirmed change')).toBeNull();

    await rendered.rerender(React.createElement(TrustedWorkflowScreen, {
      api,
      designer: 'usr_test',
      enabled: true,
      viewportWidth: 768,
    }));
    expect(screen.getByText('Apply one confirmed change')).toBeTruthy();
    hook.mockRestore();
  });

  test('stages reference extraction before designer confirmation on tablet', async () => {
    const api = {} as TrustedApiClient;
    await render(React.createElement(TrustedWorkflowScreen, {
      api,
      designer: 'usr_test',
      enabled: true,
      viewportWidth: 768,
    }));

    await fireEvent.press(screen.getByText('Factory-spec reference').parent!);
    expect(await screen.findByText('Extract draft from reference')).toBeTruthy();
    expect(screen.getByText('Advanced specification JSON')).toBeTruthy();
    await fireEvent.press(screen.getByText('Hand drawing / design plate').parent!);
    expect(await screen.findByText('Known scale anchor')).toBeTruthy();
  });

  test('blocks plate project creation until the corrected source inventory passes re-audit', async () => {
    const component = {
      component_id: 'stone.center',
      source_view: 'plate_composite' as const,
      source_description: 'Oval blue center stone.',
      source_confidence: 0.92,
      canonical_spec_paths: ['stone'],
      unresolved_reason: null,
      independent_audit: null,
    };
    const spec = {
      jewelry_type: 'ring',
      template: 'solitaire_prong',
      source_component_coverage: {
        source_kind: 'designer_plate',
        components: [component],
      },
    };
    const initialCoverage: SourceCoverageResolutionResult = {
      spec,
      source_kind: 'designer_plate',
      components: [component],
      valid_spec_paths: ['jewelry_type', 'template', 'stone'],
      changed_component_ids: [],
      invalidated_audit_component_ids: [],
      blockers: [{
        code: 'source_component_not_independently_audited',
        component_id: 'stone.center',
        message: 'The center stone mapping has not been independently audited.',
        required_resolution: 'Run the independent component-coverage audit.',
      }],
      factory_ready: false,
      legacy_provenance: false,
      resolved_by: null,
      audit: {
        requested: true,
        status: 'review_required',
        audited_component_ids: [],
        blocker_count: 1,
      },
    };
    const passedComponent = {
      ...component,
      independent_audit: {
        kind: 'independent_component_audit' as const,
        verdict: 'pass' as const,
        auditor: 'skeptical-source-component-audit.v2',
        source_view: 'plate_composite' as const,
        observed_description: 'The visible center stone is represented by the mapped stone record.',
        evidence_sha256: 'a'.repeat(64),
      },
    };
    const passedCoverage: SourceCoverageResolutionResult = {
      ...initialCoverage,
      components: [passedComponent],
      blockers: [],
      factory_ready: true,
      resolved_by: 'usr_test',
      audit: {
        requested: true,
        status: 'pass',
        audited_component_ids: ['stone.center'],
        blocker_count: 0,
      },
    };
    const extractPlateDraft = jest.fn(async () => ({
      data: {
        spec,
        read: { assembly: 'oval center solitaire' },
        uncertainties: ['Independent audit requires review.'],
        provenance: 'grok_vision_hand_plate_draft' as const,
        requires_designer_confirmation: true as const,
        source_coverage_audit: { status: 'review_required' as const, blocker_count: 1 },
        source_coverage: initialCoverage,
      },
      error: null,
      status: 200,
    }));
    const resolveSourceCoverage = jest.fn(async () => ({
      data: passedCoverage,
      error: null,
      status: 200,
    }));
    const api = {
      extractPlateDraft,
      resolveSourceCoverage,
    } as unknown as TrustedApiClient;

    const rendered = await render(React.createElement(TrustedWorkflowScreen, {
      api,
      designer: 'usr_test',
      enabled: true,
      viewportWidth: 768,
    }));
    await fireEvent.press(screen.getByText('Factory-spec reference').parent!);
    await fireEvent.press(screen.getByText('Hand drawing / design plate').parent!);
    await fireEvent.changeText(
      screen.getByPlaceholderText('Paste the uploaded image bytes from the canvas adapter.'),
      'cGxhdGU=',
    );
    await fireEvent.press(screen.getByText('Extract draft from reference'));

    expect(await screen.findByText('stone.center')).toBeTruthy();
    expect(screen.getByText('Create project').parent).toBeDisabled();
    await fireEvent.press(screen.getByText('Re-run independent source audit'));
    expect(await screen.findByText(/Independent component accounting passed/)).toBeTruthy();
    expect(resolveSourceCoverage).toHaveBeenCalledWith(expect.objectContaining({
      source_image_base64: 'cGxhdGU=',
      resolutions: [],
      run_independent_audit: true,
    }));
    expect(screen.getByText('Create project').parent).not.toBeDisabled();
    await fireEvent.changeText(
      screen.getByPlaceholderText('Advanced specification record; the image is saved only after validation.'),
      `${JSON.stringify(spec)} `,
    );
    expect(screen.getByText('Create project').parent).toBeDisabled();
    expect(screen.getByText(/specification JSON changed after the last audit/)).toBeTruthy();
    await rendered.unmount();
  });

  test('applies the same source gate to a finished jewelry reference', async () => {
    const component = {
      component_id: 'setting.primary',
      source_view: 'three_quarter' as const,
      source_description: 'Four-prong raised center setting.',
      source_confidence: 0.88,
      canonical_spec_paths: ['setting'],
      unresolved_reason: null,
      independent_audit: null,
    };
    const spec = {
      jewelry_type: 'ring',
      template: 'solitaire_prong',
      source_component_coverage: {
        source_kind: 'imported_reference',
        components: [component],
      },
    };
    const blocked: SourceCoverageResolutionResult = {
      spec,
      source_kind: 'imported_reference',
      components: [component],
      valid_spec_paths: ['jewelry_type', 'template', 'setting'],
      changed_component_ids: [],
      invalidated_audit_component_ids: [],
      blockers: [{
        code: 'source_component_not_independently_audited',
        component_id: 'setting.primary',
        message: 'The visible setting has not been independently audited.',
        required_resolution: 'Run the independent component-coverage audit.',
      }],
      factory_ready: false,
      legacy_provenance: false,
      resolved_by: null,
      audit: {
        requested: true,
        status: 'review_required',
        audited_component_ids: [],
        blocker_count: 1,
      },
    };
    const passed: SourceCoverageResolutionResult = {
      ...blocked,
      components: [{
        ...component,
        independent_audit: {
          kind: 'independent_component_audit',
          verdict: 'pass',
          auditor: 'skeptical-source-component-audit.v2',
          source_view: 'three_quarter',
          observed_description: 'The visible four-prong setting matches the mapped setting record.',
          evidence_sha256: 'c'.repeat(64),
        },
      }],
      blockers: [],
      factory_ready: true,
      resolved_by: 'usr_test',
      audit: {
        requested: true,
        status: 'pass',
        audited_component_ids: ['setting.primary'],
        blocker_count: 0,
      },
    };
    const extractImageDraft = jest.fn(async () => ({
      data: { spec, source_coverage: blocked },
      error: null,
      status: 200,
    }));
    const resolveSourceCoverage = jest.fn(async () => ({
      data: passed,
      error: null,
      status: 200,
    }));
    const api = { extractImageDraft, resolveSourceCoverage } as unknown as TrustedApiClient;

    const rendered = await render(React.createElement(TrustedWorkflowScreen, {
      api,
      designer: 'usr_test',
      enabled: true,
      viewportWidth: 768,
    }));
    await fireEvent.press(screen.getByText('Factory-spec reference').parent!);
    await fireEvent.changeText(
      screen.getByPlaceholderText('Paste the uploaded image bytes from the canvas adapter.'),
      'cGhvdG8=',
    );
    await fireEvent.press(screen.getByText('Extract draft from reference'));

    expect(await screen.findByText('setting.primary')).toBeTruthy();
    expect(screen.getByText('Create project').parent).toBeDisabled();
    await fireEvent.press(screen.getByText('Re-run independent source audit'));
    expect(await screen.findByText(/Independent component accounting passed/)).toBeTruthy();
    expect(resolveSourceCoverage).toHaveBeenCalledWith(expect.objectContaining({
      source_image_base64: 'cGhvdG8=',
      resolutions: [],
      run_independent_audit: true,
    }));
    expect(screen.getByText('Create project').parent).not.toBeDisabled();
    await fireEvent.changeText(
      screen.getByPlaceholderText('Advanced specification record; the image is saved only after validation.'),
      `${JSON.stringify(spec)} `,
    );
    expect(screen.getByText('Create project').parent).toBeDisabled();
    await rendered.unmount();
  });

  test('offers the confirmed-reference beauty-render transition on tablet and desktop only', async () => {
    const importedAsset = {
      asset_id: 'asset_imported',
      root_id: 'project_imported',
      parent_asset_id: null,
      capability: 'IMPORTED_REFERENCE',
      provenance: 'imported_reference',
      revision: 1,
      design_id: 'design_imported',
      design_version: 3,
      region: null,
      instruction: 'Designer-confirmed imported reference',
      drift: null,
      pinned: false,
      media_type: 'image/png',
      image_url: 'https://facetta.test/assets/asset_imported/image',
      created_by: 'usr_test',
      created_at: null,
      legacy_provenance: false,
    };
    const project: ProjectDetail = {
      id: 'project_imported',
      root_id: 'project_imported',
      title: 'Confirmed sketch ring',
      collection: null,
      tags: [],
      owner: 'usr_test',
      state: 'refining',
      design_id: 'design_imported',
      active_asset_id: 'asset_imported',
      active_design_version: 3,
      active_revision: importedAsset,
      pinned_revision: null,
      revisions: [{
        revision: 1,
        asset: importedAsset,
        spec_version: 3,
        spec_change: [],
        ignored_fields: [],
        qa: null,
        routing: null,
        created_at: null,
      }],
      assets: [importedAsset],
      derived_assets: [{
        ...importedAsset,
        asset_id: 'line_art_confirmed',
        parent_asset_id: 'asset_imported',
        capability: 'LINE_ART',
        provenance: 'confirmed_line_art',
        revision: null,
      }, {
        ...importedAsset,
        asset_id: 'colored_line_art_confirmed',
        parent_asset_id: 'line_art_confirmed',
        capability: 'COLORED_LINE_ART',
        provenance: 'confirmed_colored_line_art',
        revision: null,
      }],
      approval: null,
      factory_ready: false,
      factory_blockers: [],
      primary_revision_count: 1,
      has_factory_drawing: false,
      cover_asset_id: 'asset_imported',
      created_at: null,
      updated_at: null,
    };
    const createBeautyRender = jest.fn(async () => undefined);
    const workflow = {
      state: {
        ...initialTrustedWorkflowState,
        phase: 'refine' as const,
        project_id: project.id,
        project,
      },
      createFromBrief: jest.fn(), createFromPrompt: jest.fn(), createFromDrawing: jest.fn(), createFromImage: jest.fn(),
      promoteCreativeCandidate: jest.fn(),
      openProject: jest.fn(), refreshProject: jest.fn(), selectPhase: jest.fn(),
      readMarkup: jest.fn(), confirmMarkup: jest.fn(), applyConfirmedMarkup: jest.fn(),
      createBeautyRender,
      createProductPhoto: jest.fn(), createLineArt: jest.fn(), colorizeLineArt: jest.fn(),
      regenerateWarningCandidate: jest.fn(), acceptWarningCandidate: jest.fn(),
      discardWarningCandidate: jest.fn(), discardMarkup: jest.fn(),
      startApproval: jest.fn(), loadApproval: jest.fn(), respondToApproval: jest.fn(),
      loadFactoryPack: jest.fn(), clearError: jest.fn(), clearWorkspace: jest.fn(),
      canAcceptWarningCandidate: false,
    } as TrustedWorkflowController;
    const hook = jest.spyOn(trustedWorkflowModule, 'useTrustedWorkflow')
      .mockReturnValue(workflow);
    const createMarketingPack = jest.fn(async () => ({
      data: {
        status: 'review_required' as const,
        project_id: project.id,
        source_asset_id: 'asset_imported',
        design_version: 3,
        requested_count: 2,
        candidate_count: 1,
        failed_count: 1,
        maximum_provider_attempts: 6,
        actual_attempts: 3,
        candidates: [{
          preset: 'catalog_white' as const,
          framing: 'portrait' as const,
          image_run_id: 'run_marketing',
          candidate_id: 'candidate_marketing',
          preview_url: 'https://facetta.test/marketing.png',
          qa: {
            verdict: 'warn' as const,
            accepted: false,
            review_required: true,
            score: 93,
            summary: 'Review presentation.',
            failed_checks: [],
            warnings: [],
            checks: [],
          },
          routing: {
            attempt_count: 1,
            used_retry: false,
            used_fallback: false,
            cache_hit: false,
            run_id: 'run_marketing',
          },
        }],
        failures: [{
          preset: 'luxury_studio' as const,
          image_run_id: null,
          error_category: 'provider',
          code: 'provider_timeout',
          detail: 'Provider timed out.',
        }],
      },
      error: null,
      status: 200,
    }));
    const api = {
      assetImageUrl: jest.fn(() => 'https://facetta.test/assets/asset_imported/image'),
      createMarketingPack,
    } as unknown as TrustedApiClient;

    const rendered = await render(React.createElement(TrustedWorkflowScreen, {
      api,
      designer: 'usr_test',
      enabled: true,
      viewportWidth: 768,
    }));

    await fireEvent.press(screen.getByText('Client presentation').parent!);
    expect(screen.getByText('Create a beauty render from confirmed colored line art')).toBeTruthy();
    expect(screen.getByText(/Exact render source: colored_line_art_confirmed · spec 3/)).toBeTruthy();
    await fireEvent.press(screen.getByText('Create QA-checked beauty render'));
    expect(createBeautyRender).toHaveBeenCalledWith('');
    await fireEvent.press(screen.getByText('Marketing images').parent!);
    const luxuryChoices = screen.getAllByText('Luxury studio');
    await fireEvent.press(luxuryChoices.at(-1)!.parent!);
    await fireEvent.press(screen.getByText('Generate review candidates'));
    expect(createMarketingPack).toHaveBeenCalledWith(project.id, expect.objectContaining({
      presets: ['catalog_white', 'luxury_studio'],
      expected_asset_id: 'asset_imported',
      expected_design_version: 3,
    }));
    expect(await screen.findByText(/catalog white · portrait/)).toBeTruthy();
    expect(screen.getByText(/luxury studio failed/)).toBeTruthy();
    await rendered.unmount();

    workflow.state = { ...workflow.state, busy: 'beauty_render' };
    const loading = await render(React.createElement(TrustedWorkflowScreen, {
      api,
      designer: 'usr_test',
      enabled: true,
      viewportWidth: 1440,
    }));
    expect(screen.getByText(/Building and checking a polished render/)).toBeTruthy();
    await loading.unmount();

    workflow.state = { ...workflow.state, busy: null };
    const phone = await render(React.createElement(TrustedWorkflowScreen, {
      api,
      designer: 'usr_test',
      enabled: true,
      viewportWidth: 390,
    }));
    expect(screen.queryByText('Create QA-checked beauty render')).toBeNull();
    await phone.unmount();
    hook.mockRestore();
  });

  test('treats Factory as an optional destination and shows only the chosen presentation tools', async () => {
    const importedAsset = {
      asset_id: 'asset_destination',
      root_id: 'project_destination',
      parent_asset_id: null,
      capability: 'IMPORTED_REFERENCE',
      provenance: 'imported_reference',
      revision: 1,
      design_id: 'design_destination',
      design_version: 1,
      region: null,
      instruction: 'Designer-confirmed imported reference',
      drift: null,
      pinned: false,
      media_type: 'image/png',
      image_url: 'https://facetta.test/assets/asset_destination/image',
      created_by: 'usr_test',
      created_at: null,
      legacy_provenance: false,
    };
    const project: ProjectDetail = {
      id: 'project_destination', root_id: 'project_destination',
      title: 'Destination ring', collection: null, tags: [], owner: 'usr_test',
      state: 'refining', design_id: 'design_destination',
      active_asset_id: importedAsset.asset_id, active_design_version: 1,
      active_revision: importedAsset, pinned_revision: null,
      revisions: [{
        revision: 1, asset: importedAsset, spec_version: 1, spec_change: [],
        ignored_fields: [], qa: null, routing: null, created_at: null,
      }],
      assets: [importedAsset], derived_assets: [], approval: null,
      factory_ready: false, factory_blockers: [], primary_revision_count: 1,
      has_factory_drawing: false, cover_asset_id: importedAsset.asset_id,
      created_at: null, updated_at: null,
    };
    const workflow = {
      state: {
        ...initialTrustedWorkflowState,
        phase: 'refine' as const,
        project_id: project.id,
        project,
      },
      createFromBrief: jest.fn(), createFromPrompt: jest.fn(), createFromDrawing: jest.fn(), createFromImage: jest.fn(),
      promoteCreativeCandidate: jest.fn(),
      openProject: jest.fn(), refreshProject: jest.fn(), selectPhase: jest.fn(),
      readMarkup: jest.fn(), confirmMarkup: jest.fn(), applyConfirmedMarkup: jest.fn(),
      createBeautyRender: jest.fn(), createProductPhoto: jest.fn(), createLineArt: jest.fn(), colorizeLineArt: jest.fn(),
      regenerateWarningCandidate: jest.fn(), acceptWarningCandidate: jest.fn(), discardWarningCandidate: jest.fn(),
      discardMarkup: jest.fn(), startApproval: jest.fn(), loadApproval: jest.fn(), respondToApproval: jest.fn(),
      loadFactoryPack: jest.fn(), clearError: jest.fn(), clearWorkspace: jest.fn(),
      canAcceptWarningCandidate: false,
    } as TrustedWorkflowController;
    const hook = jest.spyOn(trustedWorkflowModule, 'useTrustedWorkflow')
      .mockReturnValue(workflow);
    const api = {
      assetImageUrl: jest.fn(() => 'https://facetta.test/assets/asset_destination/image'),
    } as unknown as TrustedApiClient;

    await render(React.createElement(TrustedWorkflowScreen, {
      api, designer: 'usr_test', enabled: true, viewportWidth: 768,
    }));

    expect(screen.getByText('My library')).toBeTruthy();
    expect(screen.getByText('Client presentation')).toBeTruthy();
    expect(screen.getByText('Marketing images')).toBeTruthy();
    expect(screen.getByText(/safely kept in your Studio library/)).toBeTruthy();
    expect(screen.queryByText('Create a beauty render from this confirmed reference')).toBeNull();
    expect(screen.queryByText('Create product photography')).toBeNull();
    expect(screen.queryByText('Create an ecommerce image set')).toBeNull();
    expect(screen.queryByText('Optional destination · Factory')).toBeNull();
    expect(screen.getByText('Need to make this piece?')).toBeTruthy();

    await fireEvent.press(screen.getByText('Client presentation').parent!);
    expect(screen.getByText('Create a beauty render from this confirmed reference')).toBeTruthy();
    expect(screen.getByText('Create product photography')).toBeTruthy();
    expect(screen.queryByText('Create an ecommerce image set')).toBeNull();

    await fireEvent.press(screen.getByText('Marketing images').parent!);
    expect(screen.queryByText('Create a beauty render from this confirmed reference')).toBeNull();
    expect(screen.getByText('Create product photography')).toBeTruthy();
    expect(screen.getByText('Create an ecommerce image set')).toBeTruthy();
    hook.mockRestore();
  });
});
