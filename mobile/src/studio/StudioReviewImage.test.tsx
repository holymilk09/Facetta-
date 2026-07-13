/// <reference types="jest" />

import React from 'react';
import {
  act, fireEvent, render, screen,
} from '@testing-library/react-native';
import { StyleSheet } from 'react-native';

import { AuthenticatedImageProvider } from '../AuthenticatedImage';
import { StudioReviewImage } from './StudioReviewImage';

async function renderInspector(onLoad = jest.fn()) {
  await render(
    <AuthenticatedImageProvider
      allowedOrigin="https://facetta.test/api"
      headers={{ Authorization: 'Bearer runtime-token' }}>
      <StudioReviewImage
        accessibilityLabel="Temporary refinement preview"
        inspectionLabel="Temporary refinement candidate"
        onLoad={onLoad}
        source={{ uri: '/assets/candidate_1/image' }}
        style={{ width: 320, height: 240 }}
      />
    </AuthenticatedImageProvider>,
  );
  return onLoad;
}

test('opens an authenticated full-detail inspector with explicit jewelry zoom controls', async () => {
  await renderInspector();

  const compact = screen.getByLabelText('Temporary refinement preview');
  expect(compact.props.source).toMatchObject({
    uri: 'https://facetta.test/assets/candidate_1/image',
    headers: { Authorization: 'Bearer runtime-token' },
  });

  await act(async () => {
    fireEvent.press(screen.getByLabelText(
      'Inspect Temporary refinement candidate in detail',
    ));
  });

  expect(screen.getByText('DETAIL INSPECTION')).toBeTruthy();
  expect(screen.getByText(/Check prongs, stone outlines, pavé spacing/)).toBeTruthy();
  const detail = screen.getByLabelText('Temporary refinement candidate detail view');
  expect(detail.props.source).toMatchObject({
    uri: 'https://facetta.test/assets/candidate_1/image',
    headers: { Authorization: 'Bearer runtime-token' },
  });

  await act(async () => {
    fireEvent.press(screen.getByLabelText('Zoom image to 4x'));
  });
  expect(screen.getByLabelText('Zoom image to 4x').props.accessibilityState).toEqual({
    selected: true,
  });
  expect(StyleSheet.flatten(
    screen.getByLabelText('Temporary refinement candidate detail view').props.style,
  ).width).toBeGreaterThan(1000);

  await act(async () => {
    fireEvent.press(screen.getByLabelText('Close image inspector'));
  });
  expect(screen.queryByLabelText('Temporary refinement candidate detail view')).toBeNull();
});

test('inspector loading and zooming cannot authorize the compact review image', async () => {
  const onLoad = await renderInspector();
  const compact = screen.getByLabelText('Temporary refinement preview');
  await act(async () => {
    fireEvent.press(screen.getByLabelText(
      'Inspect Temporary refinement candidate in detail',
    ));
  });

  expect(screen.getByLabelText(
    'Temporary refinement candidate detail view',
  ).props.onLoad).toBeUndefined();
  await act(async () => {
    fireEvent.press(screen.getByLabelText('Zoom image to 2x'));
  });
  expect(onLoad).not.toHaveBeenCalled();

  fireEvent(compact, 'load');
  expect(onLoad).toHaveBeenCalledTimes(1);
});
