/// <reference types="jest" />

import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react-native';

import {
  catalogFactoryDelta,
  ComponentCatalogPanel,
  componentCatalogPathsForSpec,
} from './ComponentCatalogPanel';
import type { TrustedApiClient } from './client';
import type {
  CatalogApplyAccepted,
  CatalogApplyCallResult,
  CatalogApplyReviewRequired,
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

const accepted: CatalogApplyAccepted = {
  status: 'accepted',
  component_path: 'metal.color',
  option_id: 'rose',
  isolation_target: roseOption.isolation_target,
  asset_id: 'ast_2',
  design_version: 2,
  image_run_id: 'run_catalog',
  spec_change: [{ path: 'metal.color', before: 'yellow', after: 'rose', label: 'gold color' }],
  qa: {
    verdict: 'pass', accepted: true, review_required: false, score: 97,
    summary: 'Image checks passed.', failed_checks: [], warnings: [], checks: [],
  },
  routing: {
    attempt_count: 1, used_retry: false, used_fallback: false,
    cache_hit: false, run_id: 'run_catalog',
  },
  project: project('ast_2', 2),
};

function clientWith(
  applyResult: CatalogApplyCallResult = { data: accepted, error: null, status: 201 },
) {
  const getComponentCatalog = jest.fn(async (path: ComponentCatalogPath) => ({
    data: ringCatalog(path), error: null, status: 200,
  }));
  const getStoneVocabulary = jest.fn(async () => ({
    data: [], error: null, status: 200,
  }));
  const applyCatalogSelection = jest.fn(async () => applyResult);
  const acceptWarningCandidate = jest.fn(async () => ({
    data: project('ast_2', 2), error: null, status: 201,
  }));
  const recordImageRunFeedback = jest.fn(async () => ({
    data: { recorded: true }, error: null, status: 201,
  }));
  return {
    client: {
      getComponentCatalog,
      getStoneVocabulary,
      applyCatalogSelection,
      acceptWarningCandidate,
      recordImageRunFeedback,
    } as unknown as TrustedApiClient,
    getComponentCatalog, applyCatalogSelection, acceptWarningCandidate,
    recordImageRunFeedback,
  };
}

describe('ComponentCatalogPanel', () => {
  test('prioritizes material and stone quick choices before structural changes', async () => {
    const api = clientWith();
    await render(React.createElement(ComponentCatalogPanel, {
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
    const applyCatalogSelection = jest.fn(async () => ({
      data: accepted, error: null, status: 201,
    }));
    const client = {
      getComponentCatalog, getStoneVocabulary, applyCatalogSelection,
      acceptWarningCandidate: jest.fn(), recordImageRunFeedback: jest.fn(),
    } as unknown as TrustedApiClient;

    await render(React.createElement(ComponentCatalogPanel, {
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
    await fireEvent.press(screen.getByText('I confirm this exact visual and design change'));
    await fireEvent.press(screen.getByText('Apply protected change'));
    await waitFor(() => expect(applyCatalogSelection).toHaveBeenCalledWith(
      'ast_root', expect.objectContaining({
        component_path: 'stone.color', option_id: "Pigeon's Blood", stone_species: 'ruby',
      }),
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
    await render(React.createElement(ComponentCatalogPanel, {
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

  test('loads only applicable catalogs and requires explicit confirmation of exact scope', async () => {
    const api = clientWith();
    const onApplied = jest.fn();
    await render(React.createElement(ComponentCatalogPanel, {
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

    await fireEvent.press(screen.getByText('Apply protected change'));
    expect(api.applyCatalogSelection).not.toHaveBeenCalled();
    await fireEvent.press(screen.getByText('I confirm this exact visual and design change'));
    await fireEvent.press(screen.getByText('Apply protected change'));

    await waitFor(() => expect(api.applyCatalogSelection).toHaveBeenCalledWith(
      'ast_root',
      {
        component_path: 'metal.color',
        option_id: 'rose',
        expected_design_version: 1,
        created_by: 'usr_designer',
        variant: 0,
      },
    ));
    expect(onApplied).toHaveBeenCalledWith(accepted);
    expect(await screen.findByText(/specification version 2/)).toBeTruthy();
  });

  test('keeps native mobile review-only even after a designer selects an option', async () => {
    const api = clientWith();
    await render(React.createElement(ComponentCatalogPanel, {
      client: api.client,
      project: project(),
      spec: ringSpec,
      createdBy: 'usr_designer',
      mobileReviewOnly: true,
    }));

    await waitFor(() => expect(screen.getByText('Rose Gold')).toBeTruthy());
    await fireEvent.press(screen.getByText('Rose Gold'));
    expect(screen.getByText(/Mobile supports reviewing catalog choices/)).toBeTruthy();
    await fireEvent.press(screen.getByText('I confirm this exact visual and design change'));
    await fireEvent.press(screen.getByText('Apply protected change'));
    expect(api.applyCatalogSelection).not.toHaveBeenCalled();
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
    const applyCatalogSelection = jest.fn();
    const client = {
      getComponentCatalog, applyCatalogSelection,
    } as unknown as TrustedApiClient;
    await render(React.createElement(ComponentCatalogPanel, {
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
    expect(screen.queryByText('I confirm this exact visual and design change')).toBeNull();
    await fireEvent.press(screen.getByText('Apply protected change'));
    expect(applyCatalogSelection).not.toHaveBeenCalled();
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
    const applyCatalogSelection = jest.fn(async () => ({
      data: { ...accepted, component_path: 'chain.style', option_id: 'curb' },
      error: null,
      status: 201,
    } as CatalogApplyCallResult));
    const client = {
      getComponentCatalog, applyCatalogSelection,
    } as unknown as TrustedApiClient;

    await render(React.createElement(ComponentCatalogPanel, {
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
    await fireEvent.press(screen.getByText('I confirm this exact visual and design change'));
    await fireEvent.press(screen.getByText('Apply protected change'));

    await waitFor(() => expect(applyCatalogSelection).toHaveBeenCalledWith(
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
        catalog_status: 'stale',
        component_path: 'metal.color',
        option_id: 'rose',
        image_run_id: null,
        applicable_jewelry_types: ['ring'],
        current_asset_id: 'ast_new',
        current_design_version: 2,
      },
    });
    await render(React.createElement(ComponentCatalogPanel, {
      client: api.client,
      project: project(),
      spec: ringSpec,
      createdBy: 'usr_designer',
    }));

    await waitFor(() => expect(screen.getByText('Rose Gold')).toBeTruthy());
    await fireEvent.press(screen.getByText('Rose Gold'));
    await fireEvent.press(screen.getByText('I confirm this exact visual and design change'));
    await fireEvent.press(screen.getByText('Apply protected change'));
    expect(await screen.findByText(/project changed while the catalog was open/i)).toBeTruthy();
    expect(screen.getByText(/current revision is untouched/i)).toBeTruthy();
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
    const { asset_id: _acceptedAssetId, ...acceptedWithoutAsset } = accepted;
    const review: CatalogApplyReviewRequired = {
      ...acceptedWithoutAsset,
      status: 'review_required',
      design_version: 1,
      image_run_id: 'run_warning',
      next_spec: { ...ringSpec, metal: { material: 'gold', karat: 18, color: 'rose' } },
      qa: {
        verdict: 'warn', accepted: false, review_required: true, score: 83,
        summary: 'Review the metal boundary.', failed_checks: [],
        warnings: ['Review the metal boundary.'], checks: [],
      },
      routing: {
        attempt_count: 2, used_retry: true, used_fallback: false,
        cache_hit: false, run_id: 'run_warning',
      },
      project: project(),
      warning_candidate: {
        run_id: 'run_warning',
        candidate_id: 'cand_warning',
        preview_url: 'https://facetta.test/candidate.png',
        operation: 'LOCAL_EDIT',
        requested_change: 'Apply rose gold.',
      },
    };
    const api = clientWith({ data: review, error: null, status: 202 });
    const onProjectChanged = jest.fn();
    await render(React.createElement(ComponentCatalogPanel, {
      client: api.client,
      project: project(),
      spec: ringSpec,
      createdBy: 'usr_designer',
      onProjectChanged,
    }));

    await waitFor(() => expect(screen.getByText('Rose Gold')).toBeTruthy());
    await fireEvent.press(screen.getByText('Rose Gold'));
    await fireEvent.press(screen.getByText('I confirm this exact visual and design change'));
    await fireEvent.press(screen.getByText('Apply protected change'));
    expect(await screen.findByText(/has not replaced the active image or specification/)).toBeTruthy();
    expect(screen.getByLabelText('Catalog warning candidate preview')).toBeTruthy();
    expect(screen.getByText('Review the metal boundary.')).toBeTruthy();
    await fireEvent.press(screen.getByText('Accept after review'));
    await waitFor(() => expect(api.acceptWarningCandidate).toHaveBeenCalledWith(
      'run_warning', 'cand_warning', 1, 'usr_designer',
    ));
    expect(api.recordImageRunFeedback).toHaveBeenCalledWith(
      'run_warning', 'accepted', 'usr_designer',
    );
    expect(onProjectChanged).toHaveBeenCalledWith(project('ast_2', 2));
  });
});
