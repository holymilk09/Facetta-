/// <reference types="jest" />

import React from 'react';
import {
  render, screen, userEvent,
} from '@testing-library/react-native';

import type { StudioActionContext } from './contracts';
import { StudioContextActionSwitcher } from './StudioContextActionSwitcher';

const preSpecContext: StudioActionContext = {
  activeDesignId: 'project_1',
  activeRevisionId: 'asset_1',
  hasExactSpecification: false,
  hasSelectedPreSpecVisual: true,
  factoryEligible: false,
};

test('keeps the six revision commands behind one collapsed trigger', async () => {
  const onLaunch = jest.fn();
  const user = userEvent.setup();
  await render(
    <StudioContextActionSwitcher
      context={preSpecContext}
      selectedActionId="refine"
      onLaunch={onLaunch}
    />,
  );

  expect(screen.queryByTestId('studio-action-menu')).toBeNull();
  expect(screen.getByLabelText('Change Studio action. Current: Refine')).toBeTruthy();

  await user.press(screen.getByTestId('studio-action-trigger'));
  expect(screen.getAllByTestId(/^studio-action-(create|vary|refine|views|present|more)$/))
    .toHaveLength(6);
  expect(screen.queryByTestId('studio-more-actions')).toBeNull();

  await user.press(screen.getByTestId('studio-action-refine'));
  expect(onLaunch).not.toHaveBeenCalled();
  expect(screen.queryByTestId('studio-action-menu')).toBeNull();
});

test('routes Views through starting facts and keeps Factory unavailable before eligibility', async () => {
  const onLaunch = jest.fn();
  const user = userEvent.setup();
  await render(
    <StudioContextActionSwitcher
      context={preSpecContext}
      selectedActionId="refine"
      onLaunch={onLaunch}
    />,
  );

  await user.press(screen.getByTestId('studio-action-trigger'));
  const views = screen.getByLabelText('Generate technical views; Save starting facts first');
  expect(views.props.accessibilityState).toEqual({ disabled: false, selected: false });
  await user.press(views);
  expect(onLaunch).toHaveBeenCalledWith({
    type: 'open_workspace', actionId: 'confirm', continueTo: 'views',
  });

  await user.press(screen.getByTestId('studio-action-trigger'));
  await user.press(screen.getByTestId('studio-action-more'));
  expect(screen.getByTestId('studio-more-actions')).toBeTruthy();
  expect(screen.getByTestId('studio-action-confirm')).toBeTruthy();
  expect(screen.queryByTestId('studio-action-factory')).toBeNull();
});

test('exposes advanced specifications and eligible Factory only through More', async () => {
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

  await user.press(screen.getByTestId('studio-action-trigger'));
  expect(screen.queryByTestId('studio-action-factory')).toBeNull();
  await user.press(screen.getByTestId('studio-action-more'));
  expect(screen.getByTestId('studio-action-specifications')).toBeTruthy();
  expect(screen.getByTestId('studio-action-factory')).toBeTruthy();

  await view.rerender(
    <StudioContextActionSwitcher
      context={{ ...exactContext, factoryEligible: false }}
      selectedActionId="views"
      onLaunch={onLaunch}
    />,
  );
  expect(screen.queryByTestId('studio-action-factory')).toBeNull();
});

test('fails closed when Views has no safe prerequisite', async () => {
  const user = userEvent.setup();
  await render(
    <StudioContextActionSwitcher
      context={{ ...preSpecContext, hasSelectedPreSpecVisual: false }}
      selectedActionId="refine"
      onLaunch={jest.fn()}
    />,
  );

  await user.press(screen.getByTestId('studio-action-trigger'));
  const views = screen.getByLabelText('Generate technical views');
  expect(views.props.accessibilityState).toEqual({ disabled: true, selected: false });
  expect(views.props.accessibilityHint).toBe('Choose a confirmable ring direction first');
});
