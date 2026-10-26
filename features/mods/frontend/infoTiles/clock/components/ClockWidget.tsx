import React, { useEffect, useState } from 'react';

import { InfoTile } from '../../../../../../frontend/src/mods/core/components/widgets/InfoTile';
import { getIntlLocale } from '../../../../../../frontend/src/i18n';
import { useI18n } from '../../../../../../frontend/src/i18n/useI18n';
import type { WidgetProps } from '../../../../../../frontend/src/mods/core/types';
import { browserTimeZone, chosenZone, cityFromTimeZone, knownPlace } from '../../region/places';
import { PLACE } from '../constants';
import { formatClock } from '../format';

/** Time and date for the viewer's region, or a place chosen in the widget settings. */
export const ClockWidget: React.FC<WidgetProps> = ({ settings, $ }) => {
  const { t } = useI18n();
  const [now, setNow] = useState(() => $.clock.now());

  useEffect(() => {
    const id = window.setInterval(() => setNow($.clock.now()), 1000);
    return () => window.clearInterval(id);
  }, [$]);

  const zone = chosenZone(String(settings[PLACE] ?? ''), browserTimeZone());
  const face = formatClock(now, zone, settings.hour12 === true, getIntlLocale());
  const place = knownPlace(zone);

  return (
    <InfoTile
      primary={face.time}
      secondary={face.date}
      footer={place ? t(place.label) : cityFromTimeZone(zone)}
      monospace
    />
  );
};
