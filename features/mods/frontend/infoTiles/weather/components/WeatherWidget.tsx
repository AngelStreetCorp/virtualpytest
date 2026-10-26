import React, { useEffect, useState } from 'react';

import { InfoTile } from '../../../../../../frontend/src/mods/core/components/widgets/InfoTile';
import { useI18n } from '../../../../../../frontend/src/i18n/useI18n';
import type { WidgetProps } from '../../../../../../frontend/src/mods/core/types';
import { browserTimeZone, chosenZone } from '../../region/places';
import { PLACE, REFRESH_MS } from '../constants';
import type { TodayWeather } from '../forecast';
import { loadToday } from '../load';

/** Today's weather for the viewer's region, or a place chosen in the widget settings. */
export const WeatherWidget: React.FC<WidgetProps> = ({ settings }) => {
  const { t } = useI18n();
  const zone = chosenZone(String(settings[PLACE] ?? ''), browserTimeZone());
  const [weather, setWeather] = useState<TodayWeather | null>(null);
  const [state, setState] = useState<'loading' | 'ok' | 'error'>('loading');

  useEffect(() => {
    let cancelled = false;
    setState('loading');
    setWeather(null);
    const load = () => {
      loadToday(zone)
        .then((row) => {
          if (cancelled) return;
          setWeather(row);
          setState('ok');
        })
        .catch(() => {
          if (!cancelled) setState('error');
        });
    };
    load();
    const id = window.setInterval(load, REFRESH_MS);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [zone]);

  if (state === 'loading') return <InfoTile state="loading" />;
  if (state === 'error') return <InfoTile state="error" errorMessage={t('Weather is unavailable')} />;
  if (!weather) return null;

  return (
    <InfoTile
      primary={`${weather.temp}°`}
      secondary={t(weather.condition)}
      footer={
        <>
          {t('High {high}° · Low {low}°', { high: weather.high, low: weather.low })}
          <br />
          {weather.placeIsKey ? t(weather.place) : weather.place}
        </>
      }
    />
  );
};
