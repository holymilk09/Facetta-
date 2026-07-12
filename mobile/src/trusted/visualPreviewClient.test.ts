/// <reference types="jest" />

import {
  createTrustedApiClient,
  decodeVisualPreviewApplyResult,
  decodeVisualPreviewResult,
} from './client';

const qa = {
  verdict: 'pass', accepted: true, review_required: false, score: 0.99,
  summary: 'Geometry preserved.', failed_checks: [], warnings: [],
  checks: [{
    key: 'geometry', label: 'Geometry', verdict: 'pass', severity: 'hard', message: 'Preserved.',
  }],
};

const asset = (id: string, parent: string | null, revision: number) => ({
  asset_id: id, root_id: 'project visual', parent_asset_id: parent,
  capability: 'VISUAL_ONLY_EDIT', provenance: 'studio_visual_preview', revision,
  design_id: null, design_version: null, media_type: 'image/png',
  image_url: `/assets/${id}/image`, created_by: 'designer',
});

const source = asset('asset source', null, 1);
const applied = asset('asset applied', source.asset_id, 2);
const projectPayload = {
  id: 'project visual', root_id: 'project visual', title: 'Visual project', owner: 'designer',
  state: 'refining', design_id: null, spec: null, active_asset_id: applied.asset_id,
  active_design_version: null, active_revision: applied,
  revisions: [
    { revision: 1, asset: source, spec_version: null, spec_change: [], ignored_fields: [] },
    { revision: 2, asset: applied, spec_version: null, spec_change: [], ignored_fields: [] },
  ],
  assets: [source, applied], derived_assets: [], factory_ready: false,
};

const previewPayload = {
  project_id: 'project visual', source_asset_id: 'asset source', image_run_id: 'run visual',
  candidate: {
    candidate_id: 'candidate visual',
    preview_url: '/studio/image-runs/run%20visual/visual-candidates/candidate%20visual/image',
    verdict: 'pass', qa,
  },
};

const applyPayload = {
  status: 'applied', project_id: 'project visual', source_asset_id: 'asset source',
  new_asset_id: 'asset applied', design_version: null, project: projectPayload,
};

describe('pre-spec visual preview client', () => {
  test('fails closed when candidate QA and verdict disagree or acceptance invents a spec version', () => {
    expect(decodeVisualPreviewResult({
      ...previewPayload,
      candidate: { ...previewPayload.candidate, verdict: 'warn' },
    })).toBeNull();
    expect(decodeVisualPreviewApplyResult({ ...applyPayload, design_version: 1 })).toBeNull();
    expect(decodeVisualPreviewApplyResult({
      ...applyPayload,
      project: { ...projectPayload, active_asset_id: 'asset source' },
    })).toBeNull();
  });

  test('uses encoded typed routes and preserves the active-asset concurrency token', async () => {
    const calls: Array<[string, RequestInit | undefined]> = [];
    const fetcher = jest.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      calls.push([url, init]);
      const payload = url.endsWith('/accept')
        ? applyPayload
        : url.endsWith('/discard')
          ? { status: 'discarded', project_id: 'project visual', candidate_id: 'candidate visual' }
          : previewPayload;
      return {
        ok: true, status: url.endsWith('/accept') ? 201 : 200,
        text: async () => JSON.stringify(payload),
      } as unknown as Response;
    });
    const client = createTrustedApiClient({ baseUrl: 'https://facetta.test/', fetcher });

    const preview = await client.createVisualPreview('project visual', {
      created_by: 'designer', expected_active_asset_id: 'asset source',
      instruction: 'warm only the center stone', scope: 'marked_region',
      mask_base64: 'mask-data', variant: 2,
    });
    expect(preview.error).toBeNull();
    expect(preview.data?.candidate.preview_url).toBe(
      'https://facetta.test/studio/image-runs/run%20visual/visual-candidates/candidate%20visual/image',
    );
    const accepted = await client.acceptVisualPreview('run visual', 'candidate visual', {
      created_by: 'designer', expected_active_asset_id: 'asset source',
    });
    expect(accepted.error).toBeNull();
    expect(accepted.data?.project.active_asset_id).toBe('asset applied');
    expect(accepted.data?.project.active_design_version).toBeNull();
    const discarded = await client.discardVisualPreview('run visual', 'candidate visual', {
      created_by: 'designer', expected_active_asset_id: 'asset source',
    });
    expect(discarded.data?.status).toBe('discarded');

    expect(calls.map(([url, init]) => [url, init?.method])).toEqual([
      ['https://facetta.test/studio/projects/project%20visual/visual-previews', 'POST'],
      ['https://facetta.test/studio/image-runs/run%20visual/visual-candidates/candidate%20visual/accept', 'POST'],
      ['https://facetta.test/studio/image-runs/run%20visual/visual-candidates/candidate%20visual/discard', 'POST'],
    ]);
    expect(JSON.parse(String(calls[0]?.[1]?.body))).toEqual({
      created_by: 'designer', expected_active_asset_id: 'asset source',
      instruction: 'warm only the center stone', scope: 'marked_region',
      mask_base64: 'mask-data', variant: 2,
    });
    expect(JSON.parse(String(calls[1]?.[1]?.body))).toEqual({
      created_by: 'designer', expected_active_asset_id: 'asset source',
    });
  });
});

