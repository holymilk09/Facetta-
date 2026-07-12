/// <reference types="jest" />

import React from 'react';
import { act, fireEvent, render } from '@testing-library/react-native';

import { ONBOARDING_STEPS, OnboardingScreen } from '../OnboardingScreen';
import { WORKFLOW_SLIDES, WorkflowShowcase } from '../WorkflowShowcase';
import { LoginScreen } from '../LoginScreen';

const forbiddenClaim = /\bgrok\b|physically validated|factory sheet[\s\S]*every time|straight to (?:the )?workshop|ready to share with your factory/i;

function copyOf(items: readonly { kicker: string; title: string; body: string }[]): string {
  return items.map(({ kicker, title, body }) => `${kicker} ${title} ${body}`).join(' ');
}

describe('truthful pre-login journey', () => {
  test('keeps onboarding provider-neutral and makes Factory optional and eligibility-gated', async () => {
    const copy = copyOf(ONBOARDING_STEPS);
    expect(copy).not.toMatch(forbiddenClaim);
    expect(copy).toMatch(/sentence, drawing, photograph, render, or master-geometry reference/i);
    expect(copy).toMatch(/precision refinement appears for revisions with confirmed design facts/i);
    expect(copy).toMatch(/preview until you apply/i);
    expect(copy).toMatch(/design families, variations, and immutable revisions/i);
    expect(copy).toMatch(/factory review stays optional.+only when a revision is eligible/i);

    const view = await render(<OnboardingScreen onDone={jest.fn()} />);
    expect(view.getByText('Begin from your idea')).toBeTruthy();
    await act(async () => { fireEvent.press(view.getByText('Continue')); });
    expect(view.getByText('Choose before you refine')).toBeTruthy();
    await act(async () => { fireEvent.press(view.getByText('Continue')); });
    expect(view.getByText('Keep every useful direction')).toBeTruthy();
    expect(view.queryByText(forbiddenClaim)).toBeNull();
  });

  test('renders Create through optional destinations without production authority claims', async () => {
    const copy = copyOf(WORKFLOW_SLIDES);
    expect(copy).not.toMatch(forbiddenClaim);
    expect(WORKFLOW_SLIDES.map(({ kicker }) => kicker)).toEqual([
      'Create', 'Choose', 'Refine', 'Review', 'Preserve', 'Choose the destination',
    ]);
    expect(copy).toMatch(/Apply appends a revision; discard leaves the saved design untouched/i);
    expect(copy).toMatch(/Factory review is optional, eligibility-gated, and never a production guarantee/i);

    const view = await render(<WorkflowShowcase onDone={jest.fn()} />);
    expect(view.getByText(/Start with what/)).toBeTruthy();
    for (let index = 1; index < WORKFLOW_SLIDES.length; index += 1) {
      await act(async () => { fireEvent.press(view.getByLabelText('Next step')); });
    }
    expect(view.getByText(/Present it now/)).toBeTruthy();
    expect(view.queryByText(forbiddenClaim)).toBeNull();
    view.unmount();
  });

  test('leads sign-in with the Studio promise instead of a factory-first claim', async () => {
    const view = await render(<LoginScreen onSignIn={jest.fn()} />);
    expect(view.getByText('Create quickly. Refine without losing the design.')).toBeTruthy();
    expect(view.queryByText('Continue with Apple')).toBeNull();
    expect(view.queryByText('Continue with Google')).toBeNull();
    expect(view.getByText(/Email sign-in is not configured for this build/)).toBeTruthy();
    expect(view.queryByText(/factory sheet|dropdowns/i)).toBeNull();
    view.unmount();
  });
});
