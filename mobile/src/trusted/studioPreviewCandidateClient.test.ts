/// <reference types="jest" />

import { createTrustedApiClient } from './client';

const sha = (character: string) => character.repeat(64);

const qa = {
  verdict: 'pass', accepted: true, review_required: false, score: 0.99,
  summary: 'The requested component changed without outside drift.',
  failed_checks: [], warnings: [],
  checks: [{
    key: 'outside_drift', label: 'Outside drift', verdict: 'pass',
    severity: 'hard', message: 'Unrelated geometry is unchanged.',
  }],
};

const baseCandidate = (candidateId: string) => ({
  candidate_id: candidateId,
  status: 'reviewing',
  image_run_id: `run ${candidateId}`,
  project_root_id: 'project one',
  source_asset_id: 'asset source',
  expected_active_asset_id: 'asset source',
  expected_design_version: null,
  source_sha256: sha('a'),
  output_sha256: sha('b'),
  requested_change: 'Warm the center stone only.',
  verdict: 'pass',
  qa,
  studio_job_id: `job ${candidateId}`,
  terminal_asset_id: null,
  created_at: '2026-07-15T01:00:00Z',
  expires_at: '2099-07-15T02:00:00Z',
  resolved_at: null,
  available_decisions: ['apply', 'save_as_variation', 'discard'],
  preview_url: `/studio/preview-candidates/${encodeURIComponent(candidateId)}/image?owner=designer`,
  decision_url: `/studio/preview-candidates/${encodeURIComponent(candidateId)}/decision`,
});

const visualCandidate = {
  ...baseCandidate('candidate visual'),
  kind: 'visual',
  scope: 'appearance',
};

const catalogCandidate = {
  ...baseCandidate('candidate catalog'),
  kind: 'catalog_revision',
  expected_design_version: 3,
  component_path: 'metal.color',
  option_id: 'rose',
  spec_change: [{
    path: 'metal.color', before: 'yellow', after: 'rose', label: 'Metal color',
  }],
  next_spec: {
    schema_version: 1,
    design_id: 'design one',
    version: 4,
    created_by: 'designer',
    created_at: '2026-07-15T01:00:00Z',
    jewelry_type: 'ring',
    template: 'solitaire',
    mode: 'basic',
    stone: {
      species: 'diamond', cut: 'round', carat: 1,
      dimensions_mm: { length: 6.5, width: 6.5, depth: 4 },
      color: { trade: 'colorless', gia: 'D' },
    },
    metal: { material: 'gold', karat: 18, color: 'rose' },
  },
};

const markupCandidate = {
  ...baseCandidate('candidate markup'),
  kind: 'markup',
  expected_design_version: 3,
  operation: 'LOCAL_EDIT',
  region_description: 'center stone',
};

const response = (payload: unknown, status = 200) => ({
  ok: status >= 200 && status < 300,
  status,
  text: async () => JSON.stringify(payload),
}) as Response;

describe('normalized Studio preview-candidate client', () => {
  test('lists the three strict kinds through one encoded route and retains catalog next_spec', async () => {
    const fetcher = jest.fn(async () => response({
      candidates: [visualCandidate, catalogCandidate, markupCandidate],
    }));
    const client = createTrustedApiClient({ baseUrl: 'https://facetta.test/', fetcher });

    const result = await client.listStudioPreviewCandidates('project one', 'designer');

    expect(result.error).toBeNull();
    expect(result.data?.candidates.map((candidate) => candidate.kind)).toEqual([
      'visual', 'catalog_revision', 'markup',
    ]);
    const catalog = result.data?.candidates[1];
    expect(catalog?.kind === 'catalog_revision' ? catalog.next_spec : null).toEqual(
      catalogCandidate.next_spec,
    );
    expect(catalog?.kind === 'catalog_revision' ? catalog.execution_mode : null).toBe('provider');
    expect(result.data?.candidates[0]?.preview_url).toBe(
      'https://facetta.test/studio/preview-candidates/candidate%20visual/image?owner=designer',
    );
    expect(result.data?.candidates[0]?.decision_url).toBe(
      'https://facetta.test/studio/preview-candidates/candidate%20visual/decision',
    );
    expect(fetcher).toHaveBeenCalledWith(
      'https://facetta.test/studio/projects/project%20one/preview-candidates',
      expect.objectContaining({ headers: expect.any(Object) }),
    );
  });

  test('derives instant execution only from a backend-validated jobless catalog row', async () => {
    const instant = {
      ...catalogCandidate,
      candidate_id: 'candidate instant catalog',
      image_run_id: 'run instant catalog',
      studio_job_id: null,
      preview_url: '/studio/preview-candidates/candidate%20instant%20catalog/image?owner=designer',
      decision_url: '/studio/preview-candidates/candidate%20instant%20catalog/decision',
    };
    const fetcher = jest.fn(async () => response({ candidates: [instant] }));
    const client = createTrustedApiClient({ baseUrl: 'https://facetta.test', fetcher });

    const result = await client.listStudioPreviewCandidates('project one', 'designer');

    expect(result.error).toBeNull();
    expect(result.data?.candidates[0]).toEqual(expect.objectContaining({
      candidate_id: 'candidate instant catalog',
      kind: 'catalog_revision',
      execution_mode: 'instant',
      studio_job_id: null,
    }));
  });

  test('gets one candidate with an owner-bound request and lists resolved candidates explicitly', async () => {
    const resolved = {
      ...visualCandidate,
      status: 'applied', terminal_asset_id: 'asset applied',
      resolved_at: '2026-07-15T01:05:00Z', available_decisions: [],
    };
    const fetcher = jest.fn(async (input: RequestInfo | URL) => (
      String(input).includes('/projects/')
        ? response({ candidates: [resolved] })
        : response(visualCandidate)
    ));
    const client = createTrustedApiClient({ baseUrl: 'https://facetta.test', fetcher });

    const found = await client.getStudioPreviewCandidate('candidate visual', 'designer');
    const listed = await client.listStudioPreviewCandidates('project one', 'designer', true);

    expect(found.data?.kind).toBe('visual');
    expect(listed.data?.candidates[0]?.status).toBe('applied');
    expect(fetcher.mock.calls.map(([input]) => String(input))).toEqual([
      'https://facetta.test/studio/preview-candidates/candidate%20visual?owner=designer',
      'https://facetta.test/studio/projects/project%20one/preview-candidates?include_resolved=true',
    ]);
  });

  test.each([
    ['foreign preview origin', {
      preview_url: 'https://evil.test/studio/preview-candidates/candidate%20visual/image?owner=designer',
    }],
    ['preview credentials', {
      preview_url: 'https://user:pass@facetta.test/studio/preview-candidates/candidate%20visual/image?owner=designer',
    }],
    ['mismatched owner', {
      preview_url: '/studio/preview-candidates/candidate%20visual/image?owner=attacker',
    }],
    ['duplicate owner', {
      preview_url: '/studio/preview-candidates/candidate%20visual/image?owner=designer&owner=designer',
    }],
    ['extra preview query', {
      preview_url: '/studio/preview-candidates/candidate%20visual/image?owner=designer&download=1',
    }],
    ['preview fragment', {
      preview_url: '/studio/preview-candidates/candidate%20visual/image?owner=designer#image',
    }],
    ['wrong preview path', {
      preview_url: '/studio/preview-candidates/candidate%20visual/other?owner=designer',
    }],
    ['decision query', {
      decision_url: '/studio/preview-candidates/candidate%20visual/decision?owner=designer',
    }],
    ['decision fragment', {
      decision_url: '/studio/preview-candidates/candidate%20visual/decision#resolve',
    }],
    ['foreign decision origin', {
      decision_url: 'https://evil.test/studio/preview-candidates/candidate%20visual/decision',
    }],
  ])('fails closed for %s', async (_name, mutation) => {
    const fetcher = jest.fn(async () => response({
      candidates: [{ ...visualCandidate, ...mutation }],
    }));
    const client = createTrustedApiClient({ baseUrl: 'https://facetta.test', fetcher });

    const result = await client.listStudioPreviewCandidates('project one', 'designer');

    expect(result.data).toBeNull();
    expect(result.error?.code).toBe('INVALID_RESPONSE');
  });

  test.each([
    ['missing catalog next_spec', { ...catalogCandidate, next_spec: undefined }],
    ['empty catalog next_spec', { ...catalogCandidate, next_spec: {} }],
    ['partial catalog next_spec', {
      ...catalogCandidate, next_spec: { version: 4, metal: { color: 'rose' } },
    }],
    ['catalog next_spec without a meaningful center stone', {
      ...catalogCandidate, next_spec: { ...catalogCandidate.next_spec, stone: {} },
    }],
    ['visual with a spec version', { ...visualCandidate, expected_design_version: 3 }],
    ['reviewing candidate without verdict', { ...visualCandidate, verdict: null }],
    ['reviewing candidate without valid QA', { ...visualCandidate, qa: {} }],
    ['QA missing explicit acceptance flags', {
      ...visualCandidate, qa: { verdict: 'pass' },
    }],
    ['QA and verdict disagreement', {
      ...visualCandidate, verdict: 'warn',
    }],
    ['pass QA marked for review', {
      ...visualCandidate, qa: { ...qa, accepted: false, review_required: true },
    }],
    ['resolved decisions still exposed', {
      ...visualCandidate, status: 'discarded', resolved_at: '2026-07-15T01:05:00Z',
    }],
    ['unknown markup operation', { ...markupCandidate, operation: 'GENERIC_EDIT' }],
  ])('rejects semantically invalid candidate: %s', async (_name, candidate) => {
    const fetcher = jest.fn(async () => response({ candidates: [candidate] }));
    const client = createTrustedApiClient({ baseUrl: 'https://facetta.test', fetcher });

    const result = await client.listStudioPreviewCandidates('project one', 'designer', true);

    expect(result.error?.code).toBe('INVALID_RESPONSE');
  });

  test('posts generic apply, variation, and discard decisions with exact CAS metadata', async () => {
    const calls: Array<[string, RequestInit | undefined]> = [];
    const fetcher = jest.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const body = JSON.parse(String(init?.body)) as { decision: string };
      calls.push([String(input), init]);
      if (body.decision === 'save_as_variation') return response({
        status: 'saved_as_variation', candidate_id: 'candidate catalog', kind: 'catalog_revision',
        source_project_id: 'project one', result_project_id: 'project variation',
        terminal_asset_id: 'asset variation', studio_job_id: 'job candidate catalog',
        family_id: 'project one', variation_index: 2,
      });
      if (body.decision === 'discard') return response({
        status: 'discarded', candidate_id: 'candidate markup', kind: 'markup',
        source_project_id: 'project one', result_project_id: 'project one',
        terminal_asset_id: null, studio_job_id: 'job candidate markup',
        family_id: null, variation_index: null,
      });
      return response({
        status: 'applied', candidate_id: 'candidate visual', kind: 'visual',
        source_project_id: 'project one', result_project_id: 'project one',
        terminal_asset_id: 'asset applied', studio_job_id: 'job candidate visual',
        family_id: null, variation_index: null,
      });
    });
    const client = createTrustedApiClient({ baseUrl: 'https://facetta.test', fetcher });

    const applied = await client.decideStudioPreviewCandidate('candidate visual', {
      created_by: 'designer', decision: 'apply', expected_active_asset_id: 'asset source',
      expected_design_version: null,
    });
    const varied = await client.decideStudioPreviewCandidate('candidate catalog', {
      created_by: 'designer', decision: 'save_as_variation',
      expected_active_asset_id: 'asset source', expected_design_version: 3,
      variation_label: ' Rose metal ',
    });
    const discarded = await client.decideStudioPreviewCandidate('candidate markup', {
      created_by: 'designer', decision: 'discard',
      expected_active_asset_id: 'asset source', expected_design_version: 3,
    });

    expect(applied.data?.status).toBe('applied');
    expect(varied.data?.result_project_id).toBe('project variation');
    expect(varied.data?.family_id).toBe('project one');
    expect(discarded.data?.terminal_asset_id).toBeNull();
    expect(calls.map(([url, init]) => [url, init?.method, JSON.parse(String(init?.body))])).toEqual([
      [
        'https://facetta.test/studio/preview-candidates/candidate%20visual/decision',
        'POST', {
          created_by: 'designer', decision: 'apply', expected_active_asset_id: 'asset source',
          expected_design_version: null,
        },
      ],
      [
        'https://facetta.test/studio/preview-candidates/candidate%20catalog/decision',
        'POST', {
          created_by: 'designer', decision: 'save_as_variation',
          expected_active_asset_id: 'asset source', expected_design_version: 3,
          variation_label: 'Rose metal',
        },
      ],
      [
        'https://facetta.test/studio/preview-candidates/candidate%20markup/decision',
        'POST', {
          created_by: 'designer', decision: 'discard', expected_active_asset_id: 'asset source',
          expected_design_version: 3,
        },
      ],
    ]);
  });

  test.each([
    ['same-project variation', {
      status: 'saved_as_variation', candidate_id: 'candidate visual', kind: 'visual',
      source_project_id: 'project one', result_project_id: 'project one',
      terminal_asset_id: 'asset variation', studio_job_id: null,
      family_id: 'project one', variation_index: 2,
    }],
    ['variation without family metadata', {
      status: 'saved_as_variation', candidate_id: 'candidate visual', kind: 'visual',
      source_project_id: 'project one', result_project_id: 'project variation',
      terminal_asset_id: 'asset variation', studio_job_id: null,
      family_id: null, variation_index: null,
    }],
    ['variation missing family_id field', {
      status: 'saved_as_variation', candidate_id: 'candidate visual', kind: 'visual',
      source_project_id: 'project one', result_project_id: 'project variation',
      terminal_asset_id: 'asset variation', studio_job_id: null,
      variation_index: 2,
    }],
    ['variation missing variation_index field', {
      status: 'saved_as_variation', candidate_id: 'candidate visual', kind: 'visual',
      source_project_id: 'project one', result_project_id: 'project variation',
      terminal_asset_id: 'asset variation', studio_job_id: null,
      family_id: 'project one',
    }],
    ['variation using reserved family-root index', {
      status: 'saved_as_variation', candidate_id: 'candidate visual', kind: 'visual',
      source_project_id: 'project one', result_project_id: 'project variation',
      terminal_asset_id: 'asset variation', studio_job_id: null,
      family_id: 'project one', variation_index: 1,
    }],
    ['apply carrying variation metadata', {
      status: 'applied', candidate_id: 'candidate visual', kind: 'visual',
      source_project_id: 'project one', result_project_id: 'project one',
      terminal_asset_id: 'asset applied', studio_job_id: null,
      family_id: 'project one', variation_index: 2,
    }],
    ['apply missing explicit family_id null', {
      status: 'applied', candidate_id: 'candidate visual', kind: 'visual',
      source_project_id: 'project one', result_project_id: 'project one',
      terminal_asset_id: 'asset applied', studio_job_id: null,
      variation_index: null,
    }],
    ['discard missing explicit variation_index null', {
      status: 'discarded', candidate_id: 'candidate visual', kind: 'visual',
      source_project_id: 'project one', result_project_id: 'project one',
      terminal_asset_id: null, studio_job_id: null,
      family_id: null,
    }],
  ])('fails closed for inconsistent generic decision metadata: %s', async (_name, payload) => {
    const fetcher = jest.fn(async () => response(payload));
    const client = createTrustedApiClient({ baseUrl: 'https://facetta.test', fetcher });

    const result = await client.decideStudioPreviewCandidate('candidate visual', {
      created_by: 'designer', decision: 'save_as_variation',
      expected_active_asset_id: 'asset source', expected_design_version: null,
      variation_label: 'Warm',
    });

    expect(result.data).toBeNull();
    expect(result.error?.code).toBe('INVALID_RESPONSE');
  });
});
