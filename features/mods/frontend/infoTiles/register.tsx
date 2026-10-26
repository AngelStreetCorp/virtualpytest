/**
 * Info Tiles mod (TASK-77): a Dashboard palette of small "info" widgets that share
 * the `InfoTile` body (frontend/src/mods/core/components/widgets/InfoTile.tsx).
 * One mod ships the whole palette so the user turns on/off a single switch and
 * picks the tiles they want from "+ Add widget". New tiles (calendar, stocks,
 * news, train times, …) belong here too — drop them under `infoTiles/<name>/`
 * with their own register, then list them under `widgets:` below.
 */
import type { ModDefinition } from '../../../../frontend/src/mods/core/types';

import { ClockWidget } from './clock/components/ClockWidget';
import { HOUR12 as CLOCK_HOUR12, PLACE as CLOCK_PLACE, WIDGET_ID as CLOCK_WIDGET_ID } from './clock/constants';
import { BROWSER, PLACE_OPTIONS } from './region/places';
import { WeatherWidget } from './weather/components/WeatherWidget';
import { PLACE as WEATHER_PLACE, WIDGET_ID as WEATHER_WIDGET_ID } from './weather/constants';

export const infoTilesMod: ModDefinition = {
  id: 'info-tiles',
  name: 'Info tiles',
  description: 'Small Dashboard widgets: clock, weather, and more.',
  defaultEnabled: true,
  // No events: the tiles are self-contained fetches (clock ticks locally, weather
  // reads Open-Meteo from the browser). If a future tile wants events (e.g. a
  // "what's running" tile), hook them here.
  register: () => undefined,
  widgets: [
    {
      id: CLOCK_WIDGET_ID,
      name: 'Clock',
      description: 'The time where you are.',
      size: 'small',
      settings: [
        { key: CLOCK_PLACE, label: 'Place', type: 'select', default: BROWSER, options: PLACE_OPTIONS },
        { key: CLOCK_HOUR12, label: '12-hour clock', type: 'boolean', default: false },
      ],
      Component: ClockWidget,
    },
    {
      id: WEATHER_WIDGET_ID,
      name: 'Weather',
      description: "Today's weather where you are.",
      size: 'small',
      settings: [
        { key: WEATHER_PLACE, label: 'Place', type: 'select', default: BROWSER, options: PLACE_OPTIONS },
      ],
      Component: WeatherWidget,
    },
  ],
};
