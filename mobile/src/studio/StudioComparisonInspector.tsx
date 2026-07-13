import React, { useCallback, useEffect, useState } from 'react';
import {
  ImageProps,
  ImageSourcePropType,
  ImageStyle,
  Modal,
  Platform,
  Pressable,
  ScrollView,
  StyleProp,
  StyleSheet,
  Text,
  useWindowDimensions,
  View,
  ViewStyle,
} from 'react-native';

import { AuthenticatedImage as Image } from '../AuthenticatedImage';
import { radius, theme } from '../theme';

export type StudioComparisonSide = 'before' | 'after';
export type StudioComparisonZoom = 1 | 2 | 4;
export type StudioComparisonLayout = 'auto' | 'toggle' | 'split';

export interface StudioComparisonImage {
  /** The immutable revision or temporary-candidate name shown throughout review. */
  label: string;
  /** Override the default Before/After wording for contexts such as Source/Candidate. */
  roleLabel?: string;
  source: ImageSourcePropType;
  accessibilityLabel?: string;
  imageRequestHeaders?: Readonly<Record<string, string>>;
  resizeMode?: ImageProps['resizeMode'];
  compactImageStyle?: StyleProp<ImageStyle>;
  /** Compact events are the only review-readiness authority. */
  onLoad?: ImageProps['onLoad'];
  onError?: ImageProps['onError'];
}

export interface StudioComparisonInspectorProps {
  before: StudioComparisonImage;
  after: StudioComparisonImage;
  style?: StyleProp<ViewStyle>;
  compactHeight?: number;
  /** Auto uses one toggleable viewport below comparisonBreakpoint and split view above it. */
  layout?: StudioComparisonLayout;
  comparisonBreakpoint?: number;
  initialSide?: StudioComparisonSide;
  inspectionTitle?: string;
  inspectionHelp?: string;
  onVisibleSideChange?: (side: StudioComparisonSide) => void;
  testID?: string;
}

const ZOOM_LEVELS: readonly StudioComparisonZoom[] = [1, 2, 4];

function roleFor(side: StudioComparisonSide, image: StudioComparisonImage): string {
  return image.roleLabel ?? (side === 'before' ? 'Before' : 'After');
}

function fullLabel(side: StudioComparisonSide, image: StudioComparisonImage): string {
  return `${roleFor(side, image)}: ${image.label}`;
}

/**
 * A single comparison decision surface for exact revisions and temporary output.
 *
 * Phones use one viewport with explicit Before/After controls, preventing distant
 * vertical images from becoming a memory test. Full-detail inspection always uses
 * the same toggleable viewport so changing sides preserves the exact zoom and scroll
 * position. Detail-image events are deliberately omitted so opening or zooming this
 * surface can never authorize Apply or Save.
 */
export function StudioComparisonInspector({
  before,
  after,
  style,
  compactHeight = 260,
  layout = 'auto',
  comparisonBreakpoint = 720,
  initialSide = 'after',
  inspectionTitle = 'Compare before and after',
  inspectionHelp = 'Inspect matching areas for geometry, setting, proportion, material, and unintended drift before deciding.',
  onVisibleSideChange,
  testID,
}: StudioComparisonInspectorProps) {
  const [visibleSide, setVisibleSide] = useState<StudioComparisonSide>(initialSide);
  const [open, setOpen] = useState(false);
  const [zoom, setZoom] = useState<StudioComparisonZoom>(1);
  const { width, height } = useWindowDimensions();
  const resolvedLayout = layout === 'auto'
    ? (width < comparisonBreakpoint ? 'toggle' : 'split')
    : layout;

  const chooseSide = useCallback((side: StudioComparisonSide) => {
    setVisibleSide(side);
    onVisibleSideChange?.(side);
  }, [onVisibleSideChange]);

  const close = useCallback(() => {
    setOpen(false);
    setZoom(1);
  }, []);

  useEffect(() => {
    if (!open || Platform.OS !== 'web' || typeof document === 'undefined') return undefined;
    const closeOnEscape = (event: KeyboardEvent): void => {
      if (event.key === 'Escape') close();
    };
    document.addEventListener('keydown', closeOnEscape);
    return () => document.removeEventListener('keydown', closeOnEscape);
  }, [close, open]);

  const viewportWidth = Math.max(280, Math.min(width - 48, 1100));
  const viewportHeight = Math.max(280, height - 220);

  const renderCompactImage = (
    side: StudioComparisonSide,
    image: StudioComparisonImage,
    hidden: boolean,
  ) => (
    <Image
      accessibilityLabel={image.accessibilityLabel ?? `${fullLabel(side, image)} compact image`}
      imageRequestHeaders={image.imageRequestHeaders}
      onError={image.onError}
      onLoad={image.onLoad}
      resizeMode={image.resizeMode ?? 'contain'}
      source={image.source}
      style={[
        styles.compactImage,
        image.compactImageStyle,
        hidden && styles.hiddenImage,
      ]}
    />
  );

  const renderDetailImage = (
    side: StudioComparisonSide,
    image: StudioComparisonImage,
    imageWidth: number,
  ) => (
    <Image
      accessibilityLabel={`${fullLabel(side, image)} detail view`}
      imageRequestHeaders={image.imageRequestHeaders}
      resizeMode={image.resizeMode ?? 'contain'}
      source={image.source}
      style={[styles.detailImage, { width: imageWidth, height: viewportHeight * zoom }]}
    />
  );

  const sideControls = (location: 'compact' | 'detail') => (
    <View accessibilityRole="tablist" style={styles.sideControls}>
      {(['before', 'after'] as const).map((side) => {
        const image = side === 'before' ? before : after;
        const selected = visibleSide === side;
        return (
          <Pressable
            key={`${location}-${side}`}
            accessibilityRole="button"
            accessibilityLabel={`Show ${fullLabel(side, image)}${location === 'detail' ? ' in detail' : ''}`}
            accessibilityState={{ selected }}
            onPress={() => chooseSide(side)}
            style={[styles.sideButton, selected && styles.sideButtonSelected]}>
            <Text numberOfLines={2} style={[styles.sideButtonText, selected && styles.sideButtonTextSelected]}>
              {fullLabel(side, image)}
            </Text>
          </Pressable>
        );
      })}
    </View>
  );

  return (
    <View style={[styles.container, style]} testID={testID}>
      {resolvedLayout === 'split' && (
        <View style={styles.persistentLabels}>
          <Text numberOfLines={2} style={styles.persistentLabel}>{fullLabel('before', before)}</Text>
          <Text numberOfLines={2} style={styles.persistentLabel}>{fullLabel('after', after)}</Text>
        </View>
      )}

      {resolvedLayout === 'toggle' && sideControls('compact')}

      <View
        accessibilityLabel="Before and after comparison viewport"
        style={[styles.compactViewport, { height: compactHeight }]}
        testID="studio-comparison-compact-viewport">
        {resolvedLayout === 'split' ? (
          <View style={styles.splitRow}>
            <View style={styles.splitPane}>{renderCompactImage('before', before, false)}</View>
            <View style={styles.splitDivider} />
            <View style={styles.splitPane}>{renderCompactImage('after', after, false)}</View>
          </View>
        ) : (
          <View style={styles.togglePane}>
            {renderCompactImage('before', before, visibleSide !== 'before')}
            {renderCompactImage('after', after, visibleSide !== 'after')}
          </View>
        )}
      </View>

      <Pressable
        accessibilityRole="button"
        accessibilityLabel="Inspect comparison in detail"
        accessibilityHint="Opens a full-detail synchronized before-and-after inspector."
        onPress={() => setOpen(true)}
        style={styles.inspectButton}>
        <Text style={styles.inspectButtonText}>Inspect comparison detail</Text>
      </Pressable>

      <Modal
        accessibilityViewIsModal
        animationType="fade"
        onRequestClose={close}
        presentationStyle="overFullScreen"
        statusBarTranslucent
        transparent
        visible={open}>
        <View style={styles.backdrop}>
          <View style={styles.dialog}>
            <View style={styles.header}>
              <View style={styles.headerCopy}>
                <Text style={styles.eyebrow}>SYNCHRONIZED COMPARISON</Text>
                <Text numberOfLines={2} style={styles.title}>{inspectionTitle}</Text>
                <Text style={styles.help}>{inspectionHelp}</Text>
              </View>
              <Pressable
                accessibilityRole="button"
                accessibilityLabel="Close comparison inspector"
                onPress={close}
                style={styles.closeButton}>
                <Text style={styles.closeButtonText}>Close</Text>
              </Pressable>
            </View>

            {resolvedLayout === 'split' && (
              <View style={styles.detailLabels}>
                <Text numberOfLines={2} style={styles.detailLabel}>{fullLabel('before', before)}</Text>
                <Text numberOfLines={2} style={styles.detailLabel}>{fullLabel('after', after)}</Text>
              </View>
            )}

            {sideControls('detail')}

            <View style={styles.zoomBar}>
              <Text style={styles.zoomLabel}>Shared zoom</Text>
              {ZOOM_LEVELS.map((level) => (
                <Pressable
                  key={level}
                  accessibilityRole="button"
                  accessibilityLabel={`Set comparison zoom to ${level}x`}
                  accessibilityState={{ selected: zoom === level }}
                  onPress={() => setZoom(level)}
                  style={[styles.zoomButton, zoom === level && styles.zoomButtonSelected]}>
                  <Text style={[styles.zoomButtonText, zoom === level && styles.zoomButtonTextSelected]}>
                    {level}×
                  </Text>
                </Pressable>
              ))}
              <Text style={styles.panHelp}>
                {zoom === 1
                  ? 'Choose 2× or 4× for close inspection.'
                  : 'Switching sides keeps the same scale and position.'}
              </Text>
            </View>

            <ScrollView
              bounces={false}
              contentContainerStyle={styles.verticalInspectionContent}
              style={styles.inspectionViewport}
              testID="studio-comparison-detail-viewport">
              <ScrollView
                bounces={false}
                horizontal
                contentContainerStyle={styles.horizontalInspectionContent}
                style={{ width: viewportWidth }}>
                {renderDetailImage(
                  visibleSide,
                  visibleSide === 'before' ? before : after,
                  viewportWidth * zoom,
                )}
              </ScrollView>
            </ScrollView>
          </View>
        </View>
      </Modal>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    overflow: 'hidden',
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: theme.line,
    backgroundColor: theme.card,
  },
  persistentLabels: {
    flexDirection: 'row',
    gap: 10,
    paddingHorizontal: 12,
    paddingTop: 12,
  },
  persistentLabel: { flex: 1, color: theme.ink, fontSize: 11, fontWeight: '800' },
  sideControls: {
    flexDirection: 'row',
    gap: 8,
    paddingHorizontal: 12,
    paddingVertical: 10,
  },
  sideButton: {
    flex: 1,
    minHeight: 44,
    alignItems: 'center',
    justifyContent: 'center',
    borderRadius: radius.sm,
    borderWidth: 1,
    borderColor: theme.line,
    backgroundColor: theme.paper,
    paddingHorizontal: 10,
    paddingVertical: 6,
  },
  sideButtonSelected: { borderColor: theme.accent, backgroundColor: theme.goldSoft },
  sideButtonText: { color: theme.faint, fontSize: 10, fontWeight: '800', textAlign: 'center' },
  sideButtonTextSelected: { color: theme.ink },
  compactViewport: { overflow: 'hidden', backgroundColor: '#111015' },
  togglePane: { flex: 1, position: 'relative' },
  compactImage: { ...StyleSheet.absoluteFill, backgroundColor: '#111015' },
  hiddenImage: { opacity: 0 },
  splitRow: { flex: 1, flexDirection: 'row' },
  splitPane: { flex: 1, position: 'relative' },
  splitDivider: { width: 1, backgroundColor: '#5b5466' },
  inspectButton: {
    minHeight: 44,
    alignItems: 'center',
    justifyContent: 'center',
    borderTopWidth: 1,
    borderTopColor: theme.line,
    backgroundColor: theme.paper,
    paddingHorizontal: 14,
  },
  inspectButtonText: { color: theme.accent, fontSize: 11, fontWeight: '800' },
  backdrop: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: 'rgba(10, 9, 13, 0.84)',
    padding: 18,
  },
  dialog: {
    width: '100%',
    maxWidth: 1180,
    maxHeight: '100%',
    overflow: 'hidden',
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: '#393442',
    backgroundColor: '#17151c',
  },
  header: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: 16,
    padding: 16,
    borderBottomWidth: 1,
    borderBottomColor: '#393442',
  },
  headerCopy: { flex: 1, minWidth: 0 },
  eyebrow: { color: '#b7a7f7', fontSize: 9, fontWeight: '800', letterSpacing: 1.4 },
  title: { color: '#ffffff', fontFamily: theme.serif, fontSize: 22, lineHeight: 28, marginTop: 4 },
  help: { color: '#b8b2c0', fontSize: 11, lineHeight: 16, marginTop: 4 },
  closeButton: {
    minHeight: 44,
    alignItems: 'center',
    justifyContent: 'center',
    borderRadius: radius.pill,
    borderWidth: 1,
    borderColor: '#5b5466',
    paddingHorizontal: 14,
  },
  closeButtonText: { color: '#ffffff', fontSize: 11, fontWeight: '800' },
  detailLabels: {
    flexDirection: 'row',
    gap: 12,
    paddingHorizontal: 16,
    paddingTop: 10,
  },
  detailLabel: { flex: 1, color: '#ffffff', fontSize: 11, fontWeight: '800' },
  zoomBar: {
    minHeight: 60,
    flexDirection: 'row',
    flexWrap: 'wrap',
    alignItems: 'center',
    gap: 8,
    paddingHorizontal: 16,
    paddingVertical: 8,
    borderBottomWidth: 1,
    borderBottomColor: '#393442',
  },
  zoomLabel: { color: '#b8b2c0', fontSize: 11, fontWeight: '700', marginRight: 2 },
  zoomButton: {
    minWidth: 44,
    minHeight: 44,
    alignItems: 'center',
    justifyContent: 'center',
    borderRadius: radius.pill,
    borderWidth: 1,
    borderColor: '#5b5466',
    paddingHorizontal: 10,
  },
  zoomButtonSelected: { backgroundColor: '#6f52d9', borderColor: '#8a70e5' },
  zoomButtonText: { color: '#d3ced9', fontSize: 11, fontWeight: '800' },
  zoomButtonTextSelected: { color: '#ffffff' },
  panHelp: { flex: 1, minWidth: 210, color: '#928a9b', fontSize: 10, textAlign: 'right' },
  inspectionViewport: { flexGrow: 0, backgroundColor: '#111015' },
  verticalInspectionContent: { alignItems: 'center' },
  horizontalInspectionContent: { alignItems: 'center', justifyContent: 'center' },
  detailImage: { backgroundColor: '#111015' },
});
