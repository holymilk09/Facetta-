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
  assert.equal(
    designerErrorMessage({ category: 'evaluation', status: 502 }, 'create'),
    'Facetta could not verify the generated result, so nothing was saved or charged. Try again.',
  );
  assert.equal(
    designerErrorMessage({ category: 'network', status: 0 }, 'activity'),
    'Facetta is temporarily unavailable. This request was not started. Try again shortly.',
  );
  assert.match(designerErrorMessage({ category: 'validation', status: 422 }, 'create'), /reference/);
  assert.match(designerErrorMessage({ category: 'authentication', status: 401 }, 'confirm'), /Sign in again/);
  assert.match(designerErrorMessage({ category: 'authorization', status: 403 }, 'confirm'), /signed-in account/);
  assert.equal(
    designerErrorMessage({ code: 'STUDIO_CREATE_STATUS_UNCONFIRMED' }, 'create'),
    'This request may still be finishing. Check Activity before starting it again.',
  );
});

test('missing image configuration is not misreported as a connection failure', () => {
  const message = designerErrorMessage({
    code: 'provider_not_configured',
    category: 'unavailable',
    status: 503,
    message: 'OPENAI_API_KEY is not configured for provider image generation QA.',
  }, 'refine');
  assert.equal(
    message,
    'Image creation is not configured for this Facetta workspace. Ask a workspace administrator to finish image setup, then try again. Nothing was saved or charged.',
  );
  assert.doesNotMatch(message, /could not connect|openai|api[_ ]?key|provider|qa|model/i);
});

test('image-service failures are not misreported as connection failures', () => {
  const message = designerErrorMessage({
    code: 'HTTP_503',
    category: 'provider',
    status: 503,
    message: 'Image provider rejected the request because an internal key is missing.',
  }, 'refine');
  assert.equal(
    message,
    "Facetta's image service could not complete this request. Try again shortly. Nothing was saved or charged.",
  );
  assert.doesNotMatch(message, /could not connect|provider|api[_ ]?key|model/i);
});
