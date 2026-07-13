import React, { useCallback, useEffect, useState } from 'react';
import {
  ImageProps,
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
} from 'react-native';

import { AuthenticatedImage as Image } from '../AuthenticatedImage';
import { radius, theme } from '../theme';

type ZoomLevel = 1 | 2 | 4;

export interface StudioReviewImageProps extends Omit<ImageProps, 'style'> {
  /** A decision-specific name such as "Source revision 3" or "Candidate view". */
  inspectionLabel: string;
  style?: StyleProp<ImageStyle>;
  imageRequestHeaders?: Readonly<Record<string, string>>;
}

const ZOOM_LEVELS: readonly ZoomLevel[] = [1, 2, 4];

/**
 * An authenticated image with a separate full-detail inspection surface.
 *
 * The compact image remains the only source of onLoad/onError events. Loading
 * or zooming the inspector can never satisfy a review-readiness gate by itself.
 */
export function StudioReviewImage({
  inspectionLabel,
  source,
  style,
  imageRequestHeaders,
  accessibilityLabel,
  onLoad,
  onError,
  resizeMode = 'contain',
  ...imageProps
}: StudioReviewImageProps) {
  const [open, setOpen] = useState(false);
  const [zoom, setZoom] = useState<ZoomLevel>(1);
  const { width, height } = useWindowDimensions();

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
  const viewportHeight = Math.max(280, height - 190);

  return (
    <>
      <Pressable
        accessibilityRole="button"
        accessibilityLabel={`Inspect ${inspectionLabel} in detail`}
        accessibilityHint="Opens a full-detail jewelry image inspector."
        onPress={(event) => {
          event.stopPropagation();
          setOpen(true);
        }}
        style={[styles.thumbnailButton, style]}>
        <Image
          {...imageProps}
          accessibilityLabel={accessibilityLabel}
          imageRequestHeaders={imageRequestHeaders}
          onLoad={onLoad}
          onError={onError}
          resizeMode={resizeMode}
          source={source}
          style={styles.thumbnailImage}
        />
        <View pointerEvents="none" style={styles.inspectBadge}>
          <Text style={styles.inspectBadgeText}>Inspect detail</Text>
        </View>
      </Pressable>

      <Modal
        animationType="fade"
        accessibilityViewIsModal
        onRequestClose={close}
        presentationStyle="overFullScreen"
        statusBarTranslucent
        transparent
        visible={open}>
        <View style={styles.backdrop}>
          <View style={styles.dialog}>
            <View style={styles.header}>
              <View style={styles.headerCopy}>
                <Text style={styles.eyebrow}>DETAIL INSPECTION</Text>
                <Text numberOfLines={2} style={styles.title}>{inspectionLabel}</Text>
                <Text style={styles.help}>
                  Check prongs, stone outlines, pavé spacing, edges, and unintended drift before deciding.
                </Text>
              </View>
              <Pressable
                accessibilityRole="button"
                accessibilityLabel="Close image inspector"
                onPress={close}
                style={styles.closeButton}>
                <Text style={styles.closeButtonText}>Close</Text>
              </Pressable>
            </View>

            <View style={styles.zoomBar}>
              <Text style={styles.zoomLabel}>Zoom</Text>
              {ZOOM_LEVELS.map((level) => (
                <Pressable
                  key={level}
                  accessibilityRole="button"
                  accessibilityLabel={`Zoom image to ${level}x`}
                  accessibilityState={{ selected: zoom === level }}
                  onPress={() => setZoom(level)}
                  style={[styles.zoomButton, zoom === level && styles.zoomButtonSelected]}>
                  <Text style={[styles.zoomButtonText, zoom === level && styles.zoomButtonTextSelected]}>
                    {level}×
                  </Text>
                </Pressable>
              ))}
              <Text style={styles.panHelp}>{zoom === 1 ? 'Choose 2× or 4× for close inspection.' : 'Scroll to inspect the enlarged image.'}</Text>
            </View>

            <ScrollView
              bounces={false}
              contentContainerStyle={styles.verticalInspectionContent}
              style={styles.inspectionViewport}>
              <ScrollView
                bounces={false}
                horizontal
                contentContainerStyle={styles.horizontalInspectionContent}
                style={{ width: viewportWidth }}>
                <Image
                  {...imageProps}
                  accessibilityLabel={`${inspectionLabel} detail view`}
                  imageRequestHeaders={imageRequestHeaders}
                  resizeMode="contain"
                  source={source}
                  style={{
                    width: viewportWidth * zoom,
                    height: viewportHeight * zoom,
                    backgroundColor: '#111015',
                  }}
                />
              </ScrollView>
            </ScrollView>
          </View>
        </View>
      </Modal>
    </>
  );
}

const styles = StyleSheet.create({
  thumbnailButton: {
    overflow: 'hidden',
    position: 'relative',
  },
  thumbnailImage: {
    position: 'absolute',
    top: 0,
    right: 0,
    bottom: 0,
    left: 0,
  },
  inspectBadge: {
    position: 'absolute',
    right: 8,
    bottom: 8,
    borderRadius: radius.pill,
    backgroundColor: 'rgba(17, 16, 21, 0.82)',
    paddingHorizontal: 9,
    paddingVertical: 5,
  },
  inspectBadgeText: { color: '#ffffff', fontSize: 9, fontWeight: '800', letterSpacing: 0.2 },
  backdrop: {
    flex: 1,
    backgroundColor: 'rgba(10, 9, 13, 0.84)',
    padding: 18,
    alignItems: 'center',
    justifyContent: 'center',
  },
  dialog: {
    width: '100%',
    maxWidth: 1180,
    maxHeight: '100%',
    overflow: 'hidden',
    borderRadius: radius.lg,
    backgroundColor: '#17151c',
    borderWidth: 1,
    borderColor: '#393442',
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
    justifyContent: 'center',
    borderRadius: radius.pill,
    borderWidth: 1,
    borderColor: '#5b5466',
    paddingHorizontal: 14,
  },
  closeButtonText: { color: '#ffffff', fontSize: 11, fontWeight: '800' },
  zoomBar: {
    minHeight: 54,
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
    minHeight: 36,
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
  panHelp: { flex: 1, minWidth: 220, color: '#928a9b', fontSize: 10, textAlign: 'right' },
  inspectionViewport: { flexGrow: 0, backgroundColor: '#111015' },
  verticalInspectionContent: { alignItems: 'center' },
  horizontalInspectionContent: { alignItems: 'center', justifyContent: 'center' },
});
