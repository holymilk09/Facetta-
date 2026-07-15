import React, { useState } from 'react';
import {
  Pressable, ScrollView, StyleSheet, Text, View,
} from 'react-native';

import { radius, shadows, theme } from '../theme';
import {
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
 * The six stable, revision-scoped Studio commands. Optional destinations are
 * disclosed separately so the designer never has to rediscover core actions.
 */
export function StudioContextActionSwitcher({
  context,
  selectedActionId,
  onLaunch,
}: StudioContextActionSwitcherProps) {
  const revisionActionKey = [
    context.activeDesignId ?? '',
    context.activeRevisionId ?? '',
    selectedActionId,
  ].join(':');
  const [moreDisclosure, setMoreDisclosure] = useState({
    key: revisionActionKey,
    open: false,
  });
  const optionalExpanded = moreDisclosure.key === revisionActionKey
    && moreDisclosure.open;
  const actions = getStudioContextActions(context);
  const optionalActions = getVisibleStudioActions(context, 'more');
  const currentIsOptional = optionalActions.some((action) => action.id === selectedActionId);

  const selectAction = (actionId: StudioActionId): void => {
    if (actionId === selectedActionId) {
      setMoreDisclosure({ key: revisionActionKey, open: false });
      return;
    }
    const intent = resolveStudioActionLaunch(actionId, context);
    if (intent.type === 'toggle_optional') {
      setMoreDisclosure({ key: revisionActionKey, open: !optionalExpanded });
      return;
    }
    if (intent.type === 'unavailable') return;
    setMoreDisclosure({ key: revisionActionKey, open: false });
    onLaunch(intent);
  };

  return (
    <View style={styles.container}>
      <ScrollView
        testID="studio-action-rail"
        accessibilityRole="toolbar"
        accessibilityLabel="Actions for this saved revision"
        horizontal
        showsHorizontalScrollIndicator={false}
        style={styles.rail}
        contentContainerStyle={styles.railContent}
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
          const accessibilityHint = prerequisite !== null
            ? `${action.description} Opens ${prerequisite.label}, then continues to ${action.shortLabel}.`
            : unavailableReason !== null
              ? `${action.description} Unavailable: ${unavailableReason}.`
              : action.description;
          return (
            <Pressable
              key={action.id}
              testID={`studio-action-${action.id}`}
              accessibilityRole="button"
              accessibilityLabel={accessibilityLabel}
              accessibilityHint={accessibilityHint}
              accessibilityState={{
                disabled: unavailable,
                selected,
                ...(action.id === 'more' ? { expanded: optionalExpanded } : {}),
              }}
              disabled={unavailable}
              onPress={() => selectAction(action.id)}
              style={({ pressed }) => [
                styles.railAction,
                selected && styles.railActionSelected,
                unavailable && styles.railActionUnavailable,
                pressed && !unavailable && styles.railActionPressed,
              ]}>
              <Text
                numberOfLines={1}
                style={[styles.railActionLabel, selected && styles.railActionLabelSelected]}>
                {action.shortLabel}
              </Text>
            </Pressable>
          );
        })}
      </ScrollView>

      {optionalExpanded && (
        <View
          testID="studio-more-actions"
          accessibilityRole="menu"
          accessibilityLabel="Optional actions for this saved revision"
          style={[styles.optionalPanel, shadows.soft]}>
          {optionalActions.map((optionalAction) => (
            <Pressable
              key={optionalAction.id}
              testID={`studio-action-${optionalAction.id}`}
              accessibilityRole="menuitem"
              accessibilityLabel={optionalAction.label}
              accessibilityHint={optionalAction.description}
              accessibilityState={{ selected: optionalAction.id === selectedActionId }}
              onPress={() => selectAction(optionalAction.id)}
              style={({ pressed }) => [
                styles.optionalAction,
                optionalAction.id === selectedActionId && styles.optionalActionSelected,
                pressed && styles.optionalActionPressed,
              ]}>
              <Text style={[
                styles.optionalActionLabel,
                optionalAction.id === selectedActionId && styles.optionalActionLabelSelected,
              ]}>
                {optionalAction.shortLabel}
              </Text>
            </Pressable>
          ))}
        </View>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    minWidth: 0,
    position: 'relative',
    width: '100%',
    zIndex: 40,
  },
  rail: { flexGrow: 0, width: '100%' },
  railContent: {
    flexDirection: 'row',
    flexWrap: 'nowrap',
    gap: 6,
    paddingHorizontal: 2,
    paddingVertical: 3,
  },
  railAction: {
    alignItems: 'center',
    backgroundColor: theme.card,
    borderColor: theme.line,
    borderRadius: radius.pill,
    borderWidth: 1,
    justifyContent: 'center',
    minHeight: 44,
    minWidth: 68,
    paddingHorizontal: 13,
    paddingVertical: 8,
  },
  railActionSelected: { backgroundColor: theme.ink, borderColor: theme.ink },
  railActionUnavailable: { opacity: 0.48 },
  railActionPressed: { backgroundColor: theme.blush },
  railActionLabel: { color: theme.ink, fontSize: 11, fontWeight: '800' },
  railActionLabelSelected: { color: '#ffffff' },
  optionalPanel: {
    alignItems: 'stretch',
    backgroundColor: theme.card,
    borderColor: theme.line,
    borderRadius: radius.md,
    borderWidth: 1,
    gap: 4,
    marginTop: 6,
    padding: 7,
  },
  optionalAction: {
    borderRadius: radius.sm,
    minHeight: 44,
    paddingHorizontal: 11,
    paddingVertical: 10,
  },
  optionalActionSelected: { backgroundColor: theme.goldSoft },
  optionalActionPressed: { backgroundColor: theme.blush },
  optionalActionLabel: { color: theme.ink, fontSize: 12, fontWeight: '800' },
  optionalActionLabelSelected: { color: theme.accent },
});
