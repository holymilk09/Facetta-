/// <reference types="jest" />

import React from 'react';
import {
  fireEvent, render, screen,
} from '@testing-library/react-native';

import { getStudioDestination } from './destinations';
import { StudioDestinationChooser } from './StudioDestinationChooser';

const savedContext = {
  activeProjectId: 'project_1',
  activeRevisionId: 'asset_4',
  hasExactSpecification: true,
  factoryEligible: false,
};

test('keeps the three everyday destinations in registry order with their descriptions', async () => {
  const onSelect = jest.fn();
  await render(<StudioDestinationChooser context={savedContext} onSelect={onSelect} />);

  expect(screen.getAllByTestId(/studio-destination-card-/).map((card) => (
    card.props.accessibilityLabel
  ))).toEqual(['Library', 'Client review', 'Campaign image set']);

  for (const id of ['library', 'client', 'marketing'] as const) {
    const destination = getStudioDestination(id);
    expect(screen.getByText(destination.description)).toBeTruthy();
    expect(screen.getByTestId(`studio-destination-availability-${id}`).props.children)
      .toBe('Available now');
  }

  fireEvent.press(screen.getByLabelText('Campaign image set'));
  expect(onSelect).toHaveBeenCalledWith('marketing');
});

test('shows Factory only when the exact active revision passes its registry predicate', async () => {
  const onSelect = jest.fn();
  const view = await render(
    <StudioDestinationChooser context={savedContext} onSelect={onSelect} />,
  );

  expect(screen.queryByLabelText('Factory')).toBeNull();

  await view.rerender(<StudioDestinationChooser
    context={{ ...savedContext, factoryEligible: true }}
    onSelect={onSelect}
  />);

  expect(screen.getAllByTestId(/studio-destination-card-/).map((card) => (
    card.props.accessibilityLabel
  ))).toEqual(['Library', 'Client review', 'Campaign image set', 'Factory']);
  expect(screen.getByText(getStudioDestination('factory').description)).toBeTruthy();
  expect(screen.getByTestId('studio-destination-availability-factory').props.children)
    .toBe('Available for this exact revision');

  fireEvent.press(screen.getByLabelText('Factory'));
  expect(onSelect).toHaveBeenCalledWith('factory');
});

test('omits the destination already being viewed without changing registry order or eligibility', async () => {
  const onSelect = jest.fn();
  await render(<StudioDestinationChooser
    context={{ ...savedContext, factoryEligible: true }}
    excludeDestinations={['library']}
    onSelect={onSelect}
    title="Create images from this revision"
  />);

  expect(screen.getByText('Create images from this revision')).toBeTruthy();
  expect(screen.queryByLabelText('Library')).toBeNull();
  expect(screen.getAllByTestId(/studio-destination-card-/).map((card) => (
    card.props.accessibilityLabel
  ))).toEqual(['Client review', 'Campaign image set', 'Factory']);

  fireEvent.press(screen.getByLabelText('Client review'));
  expect(onSelect).toHaveBeenCalledWith('client');
});

test('does not expose Factory when specification or backend eligibility is missing', async () => {
  const view = await render(
    <StudioDestinationChooser
      context={{ ...savedContext, hasExactSpecification: false, factoryEligible: true }}
      onSelect={jest.fn()}
    />,
  );
  expect(screen.queryByLabelText('Factory')).toBeNull();

  await view.rerender(<StudioDestinationChooser
    context={{ ...savedContext, hasExactSpecification: true, factoryEligible: false }}
    onSelect={jest.fn()}
  />);
  expect(screen.queryByLabelText('Factory')).toBeNull();
});

test('surfaces unavailable saved-revision requirements without firing a selection', async () => {
  const onSelect = jest.fn();
  await render(<StudioDestinationChooser
    context={{
      activeProjectId: null,
      activeRevisionId: null,
      hasExactSpecification: false,
      factoryEligible: false,
    }}
    onSelect={onSelect}
  />);

  expect(screen.getAllByText('Available after a saved revision is selected')).toHaveLength(3);
  expect(screen.queryByLabelText('Factory')).toBeNull();
  expect(screen.getByLabelText('Library').props.accessibilityState).toEqual({ disabled: true });

  fireEvent.press(screen.getByLabelText('Library'));
  expect(onSelect).not.toHaveBeenCalled();
});
