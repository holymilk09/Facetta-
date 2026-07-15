/// <reference types="jest" />

import {
  createTrustedApiClient,
  decodeCreativeDirectionReviewDraft,
} from './client';

const draft = {
  project_root_id: 'project one',
  studio_job_id: 'job create',
  selected_candidate_id: 'candidate primary',
  retained: [{ candidate_id: 'candidate kept', label: 'Direction 2' }],
  version: 2,
  updated_at: '2026-07-15T01:02:03Z',
};

describe('creative direction review draft client', () => {
  test('decodes only canonical, disjoint, versioned draft selections', () => {
    expect(decodeCreativeDirectionReviewDraft(draft)).toEqual(draft);
    expect(decodeCreativeDirectionReviewDraft({ ...draft, version: 0 })).toBeNull();
    expect(decodeCreativeDirectionReviewDraft({ ...draft, updated_at: 'not-a-date' })).toBeNull();
    expect(decodeCreativeDirectionReviewDraft({
      ...draft,
      retained: [{ candidate_id: 'candidate primary', label: 'Duplicate' }],
    })).toBeNull();
    expect(decodeCreativeDirectionReviewDraft({
      ...draft,
      retained: [{ candidate_id: 'candidate kept', label: ' untrimmed ' }],
    })).toBeNull();
    expect(decodeCreativeDirectionReviewDraft({
      ...draft,
      selected_candidate_id: ' candidate primary',
    })).toBeNull();
    expect(decodeCreativeDirectionReviewDraft({
      ...draft,
      retained: [{ candidate_id: 'candidate kept ', label: 'Direction 2' }],
    })).toBeNull();
  });

  test('uses the project-scoped GET and versioned PUT contract', async () => {
    const fetcher = jest.fn(async (
      _input: RequestInfo | URL,
      _init?: RequestInit,
    ) => ({
      ok: true,
      status: 200,
      text: async () => JSON.stringify(draft),
    } as unknown as Response));
    const api = createTrustedApiClient({ baseUrl: 'https://facetta.test/', fetcher });

    const loaded = await api.getCreativeDirectionReviewDraft('project one', 'job create');
    const saved = await api.putCreativeDirectionReviewDraft('project one', {
      studio_job_id: 'job create',
      expected_version: 1,
      selected_candidate_id: 'candidate primary',
      retained: [{ candidate_id: 'candidate kept', label: 'Direction 2' }],
    });

    expect(loaded.data).toEqual(draft);
    expect(saved.data).toEqual(draft);
    expect(fetcher.mock.calls[0]?.[0]).toBe(
      'https://facetta.test/projects/project%20one/creative-directions/review-draft?studio_job_id=job+create',
    );
    expect(fetcher.mock.calls[0]?.[1]?.method).toBeUndefined();
    expect(fetcher.mock.calls[1]?.[0]).toBe(
      'https://facetta.test/projects/project%20one/creative-directions/review-draft?studio_job_id=job+create',
    );
    expect(fetcher.mock.calls[1]?.[1]?.method).toBe('PUT');
    expect(JSON.parse(String(fetcher.mock.calls[1]?.[1]?.body))).toEqual({
      studio_job_id: 'job create',
      expected_version: 1,
      selected_candidate_id: 'candidate primary',
      retained: [{ candidate_id: 'candidate kept', label: 'Direction 2' }],
    });
  });

  test('preserves stale-version conflicts for gateway reconciliation', async () => {
    const fetcher = jest.fn(async (
      _input: RequestInfo | URL,
      _init?: RequestInit,
    ) => ({
      ok: false,
      status: 409,
      text: async () => JSON.stringify({
        code: 'STALE_CREATE_REVIEW_DRAFT',
        message: 'The Create review changed on another device.',
      }),
    } as unknown as Response));
    const api = createTrustedApiClient({ baseUrl: 'https://facetta.test', fetcher });

    const result = await api.putCreativeDirectionReviewDraft('project one', {
      studio_job_id: 'job create', expected_version: 1,
      selected_candidate_id: 'candidate primary', retained: [],
    });

    expect(result.data).toBeNull();
    expect(result.status).toBe(409);
    expect(result.error?.category).toBe('stale_version');
  });
});
