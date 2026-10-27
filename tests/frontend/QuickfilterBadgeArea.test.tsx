// @vitest-environment jsdom
/**
 * QuickfilterBadgeArea (TASK-120): per-user-configurable chip row under the
 * device-control toolbar. Replaces the profile-only DeviceProfileChips.
 */
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { QuickfilterBadgeArea } from '../../frontend/src/components/common/QuickfilterBadgeArea';

afterEach(cleanup);
beforeEach(() => window.localStorage.clear());

const baseProps = {
  uniqueProfiles: ['counting_cars', 'egg_quality', 'tv_app', 'tv_lite'] as string[],
  profileCounts: { counting_cars: 1, egg_quality: 1, tv_app: 7, tv_lite: 27 },
  profileFilter: [] as string[],
  onProfileFilterChange: vi.fn(),

  uniqueDeviceModels: ['fire_tv_fireos', 'stb-testop', 'android_tv'] as string[],
  // 'stb-testop' is quoted: the TASK-176 rename turned the model id into a
  // hyphenated name, which is not a valid bare object key.
  deviceModelCounts: { fire_tv_fireos: 8, 'stb-testop': 14, android_tv: 2 },
  deviceModelFilter: [] as string[],
  onDeviceModelFilterChange: vi.fn(),

  uniqueFlags: ['loud', 'silent', 'kitchen'] as string[],
  flagCounts: { loud: 3, silent: 2, kitchen: 1 },
  flagFilter: [] as string[],
  onFlagFilterChange: vi.fn(),

  favoriteTargetOptions: ['device1 - h1', 'device2 - h1'] as string[],
  onFavoritesToggle: vi.fn(),
};

describe('QuickfilterBadgeArea — visibility', () => {
  it('still renders the bolt when no chips would show — the user can re-enable from the configure popover', () => {
    // Profiles is the only category, every device is on the default (tv_app), so
    // the profiles row produces no chips. The row must stay visible because
    // the bolt is the only entry point to the configure popover.
    render(
      <QuickfilterBadgeArea
        {...baseProps}
        uniqueProfiles={['tv_app']}
        profileCounts={{ tv_app: 5 }}
      />,
    );
    expect(screen.getByTestId('quickfilter-badge-area')).toBeTruthy();
    expect(screen.getByTestId('quickfilter-marker')).toBeTruthy();
  });

  it('renders the bolt only when the user has explicitly cleared every category (no chips, no hint)', () => {
    // Start with no categories enabled. The row stays visible with just the
    // bolt — the user can re-enable from the configure popover.
    window.localStorage.setItem('vpt_quickfilter_config_v1', JSON.stringify([]));
    render(<QuickfilterBadgeArea {...baseProps} />);
    expect(screen.getByTestId('quickfilter-badge-area')).toBeTruthy();
    expect(screen.getByTestId('quickfilter-marker')).toBeTruthy();
    expect(screen.queryByTestId('quickfilter-empty-hint')).toBeNull();
  });

  it('renders the bolt marker and chips when a non-default profile is present', () => {
    render(<QuickfilterBadgeArea {...baseProps} />);
    expect(screen.getByTestId('quickfilter-badge-area')).toBeTruthy();
    expect(screen.getByTestId('quickfilter-marker')).toBeTruthy();
    // The chips carry the short name of the profile, not its id.
    expect(screen.getByText('Car count')).toBeTruthy();
    expect(screen.getByText('Eggs')).toBeTruthy();
    expect(screen.getByText('TV')).toBeTruthy();
    expect(screen.getByText('Lite')).toBeTruthy();
    expect(screen.getByText('Car count').parentElement?.textContent).toContain('1');
  });
});

describe('QuickfilterBadgeArea — chip toggle', () => {
  it('clicking a profile chip toggles the profile filter', () => {
    const onProfileChange = vi.fn();
    render(
      <QuickfilterBadgeArea
        {...baseProps}
        uniqueProfiles={['counting_cars', 'tv_app']}
        profileCounts={{ counting_cars: 1, tv_app: 7 }}
        onProfileFilterChange={onProfileChange}
      />,
    );
    fireEvent.click(screen.getByText('Car count'));
    expect(onProfileChange).toHaveBeenCalledWith(['counting_cars']);
  });

  it('clicking an already-selected chip clears it', () => {
    const onProfileChange = vi.fn();
    render(
      <QuickfilterBadgeArea
        {...baseProps}
        uniqueProfiles={['counting_cars', 'tv_app']}
        profileCounts={{ counting_cars: 1, tv_app: 7 }}
        profileFilter={['counting_cars']}
        onProfileFilterChange={onProfileChange}
      />,
    );
    fireEvent.click(screen.getByText('Car count'));
    expect(onProfileChange).toHaveBeenCalledWith([]);
  });
});

describe('QuickfilterBadgeArea — tags', () => {
  it('renders a chip per unique tag when the tags category is enabled', () => {
    window.localStorage.setItem('vpt_quickfilter_config_v1', JSON.stringify(['tags']));
    render(<QuickfilterBadgeArea {...baseProps} />);
    expect(screen.getByText('loud')).toBeTruthy();
    expect(screen.getByText('silent')).toBeTruthy();
    expect(screen.getByText('kitchen')).toBeTruthy();
  });

  it('clicking a tag chip toggles the flag filter', () => {
    const onFlagChange = vi.fn();
    window.localStorage.setItem('vpt_quickfilter_config_v1', JSON.stringify(['tags']));
    render(
      <QuickfilterBadgeArea
        {...baseProps}
        onFlagFilterChange={onFlagChange}
      />,
    );
    fireEvent.click(screen.getByText('loud'));
    expect(onFlagChange).toHaveBeenCalledWith(['loud']);
  });

  it('does not render the tags row when there are no unique flags', () => {
    window.localStorage.setItem('vpt_quickfilter_config_v1', JSON.stringify(['tags']));
    render(<QuickfilterBadgeArea {...baseProps} uniqueFlags={[]} />);
    expect(screen.queryByText('loud')).toBeNull();
  });
});

describe('QuickfilterBadgeArea — favorites', () => {
  it('shows the Favorites chip when favorites are non-empty and category is enabled', () => {
    window.localStorage.setItem('vpt_quickfilter_config_v1', JSON.stringify(['profiles', 'favorites']));
    render(<QuickfilterBadgeArea {...baseProps} />);
    expect(screen.getByText('Favorites')).toBeTruthy();
  });

  it('clicking the Favorites chip calls onFavoritesToggle (parent owns the target-filter mutation)', () => {
    window.localStorage.setItem('vpt_quickfilter_config_v1', JSON.stringify(['profiles', 'favorites']));
    const onFavoritesToggle = vi.fn();
    render(
      <QuickfilterBadgeArea
        {...baseProps}
        onFavoritesToggle={onFavoritesToggle}
      />,
    );
    fireEvent.click(screen.getByText('Favorites'));
    expect(onFavoritesToggle).toHaveBeenCalledTimes(1);
  });

  it('does not show the Favorites chip when there are zero favorites', () => {
    window.localStorage.setItem('vpt_quickfilter_config_v1', JSON.stringify(['profiles', 'favorites']));
    render(<QuickfilterBadgeArea {...baseProps} favoriteTargetOptions={[]} />);
    expect(screen.queryByText('Favorites')).toBeNull();
  });
});

describe('QuickfilterBadgeArea — configure popover', () => {
  it('opens the popover when the bolt is clicked and lists every category', () => {
    render(<QuickfilterBadgeArea {...baseProps} />);
    fireEvent.click(screen.getByTestId('quickfilter-marker'));
    expect(screen.getByText('Show in quickfilters')).toBeTruthy();
    expect(screen.getByTestId('quickfilter-config-row-profiles')).toBeTruthy();
    expect(screen.getByTestId('quickfilter-config-row-models')).toBeTruthy();
    expect(screen.getByTestId('quickfilter-config-row-tags')).toBeTruthy();
    expect(screen.getByTestId('quickfilter-config-row-favorites')).toBeTruthy();
  });

  it('clicking a category row in the popover toggles it and updates the rendered chips', () => {
    render(<QuickfilterBadgeArea {...baseProps} />);
    expect(screen.queryByText('fire_tv_fireos')).toBeNull();
    fireEvent.click(screen.getByTestId('quickfilter-marker'));
    fireEvent.click(screen.getByTestId('quickfilter-config-row-models'));
    fireEvent.click(document.body);
    expect(screen.getByText('fire_tv_fireos')).toBeTruthy();
    expect(screen.getByText('stb-testop')).toBeTruthy();
  });

  it('Clear empties the selection (the user can re-enable from the bolt)', () => {
    window.localStorage.setItem('vpt_quickfilter_config_v1', JSON.stringify(['models']));
    render(<QuickfilterBadgeArea {...baseProps} />);
    // models only: profile chips hidden, model chips visible.
    expect(screen.getByText('fire_tv_fireos')).toBeTruthy();
    fireEvent.click(screen.getByTestId('quickfilter-marker'));
    fireEvent.click(screen.getByText('Clear'));
    fireEvent.click(document.body);
    // After Clear, categories is [] — the bolt is still there but no chips.
    expect(screen.queryByText('fire_tv_fireos')).toBeNull();
    expect(screen.getByTestId('quickfilter-marker')).toBeTruthy();
  });

  it('the popover no longer carries the Click-to-toggle hint', () => {
    render(<QuickfilterBadgeArea {...baseProps} />);
    fireEvent.click(screen.getByTestId('quickfilter-marker'));
    expect(screen.queryByText(/Click to toggle/i)).toBeNull();
  });
});

describe('QuickfilterBadgeArea — store writes', () => {
  it('exposes the same callbacks the dropdowns use, so chips and dropdowns stay in sync', () => {
    const onProfileChange = vi.fn();
    const onModelChange = vi.fn();
    const onFlagChange = vi.fn();
    window.localStorage.setItem(
      'vpt_quickfilter_config_v1',
      JSON.stringify(['profiles', 'models', 'tags']),
    );
    render(
      <QuickfilterBadgeArea
        {...baseProps}
        onProfileFilterChange={onProfileChange}
        onDeviceModelFilterChange={onModelChange}
        onFlagFilterChange={onFlagChange}
      />,
    );
    fireEvent.click(screen.getByText('Car count'));
    fireEvent.click(screen.getByText('fire_tv_fireos'));
    fireEvent.click(screen.getByText('loud'));
    expect(onProfileChange).toHaveBeenCalledWith(['counting_cars']);
    expect(onModelChange).toHaveBeenCalledWith(['fire_tv_fireos']);
    expect(onFlagChange).toHaveBeenCalledWith(['loud']);
    const area = screen.getByTestId('quickfilter-badge-area');
    expect(within(area).getByText('Lite')).toBeTruthy();
  });
});