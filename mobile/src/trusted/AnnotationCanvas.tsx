import React, { useMemo, useRef, useState } from 'react';
import {
  type LayoutChangeEvent,
  type NativeSyntheticEvent,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  type GestureResponderEvent,
  View,
} from 'react-native';
import { AuthenticatedImage as Image } from '../AuthenticatedImage';

import { theme } from '../theme';

export const ANNOTATION_SNAPSHOT_SCHEMA_VERSION = 1 as const;

export type AnnotationTool = 'circle' | 'rectangle' | 'arrow' | 'freehand' | 'text';

export interface NormalizedAnnotationPoint {
  /** Horizontal position in image-relative 0–1 space. */
  x: number;
  /** Vertical position in image-relative 0–1 space. */
  y: number;
}

interface AnnotationBase {
  id: string;
  color: string;
  /** Stroke width relative to the canvas's shortest edge. */
  stroke_width: number;
  /** Local edit instruction attached to this exact marked region. */
  instruction?: string;
}

export interface AnnotationRectangle extends AnnotationBase {
  type: 'rectangle';
  start: NormalizedAnnotationPoint;
  end: NormalizedAnnotationPoint;
}

export interface AnnotationCircle extends AnnotationBase {
  type: 'circle';
  start: NormalizedAnnotationPoint;
  end: NormalizedAnnotationPoint;
}

export interface AnnotationArrow extends AnnotationBase {
  type: 'arrow';
  start: NormalizedAnnotationPoint;
  end: NormalizedAnnotationPoint;
}

export interface AnnotationFreehand extends AnnotationBase {
  type: 'freehand';
  points: NormalizedAnnotationPoint[];
}

export interface AnnotationText extends AnnotationBase {
  type: 'text';
  anchor: NormalizedAnnotationPoint;
  /** Schema-v1 compatibility alias for instruction. */
  text: string;
  /** Font size relative to the canvas's shortest edge. */
  font_size: number;
}

export type CanvasAnnotation =
  | AnnotationRectangle
  | AnnotationCircle
  | AnnotationArrow
  | AnnotationFreehand
  | AnnotationText;

/**
 * Stable interchange format for a web/native raster adapter or the markup API.
 * Pixel dimensions are deliberately absent: all geometry is relative to the
 * displayed source image and survives resizing without conversion loss.
 */
export interface AnnotationCanvasSnapshot {
  schema_version: typeof ANNOTATION_SNAPSHOT_SCHEMA_VERSION;
  coordinate_space: 'normalized_image';
  source_uri: string;
  annotations: CanvasAnnotation[];
}

export interface AnnotationCanvasProps {
  sourceUri: string;
  /** Controlled snapshot. When omitted, the canvas owns its annotation state. */
  value?: AnnotationCanvasSnapshot;
  initialAnnotations?: readonly CanvasAnnotation[];
  onChange?: (snapshot: AnnotationCanvasSnapshot) => void;
  /** Emits the deterministic typed snapshot for a platform raster/API adapter. */
  onExport?: (snapshot: AnnotationCanvasSnapshot) => void;
  drawingEnabled?: boolean;
  initialTool?: AnnotationTool;
  strokeColor?: string;
  imageAspectRatio?: number;
  testID?: string;
}

interface CanvasSize {
  width: number;
  height: number;
}

const DEFAULT_STROKE_WIDTH = 0.006;
const DEFAULT_FONT_SIZE = 0.045;
const DEFAULT_ASPECT_RATIO = 1;
const MIN_SHAPE_DISTANCE = 0.004;

const TOOL_LABELS: Record<AnnotationTool, string> = {
  circle: 'Circle',
  rectangle: 'Rectangle',
  arrow: 'Arrow',
  freehand: 'Freehand',
  text: 'Text',
};

const clampNormalized = (value: number): number =>
  Math.max(0, Math.min(1, Number.isFinite(value) ? value : 0));

export function normalizeCanvasPoint(
  point: { x: number; y: number },
  size: CanvasSize,
): NormalizedAnnotationPoint {
  return {
    x: clampNormalized(size.width > 0 ? point.x / size.width : 0),
    y: clampNormalized(size.height > 0 ? point.y / size.height : 0),
  };
}

const normalizedPoint = (
  point: NormalizedAnnotationPoint,
): NormalizedAnnotationPoint => ({
  x: clampNormalized(point.x),
  y: clampNormalized(point.y),
});

const normalizedStroke = (value: number): number =>
  Math.max(0.001, Math.min(0.1, Number.isFinite(value) ? value : DEFAULT_STROKE_WIDTH));

const localInstruction = (annotation: CanvasAnnotation): string => (
  annotation.instruction ?? (annotation.type === 'text' ? annotation.text : '')
).trim();

function normalizeAnnotation(annotation: CanvasAnnotation): CanvasAnnotation {
  const instruction = localInstruction(annotation);
  const base = {
    id: annotation.id,
    color: annotation.color,
    stroke_width: normalizedStroke(annotation.stroke_width),
    ...(instruction ? { instruction } : {}),
  };
  switch (annotation.type) {
    case 'circle':
    case 'rectangle':
    case 'arrow':
      return {
        ...base,
        type: annotation.type,
        start: normalizedPoint(annotation.start),
        end: normalizedPoint(annotation.end),
      };
    case 'freehand':
      return {
        ...base,
        type: 'freehand',
        points: annotation.points.map(normalizedPoint),
      };
    case 'text':
      return {
        ...base,
        type: 'text',
        anchor: normalizedPoint(annotation.anchor),
        text: instruction,
        font_size: Math.max(0.01, Math.min(0.2, annotation.font_size)),
      };
  }
}

export function createAnnotationSnapshot(
  sourceUri: string,
  annotations: readonly CanvasAnnotation[],
): AnnotationCanvasSnapshot {
  return {
    schema_version: ANNOTATION_SNAPSHOT_SCHEMA_VERSION,
    coordinate_space: 'normalized_image',
    source_uri: sourceUri,
    annotations: annotations.map(normalizeAnnotation),
  };
}

/** Canonical JSON suitable for hashing, persistence, or an adapter boundary. */
export function serializeAnnotationSnapshot(
  snapshot: AnnotationCanvasSnapshot,
): string {
  return JSON.stringify(createAnnotationSnapshot(
    snapshot.source_uri,
    snapshot.annotations,
  ));
}

const pointDistance = (
  left: NormalizedAnnotationPoint,
  right: NormalizedAnnotationPoint,
): number => Math.hypot(right.x - left.x, right.y - left.y);

const annotationIsMeaningful = (annotation: CanvasAnnotation): boolean => {
  if (annotation.type === 'text') return true;
  if (annotation.type === 'freehand') {
    if (annotation.points.length < 2) return false;
    return annotation.points.some((point, index) =>
      index > 0 && pointDistance(annotation.points[index - 1], point) >= MIN_SHAPE_DISTANCE);
  }
  if (annotation.type === 'circle' || annotation.type === 'rectangle') {
    return Math.abs(annotation.end.x - annotation.start.x) >= MIN_SHAPE_DISTANCE
      && Math.abs(annotation.end.y - annotation.start.y) >= MIN_SHAPE_DISTANCE;
  }
  return pointDistance(annotation.start, annotation.end) >= MIN_SHAPE_DISTANCE;
};

const nextAnnotationId = (annotations: readonly CanvasAnnotation[]): string => {
  const used = new Set(annotations.map(({ id }) => id));
  let sequence = annotations.length + 1;
  while (used.has(`annotation-${sequence}`)) sequence += 1;
  return `annotation-${sequence}`;
};

function buildDraft(
  tool: AnnotationTool,
  id: string,
  point: NormalizedAnnotationPoint,
  color: string,
): CanvasAnnotation | null {
  const base = { id, color, stroke_width: DEFAULT_STROKE_WIDTH, instruction: '' };
  if (tool === 'text') {
    return {
      ...base,
      type: 'text',
      anchor: point,
      text: '',
      font_size: DEFAULT_FONT_SIZE,
    };
  }
  if (tool === 'freehand') return { ...base, type: tool, points: [point] };
  return { ...base, type: tool, start: point, end: point };
}

function moveDraft(
  annotation: CanvasAnnotation,
  point: NormalizedAnnotationPoint,
): CanvasAnnotation {
  if (annotation.type === 'text') return annotation;
  if (annotation.type === 'freehand') {
    if (annotation.points.length >= 1024) return annotation;
    const previous = annotation.points[annotation.points.length - 1];
    if (previous !== undefined && pointDistance(previous, point) < 0.002) return annotation;
    return { ...annotation, points: [...annotation.points, point] };
  }
  return { ...annotation, end: point };
}

const eventPoint = (
  event: GestureResponderEvent,
  size: CanvasSize,
): NormalizedAnnotationPoint => normalizeCanvasPoint({
  x: event.nativeEvent.locationX,
  y: event.nativeEvent.locationY,
}, size);

interface AnnotationBounds {
  minX: number;
  minY: number;
  maxX: number;
  maxY: number;
}

const annotationBounds = (annotation: CanvasAnnotation): AnnotationBounds => {
  if (annotation.type === 'text') {
    return {
      minX: annotation.anchor.x,
      minY: annotation.anchor.y,
      maxX: annotation.anchor.x,
      maxY: annotation.anchor.y,
    };
  }
  const points = annotation.type === 'freehand'
    ? annotation.points
    : [annotation.start, annotation.end];
  return points.reduce<AnnotationBounds>((bounds, point) => ({
    minX: Math.min(bounds.minX, point.x),
    minY: Math.min(bounds.minY, point.y),
    maxX: Math.max(bounds.maxX, point.x),
    maxY: Math.max(bounds.maxY, point.y),
  }), { minX: 1, minY: 1, maxX: 0, maxY: 0 });
};

const pointToSegmentDistance = (
  point: PixelPoint,
  start: PixelPoint,
  end: PixelPoint,
): number => {
  const dx = end.x - start.x;
  const dy = end.y - start.y;
  if (dx === 0 && dy === 0) return pointDistance(point, start);
  const progress = Math.max(0, Math.min(1,
    ((point.x - start.x) * dx + (point.y - start.y) * dy) / (dx * dx + dy * dy),
  ));
  return pointDistance(point, {
    x: start.x + progress * dx,
    y: start.y + progress * dy,
  });
};

const annotationContainsPoint = (
  annotation: CanvasAnnotation,
  point: NormalizedAnnotationPoint,
  size: CanvasSize,
): boolean => {
  const tolerance = 26;
  const pixelPoint = toPixelPoint(point, size);
  if (annotation.type === 'text') {
    return pointToSegmentDistance(
      pixelPoint,
      toPixelPoint(annotation.anchor, size),
      toPixelPoint(annotation.anchor, size),
    ) <= tolerance;
  }
  if (annotation.type === 'arrow') {
    return pointToSegmentDistance(
      pixelPoint,
      toPixelPoint(annotation.start, size),
      toPixelPoint(annotation.end, size),
    ) <= tolerance;
  }
  if (annotation.type === 'freehand') {
    return annotation.points.slice(1).some((end, index) =>
      pointToSegmentDistance(
        pixelPoint,
        toPixelPoint(annotation.points[index], size),
        toPixelPoint(end, size),
      ) <= tolerance);
  }
  const start = toPixelPoint(annotation.start, size);
  const end = toPixelPoint(annotation.end, size);
  const left = Math.min(start.x, end.x);
  const right = Math.max(start.x, end.x);
  const top = Math.min(start.y, end.y);
  const bottom = Math.max(start.y, end.y);
  if (annotation.type === 'circle') {
    const radiusX = Math.max(1, (right - left) / 2);
    const radiusY = Math.max(1, (bottom - top) / 2);
    const centerX = (left + right) / 2;
    const centerY = (top + bottom) / 2;
    const radial = Math.sqrt(
      ((pixelPoint.x - centerX) / radiusX) ** 2
      + ((pixelPoint.y - centerY) / radiusY) ** 2,
    );
    return radial <= 1 + tolerance / Math.min(radiusX, radiusY);
  }
  return pixelPoint.x >= left - tolerance
    && pixelPoint.x <= right + tolerance
    && pixelPoint.y >= top - tolerance
    && pixelPoint.y <= bottom + tolerance;
};

const translateAnnotation = (
  annotation: CanvasAnnotation,
  requestedDx: number,
  requestedDy: number,
): CanvasAnnotation => {
  const bounds = annotationBounds(annotation);
  const dx = Math.max(-bounds.minX, Math.min(1 - bounds.maxX, requestedDx));
  const dy = Math.max(-bounds.minY, Math.min(1 - bounds.maxY, requestedDy));
  const translatedPoint = (point: NormalizedAnnotationPoint): NormalizedAnnotationPoint => ({
    x: clampNormalized(point.x + dx),
    y: clampNormalized(point.y + dy),
  });
  if (annotation.type === 'text') {
    return { ...annotation, anchor: translatedPoint(annotation.anchor) };
  }
  if (annotation.type === 'freehand') {
    return { ...annotation, points: annotation.points.map(translatedPoint) };
  }
  return {
    ...annotation,
    start: translatedPoint(annotation.start),
    end: translatedPoint(annotation.end),
  };
};

interface PixelPoint {
  x: number;
  y: number;
}

const toPixelPoint = (
  point: NormalizedAnnotationPoint,
  size: CanvasSize,
): PixelPoint => ({ x: point.x * size.width, y: point.y * size.height });

function LineSegment({
  start,
  end,
  color,
  strokeWidth,
}: {
  start: PixelPoint;
  end: PixelPoint;
  color: string;
  strokeWidth: number;
}) {
  const length = Math.hypot(end.x - start.x, end.y - start.y);
  const angle = Math.atan2(end.y - start.y, end.x - start.x) * 180 / Math.PI;
  return (
    <View
      pointerEvents="none"
      style={{
        position: 'absolute',
        left: (start.x + end.x - length) / 2,
        top: (start.y + end.y - strokeWidth) / 2,
        width: Math.max(length, strokeWidth),
        height: strokeWidth,
        borderRadius: strokeWidth / 2,
        backgroundColor: color,
        transform: [{ rotate: `${angle}deg` }],
      }}
    />
  );
}

function RenderedAnnotation({
  annotation,
  size,
  draft = false,
  selected = false,
}: {
  annotation: CanvasAnnotation;
  size: CanvasSize;
  draft?: boolean;
  selected?: boolean;
}) {
  const minDimension = Math.max(1, Math.min(size.width, size.height));
  const strokeWidth = Math.max(2, annotation.stroke_width * minDimension);
  const opacity = draft ? 0.72 : 1;
  if (annotation.type === 'text') {
    const anchor = toPixelPoint(annotation.anchor, size);
    return (
      <View
        accessibilityLabel={`${annotation.type} annotation ${annotation.id}`}
        pointerEvents="none"
        style={{
          position: 'absolute',
          alignItems: 'center',
          backgroundColor: selected ? '#ffffff' : annotation.color,
          borderColor: annotation.color,
          borderRadius: 999,
          borderWidth: 2,
          height: 28,
          justifyContent: 'center',
          left: Math.max(0, anchor.x - 14),
          opacity,
          top: Math.max(0, anchor.y - 14),
          width: 28,
        }}>
        <Text style={{
          color: selected ? annotation.color : '#ffffff',
          fontSize: 12,
          fontWeight: '800',
        }}>
          T
        </Text>
      </View>
    );
  }
  if (annotation.type === 'freehand') {
    return (
      <View
        accessibilityLabel={`${annotation.type} annotation ${annotation.id}`}
        pointerEvents="none"
        style={[StyleSheet.absoluteFill, { opacity }]}>
        {annotation.points.slice(1).map((point, index) => (
          <LineSegment
            key={`${annotation.id}-${index}`}
            start={toPixelPoint(annotation.points[index], size)}
            end={toPixelPoint(point, size)}
            color={annotation.color}
            strokeWidth={strokeWidth}
          />
        ))}
      </View>
    );
  }
  const start = toPixelPoint(annotation.start, size);
  const end = toPixelPoint(annotation.end, size);
  if (annotation.type === 'arrow') {
    const angle = Math.atan2(end.y - start.y, end.x - start.x);
    const headLength = Math.max(10, minDimension * 0.035);
    const headOne = {
      x: end.x - headLength * Math.cos(angle - Math.PI / 6),
      y: end.y - headLength * Math.sin(angle - Math.PI / 6),
    };
    const headTwo = {
      x: end.x - headLength * Math.cos(angle + Math.PI / 6),
      y: end.y - headLength * Math.sin(angle + Math.PI / 6),
    };
    return (
      <View
        accessibilityLabel={`${annotation.type} annotation ${annotation.id}`}
        pointerEvents="none"
        style={[StyleSheet.absoluteFill, { opacity }]}>
        <LineSegment start={start} end={end} color={annotation.color} strokeWidth={strokeWidth} />
        <LineSegment start={end} end={headOne} color={annotation.color} strokeWidth={strokeWidth} />
        <LineSegment start={end} end={headTwo} color={annotation.color} strokeWidth={strokeWidth} />
      </View>
    );
  }
  const left = Math.min(start.x, end.x);
  const top = Math.min(start.y, end.y);
  const width = Math.abs(end.x - start.x);
  const height = Math.abs(end.y - start.y);
  return (
    <View
      accessibilityLabel={`${annotation.type} annotation ${annotation.id}`}
      pointerEvents="none"
      style={{
        position: 'absolute',
        left,
        top,
        width,
        height,
        borderWidth: strokeWidth,
        borderColor: annotation.color,
        borderRadius: annotation.type === 'circle' ? Math.max(width, height) : 2,
        opacity,
        shadowColor: selected ? '#ffffff' : 'transparent',
        shadowOpacity: selected ? 1 : 0,
        shadowRadius: selected ? 3 : 0,
      }}
    />
  );
}

function SelectionOutline({
  annotation,
  size,
}: {
  annotation: CanvasAnnotation;
  size: CanvasSize;
}) {
  const bounds = annotationBounds(annotation);
  const left = bounds.minX * size.width;
  const top = bounds.minY * size.height;
  const width = Math.max(28, (bounds.maxX - bounds.minX) * size.width);
  const height = Math.max(28, (bounds.maxY - bounds.minY) * size.height);
  return (
    <View
      accessibilityLabel={`Selected annotation ${annotation.id}`}
      pointerEvents="none"
      style={{
        position: 'absolute',
        borderColor: '#5b4ae0',
        borderRadius: 6,
        borderStyle: 'dashed',
        borderWidth: 2,
        height: height + 12,
        left: Math.max(0, left - 6),
        top: Math.max(0, top - 6),
        width: width + 12,
      }}
    />
  );
}

interface DragSession {
  annotation: CanvasAnnotation;
  origin: NormalizedAnnotationPoint;
}

interface PendingAnnotationEditor {
  annotation: CanvasAnnotation;
  isNew: boolean;
}

export function AnnotationCanvas({
  sourceUri,
  value,
  initialAnnotations = [],
  onChange,
  onExport,
  drawingEnabled = true,
  initialTool = 'text',
  strokeColor = '#b42318',
  imageAspectRatio,
  testID = 'annotation-canvas',
}: AnnotationCanvasProps) {
  const [internalAnnotations, setInternalAnnotations] = useState<CanvasAnnotation[]>(
    () => initialAnnotations.map(normalizeAnnotation),
  );
  const annotations = value?.annotations ?? internalAnnotations;
  const [tool, setTool] = useState<AnnotationTool>(initialTool);
  const [selectedAnnotationId, setSelectedAnnotationId] = useState<string | null>(null);
  const [createArmed, setCreateArmed] = useState(
    () => (value?.annotations.length ?? initialAnnotations.length) === 0,
  );
  const [draft, setDraftState] = useState<CanvasAnnotation | null>(null);
  const draftRef = useRef<CanvasAnnotation | null>(null);
  const [dragPreview, setDragPreviewState] = useState<CanvasAnnotation | null>(null);
  const dragSessionRef = useRef<DragSession | null>(null);
  const [pendingTextEditor, setPendingTextEditor] = useState<PendingAnnotationEditor | null>(null);
  const historyRef = useRef<CanvasAnnotation[][]>([]);
  const [size, setSize] = useState<CanvasSize>({ width: 0, height: 0 });
  const [loadedAspectRatio, setLoadedAspectRatio] = useState(DEFAULT_ASPECT_RATIO);

  const aspectRatio = imageAspectRatio !== undefined && imageAspectRatio > 0
    ? imageAspectRatio
    : loadedAspectRatio;
  const snapshot = useMemo(
    () => createAnnotationSnapshot(sourceUri, annotations),
    [annotations, sourceUri],
  );

  const setDraft = (next: CanvasAnnotation | null) => {
    draftRef.current = next;
    setDraftState(next);
  };

  const setDragPreview = (next: CanvasAnnotation | null) => {
    setDragPreviewState(next);
  };

  const publish = (next: CanvasAnnotation[], recordHistory = true) => {
    if (recordHistory) {
      historyRef.current = [
        ...historyRef.current,
        annotations.map(normalizeAnnotation),
      ];
    }
    if (value === undefined) setInternalAnnotations(next);
    onChange?.(createAnnotationSnapshot(sourceUri, next));
  };

  const replaceAnnotation = (replacement: CanvasAnnotation) => {
    publish(annotations.map((annotation) =>
      annotation.id === replacement.id ? replacement : annotation));
  };

  const startDrawing = (event: GestureResponderEvent) => {
    if (!drawingEnabled || size.width <= 0 || size.height <= 0) return;
    const point = eventPoint(event, size);
    if (!createArmed) {
      const candidates = pendingTextEditor?.isNew
        ? [...annotations, pendingTextEditor.annotation]
        : annotations;
      const hit = [...candidates].reverse().find((annotation) =>
        annotationContainsPoint(annotation, point, size));
      if (hit !== undefined) {
        setSelectedAnnotationId(hit.id);
        // Do not mount the text editor at gesture start: it sits above the
        // canvas and would move the image underneath an in-progress drag.
        // A stationary tap opens the editor after release instead.
        setPendingTextEditor(null);
        dragSessionRef.current = { annotation: hit, origin: point };
        setDragPreview(hit);
        return;
      }
      setSelectedAnnotationId(null);
      return;
    }
    if (annotations.length >= 32) return;
    const next = buildDraft(
      tool,
      nextAnnotationId(annotations),
      point,
      strokeColor,
    );
    if (next?.type === 'text') {
      setSelectedAnnotationId(next.id);
      setPendingTextEditor({ annotation: next, isNew: true });
      setCreateArmed(false);
      return;
    }
    setDraft(next);
  };

  const continueDrawing = (event: GestureResponderEvent) => {
    const dragSession = dragSessionRef.current;
    if (drawingEnabled && dragSession !== null) {
      const point = eventPoint(event, size);
      setDragPreview(translateAnnotation(
        dragSession.annotation,
        point.x - dragSession.origin.x,
        point.y - dragSession.origin.y,
      ));
      return;
    }
    const current = draftRef.current;
    if (!drawingEnabled || current === null) return;
    setDraft(moveDraft(current, eventPoint(event, size)));
  };

  const finishDrawing = (event: GestureResponderEvent) => {
    const dragSession = dragSessionRef.current;
    if (drawingEnabled && dragSession !== null) {
      const point = eventPoint(event, size);
      const moved = translateAnnotation(
        dragSession.annotation,
        point.x - dragSession.origin.x,
        point.y - dragSession.origin.y,
      );
      dragSessionRef.current = null;
      setDragPreview(null);
      if (pendingTextEditor?.isNew && pendingTextEditor.annotation.id === moved.id) {
        setPendingTextEditor({ ...pendingTextEditor, annotation: moved });
      } else if (serializeAnnotationSnapshot(createAnnotationSnapshot(sourceUri, [moved]))
        !== serializeAnnotationSnapshot(createAnnotationSnapshot(sourceUri, [dragSession.annotation]))) {
        replaceAnnotation(moved);
        if (pendingTextEditor?.annotation.id === moved.id && moved.type === 'text') {
          setPendingTextEditor({ ...pendingTextEditor, annotation: moved });
        }
      } else {
        setPendingTextEditor({ annotation: dragSession.annotation, isNew: false });
      }
      return;
    }
    const current = draftRef.current;
    if (!drawingEnabled || current === null) return;
    const final = moveDraft(current, eventPoint(event, size));
    setDraft(null);
    if (annotationIsMeaningful(final)) {
      setSelectedAnnotationId(final.id);
      setCreateArmed(false);
      setPendingTextEditor({ annotation: final, isNew: true });
    }
  };

  const handleLayout = (event: LayoutChangeEvent) => {
    const { width, height } = event.nativeEvent.layout;
    if (width > 0 && height > 0) setSize({ width, height });
  };

  const handleImageLoad = (
    event: NativeSyntheticEvent<{ source?: { width?: number; height?: number } }>,
  ) => {
    if (imageAspectRatio !== undefined) return;
    const width = event.nativeEvent.source?.width ?? 0;
    const height = event.nativeEvent.source?.height ?? 0;
    if (width > 0 && height > 0) setLoadedAspectRatio(width / height);
  };

  const undo = () => {
    if (!drawingEnabled) return;
    const previous = historyRef.current[historyRef.current.length - 1];
    if (previous !== undefined) {
      historyRef.current = historyRef.current.slice(0, -1);
      setSelectedAnnotationId(null);
      setPendingTextEditor(null);
      publish(previous, false);
      return;
    }
    if (annotations.length === 0) return;
    const removed = annotations[annotations.length - 1];
    if (removed?.id === selectedAnnotationId) setSelectedAnnotationId(null);
    publish(annotations.slice(0, -1), false);
  };

  const clear = () => {
    if (!drawingEnabled || (annotations.length === 0 && pendingTextEditor === null)) return;
    setDraft(null);
    setDragPreview(null);
    setSelectedAnnotationId(null);
    setPendingTextEditor(null);
    publish([]);
  };

  const deleteAnnotation = (annotationId: string) => {
    if (!drawingEnabled) return;
    if (pendingTextEditor?.isNew && pendingTextEditor.annotation.id === annotationId) {
      cancelPendingText();
      return;
    }
    const next = annotations.filter(({ id }) => id !== annotationId);
    if (next.length === annotations.length) return;
    publish(next);
    setPendingTextEditor(null);
    setSelectedAnnotationId(null);
  };

  const deleteSelected = () => {
    if (selectedAnnotationId !== null) deleteAnnotation(selectedAnnotationId);
  };

  const selectAnnotation = (annotation: CanvasAnnotation) => {
    if (!drawingEnabled) return;
    setCreateArmed(false);
    setPendingTextEditor(null);
    setSelectedAnnotationId(annotation.id);
  };

  const editAnnotation = (annotation: CanvasAnnotation) => {
    if (!drawingEnabled) return;
    setCreateArmed(false);
    setSelectedAnnotationId(annotation.id);
    setPendingTextEditor({ annotation, isNew: false });
  };

  const updatePendingText = (text: string) => {
    setPendingTextEditor((current) => current === null ? null : {
      ...current,
      annotation: current.annotation.type === 'text'
        ? { ...current.annotation, instruction: text, text }
        : { ...current.annotation, instruction: text },
    });
  };

  const savePendingText = () => {
    if (pendingTextEditor === null) return;
    const otherTextLength = annotations.reduce((total, annotation) =>
      total + (annotation.id !== pendingTextEditor.annotation.id
        ? localInstruction(annotation).length
        : 0), 0);
    const text = localInstruction(pendingTextEditor.annotation).slice(
      0,
      Math.max(0, Math.min(500, 2000 - otherTextLength)),
    );
    if (!text) return;
    const saved: CanvasAnnotation = pendingTextEditor.annotation.type === 'text'
      ? { ...pendingTextEditor.annotation, instruction: text, text }
      : { ...pendingTextEditor.annotation, instruction: text };
    if (pendingTextEditor.isNew) {
      if (annotations.length >= 32) return;
      publish([...annotations, saved]);
    } else {
      replaceAnnotation(saved);
    }
    setPendingTextEditor(null);
  };

  const cancelPendingText = () => {
    setPendingTextEditor(null);
    setSelectedAnnotationId(null);
  };

  const cancelInteraction = () => {
    dragSessionRef.current = null;
    setDragPreview(null);
    setDraft(null);
  };

  return (
    <View style={styles.root}>
      <View accessibilityRole="toolbar" style={styles.toolbar}>
        <Pressable
          accessibilityLabel="Select or move annotation tool"
          accessibilityRole="button"
          accessibilityState={{ disabled: !drawingEnabled, selected: !createArmed }}
          disabled={!drawingEnabled}
          onPress={() => {
            setCreateArmed(false);
            setPendingTextEditor(null);
          }}
          style={[
            styles.tool,
            !createArmed && styles.toolSelected,
            !drawingEnabled && styles.disabled,
          ]}>
          <Text style={[styles.toolText, !createArmed && styles.toolTextSelected]}>Move</Text>
        </Pressable>
        {Object.entries(TOOL_LABELS).map(([key, label]) => {
          const option = key as AnnotationTool;
          const selected = option === tool && createArmed;
          return (
            <Pressable
              key={option}
              accessibilityLabel={`${label} annotation tool`}
              accessibilityRole="button"
              accessibilityState={{ disabled: !drawingEnabled, selected }}
              disabled={!drawingEnabled}
              onPress={() => {
                setTool(option);
                setCreateArmed(true);
                setSelectedAnnotationId(null);
                setPendingTextEditor(null);
              }}
              style={[
                styles.tool,
                selected && styles.toolSelected,
                !drawingEnabled && styles.disabled,
              ]}>
              <Text style={[styles.toolText, selected && styles.toolTextSelected]}>{label}</Text>
            </Pressable>
          );
        })}
      </View>
      {drawingEnabled && (
        <Text style={styles.toolbarHelp}>
          Add a mark, or choose Move and drag any existing mark to reposition it.
        </Text>
      )}
      <View
        accessibilityHint={drawingEnabled
          ? createArmed
            ? tool === 'text'
              ? 'Tap the jewelry image where the instruction belongs, then type the edit'
              : `Draw a ${TOOL_LABELS[tool].toLowerCase()} over the jewelry image`
            : 'Tap an annotation to select it, then drag it to reposition it'
          : 'Annotations are view-only on this device'}
        accessibilityLabel="Jewelry image annotation canvas"
        accessibilityRole="button"
        accessibilityState={{ disabled: !drawingEnabled }}
        onLayout={handleLayout}
        onMoveShouldSetResponder={() => drawingEnabled}
        onResponderGrant={startDrawing}
        onResponderMove={continueDrawing}
        onResponderRelease={finishDrawing}
        onResponderTerminate={cancelInteraction}
        onStartShouldSetResponder={() => drawingEnabled}
        style={[styles.canvas, { aspectRatio }]}
        testID={testID}>
        <Image
          accessibilityIgnoresInvertColors
          onLoad={handleImageLoad}
          resizeMode="contain"
          source={{ uri: sourceUri }}
          style={StyleSheet.absoluteFill}
        />
        <View pointerEvents="none" style={StyleSheet.absoluteFill}>
          {annotations.map((annotation) => {
            const displayed = dragPreview?.id === annotation.id ? dragPreview : annotation;
            const selected = annotation.id === selectedAnnotationId;
            return (
              <React.Fragment key={annotation.id}>
                <RenderedAnnotation
                  annotation={displayed}
                  selected={selected}
                  size={size}
                />
                {selected && <SelectionOutline annotation={displayed} size={size} />}
              </React.Fragment>
            );
          })}
          {pendingTextEditor?.isNew && (
            <React.Fragment>
              <RenderedAnnotation
                annotation={dragPreview?.id === pendingTextEditor.annotation.id
                  ? dragPreview
                  : pendingTextEditor.annotation}
                selected
                size={size}
              />
              <SelectionOutline
                annotation={dragPreview?.id === pendingTextEditor.annotation.id
                  ? dragPreview
                  : pendingTextEditor.annotation}
                size={size}
              />
            </React.Fragment>
          )}
          {draft !== null && (
            <RenderedAnnotation annotation={draft} size={size} draft />
          )}
        </View>
      </View>
      {annotations.length > 0 && (
        <View accessibilityLabel="Annotation mark list" style={styles.markList}>
          <Text style={styles.markListTitle}>Marked changes</Text>
          {annotations.map((annotation, index) => {
            const selected = annotation.id === selectedAnnotationId;
            return (
              <View
                key={annotation.id}
                style={[styles.markRow, selected && styles.markRowSelected]}>
                <Pressable
                  accessibilityLabel={`Select mark ${index + 1}`}
                  accessibilityRole="button"
                  accessibilityState={{ selected }}
                  onPress={() => selectAnnotation(annotation)}
                  style={styles.markSelect}>
                  <Text style={styles.markNumber}>{index + 1}</Text>
                  <View style={styles.markCopy}>
                    <Text style={styles.markType}>{TOOL_LABELS[annotation.type]}</Text>
                    <Text numberOfLines={2} style={styles.markInstruction}>
                      {localInstruction(annotation)}
                    </Text>
                  </View>
                </Pressable>
                <Pressable
                  accessibilityLabel={`Edit mark ${index + 1} instruction`}
                  accessibilityRole="button"
                  onPress={() => editAnnotation(annotation)}
                  style={styles.markAction}>
                  <Text style={styles.markActionText}>Edit</Text>
                </Pressable>
                <Pressable
                  accessibilityLabel={`Delete mark ${index + 1}`}
                  accessibilityRole="button"
                  onPress={() => deleteAnnotation(annotation.id)}
                  style={styles.markAction}>
                  <Text style={styles.markDeleteText}>Delete</Text>
                </Pressable>
              </View>
            );
          })}
        </View>
      )}
      {pendingTextEditor !== null && (
        <View accessibilityLabel="Selected annotation instruction editor" style={styles.textEditor}>
          <Text style={styles.textEditorLabel}>What should change at this mark?</Text>
          <TextInput
            accessibilityLabel="Instruction for selected annotation"
            autoFocus
            editable={drawingEnabled}
            maxLength={500}
            multiline
            onChangeText={updatePendingText}
            placeholder="Describe the edit for this location"
            placeholderTextColor={theme.faint}
            style={[styles.textInput, !drawingEnabled && styles.disabled]}
            value={localInstruction(pendingTextEditor.annotation)}
          />
          <View style={styles.textEditorActions}>
            <Pressable
              accessibilityLabel="Cancel annotation instruction"
              accessibilityRole="button"
              onPress={cancelPendingText}
              style={styles.editorSecondaryAction}>
              <Text style={styles.actionText}>Cancel</Text>
            </Pressable>
            <Pressable
              accessibilityLabel="Save annotation instruction"
              accessibilityRole="button"
              accessibilityState={{ disabled: localInstruction(pendingTextEditor.annotation).length === 0 }}
              disabled={localInstruction(pendingTextEditor.annotation).length === 0}
              onPress={savePendingText}
              style={[
                styles.editorPrimaryAction,
                localInstruction(pendingTextEditor.annotation).length === 0 && styles.disabled,
              ]}>
              <Text style={styles.exportText}>Save instruction</Text>
            </Pressable>
          </View>
        </View>
      )}
      <View style={styles.actions}>
        <Pressable
          accessibilityLabel="Undo last annotation"
          accessibilityRole="button"
          accessibilityState={{ disabled: !drawingEnabled || annotations.length === 0 }}
          disabled={!drawingEnabled || annotations.length === 0}
          onPress={undo}
          style={[
            styles.action,
            (!drawingEnabled || annotations.length === 0) && styles.disabled,
          ]}>
          <Text style={styles.actionText}>Undo</Text>
        </Pressable>
        <Pressable
          accessibilityLabel="Clear all annotations"
          accessibilityRole="button"
          accessibilityState={{ disabled: !drawingEnabled || annotations.length === 0 }}
          disabled={!drawingEnabled || annotations.length === 0}
          onPress={clear}
          style={[
            styles.action,
            (!drawingEnabled || annotations.length === 0) && styles.disabled,
          ]}>
          <Text style={styles.actionText}>Clear</Text>
        </Pressable>
        <Pressable
          accessibilityLabel="Delete selected annotation"
          accessibilityRole="button"
          accessibilityState={{ disabled: !drawingEnabled || selectedAnnotationId === null }}
          disabled={!drawingEnabled || selectedAnnotationId === null}
          onPress={deleteSelected}
          style={[
            styles.action,
            (!drawingEnabled || selectedAnnotationId === null) && styles.disabled,
          ]}>
          <Text style={styles.actionText}>Delete selected</Text>
        </Pressable>
        <Pressable
          accessibilityLabel="Export annotation snapshot"
          accessibilityRole="button"
          accessibilityState={{ disabled: onExport === undefined }}
          disabled={onExport === undefined}
          onPress={() => onExport?.(snapshot)}
          style={[styles.exportAction, onExport === undefined && styles.disabled]}>
          <Text style={styles.exportText}>Use annotations</Text>
        </Pressable>
      </View>
      {!drawingEnabled && (
        <Text accessibilityLiveRegion="polite" style={styles.viewOnly}>
          View-only annotation review. Open on desktop or tablet to draw.
        </Text>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  root: {
    gap: 8,
    width: '100%',
  },
  toolbar: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 6,
  },
  tool: {
    backgroundColor: theme.paper,
    borderColor: theme.line,
    borderRadius: 999,
    borderWidth: 1,
    paddingHorizontal: 10,
    paddingVertical: 6,
  },
  toolSelected: {
    backgroundColor: theme.ink,
    borderColor: theme.ink,
  },
  toolText: {
    color: theme.ink,
    fontSize: 13,
  },
  toolTextSelected: {
    color: theme.paper,
  },
  toolbarHelp: {
    color: theme.faint,
    fontSize: 12,
  },
  markList: {
    borderColor: theme.line,
    borderRadius: 12,
    borderWidth: 1,
    gap: 6,
    padding: 10,
  },
  markListTitle: {
    color: theme.ink,
    fontSize: 12,
    fontWeight: '800',
  },
  markRow: {
    alignItems: 'center',
    borderColor: theme.line,
    borderRadius: 10,
    borderWidth: 1,
    flexDirection: 'row',
    gap: 6,
    padding: 7,
  },
  markRowSelected: {
    backgroundColor: '#f4f1ff',
    borderColor: '#6f52d9',
  },
  markSelect: {
    alignItems: 'center',
    flex: 1,
    flexDirection: 'row',
    gap: 8,
    minWidth: 0,
  },
  markNumber: {
    backgroundColor: '#6f52d9',
    borderRadius: 999,
    color: '#ffffff',
    fontSize: 11,
    fontWeight: '800',
    minWidth: 24,
    overflow: 'hidden',
    paddingHorizontal: 6,
    paddingVertical: 4,
    textAlign: 'center',
  },
  markCopy: { flex: 1, minWidth: 0 },
  markType: { color: theme.ink, fontSize: 11, fontWeight: '800' },
  markInstruction: { color: theme.faint, fontSize: 11, lineHeight: 15, marginTop: 1 },
  markAction: { paddingHorizontal: 7, paddingVertical: 7 },
  markActionText: { color: '#5c3fc0', fontSize: 11, fontWeight: '800' },
  markDeleteText: { color: theme.danger, fontSize: 11, fontWeight: '800' },
  textInput: {
    backgroundColor: theme.paper,
    borderColor: theme.line,
    borderRadius: 10,
    borderWidth: 1,
    color: theme.ink,
    fontSize: 14,
    paddingHorizontal: 10,
    paddingVertical: 8,
  },
  textEditor: {
    backgroundColor: '#f7f4ee',
    borderColor: theme.line,
    borderRadius: 12,
    borderWidth: 1,
    gap: 8,
    padding: 10,
  },
  textEditorLabel: {
    color: theme.ink,
    fontSize: 13,
    fontWeight: '700',
  },
  textEditorActions: {
    flexDirection: 'row',
    gap: 8,
    justifyContent: 'flex-end',
  },
  editorSecondaryAction: {
    backgroundColor: theme.paper,
    borderColor: theme.ink,
    borderRadius: 9,
    borderWidth: 1,
    paddingHorizontal: 12,
    paddingVertical: 7,
  },
  editorPrimaryAction: {
    backgroundColor: theme.ink,
    borderColor: theme.ink,
    borderRadius: 9,
    borderWidth: 1,
    paddingHorizontal: 12,
    paddingVertical: 7,
  },
  canvas: {
    backgroundColor: '#f1efe9',
    borderColor: theme.line,
    borderRadius: 12,
    borderWidth: 1,
    maxHeight: 720,
    overflow: 'hidden',
    width: '100%',
  },
  actions: {
    alignItems: 'center',
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 6,
  },
  action: {
    backgroundColor: theme.paper,
    borderColor: theme.ink,
    borderRadius: 10,
    borderWidth: 1,
    paddingHorizontal: 12,
    paddingVertical: 7,
  },
  actionText: {
    color: theme.ink,
    fontSize: 13,
  },
  exportAction: {
    backgroundColor: theme.ink,
    borderColor: theme.ink,
    borderRadius: 10,
    borderWidth: 1,
    paddingHorizontal: 12,
    paddingVertical: 7,
  },
  exportText: {
    color: theme.paper,
    fontSize: 13,
  },
  disabled: {
    opacity: 0.38,
  },
  viewOnly: {
    color: theme.faint,
    fontSize: 12,
  },
});
