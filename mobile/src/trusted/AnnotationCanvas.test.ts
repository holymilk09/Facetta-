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

const saveInstruction = async (instruction: string) => {
  await fireEvent.changeText(
    screen.getByLabelText('Instruction for selected annotation'),
    instruction,
  );
  await fireEvent.press(screen.getByLabelText('Save annotation instruction'));
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
    await saveInstruction('Make this circle warmer');

    await fireEvent.press(screen.getByLabelText('Rectangle annotation tool'));
    await draw(canvas, [40, 20], [], [80, 60]);
    await saveInstruction('Polish this boxed area');

    await fireEvent.press(screen.getByLabelText('Arrow annotation tool'));
    await draw(canvas, [10, 90], [], [190, 10]);
    await saveInstruction('Lower this arrow target');

    await fireEvent.press(screen.getByLabelText('Freehand annotation tool'));
    await draw(canvas, [0, 0], [[100, 50]], [200, 100]);
    await saveInstruction('Refine this traced edge');

    await fireEvent.press(screen.getByLabelText('Text annotation tool'));
    expect(screen.queryByLabelText('Instruction for selected annotation')).toBeNull();
    await draw(canvas, [150, 80], [], [150, 80]);
    await fireEvent.changeText(
      screen.getByLabelText('Instruction for selected annotation'),
      'Widen only this shoulder',
    );
    await fireEvent.press(screen.getByLabelText('Save annotation instruction'));

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
    expect(snapshot.annotations.map(({ instruction }) => instruction)).toEqual([
      'Make this circle warmer',
      'Polish this boxed area',
      'Lower this arrow target',
      'Refine this traced edge',
      'Widen only this shoulder',
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
      instruction: 'Widen only this shoulder',
      text: 'Widen only this shoulder',
    });
  });

  test('selects overlapping marks from the numbered list and edits or deletes either one', async () => {
    const changed = jest.fn<void, [AnnotationCanvasSnapshot]>();
    await render(React.createElement(AnnotationCanvas, {
      sourceUri: imageUri,
      imageAspectRatio: 2,
      initialAnnotations: [{
        id: 'annotation-1',
        type: 'rectangle',
        start: { x: 0.1, y: 0.1 },
        end: { x: 0.7, y: 0.7 },
        instruction: 'Narrow this setting',
        color: '#b42318',
        stroke_width: 0.006,
      }, {
        id: 'annotation-2',
        type: 'circle',
        start: { x: 0.2, y: 0.2 },
        end: { x: 0.6, y: 0.6 },
        instruction: 'Lower this stone',
        color: '#b42318',
        stroke_width: 0.006,
      }],
      onChange: changed,
    }));
    const canvas = screen.getByLabelText('Jewelry image annotation canvas');
    await fireEvent(canvas, 'layout', {
      nativeEvent: { layout: { x: 0, y: 0, width: 200, height: 100 } },
    });

    expect(screen.getByLabelText('Annotation mark list')).toBeTruthy();
    await fireEvent.press(screen.getByLabelText('Select mark 1'));
    expect(screen.getByLabelText('Select mark 1').props.accessibilityState.selected).toBe(true);
    await fireEvent.press(screen.getByLabelText('Edit mark 1 instruction'));
    await fireEvent.changeText(
      screen.getByLabelText('Instruction for selected annotation'),
      'Narrow the setting and soften both shoulders',
    );
    await fireEvent.press(screen.getByLabelText('Save annotation instruction'));
    expect(changed.mock.calls[0][0].annotations[0]).toMatchObject({
      id: 'annotation-1',
      instruction: 'Narrow the setting and soften both shoulders',
    });

    await fireEvent.press(screen.getByLabelText('Delete mark 2'));
    expect(changed.mock.calls[1][0].annotations).toEqual([
      expect.objectContaining({ id: 'annotation-1' }),
    ]);

    // The center is far from the rectangle perimeter; selecting it proves
    // that shape interiors, not only their strokes, are interactive.
    await draw(canvas, [80, 40], [], [80, 40]);
    expect(screen.getByLabelText('Selected annotation instruction editor')).toBeTruthy();
    expect(screen.getByDisplayValue('Narrow the setting and soften both shoulders')).toBeTruthy();
  });

  test('keeps an unsaved text target out of the snapshot and supports save, edit, and cancel', async () => {
    const changed = jest.fn<void, [AnnotationCanvasSnapshot]>();
    await render(React.createElement(AnnotationCanvas, {
      sourceUri: imageUri,
      imageAspectRatio: 2,
      onChange: changed,
    }));
    const canvas = screen.getByLabelText('Jewelry image annotation canvas');
    await fireEvent(canvas, 'layout', {
      nativeEvent: { layout: { x: 0, y: 0, width: 200, height: 100 } },
    });

    await fireEvent.press(screen.getByLabelText('Text annotation tool'));
    await draw(canvas, [80, 40], [], [80, 40]);
    expect(changed).not.toHaveBeenCalled();
    expect(screen.getByLabelText('Selected annotation annotation-1')).toBeTruthy();
    await fireEvent.changeText(
      screen.getByLabelText('Instruction for selected annotation'),
      'Lower this setting',
    );
    expect(changed).not.toHaveBeenCalled();
    await fireEvent.press(screen.getByLabelText('Save annotation instruction'));
    expect(changed).toHaveBeenCalledTimes(1);
    expect(changed.mock.calls[0][0].annotations).toEqual([
      expect.objectContaining({
        id: 'annotation-1',
        type: 'text',
        anchor: { x: 0.4, y: 0.4 },
        text: 'Lower this setting',
      }),
    ]);

    await draw(canvas, [80, 40], [], [80, 40]);
    await fireEvent.changeText(
      screen.getByLabelText('Instruction for selected annotation'),
      'Raise this setting instead',
    );
    await fireEvent.press(screen.getByLabelText('Save annotation instruction'));
    expect(changed).toHaveBeenCalledTimes(2);
    expect(changed.mock.calls[1][0].annotations).toEqual([
      expect.objectContaining({
        id: 'annotation-1',
        text: 'Raise this setting instead',
      }),
    ]);

    await fireEvent.press(screen.getByLabelText('Text annotation tool'));
    await draw(canvas, [160, 80], [], [160, 80]);
    await fireEvent.changeText(
      screen.getByLabelText('Instruction for selected annotation'),
      'Discard me',
    );
    await fireEvent.press(screen.getByLabelText('Cancel annotation instruction'));
    expect(changed).toHaveBeenCalledTimes(2);
    expect(screen.queryByLabelText('text annotation annotation-2')).toBeNull();
  });

  test.each<{
    name: string;
    annotation: CanvasAnnotation;
    grab: [number, number];
    expected: object;
  }>([
    {
      name: 'rectangle',
      annotation: {
        id: 'annotation-1', type: 'rectangle', color: '#b42318', stroke_width: 0.006,
        start: { x: 0.1, y: 0.1 }, end: { x: 0.3, y: 0.3 },
      },
      grab: [20, 10],
      expected: { start: { x: 0.5, y: 0.5 }, end: { x: 0.7, y: 0.7 } },
    },
    {
      name: 'circle',
      annotation: {
        id: 'annotation-1', type: 'circle', color: '#b42318', stroke_width: 0.006,
        start: { x: 0.1, y: 0.1 }, end: { x: 0.3, y: 0.3 },
      },
      grab: [20, 20],
      expected: { start: { x: 0.5, y: 0.4 }, end: { x: 0.7, y: 0.6 } },
    },
    {
      name: 'arrow',
      annotation: {
        id: 'annotation-1', type: 'arrow', color: '#b42318', stroke_width: 0.006,
        start: { x: 0.1, y: 0.1 }, end: { x: 0.3, y: 0.3 },
      },
      grab: [40, 20],
      expected: { start: { x: 0.4, y: 0.4 }, end: { x: 0.6, y: 0.6 } },
    },
    {
      name: 'freehand',
      annotation: {
        id: 'annotation-1', type: 'freehand', color: '#b42318', stroke_width: 0.006,
        points: [{ x: 0.1, y: 0.1 }, { x: 0.3, y: 0.3 }],
      },
      grab: [40, 20],
      expected: { points: [{ x: 0.4, y: 0.4 }, { x: 0.6, y: 0.6 }] },
    },
    {
      name: 'text',
      annotation: {
        id: 'annotation-1', type: 'text', color: '#b42318', stroke_width: 0.006,
        anchor: { x: 0.2, y: 0.2 }, text: 'Move me', font_size: 0.045,
      },
      grab: [40, 20],
      expected: { anchor: { x: 0.5, y: 0.5 }, text: 'Move me' },
    },
  ])('selects and repositions a $name annotation without changing its geometry', async ({
    annotation,
    grab,
    expected,
  }) => {
    const changed = jest.fn<void, [AnnotationCanvasSnapshot]>();
    const view = await render(React.createElement(AnnotationCanvas, {
      sourceUri: imageUri,
      imageAspectRatio: 2,
      initialAnnotations: [annotation],
      onChange: changed,
    }));
    const canvas = screen.getByLabelText('Jewelry image annotation canvas');
    await fireEvent(canvas, 'layout', {
      nativeEvent: { layout: { x: 0, y: 0, width: 200, height: 100 } },
    });
    await draw(canvas, grab, [], [100, 50]);

    expect(screen.getByLabelText('Selected annotation annotation-1')).toBeTruthy();
    expect(changed).toHaveBeenCalledTimes(1);
    expect(changed.mock.calls[0][0].annotations[0]).toMatchObject(expected);
    if (annotation.type === 'text') {
      expect(screen.queryByLabelText('Instruction for selected annotation')).toBeNull();
    }
    view.unmount();
  });

  test('rolls back a terminated drag and deletes only the selected annotation', async () => {
    const original: CanvasAnnotation[] = [{
      id: 'annotation-1',
      type: 'rectangle',
      start: { x: 0.1, y: 0.1 },
      end: { x: 0.3, y: 0.3 },
      color: '#b42318',
      stroke_width: 0.006,
    }, {
      id: 'annotation-2',
      type: 'arrow',
      start: { x: 0.6, y: 0.6 },
      end: { x: 0.8, y: 0.8 },
      color: '#b42318',
      stroke_width: 0.006,
    }];
    const changed = jest.fn<void, [AnnotationCanvasSnapshot]>();
    await render(React.createElement(AnnotationCanvas, {
      sourceUri: imageUri,
      imageAspectRatio: 2,
      initialAnnotations: original,
      onChange: changed,
    }));
    const canvas = screen.getByLabelText('Jewelry image annotation canvas');
    await fireEvent(canvas, 'layout', {
      nativeEvent: { layout: { x: 0, y: 0, width: 200, height: 100 } },
    });

    await fireEvent(canvas, 'responderGrant', responderEvent(20, 10));
    await fireEvent(canvas, 'responderMove', responderEvent(100, 50));
    await fireEvent(canvas, 'responderTerminate', responderEvent(100, 50));
    expect(changed).not.toHaveBeenCalled();

    await draw(canvas, [20, 10], [], [20, 10]);
    await fireEvent.press(screen.getByLabelText('Delete selected annotation'));
    expect(changed).toHaveBeenCalledTimes(1);
    expect(changed.mock.calls[0][0].annotations).toEqual([
      expect.objectContaining({ id: 'annotation-2', type: 'arrow' }),
    ]);
    expect(original).toHaveLength(2);
  });

  test('clamps a moved annotation to the canvas without reshaping it', async () => {
    const changed = jest.fn<void, [AnnotationCanvasSnapshot]>();
    await render(React.createElement(AnnotationCanvas, {
      sourceUri: imageUri,
      imageAspectRatio: 2,
      initialAnnotations: [{
        id: 'annotation-1',
        type: 'rectangle',
        start: { x: 0.7, y: 0.7 },
        end: { x: 0.9, y: 0.9 },
        color: '#b42318',
        stroke_width: 0.006,
      }],
      onChange: changed,
    }));
    const canvas = screen.getByLabelText('Jewelry image annotation canvas');
    await fireEvent(canvas, 'layout', {
      nativeEvent: { layout: { x: 0, y: 0, width: 200, height: 100 } },
    });
    await draw(canvas, [140, 70], [], [400, 300]);
    const moved = changed.mock.calls[0][0].annotations[0];
    expect(moved).toMatchObject({ type: 'rectangle' });
    if (moved.type !== 'rectangle') throw new Error('Expected a rectangle');
    expect(moved.start.x).toBeCloseTo(0.8);
    expect(moved.start.y).toBeCloseTo(0.8);
    expect(moved.end).toEqual({ x: 1, y: 1 });
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
