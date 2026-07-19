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
    save_as_variation_url: '/studio/image-runs/run%20visual/visual-candidates/candidate%20visual/save-as-variation',
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
    expect(decodeVisualPreviewApplyResult({
      ...applyPayload,
      project: {
        ...projectPayload,
        active_revision: { ...applied, parent_asset_id: null },
        revisions: [
          projectPayload.revisions[0],
          {
            ...projectPayload.revisions[1],
            asset: { ...applied, parent_asset_id: null },
          },
        ],
      },
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
      raw_user_instruction: 'Make only the center stone warmer.',
      input_mode: 'point',
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
      raw_user_instruction: 'Make only the center stone warmer.', input_mode: 'point',
      mask_base64: 'mask-data', variant: 2,
    });
    expect(JSON.parse(String(calls[1]?.[1]?.body))).toEqual({
      created_by: 'designer', expected_active_asset_id: 'asset source',
    });
  });

  test('reads chronological raw prompt history without exposing compiled provider text', async () => {
    const internal = 'KEEP ALL OTHER DETAILS FIXED.';
    const fetcher = jest.fn(async () => ({
      ok: true,
      status: 200,
      text: async () => JSON.stringify({ prompts: [{
        prompt_id: 'scp_1',
        sequence: 1,
        prompt: 'Make the chain white gold and braided.',
        annotations: [],
        input_mode: 'describe',
        scope: 'appearance',
        variant: 0,
        source_asset_id: 'asset source',
        source_sha256: 'a'.repeat(64),
        studio_job_id: 'job_1',
        state: 'applied',
        candidate_id: 'candidate visual',
        image_run_id: 'run visual',
        applied_asset_id: 'asset applied',
        created_at: '2026-07-19T00:00:00Z',
      }] }),
    } as Response));
    const client = createTrustedApiClient({ baseUrl: 'https://facetta.test', fetcher });

    const result = await client.getStudioContinuationPrompts('project visual');

    expect(result.error).toBeNull();
    expect(result.data?.prompts[0]).toMatchObject({
      sequence: 1,
      prompt: 'Make the chain white gold and braided.',
      state: 'applied',
      applied_asset_id: 'asset applied',
    });
    expect(result.data?.prompts[0]?.prompt).not.toContain(internal);
    expect(fetcher).toHaveBeenCalledWith(
      'https://facetta.test/studio/projects/project%20visual/continuation-prompts',
      expect.objectContaining({ headers: { Accept: 'application/json' } }),
    );
  });

  test('lists only typed same-origin pending visual candidates', async () => {
    const fetcher = jest.fn(async () => ({
      ok: true, status: 200,
      text: async () => JSON.stringify({ candidates: [{
        candidate_id: 'candidate visual', image_run_id: 'run visual',
        source_asset_id: 'asset source',
        preview_url: '/studio/image-runs/run%20visual/visual-candidates/candidate%20visual/image',
        save_as_variation_url: '/studio/image-runs/run%20visual/visual-candidates/candidate%20visual/save-as-variation',
        verdict: 'pass', requested_change: 'Warm the center stone',
        scope: 'appearance', qa, expires_at: '2099-01-01T00:00:00Z',
      }] }),
    } as Response));
    const client = createTrustedApiClient({ baseUrl: 'https://facetta.test', fetcher });
    const result = await client.listVisualPreviews('project visual');
    expect(result.error).toBeNull();
    expect(result.data?.candidates[0]?.preview_url).toBe(
      'https://facetta.test/studio/image-runs/run%20visual/visual-candidates/candidate%20visual/image',
    );
    expect(fetcher).toHaveBeenCalledWith(
      'https://facetta.test/studio/projects/project%20visual/visual-candidates',
      expect.objectContaining({ headers: { Accept: 'application/json' } }),
    );
  });

  test('uses the validated visual variation capability and trims its explicit label', async () => {
    const fetcher = jest.fn(async (_input: RequestInfo | URL, init?: RequestInit) => ({
      ok: true, status: 201,
      text: async () => JSON.stringify({
        status: 'saved_as_variation', family_id: 'family_visual', variation_index: 2,
        source_project_id: 'project_visual', source_asset_id: 'asset_visual',
        project: projectPayload,
      }),
    } as Response));
    const client = createTrustedApiClient({ baseUrl: 'https://facetta.test', fetcher });
    const result = await client.saveVisualPreviewAsVariation(
      'run visual', 'candidate visual', previewPayload.candidate.save_as_variation_url,
      { created_by: 'designer', label: '  Warm direction  ' },
    );
    expect(result.error).toBeNull();
    expect(result.data).toMatchObject({
      source_project_id: 'project_visual', source_asset_id: 'asset_visual',
    });
    expect(fetcher).toHaveBeenCalledWith(
      'https://facetta.test/studio/image-runs/run%20visual/visual-candidates/candidate%20visual/save-as-variation',
      expect.objectContaining({ method: 'POST' }),
    );
    expect(JSON.parse(String(fetcher.mock.calls[0]?.[1]?.body))).toEqual({
      created_by: 'designer', label: 'Warm direction',
    });
  });
});
