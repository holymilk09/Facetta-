import React, { useEffect, useRef } from 'react';
import { Animated, Easing, ImageSourcePropType, StyleSheet, View } from 'react-native';

const concept = require('../assets/studio-ai-design-v3.png');
const variations = require('../assets/studio-setting-variations-v2.png');
const modelTryOn = require('../assets/studio-model-commerce-v2.png');
const precision = require('../assets/studio-precision-edit.png');
const coloredPlate = require('../assets/studio-colored-technical-plate-v1.png');
const factorySheet = require('../assets/studio-monochrome-factory-sheet-v1.png');
const highJewelryRing = require('../assets/studio-asymmetric-paraiba-ring-v1.png');
const highJewelryBracelet = require('../assets/studio-high-jewelry-aquamarine-cuff-v1.png');

function DriftRail({
  images,
  duration,
  reverse = false,
}: {
  images: ImageSourcePropType[];
  duration: number;
  reverse?: boolean;
}) {
  const progress = useRef(new Animated.Value(0)).current;
  const repeated = [...images, ...images];

  useEffect(() => {
    const loop = Animated.loop(
      Animated.timing(progress, {
        toValue: 1,
        duration,
        easing: Easing.linear,
        useNativeDriver: true,
      }),
    );
    loop.start();
    return () => loop.stop();
  }, [duration, progress]);

  const travel = images.length * 182;
  const translateY = progress.interpolate({
    inputRange: [0, 1],
    outputRange: reverse ? [-travel, 0] : [0, -travel],
  });

  return (
    <Animated.View style={[styles.rail, { transform: [{ translateY }] }]}>
      {repeated.map((source, index) => (
        <Animated.Image key={index} source={source} style={styles.tile} resizeMode="cover" />
      ))}
    </Animated.View>
  );
}

/** Decorative, continuously moving jewelry references for entry screens. */
export function StudioCollageBackground() {
  return (
    <View testID="studio-collage-viewport" pointerEvents="none" style={styles.viewport}>
      <View style={styles.paper} />
      <View style={styles.columns}>
        <DriftRail images={[highJewelryRing, highJewelryBracelet, concept, coloredPlate, variations, factorySheet]} duration={58000} />
        <DriftRail images={[highJewelryBracelet, modelTryOn, factorySheet, highJewelryRing, precision, coloredPlate]} duration={65000} reverse />
      </View>
      <View style={styles.veil} />
    </View>
  );
}

const styles = StyleSheet.create({
  // The rails intentionally extend well beyond the viewport so their loop has
  // no visible seam. Clip them here: without this boundary React Native Web
  // includes the off-screen rail in the document height, creating a tall,
  // mostly blank page after onboarding transitions.
  viewport: { ...StyleSheet.absoluteFill, overflow: 'hidden' },
  paper: { ...StyleSheet.absoluteFill, backgroundColor: '#e9e5ed' },
  columns: {
    position: 'absolute',
    top: -230,
    left: -46,
    flexDirection: 'row',
    gap: 12,
    opacity: 0.62,
    transform: [{ rotate: '-4deg' }, { scale: 1.12 }],
  },
  rail: { width: 154, gap: 12 },
  tile: {
    width: 154,
    height: 170,
    borderRadius: 18,
    backgroundColor: '#ffffff',
    borderWidth: 1,
    borderColor: 'rgba(71,58,84,0.12)',
  },
  veil: { ...StyleSheet.absoluteFill, backgroundColor: 'rgba(249,248,247,0.68)' },
});
