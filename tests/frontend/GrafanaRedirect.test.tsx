import { render } from '@testing-library/react';
import React from 'react';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import GrafanaRedirect from '../../frontend/src/pages/GrafanaRedirect';

describe('GrafanaRedirect page', () => {
  const originalLocation = window.location;

  beforeEach(() => {
    // jsdom's window.location.href setter throws "Not implemented: navigation"
    // unless we replace location with a writable stub first.
    // @ts-expect-error deleting to redefine below
    delete (window as any).location;
    (window as any).location = {
      ...originalLocation,
      pathname: '/grafana/d/abc/system-monitoring',
      search: '?orgId=1',
      hash: '',
      href: '',
    };
  });

  afterEach(() => {
    (window as any).location = originalLocation;
  });

  it('redirects to the Grafana URL derived from the current path', () => {
    const { container } = render(<GrafanaRedirect />);

    expect(container).toBeEmptyDOMElement();
    expect(window.location.href).toBe(
      'http://localhost/grafana/d/abc/system-monitoring?orgId=1',
    );
  });
});
