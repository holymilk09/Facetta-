/// <reference types="jest" />

import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react-native';

import { DraftFactorySheetPreview } from './DraftFactorySheetPreview';

describe('DraftFactorySheetPreview', () => {
  test('renders a preliminary sheet and marks it stale after facts change', async () => {
    const previewDraftFactorySheet = jest.fn(async () => ({
      data: {
        svg: '<svg xmlns="http://www.w3.org/2000/svg"><text>EST. 2.8 mm</text></svg>',
        authority: 'preliminary_not_for_production' as const,
      },
      error: null,
      status: 200,
    }));
    const first = { jewelry_type: 'ring', band: { width_mm: 2.8 } };
    const view = await render(React.createElement(DraftFactorySheetPreview, {
      spec: first,
      client: { previewDraftFactorySheet },
    }));

    await fireEvent.press(screen.getByText('Preview dimensional diagram'));
    expect(previewDraftFactorySheet).toHaveBeenCalledWith(first);
    expect(await screen.findByText(/Preliminary specification review/)).toBeTruthy();
    expect(screen.getByTestId('factory-sheet-webview')).toBeTruthy();

    view.rerender(React.createElement(DraftFactorySheetPreview, {
      spec: { jewelry_type: 'ring', band: { width_mm: 3.2 } },
      client: { previewDraftFactorySheet },
    }));
    expect(await screen.findByText(/Factory facts changed after this diagram/)).toBeTruthy();
  });
});
