/// <reference types="node" />

import assert from 'node:assert/strict';
import test from 'node:test';

import { createStudioGateway } from './gateway';

test('Present rejects a response that is not bound to the exact requested revision', async () => {
  const gateway = createStudioGateway({
    createMarketingPack: async () => ({
      data: {
        status: 'review_required',
        project_id: 'project_1',
        source_asset_id: 'different_asset',
        design_version: 7,
        requested_count: 1,
        candidate_count: 0,
        failed_count: 1,
        maximum_provider_attempts: 3,
        actual_attempts: 1,
        candidates: [],
        failures: [],
      },
      error: null,
      status: 201,
    }),
  } as unknown as Parameters<typeof createStudioGateway>[0]);

  const result = await gateway.createMarketingPresentation('project_1', {
    created_by: 'designer',
    expected_asset_id: 'asset_7',
    expected_design_version: 7,
    presets: ['catalog_white'],
  });

  assert.equal(result.data, null);
  assert.equal(result.error?.code, 'INVALID_PRESENTATION_LINEAGE');
  assert.equal(result.error?.category, 'invalid_response');
});
