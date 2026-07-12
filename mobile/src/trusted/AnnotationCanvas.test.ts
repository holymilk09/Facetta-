/// <reference types="jest" />

import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react-native';

import {
  AnnotationCanvas,
  createAnnotationSnapshot,
  normalizeCanvasPoint,
  serializeAnnotationSnapshot,
  type AnnotationCanvasSnapshot,
  type CanvasAnnotation,
} from './AnnotationCanvas';

const imageUri = 'data:image/png;base64,aW1hZ2U=';

const responderEvent = (locationX: number, locationY: number) => ({
  nativeEvent: { locationX, locationY },
});

const draw = async (
  canvas: ReturnType<typeof screen.getByLabelText>,
  start: [number, number],
  moves: [number, number][],
  end: [number, number],
) => {
  await fireEvent(canvas, 'responderGrant', responderEvent(...start));
  for (const point of moves) {
    await fireEvent(canvas, 'responderMove', responderEvent(...point));
  }
  await fireEvent(canvas, 'responderRelease', responderEvent(...end));
};

describe('AnnotationCanvas normalized geometry', () => {
  test('normalizes and clamps points independently of rendered pixel size', () => {
    expect(normalizeCanvasPoint({ x: 100, y: 50 }, { width: 200, height: 100 }))
      .toEqual({ x: 0.5, y: 0.5 });
    expect(normalizeCanvasPoint({ x: 400, y: 200 }, { width: 800, height: 400 }))
      .toEqual({ x: 0.5, y: 0.5 });
    expect(normalizeCanvasPoint({ x: -20, y: 900 }, { width: 200, height: 100 }))
      .toEqual({ x: 0, y: 1 });
  });

  test('exports a canonical, normalized, versioned adapter snapshot', () => {
    const source: CanvasAnnotation[] = [{
      id: 'annotation-1',
      type: 'rectangle',
      start: { x: -1, y: 0.25 },
      end: { x: 2, y: 0.75 },
      color: '#ff0000',
      stroke_width: 5,
    }];
    const snapshot = createAnnotationSnapshot(imageUri, source);

    expect(snapshot).toEqual({
      schema_version: 1,
      coordinate_space: 'normalized_image',
      source_uri: imageUri,
      annotations: [{
        id: 'annotation-1',
        color: '#ff0000',
        stroke_width: 0.1,
        type: 'rectangle',
        start: { x: 0, y: 0.25 },
        end: { x: 1, y: 0.75 },
      }],
    });
    expect(serializeAnnotationSnapshot(snapshot)).toBe(JSON.stringify(snapshot));
  });
});

describe('AnnotationCanvas interaction', () => {
  test('draws circle, rectangle, arrow, freehand, and text into one typed snapshot', async () => {
    const changed = jest.fn<void, [AnnotationCanvasSnapshot]>();
    const exported = jest.fn<void, [AnnotationCanvasSnapshot]>();
    await render(React.createElement(AnnotationCanvas, {
      sourceUri: imageUri,
      imageAspectRatio: 2,
      onChange: changed,
      onExport: exported,
    }));
    const canvas = screen.getByLabelText('Jewelry image annotation canvas');
    await fireEvent(canvas, 'layout', {
      nativeEvent: { layout: { x: 0, y: 0, width: 200, height: 100 } },
    });

    await fireEvent.press(screen.getByLabelText('Circle annotation tool'));
    await draw(canvas, [20, 10], [], [100, 50]);

    await fireEvent.press(screen.getByLabelText('Rectangle annotation tool'));
    await draw(canvas, [40, 20], [], [80, 60]);

    await fireEvent.press(screen.getByLabelText('Arrow annotation tool'));
    await draw(canvas, [10, 90], [], [190, 10]);

    await fireEvent.press(screen.getByLabelText('Freehand annotation tool'));
    await draw(canvas, [0, 0], [[100, 50]], [200, 100]);

    await fireEvent.press(screen.getByLabelText('Text annotation tool'));
    await fireEvent.changeText(
      screen.getByLabelText('Annotation text'),
      'Widen only this shoulder',
    );
    await draw(canvas, [150, 80], [], [150, 80]);

    expect(screen.getByLabelText('circle annotation annotation-1')).toBeTruthy();
    expect(screen.getByLabelText('rectangle annotation annotation-2')).toBeTruthy();
    expect(screen.getByLabelText('arrow annotation annotation-3')).toBeTruthy();
    expect(screen.getByLabelText('freehand annotation annotation-4')).toBeTruthy();
    expect(screen.getByLabelText('text annotation annotation-5')).toBeTruthy();
    expect(changed).toHaveBeenCalledTimes(5);

    await fireEvent.press(screen.getByLabelText('Export annotation snapshot'));
    const snapshot = exported.mock.calls[0][0];
    expect(snapshot.schema_version).toBe(1);
    expect(snapshot.coordinate_space).toBe('normalized_image');
    expect(snapshot.annotations.map(({ type }) => type)).toEqual([
      'circle',
      'rectangle',
      'arrow',
      'freehand',
      'text',
    ]);
    expect(snapshot.annotations[0]).toMatchObject({
      start: { x: 0.1, y: 0.1 },
      end: { x: 0.5, y: 0.5 },
    });
    expect(snapshot.annotations[3]).toMatchObject({
      points: [{ x: 0, y: 0 }, { x: 0.5, y: 0.5 }, { x: 1, y: 1 }],
    });
    expect(snapshot.annotations[4]).toMatchObject({
      anchor: { x: 0.75, y: 0.8 },
      text: 'Widen only this shoulder',
    });
  });

  test('undoes and clears annotations without mutating the input array', async () => {
    const original: CanvasAnnotation[] = [{
      id: 'annotation-1',
      type: 'rectangle',
      start: { x: 0.1, y: 0.1 },
      end: { x: 0.4, y: 0.4 },
      color: '#b42318',
      stroke_width: 0.006,
    }, {
      id: 'annotation-2',
      type: 'circle',
      start: { x: 0.5, y: 0.5 },
      end: { x: 0.8, y: 0.8 },
      color: '#b42318',
      stroke_width: 0.006,
    }];
    const changed = jest.fn<void, [AnnotationCanvasSnapshot]>();
    await render(React.createElement(AnnotationCanvas, {
      sourceUri: imageUri,
      initialAnnotations: original,
      onChange: changed,
    }));

    await fireEvent.press(screen.getByLabelText('Undo last annotation'));
    expect(changed.mock.calls[0][0].annotations).toHaveLength(1);
    expect(screen.queryByLabelText('circle annotation annotation-2')).toBeNull();

    await fireEvent.press(screen.getByLabelText('Clear all annotations'));
    expect(changed.mock.calls[1][0].annotations).toEqual([]);
    expect(original).toHaveLength(2);
  });

  test('keeps annotations reviewable while disabling all drawing mutation controls', async () => {
    const initial = createAnnotationSnapshot(imageUri, [{
      id: 'annotation-1',
      type: 'arrow',
      start: { x: 0.1, y: 0.2 },
      end: { x: 0.8, y: 0.7 },
      color: '#b42318',
      stroke_width: 0.006,
    }]);
    const changed = jest.fn<void, [AnnotationCanvasSnapshot]>();
    const exported = jest.fn<void, [AnnotationCanvasSnapshot]>();
    await render(React.createElement(AnnotationCanvas, {
      sourceUri: imageUri,
      value: initial,
      drawingEnabled: false,
      onChange: changed,
      onExport: exported,
    }));

    const canvas = screen.getByLabelText('Jewelry image annotation canvas');
    await fireEvent(canvas, 'layout', {
      nativeEvent: { layout: { x: 0, y: 0, width: 200, height: 100 } },
    });
    await draw(canvas, [0, 0], [], [100, 100]);
    await fireEvent.press(screen.getByLabelText('Undo last annotation'));
    await fireEvent.press(screen.getByLabelText('Clear all annotations'));

    expect(screen.getByLabelText('arrow annotation annotation-1')).toBeTruthy();
    expect(screen.getByText(/View-only annotation review/)).toBeTruthy();
    expect(screen.getByLabelText('Circle annotation tool').props.accessibilityState)
      .toMatchObject({ disabled: true });
    expect(changed).not.toHaveBeenCalled();

    await fireEvent.press(screen.getByLabelText('Export annotation snapshot'));
    expect(exported).toHaveBeenCalledWith(initial);
  });
});
