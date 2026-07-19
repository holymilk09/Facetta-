/// <reference types="jest" />
import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react-native';

import { StudioCanvasEditPanel } from './StudioCanvasEditPanel';

const handlers = (overrides: Record<string, unknown> = {}) => ({
  onRequestAnnotation: jest.fn(),
  onClearAnnotation: jest.fn(),
  onPreviewChange: jest.fn(),
  onApplyPreview: jest.fn(),
  onSaveAsVariationPreview: jest.fn(),
  onDiscardPreview: jest.fn(),
  ...overrides,
}) as any;

test('starts with one plain-language edit and an explicit preservation promise', async () => {
  const callbacks = handlers();
  await render(<StudioCanvasEditPanel {...callbacks} creditEstimate={20} />);

  expect(screen.getByText('Make your changes.')).toBeTruthy();
  expect(screen.getByText(/keeps unmarked details fixed/i)).toBeTruthy();
  expect(screen.getByText(
    'Preview now · 0 credits. 20 credits only if you Apply or Save as variation.',
  )).toBeTruthy();
  expect(screen.getByText('Preview changes').parent?.props.accessibilityState).toEqual({ disabled: true });

  await fireEvent.changeText(screen.getByLabelText('Edit instruction'), 'Make the band slightly narrower.');
  await fireEvent.press(screen.getByText('Preview changes'));

  expect(callbacks.onPreviewChange).toHaveBeenCalledWith({
    mode: 'describe',
    instruction: 'Make the band slightly narrower.',
    annotation: null,
    backgroundPreset: null,
    anglePreset: null,
    preserveUnrequestedDetails: true,
  });
});

test('point mode requires both a marked area and an instruction', async () => {
  const callbacks = handlers();
  const view = await render(<StudioCanvasEditPanel {...callbacks} annotation={null} />);

  await fireEvent.press(screen.getByLabelText('Mark up editing tool'));
  await fireEvent.press(screen.getByText('Mark design'));
  expect(callbacks.onRequestAnnotation).toHaveBeenCalledTimes(1);

  await fireEvent.changeText(screen.getByLabelText('Edit instruction'), 'Make these prongs finer.');
  expect(screen.getByText('Preview changes').parent?.props.accessibilityState).toEqual({ disabled: true });

  await view.rerender(<StudioCanvasEditPanel {...callbacks} annotation={{ markCount: 1, label: 'Prongs marked' }} />);
  expect(screen.getByText('Prongs marked')).toBeTruthy();
  await fireEvent.press(screen.getByText('Preview changes'));

  expect(callbacks.onPreviewChange).toHaveBeenCalledWith(expect.objectContaining({
    mode: 'point',
    instruction: 'Make these prongs finer.',
    annotation: { markCount: 1, label: 'Prongs marked' },
    preserveUnrequestedDetails: true,
  }));
});

test('locally instructed marks preview without a conflicting global instruction', async () => {
  const callbacks = handlers();
  const view = await render(
    <StudioCanvasEditPanel
      {...callbacks}
      annotation={{
        markCount: 2,
        label: '2 marked changes ready',
        everyMarkCarriesInstruction: false,
      }}
    />,
  );

  await fireEvent.press(screen.getByLabelText('Mark up editing tool'));
  await fireEvent.changeText(
    screen.getByLabelText('Edit instruction'),
    'This stale global instruction must not be sent.',
  );
  await view.rerender(
    <StudioCanvasEditPanel
      {...callbacks}
      annotation={{
        markCount: 2,
        label: '2 marked changes ready',
        everyMarkCarriesInstruction: true,
      }}
    />,
  );
  expect(screen.getByText(/Every mark has its own instruction/i)).toBeTruthy();
  expect(screen.queryByLabelText('Edit instruction')).toBeNull();
  expect(screen.getByText('Preview changes').parent?.props.accessibilityState).toEqual({ disabled: false });
  await fireEvent.press(screen.getByText('Preview changes'));

  expect(callbacks.onPreviewChange).toHaveBeenCalledWith(expect.objectContaining({
    mode: 'point',
    instruction: '',
    annotation: expect.objectContaining({
      markCount: 2,
      everyMarkCarriesInstruction: true,
    }),
  }));
});

test('background and angle presets submit presentation-only requests', async () => {
  const callbacks = handlers();
  await render(<StudioCanvasEditPanel {...callbacks} />);

  await fireEvent.press(screen.getByLabelText('Background editing tool'));
  await fireEvent.press(screen.getByText('Dark luxury'));
  await fireEvent.press(screen.getByText('Preview changes'));
  expect(callbacks.onPreviewChange).toHaveBeenLastCalledWith(expect.objectContaining({
    mode: 'background',
    instruction: 'Show the jewelry on the selected dark luxury background.',
    backgroundPreset: 'dark_luxury',
    preserveUnrequestedDetails: true,
  }));

  await fireEvent.press(screen.getByLabelText('Angle editing tool'));
  await fireEvent.press(screen.getByText('Three-quarter'));
  await fireEvent.press(screen.getByText('Preview changes'));
  expect(callbacks.onPreviewChange).toHaveBeenLastCalledWith(expect.objectContaining({
    mode: 'angle',
    instruction: 'Show the same jewelry from the selected three quarter angle.',
    anglePreset: 'three_quarter',
    preserveUnrequestedDetails: true,
  }));
});

test('symmetry is an explicit one-click repair that keeps the center fixed', async () => {
  const callbacks = handlers();
  await render(<StudioCanvasEditPanel {...callbacks} />);

  await fireEvent.press(screen.getByLabelText('Symmetry editing tool'));

  expect(screen.getByText('Match both sides')).toBeTruthy();
  expect(screen.getByText(/Intentional asymmetry will otherwise be preserved/i)).toBeTruthy();
  expect(screen.getByText('Preview changes').parent?.props.accessibilityState).toEqual({ disabled: false });

  await fireEvent.press(screen.getByText('Preview changes'));

  expect(callbacks.onPreviewChange).toHaveBeenCalledWith({
    mode: 'symmetry',
    instruction: expect.stringMatching(/Mirror corresponding jewelry elements link by link/),
    annotation: null,
    backgroundPreset: null,
    anglePreset: null,
    preserveUnrequestedDetails: true,
  });
  expect(callbacks.onPreviewChange.mock.calls[0][0].instruction).toMatch(/Keep the center element/);
});

test('restores an app-owned canvas mode and reports the next mode', async () => {
  const callbacks = handlers({ onModeChange: jest.fn() });
  const view = await render(
    <StudioCanvasEditPanel {...callbacks} modeValue="symmetry" />,
  );

  expect(view.getByLabelText('Symmetry editing tool').props.accessibilityState.selected).toBe(true);
  await fireEvent.press(view.getByLabelText('Mark up editing tool'));
  expect(callbacks.onModeChange).toHaveBeenCalledWith('point');
});

test('a temporary preview exposes Apply, Save as variation, and Discard as separate decisions', async () => {
  const callbacks = handlers();
  await render(
    <StudioCanvasEditPanel
      {...callbacks}
      preview={{ summary: 'The background changed; the jewelry remains unchanged.' }}
    />,
  );

  expect(screen.getByText('TEMPORARY PREVIEW')).toBeTruthy();
  expect(screen.getByText(/Apply saves a new revision/i)).toBeTruthy();
  expect(screen.queryByText('Preview changes')).toBeNull();

  await fireEvent.press(screen.getByText('Discard'));
  await fireEvent.press(screen.getByText('Save as variation'));
  await fireEvent.press(screen.getByText('Apply change'));
  expect(callbacks.onDiscardPreview).toHaveBeenCalledTimes(1);
  expect(callbacks.onSaveAsVariationPreview).toHaveBeenCalledTimes(1);
  expect(callbacks.onApplyPreview).toHaveBeenCalledTimes(1);
});

test('an unavailable Apply explains why while Discard remains available', async () => {
  const callbacks = handlers();
  await render(
    <StudioCanvasEditPanel
      {...callbacks}
      preview={{ summary: 'The candidate is still temporary.' }}
      applyDisabled
      applyDisabledReason="Wait until both comparison images are ready before applying."
    />,
  );

  const reason = screen.getByText(/both comparison images are ready/i);
  expect(reason.props.accessibilityRole).toBe('alert');
  expect(screen.getByText('Apply change').parent?.props.accessibilityState).toEqual({ disabled: true });
  expect(screen.getByText('Discard').parent?.props.accessibilityState).toEqual({ disabled: false });

  await fireEvent.press(screen.getByText('Apply change'));
  await fireEvent.press(screen.getByText('Discard'));
  expect(callbacks.onApplyPreview).not.toHaveBeenCalled();
  expect(callbacks.onDiscardPreview).toHaveBeenCalledTimes(1);
});

test('working and error states fail closed', async () => {
  const callbacks = handlers();
  await render(
    <StudioCanvasEditPanel
      {...callbacks}
      error="The preview could not be created. Try again."
      working="preview"
    />,
  );

  expect(screen.getByText('The preview could not be created. Try again.').props.accessibilityRole).toBe('alert');
  expect(screen.getByText('Preparing preview…')).toBeTruthy();
  expect(screen.getByText('Preparing preview…').parent?.props.accessibilityState).toEqual({ disabled: true });
  await fireEvent.press(screen.getByText('Preparing preview…'));
  expect(callbacks.onPreviewChange).not.toHaveBeenCalled();
});
