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
  /** Optional sentence retained when Refine routes a localized request here. */
  initialTextDraft?: string;
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

function normalizeAnnotation(annotation: CanvasAnnotation): CanvasAnnotation {
  const base = {
    id: annotation.id,
    color: annotation.color,
    stroke_width: normalizedStroke(annotation.stroke_width),
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
        text: annotation.text,
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
  if (annotation.type === 'text') return annotation.text.trim().length > 0;
  if (annotation.type === 'freehand') {
    if (annotation.points.length < 2) return false;
    return annotation.points.some((point, index) =>
      index > 0 && pointDistance(annotation.points[index - 1], point) >= MIN_SHAPE_DISTANCE);
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
  text: string,
): CanvasAnnotation | null {
  const base = { id, color, stroke_width: DEFAULT_STROKE_WIDTH };
  if (tool === 'text') {
    const cleaned = text.trim();
    if (!cleaned) return null;
    return {
      ...base,
      type: 'text',
      anchor: point,
      text: cleaned,
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
}: {
  annotation: CanvasAnnotation;
  size: CanvasSize;
  draft?: boolean;
}) {
  const minDimension = Math.max(1, Math.min(size.width, size.height));
  const strokeWidth = Math.max(2, annotation.stroke_width * minDimension);
  const opacity = draft ? 0.72 : 1;
  if (annotation.type === 'text') {
    const anchor = toPixelPoint(annotation.anchor, size);
    return (
      <Text
        accessibilityLabel={`${annotation.type} annotation ${annotation.id}`}
        pointerEvents="none"
        style={{
          position: 'absolute',
          left: anchor.x,
          top: anchor.y,
          maxWidth: Math.max(1, size.width - anchor.x),
          color: annotation.color,
          fontWeight: '700',
          fontSize: Math.max(12, annotation.font_size * minDimension),
          textShadowColor: '#ffffff',
          textShadowOffset: { width: 0, height: 1 },
          textShadowRadius: 2,
          opacity,
        }}>
        {annotation.text}
      </Text>
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
      }}
    />
  );
}

export function AnnotationCanvas({
  sourceUri,
  value,
  initialAnnotations = [],
  onChange,
  onExport,
  drawingEnabled = true,
  initialTool = 'rectangle',
  initialTextDraft = '',
  strokeColor = '#b42318',
  imageAspectRatio,
  testID = 'annotation-canvas',
}: AnnotationCanvasProps) {
  const [internalAnnotations, setInternalAnnotations] = useState<CanvasAnnotation[]>(
    () => initialAnnotations.map(normalizeAnnotation),
  );
  const annotations = value?.annotations ?? internalAnnotations;
  const [tool, setTool] = useState<AnnotationTool>(initialTool);
  const [textDraft, setTextDraft] = useState(initialTextDraft);
  const [draft, setDraftState] = useState<CanvasAnnotation | null>(null);
  const draftRef = useRef<CanvasAnnotation | null>(null);
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

  const publish = (next: CanvasAnnotation[]) => {
    if (value === undefined) setInternalAnnotations(next);
    onChange?.(createAnnotationSnapshot(sourceUri, next));
  };

  const startDrawing = (event: GestureResponderEvent) => {
    if (!drawingEnabled || size.width <= 0 || size.height <= 0) return;
    const next = buildDraft(
      tool,
      nextAnnotationId(annotations),
      eventPoint(event, size),
      strokeColor,
      textDraft,
    );
    if (next?.type === 'text') {
      publish([...annotations, next]);
      return;
    }
    setDraft(next);
  };

  const continueDrawing = (event: GestureResponderEvent) => {
    const current = draftRef.current;
    if (!drawingEnabled || current === null) return;
    setDraft(moveDraft(current, eventPoint(event, size)));
  };

  const finishDrawing = (event: GestureResponderEvent) => {
    const current = draftRef.current;
    if (!drawingEnabled || current === null) return;
    const final = moveDraft(current, eventPoint(event, size));
    setDraft(null);
    if (annotationIsMeaningful(final)) publish([...annotations, final]);
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
    if (!drawingEnabled || annotations.length === 0) return;
    publish(annotations.slice(0, -1));
  };

  const clear = () => {
    if (!drawingEnabled || annotations.length === 0) return;
    setDraft(null);
    publish([]);
  };

  return (
    <View style={styles.root}>
      <View accessibilityRole="toolbar" style={styles.toolbar}>
        {Object.entries(TOOL_LABELS).map(([key, label]) => {
          const option = key as AnnotationTool;
          const selected = option === tool;
          return (
            <Pressable
              key={option}
              accessibilityLabel={`${label} annotation tool`}
              accessibilityRole="button"
              accessibilityState={{ disabled: !drawingEnabled, selected }}
              disabled={!drawingEnabled}
              onPress={() => setTool(option)}
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
      {tool === 'text' && (
        <TextInput
          accessibilityLabel="Annotation text"
          editable={drawingEnabled}
          onChangeText={setTextDraft}
          placeholder="Type a note, then tap its target"
          placeholderTextColor={theme.faint}
          style={[styles.textInput, !drawingEnabled && styles.disabled]}
          value={textDraft}
        />
      )}
      <View
        accessibilityHint={drawingEnabled
          ? `Draw a ${TOOL_LABELS[tool].toLowerCase()} over the jewelry image`
          : 'Annotations are view-only on this device'}
        accessibilityLabel="Jewelry image annotation canvas"
        accessibilityRole="button"
        accessibilityState={{ disabled: !drawingEnabled }}
        onLayout={handleLayout}
        onMoveShouldSetResponder={() => drawingEnabled}
        onResponderGrant={startDrawing}
        onResponderMove={continueDrawing}
        onResponderRelease={finishDrawing}
        onResponderTerminate={finishDrawing}
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
          {annotations.map((annotation) => (
            <RenderedAnnotation key={annotation.id} annotation={annotation} size={size} />
          ))}
          {draft !== null && (
            <RenderedAnnotation annotation={draft} size={size} draft />
          )}
        </View>
      </View>
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
