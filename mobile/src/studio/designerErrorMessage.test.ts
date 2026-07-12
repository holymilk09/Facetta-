import assert from 'node:assert/strict';
import test from 'node:test';

import { designerErrorMessage } from './designerErrorMessage';

test('designer errors never echo backend diagnostics or identifiers', () => {
  const raw = {
    code: 'provider_grok_asset_id_run_id_expected_design_version',
    category: 'server',
    status: 500,
    message: 'Grok rejected base64 for asset_id ast_1 run_id run_2 expected_design_version=4',
  };
  const message = designerErrorMessage(raw, 'refine');
  assert.equal(message, 'Facetta could not prepare that change. Your saved design is unchanged.');
  assert.doesNotMatch(message, /grok|provider|base64|asset_id|run_id|design_version/i);
});

test('designer errors give specific safe recovery guidance', () => {
  assert.match(designerErrorMessage({ code: 'stale_asset_revision', status: 409 }, 'refine'), /Reopen/);
  assert.match(designerErrorMessage({ category: 'quality', status: 422 }, 'views'), /Nothing was saved or charged/);
  assert.match(designerErrorMessage({ category: 'network', status: 0 }, 'activity'), /connection/);
  assert.match(designerErrorMessage({ category: 'validation', status: 422 }, 'create'), /reference/);
});
