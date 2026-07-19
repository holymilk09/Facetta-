import React from 'react';
import {
  Pressable, StyleSheet, Text, View,
} from 'react-native';

import { radius, shadows, theme } from '../theme';
import {
  STUDIO_DESTINATIONS,
  type StudioDestinationContext,
  type StudioDestinationDefinition,
  type StudioDestinationId,
} from './destinations';

export interface StudioDestinationChooserProps {
  context: StudioDestinationContext;
  onSelect: (destinationId: StudioDestinationId) => void;
  title?: string;
  description?: string;
  /** Omit the destination the designer is already viewing to avoid no-op loops. */
  excludeDestinations?: readonly StudioDestinationId[];
  /** Context-specific product copy without changing the canonical destination contract. */
  destinationCopy?: Partial<Record<StudioDestinationId, {
    label?: string;
    description?: string;
  }>>;
}

const availabilityLabel = (
  destination: StudioDestinationDefinition,
  available: boolean,
): string => {
  if (available && destination.id === 'factory') {
    return 'Available for this exact revision';
  }
  if (available) return 'Available now';
  return 'Available after a saved revision is selected';
};

/**
 * One product-language handoff for every accepted Studio revision.
 *
 * Library, Client, and Marketing stay in a predictable order. Factory is an
 * optional destination and is omitted until the canonical registry confirms
 * that the exact active revision is eligible.
 */
export function StudioDestinationChooser({
  context,
  onSelect,
  title = 'Where next?',
  description = 'Choose what you want to do with this saved revision.',
  excludeDestinations = [],
  destinationCopy = {},
}: StudioDestinationChooserProps) {
  const destinations = STUDIO_DESTINATIONS.filter((destination) => (
    !excludeDestinations.includes(destination.id)
    && (destination.id !== 'factory' || destination.isAvailable(context))
  ));

  return (
    <View style={styles.container}>
      <Text style={styles.title}>{title}</Text>
      <Text style={styles.description}>{description}</Text>
      <View style={styles.destinationList}>
        {destinations.map((destination) => {
          const available = destination.isAvailable(context);
          const availability = availabilityLabel(destination, available);
          const label = destinationCopy[destination.id]?.label ?? destination.label;
          const destinationDescription = destinationCopy[destination.id]?.description
            ?? destination.description;
          return (
            <Pressable
              key={destination.id}
              testID={`studio-destination-card-${destination.id}`}
              accessibilityRole="button"
              accessibilityLabel={label}
              accessibilityHint={`${destinationDescription} ${availability}.`}
              accessibilityState={{ disabled: !available }}
              disabled={!available}
              onPress={() => onSelect(destination.id)}
              style={({ pressed }) => [
                styles.destinationCard,
                !available && styles.destinationCardUnavailable,
                pressed && available && styles.destinationCardPressed,
              ]}>
              <View style={styles.cardHeading}>
                <Text style={styles.destinationLabel}>{label}</Text>
                <Text
                  testID={`studio-destination-availability-${destination.id}`}
                  style={[styles.availability, !available && styles.availabilityUnavailable]}>
                  {availability}
                </Text>
              </View>
              <Text style={styles.destinationDescription}>{destinationDescription}</Text>
            </Pressable>
          );
        })}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    gap: 8,
  },
  title: {
    color: theme.ink,
    fontFamily: theme.serif,
    fontSize: 22,
  },
  description: {
    color: theme.faint,
    fontSize: 14,
    lineHeight: 20,
  },
  destinationList: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 10,
    marginTop: 4,
  },
  destinationCard: {
    backgroundColor: theme.card,
    borderColor: theme.line,
    borderRadius: radius.md,
    borderWidth: 1,
    flexBasis: 210,
    flexGrow: 1,
    gap: 8,
    minHeight: 126,
    padding: 14,
    ...shadows.soft,
  },
  destinationCardPressed: {
    backgroundColor: theme.goldSoft,
    borderColor: theme.gold,
  },
  destinationCardUnavailable: {
    backgroundColor: theme.paper,
    opacity: 0.55,
  },
  cardHeading: {
    alignItems: 'flex-start',
    gap: 6,
  },
  destinationLabel: {
    color: theme.ink,
    fontFamily: theme.serif,
    fontSize: 17,
  },
  availability: {
    color: theme.ok,
    fontSize: 11,
    fontWeight: '600',
    letterSpacing: 0.2,
  },
  availabilityUnavailable: {
    color: theme.faint,
  },
  destinationDescription: {
    color: theme.faint,
    fontSize: 13,
    lineHeight: 18,
  },
});
