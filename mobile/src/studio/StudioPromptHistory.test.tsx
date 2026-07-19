import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react-native';

import type {
  AssetSummary, ProjectDetail, ProjectRevision, StudioContinuationPrompt,
} from '../trusted/types';
import { StudioPromptHistory, studioPromptHistory } from './StudioPromptHistory';

function asset(
  id: string,
  revision: number,
  instruction: string,
  parentAssetId: string | null,
): AssetSummary {
  return {
    asset_id: id,
    root_id: 'project_1',
    parent_asset_id: parentAssetId,
    capability: 'CREATIVE_RENDER',
    provenance: 'studio_visual_revision',
    revision,
    design_id: null,
    design_version: null,
    region: null,
    instruction,
    drift: null,
    pinned: false,
    media_type: 'image/png',
    image_url: `https://test/${id}.png`,
    created_by: 'designer',
    created_at: `2026-07-19T00:0${revision}:00Z`,
    legacy_provenance: false,
  };
}

function revision(item: AssetSummary): ProjectRevision {
  return {
    revision: item.revision ?? 0,
    asset: item,
    spec_version: null,
    spec_change: [],
    ignored_fields: [],
    qa: null,
    routing: null,
    created_at: item.created_at,
  };
}

const first = asset('asset_1', 1, 'Ruby on a gold necklace', null);
const second = asset(
  'asset_2', 2,
  'Add three small diamond and tsavorite leaves on each side of the ruby.',
  first.asset_id,
);
const restored = asset('asset_3', 3, 'Restored from revision asset asset_1', second.asset_id);

const project = {
  id: 'project_1',
  root_id: 'project_1',
  title: 'Ruby necklace',
  collection: null,
  tags: [],
  owner: 'designer',
  state: 'refining',
  design_id: null,
  spec: null,
  active_asset_id: restored.asset_id,
  active_design_version: null,
  active_revision: restored,
  pinned_revision: null,
  revisions: [revision(first), revision(second), revision(restored)],
  assets: [first, second, restored],
  derived_assets: [],
  approval: null,
  factory_ready: false,
  factory_blockers: [],
  primary_revision_count: 3,
  has_factory_drawing: false,
  cover_asset_id: restored.asset_id,
  created_at: null,
  updated_at: null,
} as ProjectDetail;

describe('StudioPromptHistory', () => {
  it('uses the raw continuation ledger instead of compiled saved instructions', async () => {
    const rawPrompt: StudioContinuationPrompt = {
      prompt_id: 'scp_1', sequence: 1,
      prompt: 'Make both necklace sides use the same alternating diamond pattern.',
      annotations: [], input_mode: 'symmetry', scope: 'appearance', variant: 0,
      source_asset_id: first.asset_id, source_sha256: 'a'.repeat(64),
      studio_job_id: 'job_1', state: 'applied', candidate_id: 'candidate_1',
      outcome_code: null,
      image_run_id: 'run_1', applied_asset_id: second.asset_id,
      created_at: '2026-07-19T00:00:00Z',
    };
    const compiledProject = {
      ...project,
      revisions: [
        revision(first),
        revision({
          ...second,
          instruction: 'Internal preservation suffix that must never be shown.',
        }),
      ],
    } as ProjectDetail;

    expect(studioPromptHistory(compiledProject, [rawPrompt]).map((entry) => entry.prompt)).toEqual([
      'Ruby on a gold necklace',
      'Make both necklace sides use the same alternating diamond pattern.',
    ]);
    await render(<StudioPromptHistory project={compiledProject} continuationPrompts={[rawPrompt]} />);
    expect(screen.getByText('Saved in Revision 2')).toBeTruthy();
    expect(screen.queryByText('Internal preservation suffix that must never be shown.')).toBeNull();
  });

  it('keeps exact markup prompts when the durable continuation ledger is empty', () => {
    const exactProject = {
      ...project,
      design_id: 'design_1',
      active_design_version: 2,
      revisions: [revision(first), revision(second)],
    } as ProjectDetail;

    expect(studioPromptHistory(exactProject, []).map((entry) => entry.prompt)).toEqual([
      'Ruby on a gold necklace',
      'Add three small diamond and tsavorite leaves on each side of the ruby.',
    ]);
  });

  it('shows accepted designer prompts in immutable revision order', async () => {
    expect(studioPromptHistory(project).map((entry) => entry.prompt)).toEqual([
      'Ruby on a gold necklace',
      'Add three small diamond and tsavorite leaves on each side of the ruby.',
    ]);

    await render(<StudioPromptHistory project={project} />);
    expect(screen.getByText('Ruby on a gold necklace')).toBeTruthy();
    expect(screen.getByText('Add three small diamond and tsavorite leaves on each side of the ruby.')).toBeTruthy();
    expect(screen.queryByText('Restored from revision asset asset_1')).toBeNull();
  });

  it('keeps a pending prompt visibly temporary until Apply', async () => {
    await render(
      <StudioPromptHistory
        project={project}
        previewPrompt="Make the chain white gold and braided."
      />,
    );

    expect(screen.getByText('TEMPORARY PREVIEW')).toBeTruthy();
    expect(screen.getByText('Make the chain white gold and braided.')).toBeTruthy();
    expect(screen.getByText('Apply to save this as the next revision.')).toBeTruthy();
  });

  it('explains failed and discarded attempts without implying a revision was lost', async () => {
    const base: StudioContinuationPrompt = {
      prompt_id: 'scp_failed', sequence: 1, prompt: 'Deepen the marked leaf color.',
      annotations: [], input_mode: 'point', scope: 'marked_region', variant: 0,
      source_asset_id: restored.asset_id, source_sha256: 'b'.repeat(64),
      studio_job_id: 'job_failed', state: 'failed', outcome_code: 'image_quality_failed',
      candidate_id: null, image_run_id: null, applied_asset_id: null,
      created_at: '2026-07-19T01:00:00Z',
    };
    await render(<StudioPromptHistory project={project} continuationPrompts={[
      base,
      { ...base, prompt_id: 'scp_discarded', sequence: 2, prompt: 'Try emerald green.',
        state: 'discarded', outcome_code: 'request_canceled' },
    ]} />);
    await fireEvent.press(screen.getByLabelText('Show design prompt history'));

    expect(screen.getByText(
      'Preview did not pass jewelry quality checks · saved revision unchanged',
    )).toBeTruthy();
    expect(screen.getByText('Preview discarded · saved revision unchanged')).toBeTruthy();
    expect(screen.queryByText(/no revision saved/i)).toBeNull();
  });

  it('reuses wording only when the failure belongs to the active revision', async () => {
    const onReusePrompt = jest.fn();
    const failed: StudioContinuationPrompt = {
      prompt_id: 'scp_retry', sequence: 1, prompt: 'Deepen the marked leaf color.',
      annotations: [], input_mode: 'point', scope: 'marked_region', variant: 0,
      source_asset_id: restored.asset_id, source_sha256: 'c'.repeat(64),
      studio_job_id: 'job_retry', state: 'failed', outcome_code: 'image_quality_failed',
      candidate_id: null, image_run_id: null, applied_asset_id: null,
      created_at: '2026-07-19T01:00:00Z',
    };
    const { rerender } = await render(
      <StudioPromptHistory
        project={project}
        continuationPrompts={[failed]}
        onReusePrompt={onReusePrompt}
      />,
    );
    await fireEvent.press(screen.getByLabelText('Reuse wording: Deepen the marked leaf color.'));
    expect(onReusePrompt).toHaveBeenCalledWith('Deepen the marked leaf color.');

    await rerender(<StudioPromptHistory
      project={project}
      continuationPrompts={[{ ...failed, source_asset_id: first.asset_id }]}
      onReusePrompt={onReusePrompt}
    />);
    expect(screen.queryByText('Reuse wording')).toBeNull();
  });

  it('collapses long histories by default so the editor remains reachable', async () => {
    const prompts = Array.from({ length: 4 }, (_, index): StudioContinuationPrompt => ({
      prompt_id: `scp_${index + 1}`, sequence: index + 1, prompt: `Request ${index + 1}`,
      annotations: [], input_mode: 'describe', scope: 'appearance', variant: 0,
      source_asset_id: restored.asset_id, source_sha256: 'd'.repeat(64),
      studio_job_id: `job_${index + 1}`, state: 'failed', outcome_code: 'image_quality_failed',
      candidate_id: null, image_run_id: null, applied_asset_id: null,
      created_at: `2026-07-19T0${index + 1}:00:00Z`,
    }));
    await render(<StudioPromptHistory project={project} continuationPrompts={prompts} />);

    expect((await screen.findByLabelText('Show design prompt history')).props.accessibilityState)
      .toEqual({ expanded: false });
    expect(screen.queryByText('Request 1')).toBeNull();
    await fireEvent.press(screen.getByLabelText('Show design prompt history'));
    expect(screen.getByText('Request 4')).toBeTruthy();
  });

  it('offers a separate path without deleting the saved conversation', async () => {
    const onStartNewDesign = jest.fn();
    await render(<StudioPromptHistory project={project} onStartNewDesign={onStartNewDesign} />);

    fireEvent.press(screen.getByLabelText('Start a separate design'));
    expect(onStartNewDesign).toHaveBeenCalledTimes(1);
    expect(screen.getByText('Ruby on a gold necklace')).toBeTruthy();
  });
});
