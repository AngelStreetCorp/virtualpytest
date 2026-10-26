import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import React from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';

const post = vi.fn();
vi.mock('../../frontend/src/utils/apiClient', () => ({ api: { post: (...a: unknown[]) => post(...a) } }));

import AdBreaksDialog from '../../frontend/src/components/monitoring/AdBreaksDialog';

afterEach(() => post.mockReset());

const host = { host_name: 'vpt-lenovo5', host_url: '/host/vpt-lenovo5', devices: [{ device_id: 'device5', video_capture_path: '/var/www/html/stream/capture5' }] };
const BREAK = { id: 'capture5:1793000000', start: 1793000000, end: 1793000300, duration_s: 300, kind: 'confirmed', thumbs: ['b1793000001/1793000001.jpg', 'b1793000001/1793000031.jpg'], not_ad: false };

describe('the ad breaks review (owner, 2026-10-26)', () => {
  it('lists each break with its pictures and lets a person say "not an ad"', async () => {
    post.mockResolvedValueOnce({ success: true, breaks: [BREAK] }).mockResolvedValueOnce({ success: true, queued: true });
    render(<AdBreaksDialog open onClose={() => {}} host={host} deviceId="device5" deviceName="Ads loop" />);
    await waitFor(() => expect(screen.getAllByTestId('ad-break-row')).toHaveLength(1));
    expect(screen.getAllByTestId('ad-break-thumb')).toHaveLength(2);
    expect((screen.getAllByTestId('ad-break-thumb')[0] as HTMLImageElement).src).toContain('/ads/b1793000001/1793000001.jpg');
    expect(screen.getByText('seen before')).toBeTruthy();
    fireEvent.click(screen.getByTestId('ad-break-not-ad'));
    await waitFor(() => expect(screen.getByText('marked not an ad')).toBeTruthy());
    expect(post.mock.calls[1][1]).toMatchObject({ device_id: 'device5', break_id: BREAK.id });
    expect(screen.queryByTestId('ad-break-not-ad')).toBeNull();
  });

  it('shows 299.6 s as 5:00, never 4:60', async () => {
    post.mockResolvedValueOnce({ success: true, breaks: [{ ...BREAK, duration_s: 299.6, not_ad: true }] });
    render(<AdBreaksDialog open onClose={() => {}} host={host} deviceId="device5" />);
    await waitFor(() => expect(screen.getAllByText('5:00').length).toBeGreaterThan(0));
    expect(screen.queryByText('4:60')).toBeNull();
  });

  it('says so when there was no break', async () => {
    post.mockResolvedValueOnce({ success: true, breaks: [] });
    render(<AdBreaksDialog open onClose={() => {}} host={host} deviceId="device5" />);
    await waitFor(() => expect(screen.getByText('No ad break in the last 24 h.')).toBeTruthy());
  });
});
