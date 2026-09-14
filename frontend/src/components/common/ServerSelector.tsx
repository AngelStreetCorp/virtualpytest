import React from 'react';
import { FormControl, InputLabel, Select, MenuItem, Chip, Box, CircularProgress } from '@mui/material';
import { useServerManager } from '../../hooks/useServerManager';

interface ServerSelectorProps {
  size?: 'small' | 'medium';
  minWidth?: number;
  label?: string;
  variant?: 'outlined' | 'standard' | 'filled';
}

export const ServerSelector: React.FC<ServerSelectorProps> = ({
  size = 'small',
  minWidth = 200,
  label = 'Server',
  variant = 'outlined'
}) => {
  const { selectedServer, setSelectedServer, availableServers, failedServers, serverHostsData, isServerChanging } = useServerManager();

  return (
    <FormControl size={size} sx={{ minWidth }} variant={variant}>
      <InputLabel>{isServerChanging ? 'Switching...' : label}</InputLabel>
      <Select
        value={selectedServer}
        label={isServerChanging ? 'Switching...' : label}
        onChange={(e) => setSelectedServer(e.target.value)}
        disabled={isServerChanging}
        startAdornment={isServerChanging ? (
          <CircularProgress size={16} sx={{ mr: 1, ml: -0.5 }} />
        ) : undefined}
        sx={{
          opacity: isServerChanging ? 0.7 : 1,
          '& .MuiSelect-select': {
            display: 'flex',
            alignItems: 'center',
          }
        }}
      >
        {availableServers.map((serverUrl) => {
          const isFailed = failedServers.has(serverUrl);
          const serverData = serverHostsData.find(s => s.server_info.server_url === serverUrl);
          const displayName = serverData?.server_info.server_name || serverUrl.replace(/^https?:\/\//, '');
          
          return (
            <MenuItem 
              key={serverUrl} 
              value={serverUrl}
              disabled={isFailed}
              sx={{
                color: isFailed ? '#d32f2f' : 'inherit',
                '&.Mui-disabled': {
                  opacity: 1,
                  color: '#d32f2f'
                }
              }}
            >
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, width: '100%' }}>
                {displayName}
                {isFailed && (
                  <Chip 
                    label="Offline" 
                    size="small" 
                    color="error" 
                    sx={{ height: 20, fontSize: '0.7rem' }}
                  />
                )}
              </Box>
            </MenuItem>
          );
        })}
      </Select>
    </FormControl>
  );
};
