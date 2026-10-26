import { Box } from '@mui/material';
import React, { useEffect, useState } from 'react';

import { useLolLiveOverlay } from '../../../hooks/rec/useLolLiveOverlay';
import { Host } from '../../../types/common/Host_Types';
import { LolMarker } from '../../../types/game/LolOverlay_Types';
import { LolOverlay } from './LolOverlay';
import { LolSpellRow } from './LolSpellRow';

/** Live LoL overlay for the rec stream modal: polls the host, animates marker fade between polls. */
export const LolLiveOverlay: React.FC<{ host: Host }> = ({ host }) => {
  const { data, receivedAt } = useLolLiveOverlay(host, true);
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 100);
    return () => clearInterval(id);
  }, []);

  const sinceReceived = receivedAt ? (now - receivedAt) / 1000 : 0;
  const markers: LolMarker[] = (data?.recent_inputs ?? []).map((i) => ({ ...i, age: i.age_s + sinceReceived }));
  return (
    <>
      <LolOverlay zones={data?.zones ?? []} markers={markers} frame={data?.frame} units={data?.world?.units} message={data ? null : 'No live data from the LoL bot'} />
      {data?.state?.spells && (
        <Box sx={{ position: 'absolute', left: 8, bottom: 8, zIndex: 21, pointerEvents: 'none' }}>
          <LolSpellRow spells={data.state.spells} />
        </Box>
      )}
    </>
  );
};
