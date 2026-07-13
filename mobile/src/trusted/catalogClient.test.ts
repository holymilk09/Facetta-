/// <reference types="jest" />

import {
  classifyCatalogApplyFailure,
  createTrustedApiClient,
  decodeCatalogApplyResult,
  decodeCatalogPreviewAcceptResult,
  decodeCatalogPreviewResult,
  decodeComponentCatalog,
} from './client';

const option = {
  id: 'rose',
  display: 'Rose Gold',
  visual_geometry: [
    'warm pink rose-gold hue on every visible metal surface',
    'no change to component geometry',
  ],
  isolation_target: 'all visible metal surfaces; exclude every gemstone',
  frozen_facts: ['stone', 'side_stones', 'setting', 'band.width_mm'],
  factory_fields: { 'metal.color': 'rose' },
  derived_factory_fields: [],
  selection_requirements: ['metal.material == gold'],
};

const catalogPayload = {
  component_path: 'metal.color',
  display: 'Gold color',
  applicable_jewelry_types: ['ring'],
  image_agent_status: 'catalog_ready',
  preview_execution_modes: ['instant', 'provider'],
  options: [option],
};

const projectPayload = (assetId: string, version: number) => ({
  id: 'ast_root',
  root_id: 'ast_root',
  title: 'Catalog ring',
  owner: 'usr_designer',
  state: 'refining',
  design_id: 'dsn_ring',
  spec: {
    jewelry_type: 'ring',
    metal: { material: 'gold', karat: 18, color: version === 1 ? 'yellow' : 'rose' },
  },
  active_asset_id: assetId,
  active_design_version: version,
  active_revision: {
    asset_id: assetId,
    root_id: 'ast_root',
    capability: 'LOCALIZED_EDIT',
    provenance: 'catalog_revision',
    revision: version,
    design_id: 'dsn_ring',
    design_version: version,
  },
  revisions: [],
  assets: [],
  derived_assets: [],
  factory_ready: false,
  factory_blockers: [],
});

const qa = (verdict: 'pass' | 'warn') => ({
  verdict,
  accepted: verdict === 'pass',
  review_required: verdict === 'warn',
  score: verdict === 'pass' ? 97 : 82,
  summary: verdict === 'pass' ? 'Image checks passed.' : 'Review the color boundary.',
  failed_checks: verdict === 'pass' ? [] : ['minor_boundary_uncertainty'],
  warnings: verdict === 'warn' ? ['Review the color boundary.'] : [],
  checks: [],
});

const acceptedPayload = {
  status: 'accepted',
  component_path: 'metal.color',
  option_id: 'rose',
  isolation_target: option.isolation_target,
  asset_id: 'ast_2',
  design_version: 2,
  image_run_id: 'run_catalog',
  spec_change: [{
    path: 'metal.color', before: 'yellow', after: 'rose', label: 'gold color',
  }],
  qa: qa('pass'),
  routing: {
    attempt_count: 1,
    used_retry: false,
    used_fallback: false,
    cache_hit: false,
    run_id: 'run_catalog',
  },
  project: projectPayload('ast_2', 2),
};

const reviewPayload = {
  status: 'review_required',
  component_path: 'metal.color',
  option_id: 'rose',
  isolation_target: option.isolation_target,
  design_version: 1,
  image_run_id: 'run_warning',
  spec_change: [{
    path: 'metal.color', before: 'yellow', after: 'rose', label: 'gold color',
  }],
  next_spec: {
    jewelry_type: 'ring',
    metal: { material: 'gold', karat: 18, color: 'rose' },
  },
  qa: qa('warn'),
  routing: {
    attempt_count: 2,
    used_retry: true,
    used_fallback: false,
    cache_hit: false,
    run_id: 'run_warning',
  },
  project: projectPayload('ast_root', 1),
  warning_candidate: {
    run_id: 'run_warning',
    candidate_id: 'cand_warning',
    preview_url: '/image-runs/run_warning/candidates/cand_warning/image',
    operation: 'LOCAL_EDIT',
    requested_change: 'Apply the exact rose-gold catalog selection.',
  },
};

const previewPayload = {
  status: 'preview_ready',
  component_path: 'metal.color',
  option_id: 'rose',
  isolation_target: option.isolation_target,
  source_asset_id: 'ast_root',
  design_version: 1,
  image_run_id: 'run_preview',
  spec_change: [{
    path: 'metal.color', before: 'yellow', after: 'rose', label: 'gold color',
  }],
  next_spec: {
    jewelry_type: 'ring',
    metal: { material: 'gold', karat: 18, color: 'rose' },
  },
  qa: qa('pass'),
  routing: {
    attempt_count: 1,
    used_retry: false,
    used_fallback: false,
    cache_hit: false,
    run_id: 'run_preview',
  },
  project: projectPayload('ast_root', 1),
  candidate: {
    run_id: 'run_preview',
    candidate_id: 'cand_preview',
    preview_url: '/image-runs/run_preview/catalog-candidates/cand_preview/image',
    accept_url: '/image-runs/run_preview/catalog-candidates/cand_preview/accept',
    discard_url: '/image-runs/run_preview/catalog-candidates/cand_preview',
    save_as_variation_url: '/image-runs/run_preview/catalog-candidates/cand_preview/save-as-variation',
    verdict: 'pass',
    expires_in_seconds: 7200,
  },
};

const instantPreviewPayload = {
  ...previewPayload,
  routing: {
    ...previewPayload.routing,
    execution_mode: 'instant_masked_transform',
    provider_calls: 0,
    attempt_count: 0,
  },
  candidate: {
    ...previewPayload.candidate,
    studio_job_id: null,
  },
};

const acceptedPreviewPayload = {
  status: 'accepted',
  asset_id: 'ast_2',
  design_version: 2,
  image_run_id: 'run_preview',
  spec_change: previewPayload.spec_change,
  project: projectPayload('ast_2', 2),
};

describe('component catalog client contracts', () => {
  test('decodes complete catalogs and both safe success outcomes', () => {
    expect(decodeComponentCatalog(catalogPayload)).toEqual(catalogPayload);

    const accepted = decodeCatalogApplyResult(acceptedPayload);
    expect(accepted?.status).toBe('accepted');
    expect(accepted?.status === 'accepted' ? accepted.asset_id : null).toBe('ast_2');

    const review = decodeCatalogApplyResult(reviewPayload);
    expect(review?.status).toBe('review_required');
    expect(review?.status === 'review_required'
      ? review.warning_candidate.candidate_id : null).toBe('cand_warning');
  });

  test.each([
    [{ ...catalogPayload, image_agent_status: 'experimental' }],
    [{ ...catalogPayload, preview_execution_modes: [] }],
    [{ ...catalogPayload, preview_execution_modes: ['instant', 'instant'] }],
    [{ ...catalogPayload, preview_execution_modes: ['instant', 'local'] }],
    [{ ...catalogPayload, component_path: 'band.secret_profile' }],
    [{ ...catalogPayload, options: [{ ...option, frozen_facts: [] }] }],
    [{ ...catalogPayload, options: [{ ...option, selection_requirements: [7] }] }],
    [{ ...catalogPayload, options: [option, option] }],
  ])('fails closed on malformed catalog control facts', (payload) => {
    expect(decodeComponentCatalog(payload)).toBeNull();
  });

  test.each([
    [{ ...acceptedPayload, qa: qa('warn') }],
    [{ ...acceptedPayload, project: projectPayload('different_asset', 2) }],
    [{
      ...acceptedPayload,
      project: {
        ...projectPayload('ast_2', 2),
        spec: { jewelry_type: 'ring', metal: { color: 'white' } },
      },
    }],
    [{ ...acceptedPayload, routing: { ...acceptedPayload.routing, run_id: 'other_run' } }],
    [(({ next_spec: _nextSpec, ...payload }) => payload)(reviewPayload)],
    [{
      ...reviewPayload,
      warning_candidate: { ...reviewPayload.warning_candidate, run_id: 'other_run' },
    }],
  ])('fails closed when catalog revision provenance is inconsistent', (payload) => {
    expect(decodeCatalogApplyResult(payload)).toBeNull();
  });

  test('classifies warning, stale, and category-pending errors without prose parsing', () => {
    expect(classifyCatalogApplyFailure({
      code: 'image_quality_failed', message: 'failed', category: 'quality',
      status: 422, retryable: false,
    }).catalog_status).toBe('warning');
    expect(classifyCatalogApplyFailure({
      code: 'stale_design_version', message: 'stale', category: 'stale_version',
      status: 409, retryable: false,
    }).catalog_status).toBe('stale');
    expect(classifyCatalogApplyFailure({
      code: 'catalog_category_pending', message: 'pending', category: 'conflict',
      status: 409, retryable: false,
      details: { component_path: 'chain.style', current_design_version: 3 },
    })).toMatchObject({
      catalog_status: 'category_pending',
      component_path: 'chain.style',
      current_design_version: 3,
    });
  });

  test('decodes temporary preview and acceptance lineage without treating it as a revision', () => {
    expect(decodeCatalogPreviewResult(previewPayload)).toMatchObject({
      status: 'preview_ready',
      source_asset_id: 'ast_root',
      design_version: 1,
      candidate: { verdict: 'pass', expires_in_seconds: 7200 },
    });
    expect(decodeCatalogPreviewAcceptResult(acceptedPreviewPayload)).toMatchObject({
      status: 'accepted',
      asset_id: 'ast_2',
      design_version: 2,
    });
    expect(decodeCatalogPreviewResult(instantPreviewPayload)).toMatchObject({
      status: 'preview_ready',
      candidate: { studio_job_id: null },
      routing: { attempt_count: 0 },
    });
  });

  test.each([
    [{ ...instantPreviewPayload, component_path: 'stone.cut' }],
    [{ ...instantPreviewPayload, routing: { ...instantPreviewPayload.routing, provider_calls: 1 } }],
    [{ ...instantPreviewPayload, routing: { ...instantPreviewPayload.routing, attempt_count: 1 } }],
    [{ ...instantPreviewPayload, routing: { ...instantPreviewPayload.routing, used_retry: true } }],
    [{ ...instantPreviewPayload, routing: { ...instantPreviewPayload.routing, used_fallback: true } }],
    [{ ...instantPreviewPayload, routing: { ...instantPreviewPayload.routing, cache_hit: true } }],
    [{ ...instantPreviewPayload, candidate: { ...instantPreviewPayload.candidate, studio_job_id: 'job_1' } }],
    [{ ...previewPayload, routing: { ...previewPayload.routing, execution_mode: 'instant_unknown' } }],
  ])('rejects malformed or job-bound instant preview routing', (payload) => {
    expect(decodeCatalogPreviewResult(payload)).toBeNull();
  });

  test.each([
    [{ ...previewPayload, source_asset_id: 'different_asset' }],
    [{ ...previewPayload, status: 'review_required' }],
    [{ ...previewPayload, candidate: { ...previewPayload.candidate, verdict: 'warn' } }],
    [{ ...previewPayload, candidate: { ...previewPayload.candidate, run_id: 'other_run' } }],
    [{
      ...previewPayload,
      candidate: {
        ...previewPayload.candidate,
        accept_url: '/image-runs/run_preview/catalog-candidates/other/accept',
      },
    }],
    [{
      ...previewPayload,
      next_spec: {
        jewelry_type: 'ring',
        metal: { material: 'gold', karat: 18, color: 'white' },
      },
    }],
  ])('fails closed on mismatched temporary preview lineage', (payload) => {
    expect(decodeCatalogPreviewResult(payload)).toBeNull();
  });

  test('previews, accepts, and discards through normalized candidate capability URLs', async () => {
    const fetcher = jest.fn(async (
      input: RequestInfo | URL,
      init?: RequestInit,
    ) => {
      const url = String(input);
      if (init?.method === 'DELETE') {
        return {
          ok: true,
          status: 204,
          text: async () => '',
        } as unknown as Response;
      }
      const payload = url.endsWith('/accept') ? acceptedPreviewPayload : previewPayload;
      return {
        ok: true,
        status: url.endsWith('/accept') ? 201 : 201,
        text: async () => JSON.stringify(payload),
      } as unknown as Response;
    });
    const client = createTrustedApiClient({ baseUrl: 'https://facetta.test/', fetcher });
    const request = {
      component_path: 'metal.color' as const,
      option_id: 'rose',
      expected_design_version: 1,
      created_by: 'usr_designer',
    };

    const preview = await client.previewCatalogSelection('ast_root', request);
    expect(preview.error).toBeNull();
    expect(preview.data?.candidate).toMatchObject({
      preview_url: 'https://facetta.test/image-runs/run_preview/catalog-candidates/cand_preview/image',
      accept_url: 'https://facetta.test/image-runs/run_preview/catalog-candidates/cand_preview/accept',
      discard_url: 'https://facetta.test/image-runs/run_preview/catalog-candidates/cand_preview',
      save_as_variation_url: 'https://facetta.test/image-runs/run_preview/catalog-candidates/cand_preview/save-as-variation',
    });
    if (preview.data === null) throw new Error('preview fixture must decode');

    const accepted = await client.acceptCatalogPreview(preview.data.candidate, {
      expected_design_version: 1,
      created_by: 'usr_designer',
    });
    expect(accepted.error).toBeNull();
    expect(accepted.data?.asset_id).toBe('ast_2');

    const discarded = await client.discardCatalogPreview(preview.data.candidate);
    expect(discarded).toEqual({
      data: { status: 'discarded' }, error: null, status: 204,
    });
    expect(fetcher.mock.calls.map(([url, init]) => [url, init?.method])).toEqual([
      ['https://facetta.test/assets/ast_root/catalog/preview', 'POST'],
      ['https://facetta.test/image-runs/run_preview/catalog-candidates/cand_preview/accept', 'POST'],
      ['https://facetta.test/image-runs/run_preview/catalog-candidates/cand_preview', 'DELETE'],
    ]);
    expect(JSON.parse(String(fetcher.mock.calls[0]?.[1]?.body))).toEqual({
      ...request,
      variant: 0,
      execution_mode: 'provider',
    });
    expect(JSON.parse(String(fetcher.mock.calls[1]?.[1]?.body))).toEqual({
      expected_design_version: 1,
      created_by: 'usr_designer',
    });
  });

  test('serializes an opt-in instant preview without a Studio job', async () => {
    const fetcher = jest.fn(async (_url: RequestInfo | URL, _init?: RequestInit) => ({
      ok: true,
      status: 201,
      text: async () => JSON.stringify(instantPreviewPayload),
    } as unknown as Response));
    const client = createTrustedApiClient({ baseUrl: 'https://facetta.test', fetcher });

    const preview = await client.previewCatalogSelection('ast_root', {
      component_path: 'metal.color',
      option_id: 'rose',
      expected_design_version: 1,
      created_by: 'usr_designer',
      execution_mode: 'instant',
    });

    expect(preview.error).toBeNull();
    expect(JSON.parse(String(fetcher.mock.calls[0]?.[1]?.body))).toEqual({
      component_path: 'metal.color',
      option_id: 'rose',
      expected_design_version: 1,
      created_by: 'usr_designer',
      variant: 0,
      execution_mode: 'instant',
    });
  });

  test('preserves explicit instant capability errors for guarded fallback', async () => {
    const fetcher = jest.fn(async () => ({
      ok: false,
      status: 422,
      text: async () => JSON.stringify({
        code: 'instant_gold_color_unsupported',
        category: 'capability',
        detail: 'This quick-preview transform is not deployed yet.',
      }),
    } as unknown as Response));
    const client = createTrustedApiClient({ baseUrl: 'https://facetta.test', fetcher });

    const preview = await client.previewCatalogSelection('ast_root', {
      component_path: 'metal.color', option_id: 'future_gold',
      expected_design_version: 1, created_by: 'usr_designer', execution_mode: 'instant',
    });

    expect(preview.error).toMatchObject({
      code: 'instant_gold_color_unsupported', category: 'capability',
    });
  });

  test('never sends credentials to cross-origin or mismatched candidate URLs', async () => {
    const fetcher = jest.fn();
    const client = createTrustedApiClient({
      baseUrl: 'https://facetta.test',
      fetcher,
      getAccessToken: () => 'secret-test-token',
    });
    const unsafe = {
      ...previewPayload.candidate,
      accept_url: 'https://attacker.invalid/image-runs/run_preview/catalog-candidates/cand_preview/accept',
      verdict: previewPayload.candidate.verdict as 'pass' | 'warn',
    };

    const accepted = await client.acceptCatalogPreview(unsafe, {
      expected_design_version: 1,
      created_by: 'usr_designer',
    });
    expect(accepted.error).toMatchObject({
      code: 'INVALID_CANDIDATE_URL', category: 'validation',
    });
    expect(fetcher).not.toHaveBeenCalled();
  });

  test('uses encoded typed routes and returns an absolute warning preview', async () => {
    const fetcher = jest.fn(async (
      input: RequestInfo | URL,
      init?: RequestInit,
    ) => ({
      ok: true,
      status: init?.method === 'POST' ? 202 : 200,
      text: async () => JSON.stringify(
        init?.method === 'POST' ? reviewPayload : catalogPayload,
      ),
    } as unknown as Response));
    const client = createTrustedApiClient({ baseUrl: 'https://facetta.test', fetcher });

    const catalog = await client.getComponentCatalog('metal.color');
    const revision = await client.applyCatalogSelection('asset current', {
      component_path: 'metal.color',
      option_id: 'rose',
      expected_design_version: 1,
      created_by: 'usr_designer',
    });

    expect(catalog.error).toBeNull();
    expect(revision.error).toBeNull();
    expect(fetcher.mock.calls[0]?.[0]).toBe(
      'https://facetta.test/vocabulary/components/metal.color',
    );
    expect(fetcher.mock.calls[1]?.[0]).toBe(
      'https://facetta.test/assets/asset%20current/catalog/apply',
    );
    expect(JSON.parse(String(fetcher.mock.calls[1]?.[1]?.body))).toEqual({
      component_path: 'metal.color',
      option_id: 'rose',
      expected_design_version: 1,
      created_by: 'usr_designer',
      variant: 0,
    });
    expect(revision.data?.status === 'review_required'
      ? revision.data.warning_candidate.preview_url : null).toBe(
      'https://facetta.test/image-runs/run_warning/candidates/cand_warning/image',
    );
  });

  test('requests the center-stone palette in its selected species context', async () => {
    const stonePalette = {
      ...catalogPayload,
      component_path: 'stone.color',
      display: 'Center stone species and color',
      options: [{
        ...option,
        id: 'Royal Blue',
        display: 'Royal Blue',
        factory_fields: {
          'stone.species': 'sapphire',
          'stone.color': { trade: 'Royal Blue', gia: 'vivid blue' },
        },
      }],
    };
    const fetcher = jest.fn(async (_input: RequestInfo | URL) => ({
      ok: true,
      status: 200,
      text: async () => JSON.stringify(stonePalette),
    } as unknown as Response));
    const client = createTrustedApiClient({ baseUrl: 'https://facetta.test', fetcher });

    const palette = await client.getComponentCatalog('stone.color', {
      stoneSpecies: 'sapphire',
    });

    expect(palette.data?.component_path).toBe('stone.color');
    expect(fetcher.mock.calls[0]?.[0]).toBe(
      'https://facetta.test/vocabulary/components/stone.color?stone_species=sapphire',
    );
  });

  test('compiles a controlled catalog choice against an unpersisted draft', async () => {
    const nextSpec = {
      jewelry_type: 'ring',
      template: 'halo_prong',
      metal: { material: 'platinum', karat: null, color: null },
    };
    const fetcher = jest.fn(async (
      _input: RequestInfo | URL,
      _init?: RequestInit,
    ) => ({
      ok: true,
      status: 200,
      text: async () => JSON.stringify({
        spec: nextSpec,
        spec_change: [
          { path: 'metal.material', before: 'gold', after: 'platinum', label: 'metal material' },
          { path: 'metal.karat', before: 18, after: null, label: 'metal karat' },
          { path: 'metal.color', before: 'white', after: null, label: 'metal color' },
        ],
        isolation_target: 'all visible ring metal',
        frozen_facts: ['stone', 'side_stones', 'setting', 'band'],
      }),
    } as unknown as Response));
    const client = createTrustedApiClient({ baseUrl: 'https://facetta.test', fetcher });
    const spec = {
      jewelry_type: 'ring',
      template: 'halo_prong',
      metal: { material: 'gold', karat: 18, color: 'white' },
    };

    const result = await client.selectDraftCatalogOption({
      spec,
      component_path: 'metal.material',
      option_id: 'platinum',
    });

    expect(result.error).toBeNull();
    expect(result.data?.spec).toEqual(nextSpec);
    expect(result.data?.spec_change).toHaveLength(3);
    expect(fetcher.mock.calls[0]?.[0]).toBe(
      'https://facetta.test/specs/catalog/select',
    );
    expect(JSON.parse(String(fetcher.mock.calls[0]?.[1]?.body))).toEqual({
      spec,
      component_path: 'metal.material',
      option_id: 'platinum',
    });
  });

  test('loads cascading gemstone vocabulary and compiles one stone choice', async () => {
    const selectedSpec = {
      jewelry_type: 'ring',
      stone: {
        species: 'emerald',
        color: { trade: 'Muzo Green', gia: 'vivid warm green' },
      },
    };
    const fetcher = jest.fn(async (
      input: RequestInfo | URL,
      init?: RequestInit,
    ) => {
      const url = String(input);
      const payload = init?.method === 'POST'
        ? {
            spec: selectedSpec,
            spec_change: [{
              path: 'stone.species', before: 'sapphire', after: 'emerald',
              label: 'center stone species',
            }],
            isolation_target: 'center stone only',
            frozen_facts: ['stone.cut', 'stone.dimensions_mm'],
          }
        : url.endsWith('/options')
          ? {
              stone: 'emerald', display: 'Emerald', parameter_set: 'gemstone',
              colors: [{ term: 'Muzo Green', gia: 'vivid warm green' }],
              cuts: [{ id: 'emerald_cut', name: 'Emerald Cut' }],
            }
          : {
              stones: [
                { id: 'emerald', display: 'Emerald', parameter_set: 'gemstone' },
                { id: 'pearl', display: 'Pearl', parameter_set: 'pearl' },
              ],
            };
      return {
        ok: true,
        status: 200,
        text: async () => JSON.stringify(payload),
      } as unknown as Response;
    });
    const client = createTrustedApiClient({ baseUrl: 'https://facetta.test', fetcher });
    const sourceSpec = {
      jewelry_type: 'ring',
      stone: { species: 'sapphire', color: { trade: 'Royal Blue', gia: 'blue' } },
    };

    const entries = await client.getStoneVocabulary();
    const options = await client.getStoneVocabularyOptions('emerald');
    const selection = await client.selectDraftStone({
      spec: sourceSpec,
      species: 'emerald',
      trade_color: 'Muzo Green',
    });

    expect(entries.data?.map((item) => item.id)).toEqual(['emerald', 'pearl']);
    expect(options.data?.colors[0]?.term).toBe('Muzo Green');
    expect(selection.data?.spec).toEqual(selectedSpec);
    expect(fetcher.mock.calls.map(([url]) => url)).toEqual([
      'https://facetta.test/vocabulary/stones',
      'https://facetta.test/vocabulary/stones/emerald/options',
      'https://facetta.test/specs/stone/select',
    ]);
    expect(JSON.parse(String(fetcher.mock.calls[2]?.[1]?.body))).toEqual({
      spec: sourceSpec,
      species: 'emerald',
      trade_color: 'Muzo Green',
    });
  });

  test('sends exact target chain geometry and production records', async () => {
    const fetcher = jest.fn(async (
      _input: RequestInfo | URL,
      _init?: RequestInit,
    ) => ({
      ok: false,
      status: 422,
      text: async () => JSON.stringify({
        code: 'chain_target_incompatible',
        category: 'validation',
        detail: 'fixture response',
      }),
    } as unknown as Response));
    const client = createTrustedApiClient({ baseUrl: 'https://facetta.test', fetcher });
    await client.applyCatalogSelection('necklace root', {
      component_path: 'chain.style',
      option_id: 'curb',
      expected_design_version: 3,
      created_by: 'usr_designer',
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
        mode: 'stock',
        reference_kind: 'supplier_sku',
        reference: 'TARGET-CURB-2.2MM',
      },
    });

    expect(fetcher.mock.calls[0]?.[0]).toBe(
      'https://facetta.test/assets/necklace%20root/catalog/apply',
    );
    expect(JSON.parse(String(fetcher.mock.calls[0]?.[1]?.body))).toMatchObject({
      component_path: 'chain.style',
      option_id: 'curb',
      chain_geometry: {
        construction: 'open_link',
        chain_width_mm: 2.2,
        links: [{ role: 'standard', length_mm: 4.1 }],
      },
      chain_production: {
        mode: 'stock',
        reference_kind: 'supplier_sku',
        reference: 'TARGET-CURB-2.2MM',
      },
    });
  });

  test('decodes indexed chain spec changes without weakening path validation', () => {
    const source = {
      jewelry_type: 'necklace',
      chain: {
        style: 'cable',
        geometry: { links: [{ length_mm: 3.8 }] },
      },
    };
    const target = {
      jewelry_type: 'necklace',
      chain: {
        style: 'curb',
        geometry: { links: [{ length_mm: 4.1 }] },
      },
    };
    const chainPayload = {
      ...reviewPayload,
      component_path: 'chain.style',
      option_id: 'curb',
      spec_change: [
        { path: 'chain.style', before: 'cable', after: 'curb', label: 'chain style' },
        {
          path: 'chain.geometry.links[0].length_mm',
          before: 3.8,
          after: 4.1,
          label: 'link length',
        },
      ],
      next_spec: target,
      project: { ...projectPayload('ast_root', 1), spec: source },
    };
    expect(decodeCatalogApplyResult(chainPayload)?.status).toBe('review_required');
    expect(decodeCatalogApplyResult({
      ...chainPayload,
      spec_change: [{
        path: 'chain.geometry.links[-1].length_mm',
        before: 3.8,
        after: 4.1,
        label: 'invalid link',
      }],
    })).toBeNull();
  });

  test.each([
    [
      { code: 'stale_asset_revision', category: 'stale_version', detail: 'reload' },
      'stale',
    ],
    [
      {
        code: 'catalog_category_pending', category: 'capability', detail: 'pending',
        component_path: 'chain.style',
      },
      'category_pending',
    ],
  ])('turns catalog API conflicts into a typed client state', async (payload, state) => {
    const fetcher = jest.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => ({
      ok: false,
      status: 409,
      text: async () => JSON.stringify(payload),
    } as unknown as Response));
    const client = createTrustedApiClient({ baseUrl: 'https://facetta.test', fetcher });
    const result = await client.applyCatalogSelection('ast_root', {
      component_path: 'chain.style',
      option_id: 'curb',
      expected_design_version: 1,
      created_by: 'usr_designer',
    });
    expect(result.error?.catalog_status).toBe(state);
  });

  test('rejects success payloads returned under the wrong HTTP contract', async () => {
    const fetcher = jest.fn(async (
      _input: RequestInfo | URL,
      init?: RequestInit,
    ) => ({
      ok: true,
      status: 200,
      text: async () => JSON.stringify(
        init?.method === 'POST' ? acceptedPayload : catalogPayload,
      ),
    } as unknown as Response));
    const client = createTrustedApiClient({ baseUrl: 'https://facetta.test', fetcher });
    const result = await client.applyCatalogSelection('ast_root', {
      component_path: 'metal.color',
      option_id: 'rose',
      expected_design_version: 1,
      created_by: 'usr_designer',
    });
    expect(result.error).toMatchObject({
      code: 'INVALID_RESPONSE',
      category: 'decode',
      catalog_status: 'error',
    });
  });

  test('reopens a typed catalog preview with normalized decision capabilities', async () => {
    const fetcher = jest.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => ({
      ok: true, status: 200,
      text: async () => JSON.stringify({ candidates: [{
        candidate_id: 'cand warning', image_run_id: 'run warning',
        source_asset_id: 'ast_root', component_path: 'metal.color', option_id: 'rose',
        requested_change: 'Apply rose gold', verdict: 'warn',
        preview_url: '/image-runs/run%20warning/catalog-candidates/cand%20warning/image',
        save_as_variation_url: '/image-runs/run%20warning/catalog-candidates/cand%20warning/save-as-variation',
        next_spec: reviewPayload.next_spec, spec_change: reviewPayload.spec_change,
        qa: qa('warn'), routing: { ...reviewPayload.routing, run_id: 'run warning' },
        expires_at: '2099-01-01T00:00:00Z',
      }] }),
    } as Response));
    const client = createTrustedApiClient({ baseUrl: 'https://facetta.test', fetcher });
    const result = await client.listCatalogPreviews('ast_root');
    expect(result.error).toBeNull();
    expect(result.data?.candidates[0]?.candidate).toMatchObject({
      run_id: 'run warning', candidate_id: 'cand warning',
      preview_url: 'https://facetta.test/image-runs/run%20warning/catalog-candidates/cand%20warning/image',
      accept_url: 'https://facetta.test/image-runs/run%20warning/catalog-candidates/cand%20warning/accept',
      discard_url: 'https://facetta.test/image-runs/run%20warning/catalog-candidates/cand%20warning',
      save_as_variation_url: 'https://facetta.test/image-runs/run%20warning/catalog-candidates/cand%20warning/save-as-variation',
    });
  });

  test('posts an exact catalog preview to its typed save-as-variation endpoint', async () => {
    const fetcher = jest.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => ({
      ok: true, status: 201,
      text: async () => JSON.stringify({
        status: 'saved_as_variation', family_id: 'family_catalog', variation_index: 2,
        source_project_id: 'ast_1', source_asset_id: 'ast_1',
        design_id: 'dsn_variation', design_version: 1,
        project: projectPayload('ast_2', 1),
      }),
    } as Response));
    const client = createTrustedApiClient({ baseUrl: 'https://facetta.test', fetcher });
    const result = await client.saveCatalogPreviewAsVariation({
      ...previewPayload.candidate, verdict: 'pass' as const,
    }, {
      created_by: 'usr_designer', label: '  Rose halo  ',
    });
    expect(result.error).toBeNull();
    expect(result.data).toMatchObject({
      source_project_id: 'ast_1', source_asset_id: 'ast_1',
    });
    expect(fetcher).toHaveBeenCalledWith(
      'https://facetta.test/image-runs/run_preview/catalog-candidates/cand_preview/save-as-variation',
      expect.objectContaining({ method: 'POST' }),
    );
    expect(JSON.parse(String(fetcher.mock.calls[0]?.[1]?.body))).toEqual({
      created_by: 'usr_designer', label: 'Rose halo',
    });
  });
});
