import { render, screen } from '@testing-library/react';
import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { BrowserRouter } from 'react-router-dom';

vi.mock('../../frontend/src/hooks/useConfirmDialog', () => ({
  useConfirmDialog: () => ({
    dialogState: {
      open: false,
      title: 'Confirm Action',
      message: '',
      confirmText: 'OK',
      cancelText: 'Cancel',
      confirmColor: 'primary',
      onConfirm: () => {},
    },
    confirm: () => {},
    handleConfirm: () => {},
    handleCancel: () => {},
    handleDismiss: () => {},
  }),
}));

vi.mock('../../frontend/src/hooks/useToast', () => ({
  useToast: () => ({
    showSuccess: () => {},
    showError: () => {},
    showWarning: () => {},
    showInfo: () => {},
  }),
  default: () => ({
    showSuccess: () => {},
    showError: () => {},
    showWarning: () => {},
    showInfo: () => {},
  }),
}));

vi.mock('../../frontend/src/components/testcase/TestCaseSelector', async () => {
  const ReactImport = await import('react');
  return {
    TestCaseSelector: ReactImport.forwardRef(function TestCaseSelectorMock(_props, ref) {
      ReactImport.useImperativeHandle(ref, () => ({ refresh: () => {} }));
      return <div data-testid="testcase-selector" />;
    }),
  };
});

import TestCaseEditor from '../../frontend/src/pages/TestCaseEditor';

describe('TestCaseEditor page', () => {
  it('renders the Test Case heading', () => {
    render(
      <BrowserRouter>
        <TestCaseEditor />
      </BrowserRouter>,
    );

    expect(screen.getByRole('heading', { name: 'Test Case' })).toBeInTheDocument();
    expect(screen.getByTestId('testcase-selector')).toBeInTheDocument();
  });
});
