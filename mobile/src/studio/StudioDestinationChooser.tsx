import React from 'react';
import {
  Pressable, StyleSheet, Text, View,
} from 'react-native';

import { radius, shadows, theme } from '../theme';
import {
  STUDIO_DESTINATIONS,
  type StudioDestinationContext,
  type StudioDestinationId,
} from './destinations';

export interface StudioDestinationChooserProps {
  context: StudioDestinationContext;
  onSelect: (destinationId: StudioDestinationId) => void;
  title?: string;
  description?: string;
  /** Omit the destination the designer is already viewing to avoid no-op loops. */
  excludeDestinations?: readonly StudioDestinationId[];
}

const availabilityLabel = (
  available: boolean,
): string => {
  if (available) return 'Available now';
  return 'Available after a saved revision is selected';
};

/**
 * One product-language handoff for every accepted Studio revision.
 *
 * Library, Client, and Marketing stay in a predictable order. Factory is
 * intentionally absent from this everyday handoff; an eligible exact revision
 * exposes it only through the active design's contextual More menu.
 */
export function StudioDestinationChooser({
  context,
  onSelect,
  title = 'Where next?',
  description = 'Choose what you want to do with this saved revision.',
  excludeDestinations = [],
}: StudioDestinationChooserProps) {
  const destinations = STUDIO_DESTINATIONS.filter((destination) => (
    destination.id !== 'factory'
    && !excludeDestinations.includes(destination.id)
  ));

  return (
    <View style={styles.container}>
      <Text style={styles.title}>{title}</Text>
      <Text style={styles.description}>{description}</Text>
      <View style={styles.destinationList}>
        {destinations.map((destination) => {
          const available = destination.isAvailable(context);
          const availability = availabilityLabel(available);
          return (
            <Pressable
              key={destination.id}
              testID={`studio-destination-card-${destination.id}`}
              accessibilityRole="button"
              accessibilityLabel={destination.label}
              accessibilityHint={`${destination.description} ${availability}.`}
              accessibilityState={{ disabled: !available }}
              disabled={!available}
              onPress={() => onSelect(destination.id)}
              style={({ pressed }) => [
                styles.destinationCard,
                !available && styles.destinationCardUnavailable,
                pressed && available && styles.destinationCardPressed,
              ]}>
              <View style={styles.cardHeading}>
                <Text style={styles.destinationLabel}>{destination.label}</Text>
                <Text
                  testID={`studio-destination-availability-${destination.id}`}
                  style={[styles.availability, !available && styles.availabilityUnavailable]}>
                  {availability}
                </Text>
              </View>
              <Text style={styles.destinationDescription}>{destination.description}</Text>
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
