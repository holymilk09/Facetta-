import React, { useRef, useState } from 'react';
import { Platform, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { theme } from './theme';

export interface Pin {
  x_pct: number;
  y_pct: number;
  label?: string;
}

// The sheet is A4 landscape: 297 x 210.
const ASPECT = 297 / 210;

// Zoom steps. The sheet is vector SVG, so every step re-renders at the
// screen's native resolution — enlarging never costs pixels. On paper the
// sheet stays true: zoom only changes what the screen shows.
const ZOOMS = [1, 1.5, 2, 3, 4, 6];

/** Renders a sheet SVG cross-platform and reports taps as (x%, y%) pins. */
export function SheetView({
  svg,
  pins = [],
  onPin,
}: {
  svg: string;
  pins?: Pin[];
  onPin?: (xPct: number, yPct: number) => void;
}) {
  const containerRef = useRef<View>(null);
  const [zoom, setZoom] = useState(1);
  const [outerW, setOuterW] = useState(0);
  const responsive = svg.replace(/width="297mm" height="210mm"/, 'width="100%"');

  const handlePress = (e: any) => {
    if (!onPin) return;
    const { pageX, pageY } = e.nativeEvent;
    containerRef.current?.measure((_x, _y, w, h, px, py) => {
      if (!w || !h) return;
      const xPct = Math.min(100, Math.max(0, ((pageX - px) / w) * 100));
      const yPct = Math.min(100, Math.max(0, ((pageY - py) / h) * 100));
      onPin(Math.round(xPct * 10) / 10, Math.round(yPct * 10) / 10);
    });
  };

  let surface: React.ReactNode;
  if (Platform.OS === 'web') {
    // Inline the SVG into the DOM — data-URI backgrounds are unreliable here.
    const { unstable_createElement } = require('react-native-web');
    surface = unstable_createElement('div', {
      style: { width: '100%', aspectRatio: `${ASPECT}`, lineHeight: 0 },
      dangerouslySetInnerHTML: { __html: responsive },
    });
  } else {
    const { WebView } = require('react-native-webview');
    surface = (
      <WebView
        originWhitelist={['*']}
        source={{ html: `<html><body style="margin:0">${responsive}</body></html>` }}
        style={styles.image}
        scrollEnabled={false}
        pointerEvents="none"
      />
    );
  }

  // Pins live inside the (possibly enlarged) sheet surface, so their
  // percentage positions stay correct at every zoom level.
  const sheet = (
    <View ref={containerRef}>
      <Pressable onPress={handlePress} disabled={!onPin}>
        {surface}
        {pins.map((pin, i) => (
          <View
            key={i}
            style={[styles.pin, { left: `${pin.x_pct}%`, top: `${pin.y_pct}%` }]}
            pointerEvents="none">
            <Text style={styles.pinText}>{pin.label ?? String(i + 1)}</Text>
          </View>
        ))}
      </Pressable>
    </View>
  );

  const step = (dir: 1 | -1) => {
    const i = ZOOMS.indexOf(zoom);
    setZoom(ZOOMS[Math.min(ZOOMS.length - 1, Math.max(0, i + dir))]);
  };

  return (
    <View
      style={styles.container}
      onLayout={(e) => setOuterW(e.nativeEvent.layout.width)}>
      {zoom === 1 ? (
        sheet
      ) : (
        <View style={{ height: outerW / ASPECT }}>
          <ScrollView horizontal bounces={false}>
            <ScrollView bounces={false}>
              <View style={{ width: outerW * zoom }}>{sheet}</View>
            </ScrollView>
          </ScrollView>
        </View>
      )}
      <View style={styles.zoomBar} pointerEvents="box-none">
        <Pressable style={styles.zoomBtn} onPress={() => step(-1)} disabled={zoom === ZOOMS[0]}>
          <Text style={styles.zoomBtnText}>−</Text>
        </Pressable>
        <Pressable style={styles.zoomLabelBtn} onPress={() => setZoom(1)}>
          <Text style={styles.zoomLabel}>{zoom}×</Text>
        </Pressable>
        <Pressable
          style={styles.zoomBtn}
          onPress={() => step(1)}
          disabled={zoom === ZOOMS[ZOOMS.length - 1]}>
          <Text style={styles.zoomBtnText}>+</Text>
        </Pressable>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    borderWidth: 1,
    borderColor: theme.line,
    borderRadius: 4,
    overflow: 'hidden',
    backgroundColor: '#fdfdfa',
  },
  image: { width: '100%', aspectRatio: ASPECT, backgroundColor: '#fdfdfa' },
  pin: {
    position: 'absolute',
    width: 18,
    height: 18,
    marginLeft: -9,
    marginTop: -9,
    borderRadius: 9,
    backgroundColor: theme.danger,
    alignItems: 'center',
    justifyContent: 'center',
  },
  pinText: { color: '#fff', fontSize: 10, fontWeight: 'bold' },
  zoomBar: {
    position: 'absolute',
    top: 6,
    right: 6,
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: 'rgba(253, 253, 250, 0.92)',
    borderWidth: 1,
    borderColor: theme.line,
    borderRadius: 14,
    paddingHorizontal: 4,
    paddingVertical: 2,
  },
  zoomBtn: {
    width: 24,
    height: 24,
    alignItems: 'center',
    justifyContent: 'center',
  },
  zoomBtnText: { fontSize: 16, color: theme.ink, lineHeight: 20 },
  zoomLabelBtn: { paddingHorizontal: 4 },
  zoomLabel: { fontSize: 11, color: theme.faint ?? '#8a8a8a' },
});
