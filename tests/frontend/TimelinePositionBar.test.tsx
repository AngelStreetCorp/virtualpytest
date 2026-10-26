import { fireEvent, render, screen } from '@testing-library/react';
import React from 'react';
import { describe, expect, it, vi } from 'vitest';

import { TimelinePositionBar } from '../../frontend/src/components/timeline/TimelinePositionBar';
import type { TimelineSlot } from '../../frontend/src/hooks/useTimeline';

// 6 slots: 00:00 .. 00:50 of one hour
const slots = Array.from({ length: 6 }, (_, i) => ({ hour: 0, chunkIndex: i, has: true, flag: null })) as unknown as TimelineSlot[];

// jsdom has no PointerEvent: a MouseEvent of the pointer type carries the coordinates the component reads
const pointer = (el: Element, type: string, clientX: number, clientY: number) =>
  fireEvent(el, new MouseEvent(type, { bubbles: true, clientX, clientY }));

const bounds = (w: number, h: number) =>
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue({ width: w, height: h, top: 0, left: 0, right: w, bottom: h, x: 0, y: 0, toJSON: () => ({}) });

describe('TimelinePositionBar', () => {
  it('a horizontal bar jumps by the x position', () => {
    bounds(600, 22);
    const onJump = vi.fn();
    render(<TimelinePositionBar slots={slots} frame={{ from: 0, to: 0 }} onJump={onJump} />);
    const bar = screen.getByRole('slider');
    expect(bar.getAttribute('aria-orientation')).toBe('horizontal');
    pointer(bar, 'pointerdown', 450, 5);
    expect(onJump).toHaveBeenCalledWith(4);                   // 450 / 600 of 6 slots
  });

  it('a vertical bar jumps by the y position, not the x position', () => {
    bounds(22, 600);
    const onJump = vi.fn();
    render(<TimelinePositionBar slots={slots} frame={{ from: 2, to: 2 }} onJump={onJump} orientation="vertical" height={600} />);
    const bar = screen.getByRole('slider');
    expect(bar.getAttribute('aria-orientation')).toBe('vertical');
    pointer(bar, 'pointerdown', 3, 150);
    expect(onJump).toHaveBeenCalledWith(1);                   // 150 / 600 of 6 slots
    pointer(bar, 'pointermove', 3, 590);
    expect(onJump).toHaveBeenLastCalledWith(5);
  });

  it('draws nothing without slots', () => {
    const { container } = render(<TimelinePositionBar slots={[]} frame={null} onJump={() => {}} orientation="vertical" />);
    expect(container.firstChild).toBeNull();
  });
});
