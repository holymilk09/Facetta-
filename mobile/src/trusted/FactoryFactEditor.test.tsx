import React from 'react';
import { fireEvent, render, waitFor } from '@testing-library/react-native';

import {
  applyFactoryFactChange,
  FactoryFactEditor,
} from './FactoryFactEditor';
import type { JsonObject } from './types';
import type { TrustedApiClient } from './client';
import type { ComponentCatalog, ComponentCatalogPath } from './types';

const SPEC: JsonObject = {
  schema_version: 1,
  jewelry_type: 'ring',
  template: 'halo_prong',
  stone: {
    species: 'sapphire',
    cut: 'oval_brilliant',
    count: 1,
    carat: 1.5,
    dimensions_mm: { length: 8, width: 6, depth: 3.8 },
    color: { trade: 'Royal Blue', gia: 'vivid violetish blue' },
  },
  side_stones: [{
    species: 'diamond',
    cut: 'round_brilliant',
    count: 16,
    carat: 0.03,
    position: 'halo',
    dimensions_mm: { length: 1.7, width: 1.7, depth: 1.05 },
  }],
  metal: { material: 'gold', karat: 18, color: 'white', finish: 'high_polish' },
  setting: { style: 'halo_prong', prong_count: 4, gallery_height_mm: 5.2 },
  band: { profile: 'rounded', width_mm: 2.2, thickness_mm: 1.8 },
  ring_size: { system: 'US', value: 6.5 },
  dimension_provenance: {
    'band.width_mm': {
      status: 'estimated_from_reference',
      method: 'reference_vision',
      source: 'designer drawing',
      confidence: 0.4,
    },
  },
  future_extension: { preserve: true },
};

test('typed factory changes preserve unknown fields and mark measured dimensions', () => {
  const next = applyFactoryFactChange(
    SPEC,
    'band.width_mm',
    2.8,
    'designer_confirmed',
  );

  expect((next.band as JsonObject).width_mm).toBe(2.8);
  expect(next.future_extension).toEqual({ preserve: true });
  expect((next.dimension_provenance as JsonObject)['band.width_mm']).toEqual({
    status: 'designer_confirmed',
    method: 'designer_input',
    source: 'trusted factory-fact editor',
    confidence: 1,
    note: 'Designer supplied or measured this value.',
  });
  expect((SPEC.band as JsonObject).width_mm).toBe(2.2);
});

test('reference-estimate edits stay visibly estimated', () => {
  const next = applyFactoryFactChange(
    SPEC,
    'stone.dimensions_mm.length',
    8.4,
    'estimated_from_reference',
  );
  const provenance = (
    next.dimension_provenance as JsonObject
  )['stone.dimensions_mm.length'] as JsonObject;

  expect(provenance.status).toBe('estimated_from_reference');
  expect(provenance.method).toBe('nominal_reference');
  expect(provenance.note).toContain('verify before manufacturing');
});

test('editor commits typed dimensions with the selected provenance basis', async () => {
  let current = SPEC;
  const onChange = jest.fn((next: JsonObject) => {
    current = next;
  });
  const view = await render(
    <FactoryFactEditor spec={current} onChange={onChange} />,
  );

  await fireEvent.press(view.getByText('Reference estimate'));
  const width = view.getByLabelText('Band width (mm)');
  await fireEvent.changeText(width, '2.6');
  await fireEvent(width, 'blur');

  expect(onChange).toHaveBeenCalledTimes(1);
  expect((current.band as JsonObject).width_mm).toBe(2.6);
  const provenance = (
    current.dimension_provenance as JsonObject
  )['band.width_mm'] as JsonObject;
  expect(provenance.status).toBe('estimated_from_reference');
  expect(view.getByText('Stone group 1')).toBeTruthy();
  expect(view.getByText('Ring construction')).toBeTruthy();
});

test('editor can fill a previously unknown optional factory dimension', async () => {
  const draft = JSON.parse(JSON.stringify(SPEC)) as JsonObject;
  (draft.setting as JsonObject).gallery_height_mm = null;
  let current = draft;
  const onChange = jest.fn((next: JsonObject) => {
    current = next;
  });
  const view = await render(
    <FactoryFactEditor spec={draft} onChange={onChange} />,
  );

  const gallery = view.getByLabelText('Gallery height (mm)');
  await fireEvent.changeText(gallery, '5.6');
  await fireEvent(gallery, 'blur');

  expect((current.setting as JsonObject).gallery_height_mm).toBe(5.6);
  expect((
    current.dimension_provenance as JsonObject
  )['setting.gallery_height_mm']).toMatchObject({
    status: 'designer_confirmed',
    method: 'designer_input',
  });
});

test('editor uses backend catalogs for coupled choices instead of free text', async () => {
  const catalog = (
    component_path: ComponentCatalogPath,
    display: string,
    options: ComponentCatalog['options'],
  ): ComponentCatalog => ({
    component_path,
    display,
    applicable_jewelry_types: ['ring'],
    image_agent_status: 'catalog_ready',
    options,
  });
  const option = (
    id: string,
    display: string,
    factory_fields: JsonObject,
  ) => ({
    id,
    display,
    visual_geometry: ['controlled geometry'],
    isolation_target: 'exact component only',
    frozen_facts: ['all other factory facts'],
    factory_fields,
    derived_factory_fields: [],
    selection_requirements: [],
  });
  const catalogs: Record<string, ComponentCatalog> = {
    'stone.color': catalog('stone.color', 'Stone color', [
      option('royal_blue', 'Royal Blue', { 'stone.color.trade': 'Royal Blue' }),
    ]),
    'stone.cut': catalog('stone.cut', 'Center cut', [
      option('oval_brilliant', 'Oval', { 'stone.cut': 'oval_brilliant' }),
      option('emerald_cut', 'Emerald Cut', { 'stone.cut': 'emerald_cut' }),
    ]),
    'metal.material': catalog('metal.material', 'Metal alloy', [
      option('gold_18_white', '18k White Gold', {
        'metal.material': 'gold', 'metal.karat': 18, 'metal.color': 'white',
      }),
      option('platinum', 'Platinum', {
        'metal.material': 'platinum', 'metal.karat': null, 'metal.color': null,
      }),
    ]),
    'metal.color': catalog('metal.color', 'Gold color', [
      option('white', 'White', { 'metal.color': 'white' }),
      option('rose', 'Rose', { 'metal.color': 'rose' }),
    ]),
    'setting.style': catalog('setting.style', 'Center setting', [
      option('halo_prong', 'Halo prong', { 'setting.style': 'halo_prong' }),
      option('bezel', 'Bezel', {
        'setting.style': 'bezel',
        'setting.prong_count': null,
        'setting.prong_tip_mm': null,
      }),
    ]),
  };
  const getComponentCatalog = jest.fn(async (path: ComponentCatalogPath) => ({
    data: catalogs[path] ?? null,
    error: null,
    status: 200,
  }));
  const nextSpec = applyFactoryFactChange(SPEC, 'metal.material', 'platinum');
  (nextSpec.metal as JsonObject).karat = null;
  (nextSpec.metal as JsonObject).color = null;
  const selectDraftCatalogOption = jest.fn(async () => ({
    data: {
      spec: nextSpec,
      spec_change: [{
        path: 'metal.material', before: 'gold', after: 'platinum', label: 'metal material',
      }],
      isolation_target: 'all visible ring metal',
      frozen_facts: ['stone'],
    },
    error: null,
    status: 200,
  }));
  const client = {
    getComponentCatalog,
    selectDraftCatalogOption,
  } as unknown as TrustedApiClient;
  const onChange = jest.fn();
  const view = await render(
    <FactoryFactEditor spec={SPEC} onChange={onChange} client={client} />,
  );

  expect(await view.findByText('Platinum')).toBeTruthy();
  expect(view.queryByLabelText('Metal material')).toBeNull();
  expect(view.queryByLabelText('Gold karat')).toBeNull();
  expect(view.queryByLabelText('Center prongs')).toBeNull();
  expect(view.getByLabelText('Gallery height (mm)')).toBeTruthy();
  await fireEvent.press(view.getByText('Platinum'));

  await waitFor(() => expect(selectDraftCatalogOption).toHaveBeenCalledWith({
    spec: SPEC,
    component_path: 'metal.material',
    option_id: 'platinum',
  }));
  expect(onChange).toHaveBeenCalledWith(nextSpec);
  expect(getComponentCatalog).toHaveBeenCalledTimes(5);
});

test('editor cascades controlled gemstone species into valid trade colors', async () => {
  const nextSpec = JSON.parse(JSON.stringify(SPEC)) as JsonObject;
  (nextSpec.stone as JsonObject).species = 'emerald';
  (nextSpec.stone as JsonObject).color = {
    trade: 'Muzo Green', gia: 'vivid warm slightly yellowish green',
  };
  const getStoneVocabulary = jest.fn(async () => ({
    data: [
      { id: 'sapphire', display: 'Sapphire', parameter_set: 'gemstone' },
      { id: 'emerald', display: 'Emerald', parameter_set: 'gemstone' },
      { id: 'pearl', display: 'Pearl', parameter_set: 'pearl' },
    ],
    error: null,
    status: 200,
  }));
  const getStoneVocabularyOptions = jest.fn(async (species: string) => ({
    data: {
      stone: species,
      display: species === 'emerald' ? 'Emerald' : 'Sapphire',
      parameter_set: 'gemstone' as const,
      colors: species === 'emerald'
        ? [{ term: 'Muzo Green', gia: 'vivid warm slightly yellowish green' }]
        : [{ term: 'Royal Blue', gia: 'vivid violetish blue' }],
      cuts: [{ id: 'oval_brilliant', name: 'Oval Brilliant' }],
    },
    error: null,
    status: 200,
  }));
  const selectDraftStone = jest.fn(async () => ({
    data: {
      spec: nextSpec,
      spec_change: [{
        path: 'stone.species', before: 'sapphire', after: 'emerald', label: 'species',
      }],
      isolation_target: 'center stone only',
      frozen_facts: ['stone.dimensions_mm'],
    },
    error: null,
    status: 200,
  }));
  const client = {
    getStoneVocabulary,
    getStoneVocabularyOptions,
    selectDraftStone,
  } as unknown as TrustedApiClient;
  const onChange = jest.fn();
  const view = await render(
    <FactoryFactEditor spec={SPEC} onChange={onChange} client={client} />,
  );

  expect(await view.findByText('Emerald')).toBeTruthy();
  expect(view.queryByLabelText('Center species')).toBeNull();
  await fireEvent.press(view.getByText('Emerald'));
  expect(await view.findByText('Muzo Green')).toBeTruthy();
  await fireEvent.press(view.getByText('Muzo Green'));

  await waitFor(() => expect(selectDraftStone).toHaveBeenCalledWith({
    spec: SPEC,
    species: 'emerald',
    trade_color: 'Muzo Green',
  }));
  expect(onChange).toHaveBeenCalledWith(nextSpec);
  expect(getStoneVocabularyOptions).toHaveBeenCalledWith('sapphire');
  expect(getStoneVocabularyOptions).toHaveBeenCalledWith('emerald');
});
