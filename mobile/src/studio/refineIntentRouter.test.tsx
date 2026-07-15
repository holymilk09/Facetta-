import type { ComponentCatalog, StudioComponentTargeting } from '../trusted/types';
import { candidateCatalogPaths, routeRefineInstruction } from './refineIntentRouter';

const targeting = (ready: readonly string[]): StudioComponentTargeting => ({
  schema_version: 'facetta.studio-component-targeting.v1',
  asset_id: 'asset_1', asset_sha256: 'a'.repeat(64), jewelry_type: 'ring',
  component_map: {
    state: 'ready', scope: 'ring_v1', map_sha256: 'b'.repeat(64),
    mapper_contract: 'facetta.ring-component-map.v1', raster_width: 1000, raster_height: 1000,
  },
  catalog_paths: [
    'metal.color', 'metal.material', 'stone.color', 'stone.cut', 'setting.style', 'chain.style',
  ].map((componentPath) => ({
    component_path: componentPath as any,
    status: ready.includes(componentPath) ? 'ready' as const : 'unresolved' as const,
    required_component_kinds: [], component_ids: [],
    reason_code: ready.includes(componentPath) ? null : 'not_ready',
  })),
  authority: 'exact_revision_image_editing_only',
});

const catalog = (
  path: ComponentCatalog['component_path'],
  id: string,
  display: string,
): ComponentCatalog => ({
  component_path: path, display: path, applicable_jewelry_types: ['ring'],
  image_agent_status: 'catalog_ready', preview_execution_modes: ['provider'],
  options: [{
    id, display, visual_geometry: [], isolation_target: path, frozen_facts: [],
    factory_fields: {}, derived_factory_fields: [], selection_requirements: [],
  }],
});

describe('refineIntentRouter', () => {
  test('routes a unique authorized rose-gold option to its catalog', () => {
    expect(routeRefineInstruction({
      instruction: 'Use rose gold', exactSpecification: true,
      targeting: targeting(['metal.color']), catalogs: [catalog('metal.color', 'rose_gold', 'Rose gold')],
    })).toMatchObject({ kind: 'catalog', componentPath: 'metal.color', option: { id: 'rose_gold' } });
  });

  test('routes a cut only when the exact path is ready', () => {
    const emerald = catalog('stone.cut', 'emerald_cut', 'Emerald cut');
    expect(routeRefineInstruction({
      instruction: 'Use emerald cut', exactSpecification: true,
      targeting: targeting(['stone.cut']), catalogs: [emerald],
    }).kind).toBe('catalog');
    expect(routeRefineInstruction({
      instruction: 'Use emerald cut', exactSpecification: true,
      targeting: targeting([]), catalogs: [emerald],
    })).toMatchObject({ kind: 'markup_required', reason: 'unsupported_component' });
  });

  test('localized language always requires markup despite an option match', () => {
    expect(routeRefineInstruction({
      instruction: 'Make the left prong rose gold', exactSpecification: true,
      targeting: targeting(['metal.color']), catalogs: [catalog('metal.color', 'rose_gold', 'Rose gold')],
    })).toMatchObject({ kind: 'markup_required', reason: 'localized' });
  });

  test('structural language does not silently become appearance', () => {
    expect(routeRefineInstruction({
      instruction: 'Make the band wider', exactSpecification: true,
      targeting: targeting([]), catalogs: [],
    })).toMatchObject({ kind: 'markup_required', reason: 'structural' });
  });

  test('an authorized component without a unique option asks for a choice', () => {
    expect(routeRefineInstruction({
      instruction: 'Change the metal color', exactSpecification: true,
      targeting: targeting(['metal.color']), catalogs: [catalog('metal.color', 'rose_gold', 'Rose gold')],
    })).toMatchObject({ kind: 'component_choice', candidatePaths: ['metal.color'] });
  });

  test('ambiguous option matches never auto-route', () => {
    expect(routeRefineInstruction({
      instruction: 'Compare rose gold with rose gold', exactSpecification: true,
      targeting: targeting(['metal.color']),
      catalogs: [
        catalog('metal.color', 'rose_gold', 'Rose gold'),
        catalog('metal.color', 'rose_gold_alt', 'Rose gold'),
      ],
    }).kind).toBe('component_choice');
  });

  test('protected intent without exact facts requests starting facts', () => {
    expect(routeRefineInstruction({
      instruction: 'Use rose gold', exactSpecification: false,
      targeting: null, catalogs: [],
    })).toMatchObject({ kind: 'starting_facts_required', candidatePaths: ['metal.color'] });
  });

  test('presentation language remains an appearance change', () => {
    expect(routeRefineInstruction({
      instruction: 'Make the lighting warmer', exactSpecification: false,
      targeting: null, catalogs: [],
    })).toEqual({ kind: 'appearance', instruction: 'Make the lighting warmer' });
    expect(candidateCatalogPaths('Make the lighting warmer')).toEqual([]);
  });
});
