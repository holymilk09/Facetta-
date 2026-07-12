/// <reference types="node" />

import assert from 'node:assert/strict';
import test from 'node:test';

import {
  designerCheckDetail, designerCheckLabel, designerReviewState,
} from './designerReviewLanguage';

test('designer review states never expose raw evaluator verdicts', () => {
  assert.deepEqual(
    ['pass', 'warn', 'reject', 'fail'].map((value) => designerReviewState(value as any)),
    ['Design preserved', 'Review recommended', 'Could not preserve design', 'Could not preserve design'],
  );
});

test('technical drift labels collapse into one designer-facing preservation concept', () => {
  assert.equal(designerCheckLabel({ id: 'outside_drift', label: 'Outside drift' }), 'Design preservation');
  assert.equal(designerCheckLabel({ id: 'metal_color', label: 'Metal color' }), 'Material appearance');
});

test('technical evaluator details are replaced with decision guidance', () => {
  assert.equal(designerCheckDetail({ verdict: 'pass' }), 'No meaningful unintended change was detected.');
  assert.equal(designerCheckDetail({ verdict: 'warn' }), 'Compare this area carefully with the source before applying.');
  assert.equal(designerCheckDetail({ verdict: 'reject' }), 'This area changed too much from the selected source.');
});
