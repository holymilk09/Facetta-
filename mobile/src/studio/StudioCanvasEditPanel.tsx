import React, { useMemo, useState } from 'react';
import {
  Platform, Pressable, StyleSheet, Text, TextInput, useWindowDimensions, View,
} from 'react-native';

import { radius, theme } from '../theme';

export type StudioCanvasEditMode = 'describe' | 'point' | 'symmetry' | 'background' | 'angle';
export type StudioCanvasBackgroundPreset =
  | 'white_studio'
  | 'warm_neutral'
  | 'dark_luxury'
  | 'soft_shadow';
export type StudioCanvasAnglePreset = 'front' | 'three_quarter' | 'side' | 'top';
export type StudioCanvasEditWorkingState = 'preview' | 'apply' | 'discard' | null;

export interface StudioCanvasAnnotationSummary {
  markCount: number;
  label?: string;
  everyMarkCarriesInstruction?: boolean;
}

/**
 * One temporary image-model request. The caller owns API orchestration and must
 * keep the output non-canonical until the designer explicitly applies it.
 */
export interface StudioCanvasEditRequest {
  mode: StudioCanvasEditMode;
  instruction: string;
  annotation: StudioCanvasAnnotationSummary | null;
  backgroundPreset: StudioCanvasBackgroundPreset | null;
  anglePreset: StudioCanvasAnglePreset | null;
  preserveUnrequestedDetails: true;
}

export interface StudioCanvasEditPreview {
  title?: string;
  summary: string;
}

export interface StudioCanvasEditPanelProps {
  annotation?: StudioCanvasAnnotationSummary | null;
  preview?: StudioCanvasEditPreview | null;
  working?: StudioCanvasEditWorkingState;
  disabled?: boolean;
  disabledReason?: string | null;
  applyDisabled?: boolean;
  applyDisabledReason?: string | null;
  error?: string | null;
  creditEstimate?: number | null;
  instructionValue?: string;
  onInstructionChange?: (instruction: string) => void;
  onRequestAnnotation: () => void;
  onClearAnnotation?: () => void;
  onModeChange?: (mode: StudioCanvasEditMode) => void;
  onPreviewChange: (request: StudioCanvasEditRequest) => void;
  onApplyPreview: () => void;
  onSaveAsVariationPreview?: () => void;
  onDiscardPreview: () => void;
}

interface ModeDefinition {
  id: StudioCanvasEditMode;
  label: string;
  help: string;
}

const MODES: readonly ModeDefinition[] = [
  { id: 'describe', label: 'Describe', help: 'List one or several changes in plain language.' },
  { id: 'point', label: 'Mark up', help: 'Mark one or several areas, then explain what should change.' },
  { id: 'symmetry', label: 'Symmetry', help: 'Match corresponding left and right elements around the center.' },
  { id: 'background', label: 'Background', help: 'Change the setting behind the piece only.' },
  { id: 'angle', label: 'Angle', help: 'Create another view without redesigning the jewelry.' },
] as const;

const BACKGROUNDS: readonly { id: StudioCanvasBackgroundPreset; label: string }[] = [
  { id: 'white_studio', label: 'White studio' },
  { id: 'warm_neutral', label: 'Warm neutral' },
  { id: 'dark_luxury', label: 'Dark luxury' },
  { id: 'soft_shadow', label: 'Soft shadow' },
] as const;

const ANGLES: readonly { id: StudioCanvasAnglePreset; label: string }[] = [
  { id: 'front', label: 'Front' },
  { id: 'three_quarter', label: 'Three-quarter' },
  { id: 'side', label: 'Side' },
  { id: 'top', label: 'Top' },
] as const;

const instructionPlaceholder = (mode: StudioCanvasEditMode): string => {
  if (mode === 'point') return 'Example: Make the marked prongs finer and soften the marked shoulder.';
  return 'Example: Narrow the band slightly and lower the center setting.';
};

const requestInstruction = (
  mode: StudioCanvasEditMode,
  instruction: string,
  backgroundPreset: StudioCanvasBackgroundPreset | null,
  anglePreset: StudioCanvasAnglePreset | null,
): string => {
  if (mode === 'background') {
    return `Show the jewelry on the selected ${backgroundPreset?.replaceAll('_', ' ')} background.`;
  }
  if (mode === 'angle') {
    return `Show the same jewelry from the selected ${anglePreset?.replaceAll('_', ' ')} angle.`;
  }
  if (mode === 'symmetry') {
    return 'Make the left and right sides symmetrical around the centerline. Mirror corresponding jewelry elements link by link: component order, spacing, orientation, scale, metal treatment, pave coverage, gemstone treatment, and connections. Keep the center element, camera, background, and every unmentioned detail fixed.';
  }
  return instruction.trim();
};

export function StudioCanvasEditPanel({
  annotation = null,
  preview = null,
  working = null,
  disabled = false,
  disabledReason = null,
  applyDisabled = false,
  applyDisabledReason = null,
  error = null,
  creditEstimate = null,
  instructionValue,
  onInstructionChange,
  onRequestAnnotation,
  onClearAnnotation,
  onModeChange,
  onPreviewChange,
  onApplyPreview,
  onSaveAsVariationPreview,
  onDiscardPreview,
}: StudioCanvasEditPanelProps) {
  const [mode, setMode] = useState<StudioCanvasEditMode>('describe');
  const [localInstruction, setLocalInstruction] = useState('');
  const [backgroundPreset, setBackgroundPreset] = useState<StudioCanvasBackgroundPreset | null>(null);
  const [anglePreset, setAnglePreset] = useState<StudioCanvasAnglePreset | null>(null);
  const { width } = useWindowDimensions();
  const isDesktop = Platform.OS === 'web' && width >= 1000;
  const busy = working !== null;
  const instruction = instructionValue ?? localInstruction;
  const setInstruction = (next: string): void => {
    if (instructionValue === undefined) setLocalInstruction(next);
    onInstructionChange?.(next);
  };
  const everyMarkCarriesInstruction = annotation?.everyMarkCarriesInstruction === true;

  const canPreview = useMemo(() => {
    if (disabled || busy || preview !== null) return false;
    if (mode === 'describe') return instruction.trim().length > 0;
    if (mode === 'point') {
      return (annotation?.markCount ?? 0) > 0
        && (everyMarkCarriesInstruction || instruction.trim().length > 0);
    }
    if (mode === 'symmetry') return true;
    if (mode === 'background') return backgroundPreset !== null;
    return anglePreset !== null;
  }, [anglePreset, annotation?.markCount, backgroundPreset, busy, disabled,
    everyMarkCarriesInstruction, instruction, mode, preview]);

  const chooseMode = (nextMode: StudioCanvasEditMode): void => {
    if (busy || disabled || preview !== null) return;
    setMode(nextMode);
    onModeChange?.(nextMode);
  };

  const submitPreview = (): void => {
    if (!canPreview) return;
    onPreviewChange({
      mode,
      instruction: mode === 'point' && everyMarkCarriesInstruction
        ? ''
        : requestInstruction(mode, instruction, backgroundPreset, anglePreset),
      annotation: mode === 'point' ? annotation : null,
      backgroundPreset: mode === 'background' ? backgroundPreset : null,
      anglePreset: mode === 'angle' ? anglePreset : null,
      preserveUnrequestedDetails: true,
    });
  };

  return (
    <View
      accessibilityLabel="Edit selected direction"
      style={[styles.panel, isDesktop && styles.desktopPanel]}
      testID="studio-canvas-edit-panel">
      <Text style={styles.eyebrow}>EDIT SELECTED DIRECTION</Text>
      <Text style={styles.title}>Make your changes.</Text>
      <Text style={styles.help}>
        Describe or mark every requested edit. Facetta previews them together and keeps unmarked details fixed.
      </Text>

      <View accessibilityRole="tablist" style={styles.modeGrid}>
        {MODES.map((item) => {
          const selected = mode === item.id;
          return (
            <Pressable
              key={item.id}
              accessibilityRole="tab"
              accessibilityLabel={`${item.label} editing tool`}
              accessibilityState={{ selected, disabled: disabled || busy || preview !== null }}
              disabled={disabled || busy || preview !== null}
              onPress={() => chooseMode(item.id)}
              style={[styles.modeButton, selected && styles.modeButtonSelected]}>
              <Text style={[styles.modeLabel, selected && styles.modeLabelSelected]}>{item.label}</Text>
            </Pressable>
          );
        })}
      </View>

      <Text style={styles.modeHelp}>{MODES.find((item) => item.id === mode)?.help}</Text>

      {(mode === 'describe' || mode === 'point') && (
        <View style={styles.instructionBlock}>
          {mode === 'point' && (
            <View style={styles.annotationRow}>
              <View style={styles.annotationCopy}>
                <Text style={styles.fieldLabel}>Marked areas</Text>
                <Text style={styles.annotationStatus}>{(annotation?.markCount ?? 0) > 0
                  ? annotation?.label ?? `${annotation?.markCount} mark${annotation?.markCount === 1 ? '' : 's'} ready`
                  : 'No area marked yet'}</Text>
              </View>
              <Pressable
                accessibilityRole="button"
                accessibilityLabel={(annotation?.markCount ?? 0) > 0 ? 'Edit marked areas' : 'Mark the design'}
                disabled={disabled || busy || preview !== null}
                onPress={onRequestAnnotation}
                style={styles.outlineButton}>
                <Text style={styles.outlineButtonText}>{(annotation?.markCount ?? 0) > 0 ? 'Edit marks' : 'Mark design'}</Text>
              </Pressable>
              {(annotation?.markCount ?? 0) > 0 && onClearAnnotation !== undefined && (
                <Pressable
                  accessibilityRole="button"
                  accessibilityLabel="Clear marked areas"
                  disabled={disabled || busy || preview !== null}
                  onPress={onClearAnnotation}
                  style={styles.clearButton}>
                  <Text style={styles.clearButtonText}>Clear</Text>
                </Pressable>
              )}
            </View>
          )}
          {mode !== 'point' || !everyMarkCarriesInstruction ? <>
            <Text style={styles.fieldLabel}>{mode === 'point'
              ? 'Instruction for marks without their own note'
              : 'Describe the changes'}</Text>
            <TextInput
              accessibilityLabel="Edit instruction"
              editable={!disabled && !busy && preview === null}
              multiline
              onChangeText={setInstruction}
              placeholder={instructionPlaceholder(mode)}
              placeholderTextColor={theme.faint}
              style={styles.instructionInput}
              textAlignVertical="top"
              value={instruction}
            />
          </> : (
            <Text style={styles.localInstructionReady}>
              Every mark has its own instruction. You can preview without repeating them here.
            </Text>
          )}
        </View>
      )}

      {mode === 'symmetry' && (
        <View accessibilityLabel="Symmetry repair explanation" style={styles.symmetryCard}>
          <Text style={styles.fieldLabel}>Match both sides</Text>
          <Text style={styles.annotationStatus}>
            Facetta will mirror the left and right sequence around the center—down to metal, pave, stones, spacing, and orientation—while keeping the center and unrelated details fixed.
          </Text>
          <Text style={styles.symmetryCaution}>
            Use this only when both sides should match. Intentional asymmetry will otherwise be preserved.
          </Text>
        </View>
      )}

      {mode === 'background' && (
        <View accessibilityLabel="Background choices" style={styles.presetGrid}>
          {BACKGROUNDS.map((preset) => {
            const selected = backgroundPreset === preset.id;
            return (
              <Pressable
                key={preset.id}
                accessibilityRole="radio"
                accessibilityState={{ checked: selected, disabled: disabled || busy || preview !== null }}
                disabled={disabled || busy || preview !== null}
                onPress={() => setBackgroundPreset(preset.id)}
                style={[styles.presetButton, selected && styles.presetButtonSelected]}>
                <View style={[styles.backgroundSwatch, styles[`${preset.id}Swatch`]]} />
                <Text style={[styles.presetLabel, selected && styles.presetLabelSelected]}>{preset.label}</Text>
              </Pressable>
            );
          })}
        </View>
      )}

      {mode === 'angle' && (
        <View accessibilityLabel="Angle choices" style={styles.presetGrid}>
          {ANGLES.map((preset) => {
            const selected = anglePreset === preset.id;
            return (
              <Pressable
                key={preset.id}
                accessibilityRole="radio"
                accessibilityState={{ checked: selected, disabled: disabled || busy || preview !== null }}
                disabled={disabled || busy || preview !== null}
                onPress={() => setAnglePreset(preset.id)}
                style={[styles.presetButton, selected && styles.presetButtonSelected]}>
                <Text style={styles.angleMark}>{preset.id === 'front' ? '↟' : preset.id === 'three_quarter' ? '◩' : preset.id === 'side' ? '↠' : '⌄'}</Text>
                <Text style={[styles.presetLabel, selected && styles.presetLabelSelected]}>{preset.label}</Text>
              </Pressable>
            );
          })}
        </View>
      )}

      {disabled && disabledReason !== null && <Text style={styles.disabledReason}>{disabledReason}</Text>}
      {error !== null && <Text accessibilityRole="alert" style={styles.error}>{error}</Text>}

      {preview === null ? (
        <>
          {creditEstimate !== null && (
            <Text style={styles.creditEstimate}>Estimated {creditEstimate} credits after you request this preview.</Text>
          )}
          <Pressable
            accessibilityRole="button"
            accessibilityState={{ disabled: !canPreview }}
            disabled={!canPreview}
            onPress={submitPreview}
            style={[styles.primaryButton, !canPreview && styles.buttonDisabled]}>
            <Text style={styles.primaryButtonText}>{working === 'preview' ? 'Preparing preview…' : 'Preview changes'}</Text>
          </Pressable>
        </>
      ) : (
        <View style={styles.previewDecision}>
          <Text style={styles.previewEyebrow}>TEMPORARY PREVIEW</Text>
          <Text style={styles.previewTitle}>{preview.title ?? 'Review before applying'}</Text>
          <Text style={styles.previewSummary}>{preview.summary}</Text>
          {onSaveAsVariationPreview !== undefined && (
            <Pressable
              accessibilityRole="button"
              accessibilityState={{ disabled: busy }}
              disabled={busy}
              onPress={onSaveAsVariationPreview}
              style={[styles.saveVariationButton, busy && styles.buttonDisabled]}>
              <Text style={styles.saveVariationText}>Save as variation</Text>
            </Pressable>
          )}
          <View style={styles.decisionRow}>
            <Pressable
              accessibilityRole="button"
              accessibilityState={{ disabled: busy }}
              disabled={busy}
              onPress={onDiscardPreview}
              style={[styles.outlineDecisionButton, busy && styles.buttonDisabled]}>
              <Text style={styles.outlineDecisionText}>{working === 'discard' ? 'Discarding…' : 'Discard'}</Text>
            </Pressable>
            <Pressable
              accessibilityRole="button"
              accessibilityState={{ disabled: busy || applyDisabled }}
              disabled={busy || applyDisabled}
              onPress={onApplyPreview}
              style={[styles.applyButton, (busy || applyDisabled) && styles.buttonDisabled]}>
              <Text style={styles.primaryButtonText}>{working === 'apply' ? 'Applying…' : 'Apply change'}</Text>
            </Pressable>
          </View>
          {applyDisabled && applyDisabledReason !== null && (
            <Text accessibilityRole="alert" style={styles.applyDisabledReason}>
              {applyDisabledReason}
            </Text>
          )}
          <Text style={styles.previewTruth}>
            Apply saves a new revision. Save as variation starts a sibling direction. Discard leaves the selected design unchanged.
          </Text>
        </View>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  panel: {
    width: '100%',
    borderWidth: 1,
    borderColor: theme.line,
    borderRadius: radius.lg,
    backgroundColor: theme.card,
    padding: 18,
  },
  desktopPanel: { width: 320, flexGrow: 0, flexShrink: 0 },
  eyebrow: { color: '#6f52d9', fontSize: 10, fontWeight: '800', letterSpacing: 1.3 },
  title: { color: theme.ink, fontFamily: theme.serif, fontSize: 25, lineHeight: 31, marginTop: 7 },
  help: { color: theme.faint, fontSize: 12, lineHeight: 18, marginTop: 5 },
  modeGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: 7, marginTop: 16 },
  modeButton: {
    minHeight: 40,
    justifyContent: 'center',
    borderWidth: 1,
    borderColor: theme.line,
    borderRadius: radius.pill,
    backgroundColor: theme.paper,
    paddingHorizontal: 12,
    paddingVertical: 8,
  },
  modeButtonSelected: { borderColor: '#6f52d9', backgroundColor: '#eee9ff' },
  modeLabel: { color: theme.faint, fontSize: 11, fontWeight: '700' },
  modeLabelSelected: { color: '#5c3fc0' },
  modeHelp: { color: theme.faint, fontSize: 11, lineHeight: 16, marginTop: 10 },
  instructionBlock: { marginTop: 15 },
  symmetryCard: {
    marginTop: 15,
    borderWidth: 1,
    borderColor: '#cfc4f6',
    borderRadius: radius.md,
    backgroundColor: '#faf8ff',
    padding: 12,
  },
  symmetryCaution: { color: '#745513', fontSize: 10, lineHeight: 15, marginTop: 9 },
  localInstructionReady: {
    backgroundColor: '#f1fbf6',
    borderRadius: radius.sm,
    color: '#287556',
    fontSize: 11,
    lineHeight: 16,
    marginTop: 4,
    padding: 10,
  },
  fieldLabel: { color: theme.ink, fontSize: 11, fontWeight: '700' },
  instructionInput: {
    minHeight: 92,
    marginTop: 7,
    borderWidth: 1,
    borderColor: theme.line,
    borderRadius: radius.md,
    backgroundColor: theme.paper,
    color: theme.ink,
    fontSize: 13,
    lineHeight: 19,
    padding: 12,
  },
  annotationRow: { flexDirection: 'row', alignItems: 'center', flexWrap: 'wrap', gap: 7, marginBottom: 14 },
  annotationCopy: { flex: 1, minWidth: 116 },
  annotationStatus: { color: theme.faint, fontSize: 10, lineHeight: 14, marginTop: 2 },
  outlineButton: { minHeight: 40, justifyContent: 'center', borderWidth: 1, borderColor: '#6f52d9', borderRadius: radius.pill, paddingHorizontal: 12 },
  outlineButtonText: { color: '#5c3fc0', fontSize: 10, fontWeight: '800' },
  clearButton: { minHeight: 40, justifyContent: 'center', paddingHorizontal: 5 },
  clearButtonText: { color: theme.faint, fontSize: 10, fontWeight: '700' },
  presetGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: 8, marginTop: 15 },
  presetButton: {
    width: '48%',
    minHeight: 72,
    justifyContent: 'center',
    alignItems: 'center',
    borderWidth: 1,
    borderColor: theme.line,
    borderRadius: radius.md,
    backgroundColor: theme.paper,
    padding: 10,
  },
  presetButtonSelected: { borderColor: '#6f52d9', backgroundColor: '#f4f1ff' },
  presetLabel: { color: theme.faint, fontSize: 10, fontWeight: '700', marginTop: 6 },
  presetLabelSelected: { color: '#5c3fc0' },
  backgroundSwatch: { width: 28, height: 20, borderRadius: 6, borderWidth: 1, borderColor: theme.line },
  white_studioSwatch: { backgroundColor: '#ffffff' },
  warm_neutralSwatch: { backgroundColor: '#e8dfd1' },
  dark_luxurySwatch: { backgroundColor: '#272525' },
  soft_shadowSwatch: { backgroundColor: '#d7d5d0' },
  angleMark: { color: theme.ink, fontFamily: theme.serif, fontSize: 24 },
  disabledReason: { color: '#745513', backgroundColor: '#fff9e9', borderRadius: radius.sm, padding: 10, fontSize: 11, lineHeight: 16, marginTop: 14 },
  applyDisabledReason: { color: '#745513', fontSize: 11, lineHeight: 16, marginTop: 10 },
  error: { color: theme.danger, fontSize: 11, lineHeight: 16, marginTop: 14 },
  creditEstimate: { color: theme.faint, fontSize: 10, lineHeight: 15, marginTop: 16 },
  primaryButton: { minHeight: 44, alignItems: 'center', justifyContent: 'center', borderRadius: radius.pill, backgroundColor: '#6f52d9', paddingHorizontal: 16, paddingVertical: 12, marginTop: 12 },
  primaryButtonText: { color: '#ffffff', fontSize: 12, fontWeight: '800' },
  buttonDisabled: { opacity: 0.4 },
  previewDecision: { marginTop: 16, borderTopWidth: 1, borderTopColor: theme.line, paddingTop: 15 },
  previewEyebrow: { color: '#6f52d9', fontSize: 9, fontWeight: '800', letterSpacing: 1.2 },
  previewTitle: { color: theme.ink, fontSize: 14, fontWeight: '700', marginTop: 5 },
  previewSummary: { color: theme.faint, fontSize: 11, lineHeight: 17, marginTop: 5 },
  saveVariationButton: {
    minHeight: 42,
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: 1,
    borderColor: '#6f52d9',
    borderRadius: radius.pill,
    marginTop: 13,
    paddingHorizontal: 12,
  },
  saveVariationText: { color: '#5c3fc0', fontSize: 11, fontWeight: '800' },
  decisionRow: { flexDirection: 'row', gap: 8, marginTop: 13 },
  outlineDecisionButton: { flex: 1, minHeight: 44, alignItems: 'center', justifyContent: 'center', borderWidth: 1, borderColor: theme.line, borderRadius: radius.pill, paddingHorizontal: 12 },
  outlineDecisionText: { color: theme.ink, fontSize: 11, fontWeight: '800' },
  applyButton: { flex: 1.35, minHeight: 44, alignItems: 'center', justifyContent: 'center', backgroundColor: '#6f52d9', borderRadius: radius.pill, paddingHorizontal: 12 },
  previewTruth: { color: theme.faint, fontSize: 9, lineHeight: 14, marginTop: 10 },
});
