import assert from 'node:assert/strict';
import test from 'node:test';

import { getStudioAction } from './actions';
import {
  getStudioDestination, STUDIO_DESTINATIONS, STUDIO_DESTINATION_IDS,
} from './destinations';

const savedContext = {
  activeProjectId: 'project_1',
  activeRevisionId: 'asset_4',
  hasExactSpecification: true,
  factoryEnabled: true,
  factoryEligible: true,
};

test('destination registry keeps Library non-mutating and zero credit', () => {
  assert.deepEqual(STUDIO_DESTINATIONS.map((destination) => destination.id),
    STUDIO_DESTINATION_IDS,
  );
  const library = getStudioDestination('library');
  assert.equal(library.executionMode, 'instant_navigation');
  assert.equal(library.outputType, 'none');
  assert.equal(library.creditsPerOutput, 0);
  assert.equal(library.authority, 'design_record');
  assert.equal(library.createsJob, false);
  assert.equal(library.isAvailable(savedContext), true);
  assert.equal(library.isAvailable({
    ...savedContext, activeRevisionId: null,
  }), false);
});

test('generated destinations inherit policy from canonical actions', () => {
  const present = getStudioAction('present');
  for (const id of ['client', 'marketing'] as const) {
    const destination = getStudioDestination(id);
    assert.equal(destination.executionMode, present.executionMode);
    assert.equal(destination.outputType, present.outputType);
    assert.equal(destination.creditsPerOutput, present.creditEstimate);
    assert.equal(destination.authority, present.authority);
    assert.equal(destination.createsJob, present.createsJob);
    assert.deepEqual(destination.contextRequirements, present.contextRequirements);
  }

  const canonicalFactory = getStudioAction('factory');
  const factory = getStudioDestination('factory');
  assert.equal(factory.executionMode, canonicalFactory.executionMode);
  assert.equal(factory.outputType, canonicalFactory.outputType);
  assert.equal(factory.creditsPerOutput, canonicalFactory.creditEstimate);
  assert.equal(factory.authority, canonicalFactory.authority);
  assert.equal(factory.createsJob, canonicalFactory.createsJob);
  assert.deepEqual(factory.contextRequirements, canonicalFactory.contextRequirements);
});

test('Factory destination remains optional and eligibility-gated', () => {
  const factory = getStudioDestination('factory');
  assert.equal(factory.isAvailable(savedContext), true);
  assert.equal(factory.isAvailable({ ...savedContext, factoryEligible: false }), false);
  assert.equal(factory.isAvailable({ ...savedContext, factoryEnabled: false }), false);
  assert.equal(factory.isAvailable({ ...savedContext, hasExactSpecification: false }), false);
});
