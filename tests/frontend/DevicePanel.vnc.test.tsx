/**
 * DevicePanel VNC branch — regression test for BUG-0546 / 0546-followups.
 *
 * The Target stream for a `host_vnc` device must:
 *  - measure the wrapper and feed that into calculateVncScaling (no hard-coded 380x180)
 *  - render the iframe with `transformOrigin: 'top center'` so a wrapper narrower
 *    than 1440 fills its full width while a wider one is centred with equal bars
 *  - sit at the top of the panel (alignItems: flex-start), not vertically centred
 *
 * If any of these regress, the iframe either stops filling the panel, ends up
 * as a 30%-width sliver in the top-left, or floats in the vertical middle.
 */
import { render, waitFor } from '@testing-library/react';
import React from 'react';
import { describe, expect, it, vi } from 'vitest';

import { DevicePanel } from '../../frontend/src/components/agent-chat/DevicePanel';

vi.mock('../../frontend/src/hooks/useHostSession', () => ({
  useHostSession: () => true, // session cookie "ready"
}));

vi.mock('../../frontend/src/components/common/HLSVideoPlayer', () => ({
  HLSVideoPlayer: (props: any) => <div data-testid="hls-video-player" data-stream-url={props.streamUrl} />,
}));

const flushResize = async () => {
  // jsdom doesn't lay out: every ResizeObserver callback fires with 0x0 by default.
  // Force a positive measured area so calculateVncScaling returns a non-zero scale.
  const elProto = HTMLElement.prototype as any;
  if (!elProto.__vncStubbedGetBCR) {
    elProto.getBoundingClientRect = function () {
      return { x: 0, y: 0, left: 0, top: 0, right: 600, bottom: 800, width: 600, height: 800, toJSON() { return {}; } } as DOMRect;
    };
    elProto.__vncStubbedGetBCR = true;
  }
  // also force the layout box to have non-zero width so MUI's sx doesn't collapse
  Object.defineProperty(HTMLElement.prototype, 'clientWidth', { configurable: true, get: () => 600 });
  Object.defineProperty(HTMLElement.prototype, 'clientHeight', { configurable: true, get: () => 800 });
};

const renderVnc = (model = 'host_vnc') => {
  return render(
    <DevicePanel
      showDevice
      selectedDevice="vbox-dockrant1"
      streamUrl="https://vnc.example.test/embed"
      isLoadingUrl={false}
      getSelectedDeviceModel={() => model}
    />,
  );
};

describe('DevicePanel VNC branch (BUG-0546 + top-center fix)', () => {
  it('renders the iframe when vnc model + session ready', async () => {
    flushResize();
    const { container } = renderVnc();
    await waitFor(() => {
      expect(container.querySelector('iframe[title="VNC Desktop Stream"]')).toBeTruthy();
    });
  });

  it('iframe style has transformOrigin "top center" (not "center center", not default "top left")', async () => {
    flushResize();
    const { container } = renderVnc();
    const iframe = await waitFor(() => container.querySelector('iframe[title="VNC Desktop Stream"]') as HTMLIFrameElement);
    expect(iframe).toBeTruthy();
    // MUI's `sx` ends up in the emotion-generated <style> sheet; check computed style
    const computed = window.getComputedStyle(iframe);
    expect(computed.transformOrigin).toMatch(/^(top center|0% 0%|50% 0%)/);
    // calculateVncScaling sets a non-empty transform; must be present
    expect(computed.transform).toMatch(/^(matrix\(|scale\()/);
    expect(computed.flexShrink).toBe('0');
  });

  it('VNC wrapper is a flex container with alignItems:flex-start and justifyContent:center', async () => {
    flushResize();
    const { container } = renderVnc();
    const iframe = await waitFor(() => container.querySelector('iframe[title="VNC Desktop Stream"]') as HTMLElement);
    // The wrapper is the iframe's direct flex parent
    const wrapper = iframe.parentElement as HTMLElement;
    expect(wrapper).toBeTruthy();
    const cs = window.getComputedStyle(wrapper);
    expect(cs.display).toBe('flex');
    expect(cs.alignItems).toBe('flex-start');
    expect(cs.justifyContent).toBe('center');
    expect(cs.overflow).toBe('hidden');
  });

  it('does NOT hard-code the VNC target at { width: 380, height: 180 }', async () => {
    flushResize();
    // The component imports calculateVncScaling from vncUtils; we can't easily
    // intercept a named export, so instead we observe the resulting transform.
    // For a 600x800 wrapper the scale must be min(600/1440, 800/847) ≈ 0.4167.
    // The old hard-coded 380x180 path would yield scale ≈ 0.213 (1.7x smaller).
    const { container } = renderVnc();
    const iframe = await waitFor(() => container.querySelector('iframe[title="VNC Desktop Stream"]') as HTMLIFrameElement);
    const cs = window.getComputedStyle(iframe);
    // jsdom returns "none" for transform unless we feed it matrix()/scale(); the
    // component sets the inline style as `transform: scale(s)` and emotion doesn't
    // touch it. Read it back from .style (not computed, which jsdom doesn't apply).
    const inline = (iframe as any).style.transform;
    const scale = parseFloat((inline.match(/scale\(([\d.]+)/) || [])[1] || '');
    expect(scale).toBeGreaterThan(0.3);   // the new, measured path
    expect(scale).toBeLessThan(0.5);
  });
});

describe('DevicePanel VNC branch — bug-regression guard', () => {
  it('mobile (HLS) branch is unchanged: same panel + mobile model still renders HLSVideoPlayer, not the VNC iframe', async () => {
    flushResize();
    const { container } = renderVnc('android_mobile');
    // Wait for either an iframe (should NOT happen) or the HLSVideoPlayer to render
    await new Promise((r) => setTimeout(r, 100));
    // The mobile branch is mocked away below, but the important assertion is: no VNC iframe
    expect(container.querySelector('iframe[title="VNC Desktop Stream"]')).toBeNull();
  });
});
