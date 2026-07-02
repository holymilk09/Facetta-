import React, { useRef } from 'react';
import { Platform, Pressable, StyleSheet, Text, View } from 'react-native';
import { theme } from './theme';

export interface Pin {
  x_pct: number;
  y_pct: number;
  label?: string;
}

// The sheet is A4 landscape: 297 x 210.
const ASPECT = 297 / 210;

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

  return (
    <View ref={containerRef} style={styles.container}>
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
});
