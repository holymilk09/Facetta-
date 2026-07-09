import React, { useEffect, useRef } from 'react';
import { Animated, Easing, StyleSheet, View, ViewStyle } from 'react-native';
import { sketchGold, sketchInk, theme } from './theme';

// ---------------------------------------------------------------------------
// Animation hooks — all transform/opacity only, so they run on the native
// driver (and degrade gracefully to the JS driver on web).
// ---------------------------------------------------------------------------

/** Oscillates 0 → 1 → 0 forever with a sine ease. */
function useDrift(duration: number, delay = 0) {
  const value = useRef(new Animated.Value(0)).current;
  useEffect(() => {
    const loop = Animated.loop(
      Animated.sequence([
        Animated.delay(delay),
        Animated.timing(value, {
          toValue: 1,
          duration,
          easing: Easing.inOut(Easing.sin),
          useNativeDriver: true,
        }),
        Animated.timing(value, {
          toValue: 0,
          duration,
          easing: Easing.inOut(Easing.sin),
          useNativeDriver: true,
        }),
      ]),
    );
    loop.start();
    return () => loop.stop();
  }, [value, duration, delay]);
  return value;
}

/** Runs 0 → 1 forever with linear easing (for full rotations). */
function useSpin(duration: number) {
  const value = useRef(new Animated.Value(0)).current;
  useEffect(() => {
    const loop = Animated.loop(
      Animated.timing(value, {
        toValue: 1,
        duration,
        easing: Easing.linear,
        useNativeDriver: true,
      }),
    );
    loop.start();
    return () => loop.stop();
  }, [value, duration]);
  return value;
}

// ---------------------------------------------------------------------------
// Motion wrappers
// ---------------------------------------------------------------------------

/** Gentle vertical drift + horizontal sway + a slight tilt, like a sketch pinned loosely to a moodboard. */
export function Float({
  children,
  style,
  duration = 9000,
  delay = 0,
  drift = 14,
  sway = 8,
  tilt = 3,
}: {
  children: React.ReactNode;
  style?: ViewStyle;
  duration?: number;
  delay?: number;
  drift?: number;
  sway?: number;
  tilt?: number;
}) {
  const t = useDrift(duration, delay);
  return (
    <Animated.View
      style={[
        style,
        {
          transform: [
            { translateY: t.interpolate({ inputRange: [0, 1], outputRange: [-drift, drift] }) },
            { translateX: t.interpolate({ inputRange: [0, 1], outputRange: [sway, -sway] }) },
            { rotate: t.interpolate({ inputRange: [0, 1], outputRange: [`-${tilt}deg`, `${tilt}deg`] }) },
          ],
        },
      ]}>
      {children}
    </Animated.View>
  );
}

/** Continuous slow rotation, like a stone turning under a loupe. */
export function Spin({
  children,
  duration = 80000,
  style,
}: {
  children: React.ReactNode;
  duration?: number;
  style?: ViewStyle;
}) {
  const t = useSpin(duration);
  return (
    <Animated.View
      style={[
        style,
        { transform: [{ rotate: t.interpolate({ inputRange: [0, 1], outputRange: ['0deg', '360deg'] }) }] },
      ]}>
      {children}
    </Animated.View>
  );
}

/** Soft scale + opacity pulse for sparkles. */
export function Pulse({
  children,
  duration = 3200,
  delay = 0,
  style,
}: {
  children: React.ReactNode;
  duration?: number;
  delay?: number;
  style?: ViewStyle;
}) {
  const t = useDrift(duration, delay);
  return (
    <Animated.View
      style={[
        style,
        {
          opacity: t.interpolate({ inputRange: [0, 1], outputRange: [0.35, 1] }),
          transform: [{ scale: t.interpolate({ inputRange: [0, 1], outputRange: [0.75, 1.1] }) }],
        },
      ]}>
      {children}
    </Animated.View>
  );
}

// ---------------------------------------------------------------------------
// Line-art sketches — pure Views (borders + rotations), no SVG dependency.
// They echo the hand-drawn factory sheets: thin strokes, simple geometry.
// ---------------------------------------------------------------------------

/** A solitaire ring in profile: round band, rotated-square stone perched on top. */
export function RingSketch({
  size,
  color = sketchInk(0.16),
  stroke = 1.5,
}: {
  size: number;
  color?: string;
  stroke?: number;
}) {
  const stone = size * 0.24;
  return (
    <View style={{ width: size, height: size + stone * 0.7, alignItems: 'center' }}>
      <View
        style={{
          width: stone,
          height: stone,
          borderWidth: stroke,
          borderColor: color,
          transform: [{ rotate: '45deg' }],
          marginBottom: -stone * 0.3,
        }}
      />
      <View
        style={{
          width: size,
          height: size,
          borderRadius: size / 2,
          borderWidth: stroke,
          borderColor: color,
        }}
      />
    </View>
  );
}

/** A gemstone in top view: nested rotated squares crossed by a girdle line. */
export function GemSketch({
  size,
  color = sketchGold(0.3),
  stroke = 1.5,
}: {
  size: number;
  color?: string;
  stroke?: number;
}) {
  return (
    <View style={{ width: size, height: size, alignItems: 'center', justifyContent: 'center' }}>
      <View
        style={{
          position: 'absolute',
          width: size * 0.68,
          height: size * 0.68,
          borderWidth: stroke,
          borderColor: color,
          transform: [{ rotate: '45deg' }],
        }}
      />
      <View
        style={{
          position: 'absolute',
          width: size * 0.38,
          height: size * 0.38,
          borderWidth: stroke,
          borderColor: color,
          transform: [{ rotate: '45deg' }],
        }}
      />
      <View style={{ position: 'absolute', width: size * 0.96, height: stroke, backgroundColor: color }} />
      <View style={{ position: 'absolute', width: stroke, height: size * 0.96, backgroundColor: color }} />
    </View>
  );
}

/** A four-point sparkle: two thin crossing bars. */
export function SparkleSketch({
  size,
  color = sketchGold(0.5),
  stroke = 1.5,
}: {
  size: number;
  color?: string;
  stroke?: number;
}) {
  return (
    <View style={{ width: size, height: size, alignItems: 'center', justifyContent: 'center' }}>
      <View style={{ position: 'absolute', width: size, height: stroke, backgroundColor: color, borderRadius: stroke }} />
      <View style={{ position: 'absolute', width: stroke, height: size, backgroundColor: color, borderRadius: stroke }} />
    </View>
  );
}

/** A large orbit circle — the compass-drawn construction line of a technical sheet. */
export function OrbitSketch({
  size,
  color = sketchInk(0.07),
  stroke = 1,
}: {
  size: number;
  color?: string;
  stroke?: number;
}) {
  return (
    <View
      style={{
        width: size,
        height: size,
        borderRadius: size / 2,
        borderWidth: stroke,
        borderColor: color,
        borderStyle: 'dashed',
      }}
    />
  );
}

// ---------------------------------------------------------------------------
// The composed background
// ---------------------------------------------------------------------------

/**
 * Full-bleed animated backdrop: floating jewelry line-art over warm paper,
 * with soft color glows. Purely decorative — never intercepts touches.
 */
export function MotionBackground({ intensity = 1 }: { intensity?: number }) {
  const a = (base: number) => base * intensity;
  return (
    <View pointerEvents="none" style={StyleSheet.absoluteFill}>
      {/* soft atelier-light glows */}
      <View style={[styles.glow, { top: -140, right: -120, backgroundColor: theme.goldSoft }]} />
      <View style={[styles.glow, { bottom: -160, left: -140, backgroundColor: theme.blush }]} />

      {/* compass construction circles, barely there */}
      <Float style={{ position: 'absolute', top: '-12%', left: '-25%' }} duration={16000} drift={10} tilt={1}>
        <Spin duration={160000}>
          <OrbitSketch size={340} color={sketchInk(a(0.06))} />
        </Spin>
      </Float>
      <Float style={{ position: 'absolute', bottom: '-10%', right: '-30%' }} duration={19000} delay={2000} drift={12} tilt={1}>
        <Spin duration={200000}>
          <OrbitSketch size={380} color={sketchGold(a(0.12))} />
        </Spin>
      </Float>

      {/* jewelry sketches drifting like moodboard pins */}
      <Float style={{ position: 'absolute', top: '7%', left: '8%' }} duration={11000} tilt={5}>
        <RingSketch size={110} color={sketchInk(a(0.13))} />
      </Float>
      <Float style={{ position: 'absolute', top: '16%', right: '10%' }} duration={13000} delay={1200} tilt={4}>
        <Spin duration={90000}>
          <GemSketch size={92} color={sketchGold(a(0.28))} />
        </Spin>
      </Float>
      <Float style={{ position: 'absolute', bottom: '22%', left: '6%' }} duration={14000} delay={800} tilt={4}>
        <Spin duration={120000}>
          <GemSketch size={70} color={sketchInk(a(0.11))} />
        </Spin>
      </Float>
      <Float style={{ position: 'absolute', bottom: '9%', right: '12%' }} duration={12000} delay={2400} tilt={6}>
        <RingSketch size={84} color={sketchGold(a(0.24))} />
      </Float>

      {/* sparkles */}
      <Pulse style={{ position: 'absolute', top: '31%', left: '22%' }} duration={2800}>
        <SparkleSketch size={16} color={sketchGold(a(0.55))} />
      </Pulse>
      <Pulse style={{ position: 'absolute', top: '11%', right: '30%' }} duration={3600} delay={900}>
        <SparkleSketch size={12} color={sketchInk(a(0.3))} />
      </Pulse>
      <Pulse style={{ position: 'absolute', bottom: '30%', right: '24%' }} duration={3200} delay={1600}>
        <SparkleSketch size={20} color={sketchGold(a(0.45))} />
      </Pulse>
      <Pulse style={{ position: 'absolute', bottom: '14%', left: '30%' }} duration={4200} delay={500}>
        <SparkleSketch size={10} color={sketchInk(a(0.28))} />
      </Pulse>
    </View>
  );
}

const styles = StyleSheet.create({
  glow: {
    position: 'absolute',
    width: 420,
    height: 420,
    borderRadius: 210,
    opacity: 0.55,
  },
});
