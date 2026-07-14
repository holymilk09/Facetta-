/// <reference types="jest" />

import { createTrustedApiClient, decodeReviseStudioFactsResult } from './client';

const asset = (id: string, version: number) => ({
  asset_id: id, root_id: 'project facts', parent_asset_id: version === 1 ? null : 'asset source',
  capability: 'LOCALIZED_EDIT', provenance: 'studio_fact_revision', revision: version,
  design_id: 'design_facts', design_version: version, media_type: 'image/png',
  image_url: `/assets/${id}/image`, created_by: 'designer',
});

const project = (id: string, version: number) => ({
  id: 'project facts', root_id: 'project facts', title: 'Exact ring', owner: 'designer',
  state: 'refining', design_id: 'design_facts',
  spec: {
    jewelry_type: 'ring', metal: { material: 'gold', karat: 18, color: 'rose', finish: 'polished' },
    stone: {
      species: 'sapphire', cut: 'oval', carat: 1.2,
      dimensions_mm: { length: 8, width: 6, depth: 3.8 },
      color: { trade: 'royal_blue', gia: 'blue' },
    },
  },
  active_asset_id: id, active_design_version: version, active_revision: asset(id, version),
  revisions: [], assets: [], derived_assets: [], factory_ready: false, factory_blockers: [],
});

const appliedPayload = {
  status: 'applied', project_root_id: 'project facts', source_asset_id: 'asset source',
  asset_id: 'asset revised', design_id: 'design_facts', previous_design_version: 1,
  design_version: 2,
  spec_change: [
    { path: 'stone.dimensions_mm.length', before: 8, after: 8.2, label: 'stone length' },
    { path: 'metal.color', before: 'yellow', after: 'rose', label: 'metal color' },
  ],
  project_detail: project('asset revised', 2),
};

describe('Studio fact revision client', () => {
  test('decodes exact applied and no-change lineage but rejects inconsistent revisions', () => {
    expect(decodeReviseStudioFactsResult(appliedPayload)?.status).toBe('applied');
    expect(decodeReviseStudioFactsResult({
      ...appliedPayload, status: 'no_change', asset_id: 'asset source', design_version: 1,
      spec_change: [], project_detail: project('asset source', 1),
    })?.status).toBe('no_change');
    expect(decodeReviseStudioFactsResult({
      ...appliedPayload, design_version: 4,
    })).toBeNull();
  });

  test('posts typed dimension and categorical changes with immutable lineage', async () => {
    const fetcher = jest.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => ({
      ok: true, status: 200, text: async () => JSON.stringify(appliedPayload),
    } as Response));
    const client = createTrustedApiClient({ baseUrl: 'https://facetta.test', fetcher });
    const result = await client.reviseStudioFacts('project facts', {
      expected_active_asset_id: 'asset source', expected_design_version: 1,
      created_by: 'designer', changes: [
        { path: 'stone.dimensions_mm.length', value: 8.2 },
        { path: 'metal.color', value: 'rose' },
        { path: 'setting.style', value: '4_prong_basket' },
        { path: 'setting.prong_tip_mm', value: 0.9 },
      ],
    });
    expect(result.error).toBeNull();
    expect(fetcher).toHaveBeenCalledWith(
      'https://facetta.test/studio/projects/project%20facts/facts/revise',
      expect.objectContaining({ method: 'POST' }),
    );
    expect(JSON.parse(String(fetcher.mock.calls[0]?.[1]?.body))).toEqual({
      expected_active_asset_id: 'asset source', expected_design_version: 1,
      created_by: 'designer', changes: [
        { path: 'stone.dimensions_mm.length', value: 8.2 },
        { path: 'metal.color', value: 'rose' },
        { path: 'setting.style', value: '4_prong_basket' },
        { path: 'setting.prong_tip_mm', value: 0.9 },
      ],
    });
  });

  test('maps stale transport errors without leaking persistence detail', async () => {
    const fetcher = jest.fn(async () => ({
      ok: false, status: 409, text: async () => JSON.stringify({
        detail: {
          code: 'stale_fact_revision', error_category: 'conflict',
          detail: 'the active image or specification changed before this fact edit',
        },
      }),
    } as Response));
    const client = createTrustedApiClient({ baseUrl: 'https://facetta.test', fetcher });
    const result = await client.reviseStudioFacts('project facts', {
      expected_active_asset_id: 'asset source', expected_design_version: 1,
      created_by: 'designer', changes: [{ path: 'band.width_mm', value: 2.2 }],
    });
    expect(result.error).toMatchObject({
      code: 'stale_fact_revision', category: 'conflict', status: 409,
    });
  });
});
