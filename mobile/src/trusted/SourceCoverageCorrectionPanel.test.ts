/// <reference types="jest" />

import React, { useState } from 'react';
import { fireEvent, render, screen } from '@testing-library/react-native';

import {
  changedSourceCoverageResolutions,
  sourceCoverageAllowsCreation,
  SourceCoverageCorrectionPanel,
  sourceCoverageDrafts,
  type SourceCoverageCorrectionDrafts,
} from './SourceCoverageCorrectionPanel';
import type { SourceCoverageResolutionResult } from './types';

function coverage(
  overrides: Partial<SourceCoverageResolutionResult> = {},
): SourceCoverageResolutionResult {
  return {
    spec: { jewelry_type: 'ring', template: 'leaf_shoulder_prong' },
    source_kind: 'designer_plate',
    components: [{
      component_id: 'assembly.shoulder',
      source_view: 'detail',
      source_description: 'Mirrored sculpted shoulder leaves.',
      source_confidence: 0.76,
      canonical_spec_paths: [],
      unresolved_reason: 'No supported form path captures the shoulder contour.',
      independent_audit: null,
    }],
    valid_spec_paths: ['stone', 'side_stones[0]'],
    changed_component_ids: [],
    invalidated_audit_component_ids: [],
    blockers: [{
      code: 'source_component_unresolved',
      component_id: 'assembly.shoulder',
      message: 'The visible shoulder component is not mapped.',
      required_resolution: 'Map it to an existing supported path.',
    }, {
      code: 'source_component_not_independently_audited',
      component_id: 'assembly.shoulder',
      message: 'The shoulder mapping has not been independently audited.',
      required_resolution: 'Run the independent component-coverage audit.',
    }],
    factory_ready: false,
    legacy_provenance: false,
    resolved_by: null,
    audit: {
      requested: true,
      status: 'review_required',
      audited_component_ids: [],
      blocker_count: 2,
    },
    ...overrides,
  };
}

describe('SourceCoverageCorrectionPanel', () => {
  test('shows stable source evidence and submits only a selected existing path', async () => {
    const snapshot = coverage();
    const apply = jest.fn();
    const audit = jest.fn();

    function Harness() {
      const [drafts, setDrafts] = useState<SourceCoverageCorrectionDrafts>(
        sourceCoverageDrafts(snapshot.components),
      );
      return React.createElement(SourceCoverageCorrectionPanel, {
        coverage: snapshot,
        drafts,
        busy: null,
        specChangedAfterAudit: false,
        onDraftChange: (componentId, draft) => setDrafts((current) => ({
          ...current,
          [componentId]: draft,
        })),
        onApply: apply,
        onAudit: audit,
      });
    }

    const rendered = await render(React.createElement(Harness));
    expect(screen.getByText('assembly.shoulder')).toBeTruthy();
    expect(screen.getByText('Mirrored sculpted shoulder leaves.')).toBeTruthy();
    expect(screen.getByText(/Source view: detail · visual-read confidence 76%/)).toBeTruthy();
    expect(screen.getByText(/Currently unresolved: No supported form path/)).toBeTruthy();
    expect(screen.getByText(/do not prove dimensions, hidden construction, CAD geometry/)).toBeTruthy();
    expect(screen.getByText('Remaining source-coverage blockers: 2')).toBeTruthy();

    await fireEvent.press(screen.getByText('Map to existing spec paths'));
    expect(screen.getByText('stone')).toBeTruthy();
    expect(screen.getByText('side_stones[0]')).toBeTruthy();
    expect(screen.queryByText('notes_to_factory')).toBeNull();
    await fireEvent.press(screen.getByText('side_stones[0]'));
    await fireEvent.press(screen.getByText('Apply component decisions'));
    expect(apply).toHaveBeenCalledTimes(1);
    await fireEvent.press(screen.getByText('Re-run independent source audit'));
    expect(audit).toHaveBeenCalledTimes(1);
    await rendered.unmount();
  });

  test('requires a passing zero-blocker audit before reference project creation', () => {
    const blocked = coverage();
    expect(sourceCoverageAllowsCreation(blocked, false)).toBe(false);
    expect(sourceCoverageAllowsCreation({
      ...blocked,
      blockers: [],
      factory_ready: true,
      audit: {
        requested: true,
        status: 'pass',
        audited_component_ids: ['assembly.shoulder'],
        blocker_count: 0,
      },
    }, true)).toBe(false);
    expect(sourceCoverageAllowsCreation({
      ...blocked,
      blockers: [],
      factory_ready: true,
      audit: {
        requested: true,
        status: 'pass',
        audited_component_ids: ['assembly.shoulder'],
        blocker_count: 0,
      },
    }, false)).toBe(true);
  });

  test('never submits an arbitrary path absent from the server allow-list', () => {
    const snapshot = coverage();
    const drafts = sourceCoverageDrafts(snapshot.components);
    drafts['assembly.shoulder'] = {
      mode: 'mapped',
      selected_paths: ['notes_to_factory', 'side_stones[0]'],
      unresolved_note: '',
    };

    expect(changedSourceCoverageResolutions(snapshot, drafts)).toEqual([{
      component_id: 'assembly.shoulder',
      canonical_spec_paths: ['side_stones[0]'],
      unresolved_reason: null,
    }]);
  });
});
