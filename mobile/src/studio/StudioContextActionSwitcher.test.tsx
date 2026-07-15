/// <reference types="jest" />

import React from 'react';
import {
  render, screen, userEvent,
} from '@testing-library/react-native';
import { StyleSheet } from 'react-native';

import type { StudioActionContext } from './contracts';
import { StudioContextActionSwitcher } from './StudioContextActionSwitcher';

const preSpecContext: StudioActionContext = {
  activeDesignId: 'project_1',
  activeRevisionId: 'asset_1',
  hasExactSpecification: false,
  hasSelectedPreSpecVisual: true,
  factoryEligible: false,
};

test('shows the six stable revision actions immediately in a non-wrapping horizontal rail', async () => {
  const onLaunch = jest.fn();
  await render(
    <StudioContextActionSwitcher
      context={preSpecContext}
      selectedActionId="refine"
      onLaunch={onLaunch}
    />,
  );

  const rail = screen.getByTestId('studio-action-rail');
  expect(rail.props.horizontal).toBe(true);
  expect(StyleSheet.flatten(rail.props.contentContainerStyle)).toMatchObject({
    flexDirection: 'row', flexWrap: 'nowrap',
  });
  expect(screen.getAllByTestId(/^studio-action-(create|vary|refine|views|present|more)$/))
    .toHaveLength(6);
  for (const label of ['Create', 'Vary', 'Refine', 'Views', 'Present', 'More']) {
    expect(screen.getByText(label)).toBeTruthy();
  }
  expect(screen.queryByTestId('studio-action-trigger')).toBeNull();
  expect(screen.queryByTestId('studio-more-actions')).toBeNull();
  expect(screen.getByTestId('studio-action-refine').props.accessibilityState).toEqual({
    disabled: false, selected: true,
  });
  expect(StyleSheet.flatten(screen.getByTestId('studio-action-refine').props.style))
    .toMatchObject({ minHeight: 44 });
  expect(screen.queryByText('Preview a targeted change while protecting the rest of the design.'))
    .toBeNull();
  expect(screen.getByTestId('studio-action-refine').props.accessibilityHint)
    .toBe('Preview a targeted change while protecting the rest of the design.');
});

test('launches a primary action in one tap through the canonical resolver', async () => {
  const onLaunch = jest.fn();
  const user = userEvent.setup();
  await render(
    <StudioContextActionSwitcher
      context={preSpecContext}
      selectedActionId="refine"
      onLaunch={onLaunch}
    />,
  );

  await user.press(screen.getByTestId('studio-action-vary'));
  expect(onLaunch).toHaveBeenCalledWith({
    type: 'open_workspace', actionId: 'vary', continueTo: null,
  });
});

test('routes Views through starting facts while keeping Factory absent before eligibility', async () => {
  const onLaunch = jest.fn();
  const user = userEvent.setup();
  await render(
    <StudioContextActionSwitcher
      context={preSpecContext}
      selectedActionId="refine"
      onLaunch={onLaunch}
    />,
  );

  const views = screen.getByLabelText('Generate technical views; Save starting facts first');
  expect(views.props.accessibilityState).toEqual({ disabled: false, selected: false });
  expect(views.props.accessibilityHint).toContain(
    'Create consistent line-art angles from this revision and its confirmed design facts.',
  );
  await user.press(views);
  expect(onLaunch).toHaveBeenCalledWith({
    type: 'open_workspace', actionId: 'confirm', continueTo: 'views',
  });

  await user.press(screen.getByTestId('studio-action-more'));
  expect(screen.getByTestId('studio-more-actions')).toBeTruthy();
  expect(screen.getByTestId('studio-action-confirm')).toBeTruthy();
  expect(screen.queryByTestId('studio-action-factory')).toBeNull();
});

test('exposes eligible optional actions only in the separate More panel', async () => {
  const onLaunch = jest.fn();
  const user = userEvent.setup();
  const exactContext: StudioActionContext = {
    ...preSpecContext,
    hasExactSpecification: true,
    factoryEligible: true,
  };
  const view = await render(
    <StudioContextActionSwitcher
      context={exactContext}
      selectedActionId="views"
      onLaunch={onLaunch}
    />,
  );

  expect(screen.queryByTestId('studio-action-factory')).toBeNull();
  await user.press(screen.getByTestId('studio-action-more'));
  expect(screen.getByTestId('studio-action-specifications')).toBeTruthy();
  expect(screen.getByTestId('studio-action-factory')).toBeTruthy();
  expect(screen.queryByText(
    'Prepare an eligible exact ring revision for optional manufacturer review.',
  )).toBeNull();
  expect(screen.getByTestId('studio-action-factory').props.accessibilityHint)
    .toBe('Prepare an eligible exact ring revision for optional manufacturer review.');

  await view.rerender(
    <StudioContextActionSwitcher
      context={{ ...exactContext, factoryEligible: false }}
      selectedActionId="views"
      onLaunch={onLaunch}
    />,
  );
  expect(screen.queryByTestId('studio-action-factory')).toBeNull();
});

test('keeps unavailable actions visible, disabled, and accessible with the reason', async () => {
  await render(
    <StudioContextActionSwitcher
      context={{ ...preSpecContext, hasSelectedPreSpecVisual: false }}
      selectedActionId="refine"
      onLaunch={jest.fn()}
    />,
  );

  const views = screen.getByLabelText('Generate technical views');
  expect(screen.getByText('Views')).toBeTruthy();
  expect(views.props.accessibilityState).toEqual({ disabled: true, selected: false });
  expect(views.props.accessibilityHint).toContain('Choose a confirmable ring direction first');
});

test('resets More disclosure when the exact revision or selected action changes', async () => {
  const user = userEvent.setup();
  const exactContext: StudioActionContext = {
    ...preSpecContext,
    hasExactSpecification: true,
    factoryEligible: true,
  };
  const view = await render(
    <StudioContextActionSwitcher
      context={exactContext}
      selectedActionId="refine"
      onLaunch={jest.fn()}
    />,
  );

  await user.press(screen.getByTestId('studio-action-more'));
  expect(screen.getByTestId('studio-more-actions')).toBeTruthy();

  await view.rerender(
    <StudioContextActionSwitcher
      context={{ ...exactContext, activeRevisionId: 'asset_2' }}
      selectedActionId="refine"
      onLaunch={jest.fn()}
    />,
  );
  expect(screen.queryByTestId('studio-more-actions')).toBeNull();

  await user.press(screen.getByTestId('studio-action-more'));
  expect(screen.getByTestId('studio-more-actions')).toBeTruthy();
  await view.rerender(
    <StudioContextActionSwitcher
      context={{ ...exactContext, activeRevisionId: 'asset_2' }}
      selectedActionId="views"
      onLaunch={jest.fn()}
    />,
  );
  expect(screen.queryByTestId('studio-more-actions')).toBeNull();
});
