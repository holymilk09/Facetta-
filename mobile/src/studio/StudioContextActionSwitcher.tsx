import React, { useState } from 'react';
import {
  Pressable, ScrollView, StyleSheet, Text, View,
} from 'react-native';

import { radius, shadows, theme } from '../theme';
import {
  getStudioAction,
  getStudioActionPrerequisite,
  getStudioActionUnavailableReason,
  getStudioContextActions,
  getVisibleStudioActions,
  resolveStudioActionLaunch,
  type StudioActionLaunchIntent,
} from './actions';
import type {
  StudioActionContext, StudioActionId, StudioWorkspaceActionId,
} from './contracts';

export interface StudioContextActionSwitcherProps {
  context: StudioActionContext;
  selectedActionId: StudioWorkspaceActionId;
  onLaunch: (intent: StudioActionLaunchIntent) => void;
}

/**
 * A single revision-scoped command surface. Disclosure state is deliberately
 * local so opening the menu can never clear a durable Activity review or
 * mutate the parent router.
 */
export function StudioContextActionSwitcher({
  context,
  selectedActionId,
  onLaunch,
}: StudioContextActionSwitcherProps) {
  const sourceKey = `${context.activeDesignId ?? ''}:${context.activeRevisionId ?? ''}`;
  const disclosureKey = `${sourceKey}:${selectedActionId}`;
  const [disclosure, setDisclosure] = useState({
    key: disclosureKey,
    open: false,
    optionalExpanded: false,
  });
  const open = disclosure.key === disclosureKey && disclosure.open;
  const optionalExpanded = disclosure.key === disclosureKey
    && disclosure.optionalExpanded;
  const actions = getStudioContextActions(context);
  const optionalActions = getVisibleStudioActions(context, 'more');
  const currentAction = getStudioAction(selectedActionId);

  const selectAction = (actionId: StudioActionId): void => {
    if (actionId === selectedActionId) {
      setDisclosure({ key: disclosureKey, open: false, optionalExpanded: false });
      return;
    }
    const intent = resolveStudioActionLaunch(actionId, context);
    if (intent.type === 'toggle_optional') {
      setDisclosure({
        key: disclosureKey,
        open: true,
        optionalExpanded: !optionalExpanded,
      });
      return;
    }
    if (intent.type === 'unavailable') return;
    setDisclosure({ key: disclosureKey, open: false, optionalExpanded: false });
    onLaunch(intent);
  };

  const currentIsOptional = optionalActions.some((action) => action.id === selectedActionId);

  return (
    <View style={styles.container}>
      <Pressable
        testID="studio-action-trigger"
        accessibilityRole="button"
        accessibilityLabel={`Change Studio action. Current: ${currentAction.shortLabel}`}
        accessibilityHint="Shows the actions available for this exact revision."
        accessibilityState={{ expanded: open }}
        onPress={() => {
          setDisclosure({
            key: disclosureKey,
            open: !open,
            optionalExpanded: false,
          });
        }}
        style={({ pressed }) => [styles.trigger, pressed && styles.triggerPressed]}>
        <Text numberOfLines={1} style={styles.triggerLabel}>{currentAction.shortLabel}</Text>
        <Text style={styles.triggerChevron}>{open ? '⌃' : '⌄'}</Text>
      </Pressable>

      {open && (
        <View testID="studio-action-menu" style={[styles.menu, shadows.lifted]}>
          <Text style={styles.menuEyebrow}>WORK WITH THIS REVISION</Text>
          <ScrollView
            style={styles.menuScroll}
            showsVerticalScrollIndicator={false}
            keyboardShouldPersistTaps="handled">
            {actions.map((action) => {
              const prerequisite = getStudioActionPrerequisite(action, context);
              const unavailableReason = getStudioActionUnavailableReason(action, context);
              const unavailable = unavailableReason !== null && prerequisite === null;
              const selected = action.id === selectedActionId
                || (action.id === 'more' && currentIsOptional);
              const accessibilityLabel = prerequisite === null
                ? action.label
                : `${action.label}; ${unavailableReason}`;
              return (
                <React.Fragment key={action.id}>
                  <Pressable
                    testID={`studio-action-${action.id}`}
                    accessibilityRole="button"
                    accessibilityLabel={accessibilityLabel}
                    accessibilityHint={prerequisite === null
                      ? unavailableReason ?? action.description
                      : `Opens ${prerequisite.label}, then continues to ${action.shortLabel}.`}
                    accessibilityState={{ disabled: unavailable, selected }}
                    disabled={unavailable}
                    onPress={() => selectAction(action.id)}
                    style={({ pressed }) => [
                      styles.menuRow,
                      selected && styles.menuRowSelected,
                      unavailable && styles.menuRowUnavailable,
                      pressed && !unavailable && styles.menuRowPressed,
                    ]}>
                    <View style={styles.menuRowHeading}>
                      <Text style={[styles.menuRowTitle, selected && styles.menuRowTitleSelected]}>
                        {action.shortLabel}
                      </Text>
                      {selected && <Text style={styles.currentLabel}>Current</Text>}
                    </View>
                    <Text style={styles.menuRowBody}>{unavailableReason ?? action.description}</Text>
                  </Pressable>
                  {action.id === 'more' && optionalExpanded && (
                    <View testID="studio-more-actions" style={styles.optionalGroup}>
                      {optionalActions.map((optionalAction) => (
                        <Pressable
                          key={optionalAction.id}
                          testID={`studio-action-${optionalAction.id}`}
                          accessibilityRole="button"
                          accessibilityLabel={optionalAction.label}
                          accessibilityHint={optionalAction.description}
                          accessibilityState={{ selected: optionalAction.id === selectedActionId }}
                          onPress={() => selectAction(optionalAction.id)}
                          style={({ pressed }) => [
                            styles.optionalRow,
                            optionalAction.id === selectedActionId && styles.menuRowSelected,
                            pressed && styles.menuRowPressed,
                          ]}>
                          <Text style={styles.optionalTitle}>{optionalAction.shortLabel}</Text>
                          <Text style={styles.optionalBody}>{optionalAction.description}</Text>
                        </Pressable>
                      ))}
                    </View>
                  )}
                </React.Fragment>
              );
            })}
          </ScrollView>
        </View>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    position: 'relative',
    zIndex: 40,
  },
  trigger: {
    alignItems: 'center',
    backgroundColor: theme.ink,
    borderColor: theme.ink,
    borderRadius: radius.pill,
    borderWidth: 1,
    flexDirection: 'row',
    gap: 7,
    justifyContent: 'center',
    maxWidth: 132,
    minHeight: 44,
    minWidth: 88,
    paddingHorizontal: 12,
    paddingVertical: 8,
  },
  triggerPressed: { opacity: 0.82 },
  triggerLabel: { color: '#ffffff', flexShrink: 1, fontSize: 11, fontWeight: '800' },
  triggerChevron: { color: '#cbbcff', fontSize: 11, fontWeight: '800' },
  menu: {
    backgroundColor: theme.card,
    borderColor: theme.line,
    borderRadius: radius.md,
    borderWidth: 1,
    maxHeight: 390,
    padding: 8,
    position: 'absolute',
    right: 0,
    top: 42,
    width: 286,
    zIndex: 50,
  },
  menuEyebrow: {
    color: theme.faint,
    fontSize: 9,
    fontWeight: '800',
    letterSpacing: 1,
    paddingHorizontal: 9,
    paddingVertical: 7,
  },
  menuScroll: { flexGrow: 0 },
  menuRow: {
    borderRadius: radius.sm,
    gap: 3,
    paddingHorizontal: 10,
    paddingVertical: 9,
  },
  menuRowSelected: { backgroundColor: theme.goldSoft },
  menuRowUnavailable: { opacity: 0.52 },
  menuRowPressed: { backgroundColor: theme.blush },
  menuRowHeading: { alignItems: 'center', flexDirection: 'row', gap: 7 },
  menuRowTitle: { color: theme.ink, fontSize: 13, fontWeight: '800' },
  menuRowTitleSelected: { color: theme.accent },
  currentLabel: {
    color: theme.accent,
    fontSize: 8,
    fontWeight: '800',
    letterSpacing: 0.5,
    textTransform: 'uppercase',
  },
  menuRowBody: { color: theme.faint, fontSize: 10, lineHeight: 14 },
  optionalGroup: {
    borderLeftColor: theme.gold,
    borderLeftWidth: 2,
    gap: 2,
    marginBottom: 4,
    marginLeft: 13,
    paddingLeft: 6,
  },
  optionalRow: { borderRadius: radius.sm, gap: 3, paddingHorizontal: 10, paddingVertical: 8 },
  optionalTitle: { color: theme.ink, fontSize: 12, fontWeight: '800' },
  optionalBody: { color: theme.faint, fontSize: 10, lineHeight: 14 },
});
