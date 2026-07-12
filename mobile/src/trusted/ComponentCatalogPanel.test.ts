/// <reference types="jest" />

import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react-native';

import { AuthenticatedImageProvider } from '../AuthenticatedImage';
import {
  catalogFactoryDelta,
  ComponentCatalogPanel,
  componentCatalogPathsForSpec,
} from './ComponentCatalogPanel';
import type { TrustedApiClient } from './client';
import type {
  ApiResult,
  CatalogPreviewAcceptResult,
  CatalogPreviewResult,
  ComponentCatalog,
  ComponentCatalogOption,
  ComponentCatalogPath,
  JsonObject,
  ProjectDetail,
} from './types';

const ringSpec: JsonObject = {
  jewelry_type: 'ring',
  template: 'solitaire_prong',
  stone: {
    species: 'sapphire', cut: 'oval_brilliant', carat: 1.25,
    color: { trade: 'Royal Blue', gia: 'vivid blue' },
  },
  setting: { style: '4_prong_basket', prong_count: 4, prong_tip_mm: 0.8 },
  metal: { material: 'gold', karat: 18, color: 'yellow' },
  band: { width_mm: 2.1, thickness_mm: 1.8 },
};

const project = (assetId = 'ast_root', version = 1): ProjectDetail => ({
  id: 'ast_root',
  root_id: 'ast_root',
  title: 'Catalog ring',
  collection: null,
  tags: [],
  owner: 'usr_designer',
  state: 'refining',
  design_id: 'dsn_ring',
  spec: version === 1 ? ringSpec : {
    ...ringSpec,
    metal: { material: 'gold', karat: 18, color: 'rose' },
  },
  active_asset_id: assetId,
  active_design_version: version,
  active_revision: null,
  pinned_revision: null,
  revisions: [],
  assets: [],
  derived_assets: [],
  approval: null,
  factory_ready: false,
  factory_blockers: [],
  primary_revision_count: version,
  has_factory_drawing: false,
  cover_asset_id: assetId,
  created_at: null,
  updated_at: null,
});

const roseOption: ComponentCatalogOption = {
  id: 'rose',
  display: 'Rose Gold',
  visual_geometry: [
    'warm pink rose-gold hue on every visible metal surface',
    'no change to polish, dimensions, or component geometry',
  ],
  isolation_target: 'all visible metal surfaces; exclude every gemstone',
  frozen_facts: ['stone', 'side_stones', 'setting', 'band.width_mm', 'metal.karat'],
  factory_fields: { 'metal.color': 'rose' },
  derived_factory_fields: [],
  selection_requirements: ['metal.material == gold'],
};

function ringCatalog(path: ComponentCatalogPath): ComponentCatalog {
  if (path === 'metal.color') {
    return {
      component_path: path,
      display: 'Gold color',
      applicable_jewelry_types: ['ring'],
      image_agent_status: 'catalog_ready',
      options: [roseOption],
    };
  }
  const option: ComponentCatalogOption = {
    id: `${path}.choice`,
    display: `${path} choice`,
    visual_geometry: [`exact ${path} geometry`],
    isolation_target: `only ${path}`,
    frozen_facts: ['all other factory facts'],
    factory_fields: { [path]: 'choice' },
    derived_factory_fields: [],
    selection_requirements: [],
  };
  return {
    component_path: path,
    display: path,
    applicable_jewelry_types: ['ring'],
    image_agent_status: 'catalog_ready',
    options: [option],
  };
}

const accepted: CatalogPreviewAcceptResult = {
  status: 'accepted',
  asset_id: 'ast_2',
  design_version: 2,
  image_run_id: 'run_catalog',
  spec_change: [{ path: 'metal.color', before: 'yellow', after: 'rose', label: 'gold color' }],
  project: project('ast_2', 2),
};

const preview: CatalogPreviewResult = {
  status: 'preview_ready',
  component_path: 'metal.color',
  option_id: 'rose',
  isolation_target: roseOption.isolation_target,
  source_asset_id: 'ast_root',
  design_version: 1,
  image_run_id: 'run_catalog',
  spec_change: [{ path: 'metal.color', before: 'yellow', after: 'rose', label: 'gold color' }],
  next_spec: { ...ringSpec, metal: { material: 'gold', karat: 18, color: 'rose' } },
  qa: {
    verdict: 'pass', accepted: false, review_required: true, score: 97,
    summary: 'Image checks passed.', failed_checks: [], warnings: [], checks: [],
  },
  routing: {
    attempt_count: 1, used_retry: false, used_fallback: false,
    cache_hit: false, run_id: 'run_catalog',
  },
  project: project(),
  candidate: {
    run_id: 'run_catalog',
    candidate_id: 'cand_catalog',
    preview_url: 'https://facetta.test/catalog-preview.png',
    accept_url: '/image-runs/run_catalog/catalog-candidates/cand_catalog/accept',
    discard_url: '/image-runs/run_catalog/catalog-candidates/cand_catalog',
    save_as_variation_url: '/image-runs/run_catalog/catalog-candidates/cand_catalog/save-as-variation',
    verdict: 'pass',
    expires_in_seconds: 900,
  },
};

function clientWith(
  previewResult: ApiResult<CatalogPreviewResult> = { data: preview, error: null, status: 201 },
  acceptResult: ApiResult<CatalogPreviewAcceptResult> = { data: accepted, error: null, status: 201 },
) {
  const getComponentCatalog = jest.fn(async (path: ComponentCatalogPath) => ({
    data: ringCatalog(path), error: null, status: 200,
  }));
  const getStoneVocabulary = jest.fn(async () => ({
    data: [], error: null, status: 200,
  }));
  const previewCatalogSelection = jest.fn(async () => previewResult);
  const acceptCatalogPreview = jest.fn(async () => acceptResult);
  const discardCatalogPreview = jest.fn(async () => ({
    data: { status: 'discarded' as const }, error: null, status: 204,
  }));
  return {
    client: {
      getComponentCatalog,
      getStoneVocabulary,
      previewCatalogSelection,
      acceptCatalogPreview,
      discardCatalogPreview,
    } as unknown as TrustedApiClient,
    getComponentCatalog, previewCatalogSelection, acceptCatalogPreview,
    discardCatalogPreview,
  };
}

function renderWithAuth(ui: React.ReactElement) {
  return render(React.createElement(
    AuthenticatedImageProvider,
    {
      allowedOrigin: 'https://facetta.test',
      headers: { Authorization: 'Bearer test-session-token' },
      children: ui,
    },
  ));
}

describe('ComponentCatalogPanel', () => {
  test('prioritizes material and stone quick choices before structural changes', async () => {
    const api = clientWith();
    await renderWithAuth(React.createElement(ComponentCatalogPanel, {
      client: api.client,
      project: project(),
      spec: ringSpec,
      createdBy: 'usr_designer',
    }));

    await waitFor(() => expect(screen.getByText('Common material and stone changes')).toBeTruthy());
    expect(screen.getByText('Shape, setting, and construction')).toBeTruthy();
    expect(screen.queryByText('stone.cut choice')).toBeNull();
    await fireEvent.press(screen.getByText('Shape, setting, and construction'));
    expect(screen.getByText('stone.cut choice')).toBeTruthy();
  });

  test('switches species context before applying one protected stone palette choice', async () => {
    const sapphireCatalog: ComponentCatalog = {
      component_path: 'stone.color',
      display: 'Center stone species and color',
      applicable_jewelry_types: ['ring'],
      image_agent_status: 'catalog_ready',
      options: [{
        id: 'Royal Blue', display: 'Royal Blue',
        visual_geometry: ['blue sapphire with intact faceting'],
        isolation_target: 'center stone body only', frozen_facts: ['setting', 'metal'],
        factory_fields: {
          'stone.species': 'sapphire',
          'stone.color': { trade: 'Royal Blue', gia: 'vivid blue' },
        },
        derived_factory_fields: ['stone.carat'], selection_requirements: [],
      }],
    };
    const rubyCatalog: ComponentCatalog = {
      ...sapphireCatalog,
      options: [{
        id: "Pigeon's Blood", display: "Pigeon's Blood",
        visual_geometry: ['red ruby with intact faceting'],
        isolation_target: 'center stone body only', frozen_facts: ['setting', 'metal'],
        factory_fields: {
          'stone.species': 'ruby',
          'stone.color': { trade: "Pigeon's Blood", gia: 'vivid red' },
        },
        derived_factory_fields: ['stone.carat'], selection_requirements: [],
      }],
    };
    const getComponentCatalog = jest.fn(async (
      path: ComponentCatalogPath,
      context?: { stoneSpecies?: string },
    ) => ({
      data: path === 'stone.color'
        ? (context?.stoneSpecies === 'ruby' ? rubyCatalog : sapphireCatalog)
        : ringCatalog(path),
      error: null,
      status: 200,
    }));
    const getStoneVocabulary = jest.fn(async () => ({
      data: [
        { id: 'sapphire', display: 'Sapphire', parameter_set: 'gemstone' },
        { id: 'ruby', display: 'Ruby', parameter_set: 'gemstone' },
        { id: 'emerald', display: 'Emerald', parameter_set: 'gemstone' },
      ],
      error: null,
      status: 200,
    }));
    const previewCatalogSelection = jest.fn(async () => ({
      data: {
        ...preview,
        component_path: 'stone.color' as const,
        option_id: "Pigeon's Blood",
        isolation_target: 'center stone body only',
        spec_change: [
          { path: 'stone.species', before: 'sapphire', after: 'ruby', label: 'species' },
          { path: 'stone.color', before: ringSpec.stone, after: { trade: "Pigeon's Blood", gia: 'vivid red' }, label: 'color' },
        ],
        candidate: { ...preview.candidate, run_id: 'run_ruby', candidate_id: 'cand_ruby' },
      },
      error: null,
      status: 201,
    }));
    const acceptCatalogPreview = jest.fn(async () => ({
      data: { ...accepted, image_run_id: 'run_ruby' }, error: null, status: 201,
    }));
    const client = {
      getComponentCatalog, getStoneVocabulary, previewCatalogSelection,
      acceptCatalogPreview, discardCatalogPreview: jest.fn(),
    } as unknown as TrustedApiClient;

    await renderWithAuth(React.createElement(ComponentCatalogPanel, {
      client, project: project(), spec: ringSpec, createdBy: 'usr_designer',
    }));
    await waitFor(() => expect(screen.getByText(/Royal Blue/)).toBeTruthy());
    expect(screen.getByText(/Palette for sapphire/)).toBeTruthy();
    await fireEvent.press(screen.getByText('Choose another stone'));
    await fireEvent.press(screen.getByText('Ruby'));
    await waitFor(() => expect(getComponentCatalog).toHaveBeenCalledWith(
      'stone.color', { stoneSpecies: 'ruby' },
    ));
    expect(await screen.findByText("Pigeon's Blood")).toBeTruthy();
    await fireEvent.press(screen.getByText("Pigeon's Blood"));
    await fireEvent.press(screen.getByText('Preview protected change'));
    await waitFor(() => expect(previewCatalogSelection).toHaveBeenCalledWith(
      'ast_root', expect.objectContaining({
        component_path: 'stone.color', option_id: "Pigeon's Blood", stone_species: 'ruby',
      }),
    ));
    await fireEvent.press(await screen.findByText('Apply to this variation'));
    await waitFor(() => expect(acceptCatalogPreview).toHaveBeenCalledWith(
      expect.objectContaining({ run_id: 'run_ruby', candidate_id: 'cand_ruby' }),
      { expected_design_version: 1, created_by: 'usr_designer' },
    ));
  });

  test('branches the exact current revision before an exploratory component change', async () => {
    const api = clientWith();
    const variation = { ...project(), id: 'ast_variation', root_id: 'ast_variation' };
    const saveAsVariation = jest.fn(async () => ({
      data: {
        status: 'variation_created' as const,
        family_id: 'fam_ring', variation_index: 2,
        source_project_id: 'ast_root', source_asset_id: 'ast_root', project: variation,
      },
      error: null,
      status: 201,
    }));
    const onVariationCreated = jest.fn();
    const client = { ...api.client, saveAsVariation } as TrustedApiClient;
    await renderWithAuth(React.createElement(ComponentCatalogPanel, {
      client, project: project(), spec: ringSpec, createdBy: 'usr_designer', onVariationCreated,
    }));

    await waitFor(() => expect(screen.getByText('Rose Gold')).toBeTruthy());
    await fireEvent.press(screen.getByText('Rose Gold'));
    await fireEvent.press(screen.getByText('Save as variation first'));
    await waitFor(() => expect(saveAsVariation).toHaveBeenCalledWith('ast_root', {
      created_by: 'usr_designer', expected_active_asset_id: 'ast_root',
      expected_design_version: 1, label: 'Explore Rose Gold',
    }));
    expect(onVariationCreated).toHaveBeenCalledWith(variation);
  });

  test('loads only applicable catalogs and applies only the reviewed preview', async () => {
    const api = clientWith();
    const onApplied = jest.fn();
    await renderWithAuth(React.createElement(ComponentCatalogPanel, {
      client: api.client,
      project: project(),
      spec: ringSpec,
      createdBy: 'usr_designer',
      onApplied,
    }));

    await waitFor(() => expect(screen.getByText('Rose Gold')).toBeTruthy());
    expect(api.getComponentCatalog).toHaveBeenCalledTimes(5);
    expect(api.getComponentCatalog.mock.calls.map(([path]) => path)).toEqual([
      'metal.material', 'metal.color', 'stone.color', 'stone.cut', 'setting.style',
    ]);
    expect(api.getComponentCatalog).toHaveBeenCalledWith(
      'stone.color', { stoneSpecies: 'sapphire' },
    );

    await fireEvent.press(screen.getByText('Rose Gold'));
    expect(screen.getByText('yellow → rose')).toBeTruthy();
    expect(screen.getByText('all visible metal surfaces; exclude every gemstone')).toBeTruthy();
    expect(screen.getByText(/stone, side_stones, setting, band.width_mm, metal.karat/)).toBeTruthy();
    expect(screen.getByText('• metal.material == gold')).toBeTruthy();
    expect(screen.getByText(/warm pink rose-gold hue/)).toBeTruthy();

    expect(api.previewCatalogSelection).not.toHaveBeenCalled();
    await fireEvent.press(screen.getByText('Preview protected change'));

    await waitFor(() => expect(api.previewCatalogSelection).toHaveBeenCalledWith(
      'ast_root',
      {
        component_path: 'metal.color',
        option_id: 'rose',
        expected_design_version: 1,
        created_by: 'usr_designer',
        variant: 0,
      },
    ));
    expect(onApplied).not.toHaveBeenCalled();
    expect(screen.getByText('Preview checks passed. Nothing has changed yet.')).toBeTruthy();
    await fireEvent.press(screen.getByText('Apply to this variation'));
    await waitFor(() => expect(api.acceptCatalogPreview).toHaveBeenCalledWith(
      preview.candidate,
      { expected_design_version: 1, created_by: 'usr_designer' },
    ));
    expect(onApplied).toHaveBeenCalledWith(accepted);
  });

  test('keeps native mobile review-only even after a designer selects an option', async () => {
    const api = clientWith();
    await renderWithAuth(React.createElement(ComponentCatalogPanel, {
      client: api.client,
      project: project(),
      spec: ringSpec,
      createdBy: 'usr_designer',
      mobileReviewOnly: true,
    }));

    await waitFor(() => expect(screen.getByText('Rose Gold')).toBeTruthy());
    await fireEvent.press(screen.getByText('Rose Gold'));
    expect(screen.getByText(/Mobile supports reviewing catalog choices/)).toBeTruthy();
    await fireEvent.press(screen.getByText('Preview protected change'));
    expect(api.previewCatalogSelection).not.toHaveBeenCalled();
  });

  test('shows necklace chain choices while category editing remains safely pending', async () => {
    const chainOption: ComponentCatalogOption = {
      id: 'curb',
      display: 'Curb chain',
      visual_geometry: ['flattened interlocking links'],
      isolation_target: 'complete visible chain-link run only',
      frozen_facts: ['pendant', 'stones', 'setting', 'clasp', 'chain.length_mm'],
      factory_fields: { 'chain.style': 'curb' },
      derived_factory_fields: [],
      selection_requirements: [],
    };
    const chainCatalog: ComponentCatalog = {
      component_path: 'chain.style',
      display: 'Chain type',
      applicable_jewelry_types: ['necklace'],
      image_agent_status: 'catalog_ready_category_pending',
      options: [chainOption],
    };
    const getComponentCatalog = jest.fn(async () => ({
      data: chainCatalog, error: null, status: 200,
    }));
    const previewCatalogSelection = jest.fn();
    const client = {
      getComponentCatalog, previewCatalogSelection,
    } as unknown as TrustedApiClient;
    await renderWithAuth(React.createElement(ComponentCatalogPanel, {
      client,
      project: project(),
      spec: {
        jewelry_type: 'necklace',
        chain: { style: 'cable', length_mm: 450 },
      },
      createdBy: 'usr_designer',
    }));

    await waitFor(() => expect(screen.getByText('Curb chain')).toBeTruthy());
    expect(getComponentCatalog).toHaveBeenCalledWith('chain.style');
    await fireEvent.press(screen.getByText('Curb chain'));
    expect(screen.getByText(/protected image editing is not released for this category yet/)).toBeTruthy();
    await fireEvent.press(screen.getByText('Preview protected change'));
    expect(previewCatalogSelection).not.toHaveBeenCalled();
    expect(screen.queryByText(/provider|grok|model/i)).toBeNull();
  });

  test('sends a released necklace choice only with its confirmed target record', async () => {
    const chainOption: ComponentCatalogOption = {
      id: 'curb',
      display: 'Curb chain',
      visual_geometry: ['flattened interlocking links'],
      isolation_target: 'complete visible chain-link run only',
      frozen_facts: ['pendant', 'stones', 'setting', 'clasp', 'chain.length_mm'],
      factory_fields: { 'chain.style': 'curb' },
      derived_factory_fields: [],
      selection_requirements: [
        'designer-confirmed target construction-specific geometry',
        'exact target stock/sample/drawing/CAD production reference',
      ],
    };
    const chainCatalog: ComponentCatalog = {
      component_path: 'chain.style',
      display: 'Chain type',
      applicable_jewelry_types: ['necklace'],
      image_agent_status: 'catalog_ready',
      options: [chainOption],
    };
    const necklaceSpec: JsonObject = {
      jewelry_type: 'necklace',
      chain: {
        style: 'cable', length_mm: 450, clasp: 'lobster',
        pendant_connection: 'slides_through_bail',
      },
    };
    const necklaceProject = {
      ...project(),
      title: 'Catalog necklace',
      spec: necklaceSpec,
    };
    const getComponentCatalog = jest.fn(async () => ({
      data: chainCatalog, error: null, status: 200,
    }));
    const previewCatalogSelection = jest.fn(async () => ({
      data: {
        ...preview,
        component_path: 'chain.style' as const,
        option_id: 'curb',
        isolation_target: chainOption.isolation_target,
        spec_change: [{ path: 'chain.style', before: 'cable', after: 'curb', label: 'chain type' }],
        candidate: { ...preview.candidate, run_id: 'run_chain', candidate_id: 'cand_chain' },
      },
      error: null,
      status: 201,
    }));
    const acceptCatalogPreview = jest.fn(async () => ({
      data: { ...accepted, image_run_id: 'run_chain' }, error: null, status: 201,
    }));
    const client = {
      getComponentCatalog, previewCatalogSelection, acceptCatalogPreview,
      discardCatalogPreview: jest.fn(),
    } as unknown as TrustedApiClient;

    await renderWithAuth(React.createElement(ComponentCatalogPanel, {
      client,
      project: necklaceProject,
      spec: necklaceSpec,
      createdBy: 'usr_designer',
    }));
    await waitFor(() => expect(screen.getByText('Curb chain')).toBeTruthy());
    await fireEvent.press(screen.getByText('Curb chain'));
    expect(screen.getByText('Target chain manufacturing record')).toBeTruthy();
    expect(screen.getByText(/will not reuse the old chain's SKU/)).toBeTruthy();

    for (const [placeholder, value] of [
      ['Target chain width', '2.2'],
      ['Target profile thickness', '0.7'],
      ['Target end-ring OD', '3.8'],
      ['Target link thickness', '0.4'],
      ['Standard outside length', '4.1'],
      ['Standard inside length', '3.2'],
      ['Standard inside width', '1.4'],
      ['Required target-style reference', 'TARGET-CURB-2.2MM'],
    ] as const) {
      await fireEvent.changeText(screen.getByPlaceholderText(placeholder), value);
    }
    await waitFor(() => expect(screen.getByText(
      'Target geometry and production reference are complete for validation.',
    )).toBeTruthy());
    await fireEvent.press(screen.getByText('Preview protected change'));

    await waitFor(() => expect(previewCatalogSelection).toHaveBeenCalledWith(
      'ast_root',
      expect.objectContaining({
        component_path: 'chain.style',
        option_id: 'curb',
        chain_geometry: {
          construction: 'open_link',
          chain_width_mm: 2.2,
          profile_thickness_mm: 0.7,
          end_ring_outer_diameter_mm: 3.8,
          link_thickness_mm: 0.4,
          links_soldered: true,
          links: [{
            role: 'standard', length_mm: 4.1,
            inside_length_mm: 3.2, inside_width_mm: 1.4,
          }],
        },
        chain_production: {
          mode: 'stock', reference_kind: 'supplier_sku',
          reference: 'TARGET-CURB-2.2MM',
        },
      }),
    ));
    await fireEvent.press(screen.getByText('Apply to this variation'));
    await waitFor(() => expect(acceptCatalogPreview).toHaveBeenCalledWith(
      expect.objectContaining({ run_id: 'run_chain', candidate_id: 'cand_chain' }),
      { expected_design_version: 1, created_by: 'usr_designer' },
    ));
  });

  test('surfaces a stale selection as a reload state and preserves the current revision', async () => {
    const api = clientWith({
      data: null,
      status: 409,
      error: {
        code: 'stale_design_version',
        message: 'reload first',
        category: 'stale_version',
        status: 409,
        retryable: false,
      },
    });
    await renderWithAuth(React.createElement(ComponentCatalogPanel, {
      client: api.client,
      project: project(),
      spec: ringSpec,
      createdBy: 'usr_designer',
    }));

    await waitFor(() => expect(screen.getByText('Rose Gold')).toBeTruthy());
    await fireEvent.press(screen.getByText('Rose Gold'));
    await fireEvent.press(screen.getByText('Preview protected change'));
    expect(await screen.findByText('reload first')).toBeTruthy();
    expect(api.acceptCatalogPreview).not.toHaveBeenCalled();
  });

  test('catalog delta exposes deterministic dependent fields without inventing values', () => {
    expect(componentCatalogPathsForSpec({ jewelry_type: 'ring' })).toEqual([
      'metal.material', 'metal.color', 'stone.color', 'stone.cut', 'setting.style',
    ]);
    expect(componentCatalogPathsForSpec({ jewelry_type: 'bracelet' })).toEqual([]);
    expect(catalogFactoryDelta(ringSpec, {
      ...roseOption,
      id: 'emerald_cut',
      factory_fields: { 'stone.cut': 'emerald_cut' },
      derived_factory_fields: ['stone.carat'],
    })).toEqual([{
      path: 'stone.cut', before: 'oval_brilliant', after: 'emerald_cut', derived: false,
    }, {
      path: 'stone.carat', before: 1.25, after: undefined, derived: true,
    }]);
  });

  test('renders a warning candidate as temporary review evidence', async () => {
    const review: CatalogPreviewResult = {
      ...preview,
      status: 'review_required',
      image_run_id: 'run_warning',
      qa: {
        verdict: 'warn', accepted: false, review_required: true, score: 83,
        summary: 'Review the metal boundary.', failed_checks: [],
        warnings: ['Review the metal boundary.'], checks: [],
      },
      routing: {
        attempt_count: 2, used_retry: true, used_fallback: false,
        cache_hit: false, run_id: 'run_warning',
      },
      candidate: {
        run_id: 'run_warning',
        candidate_id: 'cand_warning',
        preview_url: 'https://facetta.test/candidate.png',
        accept_url: '/image-runs/run_warning/catalog-candidates/cand_warning/accept',
        discard_url: '/image-runs/run_warning/catalog-candidates/cand_warning',
        save_as_variation_url: '/image-runs/run_warning/catalog-candidates/cand_warning/save-as-variation',
        verdict: 'warn',
        expires_in_seconds: 900,
      },
    };
    const api = clientWith({ data: review, error: null, status: 202 });
    const onProjectChanged = jest.fn();
    await renderWithAuth(React.createElement(ComponentCatalogPanel, {
      client: api.client,
      project: project(),
      spec: ringSpec,
      createdBy: 'usr_designer',
      onProjectChanged,
    }));

    await waitFor(() => expect(screen.getByText('Rose Gold')).toBeTruthy());
    await fireEvent.press(screen.getByText('Rose Gold'));
    await fireEvent.press(screen.getByText('Preview protected change'));
    expect(await screen.findByText(/has not changed the active image or design record/)).toBeTruthy();
    expect(screen.getByLabelText('Temporary catalog preview')).toBeTruthy();
    expect(screen.getByText('Review the metal boundary.')).toBeTruthy();
    await fireEvent.press(screen.getByText('Apply to this variation'));
    await waitFor(() => expect(api.acceptCatalogPreview).toHaveBeenCalledWith(
      review.candidate,
      { expected_design_version: 1, created_by: 'usr_designer' },
    ));
    expect(onProjectChanged).toHaveBeenCalledWith(project('ast_2', 2));
  });
});
