import React from 'react';
import { Pressable, StyleSheet, Text, TextInput, View } from 'react-native';
import { theme } from './theme';

export function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <View style={styles.section}>
      <Text style={styles.sectionTitle}>{title}</Text>
      {children}
    </View>
  );
}

export function ChipRow<T extends string | number>({
  label,
  options,
  value,
  onSelect,
  render,
  disabled,
  disabledNote,
}: {
  label?: string;
  options: readonly T[];
  value: T | null;
  onSelect: (v: T) => void;
  render?: (v: T) => string;
  disabled?: boolean;
  disabledNote?: string;
}) {
  return (
    <View style={styles.chipBlock}>
      {label ? (
        <Text style={styles.fieldLabel}>
          {label}
          {disabled && disabledNote ? ` — ${disabledNote}` : ''}
        </Text>
      ) : null}
      <View style={styles.chipRow}>
        {options.map((opt) => {
          const selected = !disabled && opt === value;
          return (
            <Pressable
              key={String(opt)}
              disabled={disabled}
              onPress={() => onSelect(opt)}
              style={[styles.chip, selected && styles.chipSelected, disabled && styles.chipDisabled]}>
              <Text style={[styles.chipText, selected && styles.chipTextSelected]}>
                {render ? render(opt) : String(opt)}
              </Text>
            </Pressable>
          );
        })}
      </View>
    </View>
  );
}

export function Field({
  label,
  value,
  onChange,
  numeric,
  placeholder,
  multiline,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  numeric?: boolean;
  placeholder?: string;
  multiline?: boolean;
}) {
  return (
    <View style={styles.chipBlock}>
      <Text style={styles.fieldLabel}>{label}</Text>
      <TextInput
        accessibilityLabel={label}
        style={[styles.input, multiline && styles.inputMultiline]}
        value={value}
        onChangeText={onChange}
        placeholder={placeholder}
        placeholderTextColor={theme.faint}
        keyboardType={numeric ? 'decimal-pad' : 'default'}
        multiline={multiline}
      />
    </View>
  );
}

export function Button({
  title,
  onPress,
  kind = 'primary',
  disabled,
}: {
  title: string;
  onPress: () => void;
  kind?: 'primary' | 'ghost';
  disabled?: boolean;
}) {
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={title}
      accessibilityState={{ disabled: disabled === true }}
      onPress={onPress}
      disabled={disabled}
      style={[
        styles.button,
        kind === 'ghost' && styles.buttonGhost,
        disabled && { opacity: 0.4 },
      ]}>
      <Text style={[styles.buttonText, kind === 'ghost' && styles.buttonTextGhost]}>
        {title}
      </Text>
    </Pressable>
  );
}

export function Notice({ kind, text }: { kind: 'ok' | 'error' | 'info'; text: string }) {
  const color = kind === 'ok' ? theme.ok : kind === 'error' ? theme.danger : theme.faint;
  return (
    <View style={[styles.notice, { borderColor: color }]}>
      <Text style={{ color, fontSize: 13 }}>{text}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  section: {
    backgroundColor: theme.card,
    borderColor: theme.line,
    borderWidth: 1,
    borderRadius: 16,
    padding: 14,
    marginBottom: 12,
  },
  sectionTitle: {
    fontFamily: theme.serif,
    fontSize: 15,
    letterSpacing: 1.5,
    color: theme.ink,
    marginBottom: 8,
    textTransform: 'uppercase',
  },
  chipBlock: { marginBottom: 10 },
  fieldLabel: { fontSize: 12, color: theme.faint, marginBottom: 4 },
  chipRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 6 },
  chip: {
    borderWidth: 1,
    borderColor: theme.line,
    borderRadius: 14,
    paddingHorizontal: 10,
    paddingVertical: 5,
    backgroundColor: theme.paper,
  },
  chipSelected: { borderColor: theme.ink, backgroundColor: theme.ink },
  chipDisabled: { opacity: 0.3 },
  chipText: { fontSize: 13, color: theme.ink },
  chipTextSelected: { color: theme.paper },
  input: {
    borderWidth: 1,
    borderColor: theme.line,
    borderRadius: 10,
    paddingHorizontal: 10,
    paddingVertical: 6,
    fontSize: 14,
    color: theme.ink,
    backgroundColor: theme.paper,
  },
  inputMultiline: { minHeight: 60, textAlignVertical: 'top' },
  button: {
    backgroundColor: theme.ink,
    borderRadius: 10,
    paddingHorizontal: 14,
    paddingVertical: 9,
    alignItems: 'center',
    marginRight: 8,
    marginBottom: 8,
  },
  buttonGhost: { backgroundColor: 'transparent', borderWidth: 1, borderColor: theme.ink },
  buttonText: { color: theme.paper, fontSize: 13, letterSpacing: 0.5 },
  buttonTextGhost: { color: theme.ink },
  notice: {
    borderWidth: 1,
    borderRadius: 10,
    padding: 8,
    marginBottom: 8,
    backgroundColor: theme.paper,
  },
});
