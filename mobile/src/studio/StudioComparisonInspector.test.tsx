/// <reference types="jest" />

import React from 'react';
import {
  fireEvent, render, screen,
} from '@testing-library/react-native';
import { Dimensions, StyleSheet } from 'react-native';

import { AuthenticatedImageProvider } from '../AuthenticatedImage';
import {
  StudioComparisonInspector, StudioComparisonLayout,
} from './StudioComparisonInspector';

const beforeLabel = 'Exact Revision 7';
const afterLabel = 'Temporary refinement candidate';

async function renderComparison({
  layout = 'toggle' as StudioComparisonLayout,
  beforeOnLoad = jest.fn(),
  afterOnLoad = jest.fn(),
  onVisibleSideChange = jest.fn(),
} = {}) {
  await render(
    <AuthenticatedImageProvider
      allowedOrigin="https://facetta.test/api"
      headers={{ Authorization: 'Bearer runtime-token' }}>
      <StudioComparisonInspector
        after={{
          accessibilityLabel: 'Candidate compact preview',
          label: afterLabel,
          onLoad: afterOnLoad,
          roleLabel: 'After',
          source: { uri: '/assets/candidate_1/image' },
        }}
        before={{
          accessibilityLabel: 'Source compact preview',
          label: beforeLabel,
          onLoad: beforeOnLoad,
          roleLabel: 'Before',
          source: { uri: '/assets/revision_7/image' },
        }}
        layout={layout}
        onVisibleSideChange={onVisibleSideChange}
        testID="refinement-comparison"
      />
    </AuthenticatedImageProvider>,
  );
  return { afterOnLoad, beforeOnLoad, onVisibleSideChange };
}

test('phone layout keeps one decision viewport with persistent Before and After controls', async () => {
  const { onVisibleSideChange } = await renderComparison();

  expect(screen.getByTestId('studio-comparison-compact-viewport')).toBeTruthy();
  expect(screen.getByText(`Before: ${beforeLabel}`)).toBeTruthy();
  expect(screen.getByText(`After: ${afterLabel}`)).toBeTruthy();

  const beforeControl = screen.getByLabelText(`Show Before: ${beforeLabel}`);
  const afterControl = screen.getByLabelText(`Show After: ${afterLabel}`);
  expect(StyleSheet.flatten(beforeControl.props.style).minHeight).toBe(44);
  expect(StyleSheet.flatten(afterControl.props.style).minHeight).toBe(44);
  expect(afterControl.props.accessibilityState).toEqual({ selected: true });

  const beforeImage = screen.getByLabelText('Source compact preview');
  const afterImage = screen.getByLabelText('Candidate compact preview');
  expect(StyleSheet.flatten(beforeImage.props.style).opacity).toBe(0);
  expect(StyleSheet.flatten(afterImage.props.style).opacity).toBeUndefined();

  await fireEvent.press(beforeControl);
  expect(onVisibleSideChange).toHaveBeenCalledWith('before');
  expect(screen.getByLabelText(`Show Before: ${beforeLabel}`).props.accessibilityState)
    .toEqual({ selected: true });
  expect(StyleSheet.flatten(screen.getByLabelText('Source compact preview').props.style).opacity)
    .toBeUndefined();
  expect(StyleSheet.flatten(screen.getByLabelText('Candidate compact preview').props.style).opacity)
    .toBe(0);
});

test('compact images preserve authenticated loading and remain the only readiness authority', async () => {
  const { beforeOnLoad, afterOnLoad } = await renderComparison({ layout: 'split' });

  expect(screen.queryByLabelText(`Show Before: ${beforeLabel}`)).toBeNull();
  expect(screen.queryByLabelText(`Show After: ${afterLabel}`)).toBeNull();
  expect(screen.getByText(`Before: ${beforeLabel}`)).toBeTruthy();
  expect(screen.getByText(`After: ${afterLabel}`)).toBeTruthy();
  const compactBefore = screen.getByLabelText('Source compact preview');
  const compactAfter = screen.getByLabelText('Candidate compact preview');
  expect(compactBefore.props.source).toMatchObject({
    uri: 'https://facetta.test/assets/revision_7/image',
    headers: { Authorization: 'Bearer runtime-token' },
  });
  expect(compactAfter.props.source).toMatchObject({
    uri: 'https://facetta.test/assets/candidate_1/image',
    headers: { Authorization: 'Bearer runtime-token' },
  });

  await fireEvent.press(screen.getByLabelText('Inspect comparison in detail'));

  const detailAfter = screen.getByLabelText(`After: ${afterLabel} detail view`);
  expect(detailAfter.props.source).toMatchObject({
    uri: 'https://facetta.test/assets/candidate_1/image',
    headers: { Authorization: 'Bearer runtime-token' },
  });
  expect(detailAfter.props.onLoad).toBeUndefined();

  await fireEvent(detailAfter, 'load');
  expect(beforeOnLoad).not.toHaveBeenCalled();
  expect(afterOnLoad).not.toHaveBeenCalled();

  await fireEvent.press(screen.getByLabelText(`Show Before: ${beforeLabel} in detail`));
  const detailBefore = screen.getByLabelText(`Before: ${beforeLabel} detail view`);
  expect(detailBefore.props.source).toMatchObject({
    uri: 'https://facetta.test/assets/revision_7/image',
    headers: { Authorization: 'Bearer runtime-token' },
  });
  expect(detailBefore.props.onLoad).toBeUndefined();
  await fireEvent(detailBefore, 'load');
  expect(beforeOnLoad).not.toHaveBeenCalled();

  await fireEvent(compactBefore, 'load');
  await fireEvent(compactAfter, 'load');
  expect(beforeOnLoad).toHaveBeenCalledTimes(1);
  expect(afterOnLoad).toHaveBeenCalledTimes(1);
});

test('full inspection applies one shared 1x, 2x, or 4x zoom to both images', async () => {
  await renderComparison({ layout: 'split' });

  await fireEvent.press(screen.getByLabelText('Inspect comparison in detail'));

  expect(screen.getByText('SYNCHRONIZED COMPARISON')).toBeTruthy();
  const zoom1 = screen.getByLabelText('Set comparison zoom to 1x');
  const zoom2 = screen.getByLabelText('Set comparison zoom to 2x');
  const zoom4 = screen.getByLabelText('Set comparison zoom to 4x');
  expect(StyleSheet.flatten(zoom1.props.style).minHeight).toBe(44);
  expect(StyleSheet.flatten(zoom2.props.style).minHeight).toBe(44);
  expect(StyleSheet.flatten(zoom4.props.style).minHeight).toBe(44);
  expect(zoom1.props.accessibilityState).toEqual({ selected: true });

  const afterAt1x = StyleSheet.flatten(
    screen.getByLabelText(`After: ${afterLabel} detail view`).props.style,
  );

  await fireEvent.press(zoom4);
  expect(screen.getByLabelText('Set comparison zoom to 4x').props.accessibilityState)
    .toEqual({ selected: true });
  const afterAt4x = StyleSheet.flatten(
    screen.getByLabelText(`After: ${afterLabel} detail view`).props.style,
  );
  expect(afterAt4x.width).toBe(afterAt1x.width * 4);
  expect(afterAt4x.height).toBe(afterAt1x.height * 4);

  await fireEvent.press(screen.getByLabelText(`Show Before: ${beforeLabel} in detail`));
  const beforeAt4x = StyleSheet.flatten(
    screen.getByLabelText(`Before: ${beforeLabel} detail view`).props.style,
  );
  expect(beforeAt4x.width).toBe(afterAt4x.width);
  expect(beforeAt4x.height).toBe(afterAt4x.height);
  expect(screen.getByText('Switching sides keeps the same scale and position.')).toBeTruthy();

  await fireEvent.press(screen.getByLabelText('Close comparison inspector'));
  expect(screen.queryByTestId('studio-comparison-detail-viewport')).toBeNull();
});

test('auto layout selects the one-viewport controls at phone width', async () => {
  const phone = { width: 390, height: 844, scale: 3, fontScale: 1 };
  Dimensions.set({ window: phone, screen: phone });

  await renderComparison({ layout: 'auto' });

  expect(screen.getByTestId('studio-comparison-compact-viewport')).toBeTruthy();
  expect(screen.getByLabelText(`Show Before: ${beforeLabel}`)).toBeTruthy();
  expect(screen.getByLabelText(`Show After: ${afterLabel}`)).toBeTruthy();
  expect(StyleSheet.flatten(screen.getByLabelText('Source compact preview').props.style).opacity)
    .toBe(0);
  expect(StyleSheet.flatten(screen.getByLabelText('Candidate compact preview').props.style).opacity)
    .toBeUndefined();
});
