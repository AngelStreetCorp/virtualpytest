import { ExpandMore, ExpandLess } from '@mui/icons-material';
import {
  Box,
  Typography,
  Card,
  CardContent,
  Chip,
  Collapse,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Paper,
  Link,
  Tooltip,
} from '@mui/material';
import React from 'react';
import { useHref } from 'react-router-dom';

import { buildIncidentFocusUrl, IncidentFocusType } from '../../utils/incidentFocus';

interface DeviceData {
  host_name: string;
  device_id: string;
  device_name?: string;
  image_url: string;
  analysis_json: {
    audio?: boolean;
    blackscreen?: boolean;
    freeze?: boolean;
    volume_percentage?: number;
    mean_volume_db?: number;
    freeze_diffs?: number[];
    last_3_filenames?: string[];
  };
}

interface HeatMapAnalysisSectionProps {
  images: DeviceData[];
  analysisExpanded: boolean;
  onToggleExpanded: () => void;
  /** ISO timestamp of the frame being shown. When set, incident cells (Audio No,
   *  Blackscreen Yes, Freeze Yes) link to the Alerts page focused on the matching
   *  incident for that host/device/type at that time. */
  frameTimestamp?: string;
}

export const HeatMapAnalysisSection: React.FC<HeatMapAnalysisSectionProps> = ({
  images,
  analysisExpanded,
  onToggleExpanded,
  frameTimestamp,
}) => {
  // Router basename (e.g. /pi4 behind the proxy) so the new-tab href lands in this app.
  const routerBase = useHref('/').replace(/\/$/, '');

  /** Wrap an incident cell's content in a new-tab link to the focused Alerts page. */
  const incidentLink = (image: DeviceData, type: IncidentFocusType, content: React.ReactNode) => {
    if (!frameTimestamp) return content;
    const href =
      routerBase +
      buildIncidentFocusUrl({
        host: image.host_name,
        device: image.device_id,
        type,
        at: frameTimestamp,
      });
    return (
      <Tooltip title="Open incident in Alerts">
        <Link
          href={href}
          target="_blank"
          rel="noopener"
          underline="hover"
          color="inherit"
          sx={{ cursor: 'pointer', display: 'inline-flex', alignItems: 'center' }}
        >
          {content}
        </Link>
      </Tooltip>
    );
  };

  // Calculate summary from images - only count devices with actual analysis data
  const devicesWithAnalysis = images.filter((image) => image.analysis_json && typeof image.analysis_json === 'object');
  const totalDevices = devicesWithAnalysis.length;
  const devicesWithIncidents = devicesWithAnalysis.filter((image) => {
    const analysisJson = image.analysis_json || {};
    // audio === false is a real loss; undefined/null = no audio capability (N/A) → not an incident
    return analysisJson.blackscreen || analysisJson.freeze || analysisJson.audio === false;
  }).length;

  const summary =
    totalDevices > 0
      ? `${totalDevices} devices | ${devicesWithIncidents} with incidents`
      : 'No analysis data available';

  // Show a message when no analysis data is available
  if (totalDevices === 0) {
    return (
      <Card sx={{ backgroundColor: 'transparent', boxShadow: 'none' }}>
        <CardContent sx={{ py: 1 }}>
          <Box display="flex" alignItems="center" justifyContent="space-between">
            <Box display="flex" alignItems="center" gap={1}>
              <Typography variant="subtitle2" color="text.secondary">
                Device Analysis
              </Typography>
              <Typography variant="caption" color="text.secondary">
                ({images.length} devices found, no analysis data available)
              </Typography>
            </Box>
          </Box>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card sx={{ backgroundColor: 'transparent', boxShadow: 'none' }}>
      <CardContent>
        <Box
          display="flex"
          alignItems="center"
          justifyContent="space-between"
          onClick={onToggleExpanded}
          sx={{ cursor: 'pointer' }}
        >
          <Typography variant="h6">Data Analysis</Typography>
          <Box display="flex" alignItems="center" gap={1}>
            <Typography variant="body2" color="textSecondary">
              {summary}
            </Typography>
            {analysisExpanded ? <ExpandLess /> : <ExpandMore />}
          </Box>
        </Box>

        <Collapse in={analysisExpanded}>
          <Box mt={2}>
            {images.length > 0 ? (
              <TableContainer
                component={Paper}
                variant="outlined"
                sx={{
                  backgroundColor: 'transparent',
                  '& .MuiPaper-root': {
                    backgroundColor: 'transparent !important',
                    boxShadow: 'none',
                  },
                }}
              >
                <Table
                  size="small"
                  sx={{
                    backgroundColor: 'transparent',
                    '& .MuiTableRow-root': {
                      backgroundColor: 'transparent !important',
                    },
                    '& .MuiTableRow-root:hover': {
                      backgroundColor: 'transparent !important',
                    },
                    '& .MuiTableCell-root': {
                      backgroundColor: 'transparent !important',
                    },
                  }}
                >
                  <TableHead>
                    <TableRow sx={{ backgroundColor: 'transparent !important' }}>
                      <TableCell>
                        <strong>Device</strong>
                      </TableCell>
                      <TableCell>
                        <strong>Audio</strong>
                      </TableCell>
                      <TableCell>
                        <strong>Video</strong>
                      </TableCell>
                      <TableCell>
                        <strong>Volume %</strong>
                      </TableCell>
                      <TableCell>
                        <strong>Mean dB</strong>
                      </TableCell>
                      <TableCell>
                        <strong>Blackscreen</strong>
                      </TableCell>
                      <TableCell>
                        <strong>Freeze</strong>
                      </TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {images
                      .filter((image) => image.analysis_json && typeof image.analysis_json === 'object') // Only show devices with actual analysis data
                      .map((image, index) => {
                        const analysisJson = image.analysis_json || {};
                        const hasVideo = !analysisJson.blackscreen && !analysisJson.freeze;
                        // Three-state audio: true=Yes, false=No (loss), undefined/null=N/A (no audio capability)
                        const audioState =
                          analysisJson.audio === true
                            ? 'yes'
                            : analysisJson.audio === false
                              ? 'no'
                              : 'na';
                        const cleanName = (image.device_name || image.device_id || '').replace(/_Host$/, '');
                        const deviceLabel =
                          cleanName && cleanName !== image.host_name
                            ? `${image.host_name}-${cleanName}`
                            : image.host_name;

                        return (
                          <TableRow
                            key={index}
                            sx={{
                              backgroundColor: 'transparent !important',
                              '&:hover': {
                                backgroundColor: 'transparent !important',
                              },
                            }}
                          >
                            <TableCell>
                              {deviceLabel}
                            </TableCell>
                            <TableCell>
                              {(() => {
                                const chip = (
                                  <Chip
                                    label={audioState === 'yes' ? 'Yes' : audioState === 'no' ? 'No' : 'N/A'}
                                    color={audioState === 'yes' ? 'success' : audioState === 'no' ? 'error' : 'default'}
                                    size="small"
                                    sx={audioState === 'no' ? { cursor: 'pointer' } : undefined}
                                  />
                                );
                                return audioState === 'no' ? incidentLink(image, 'no_audio', chip) : chip;
                              })()}
                            </TableCell>
                            <TableCell>
                              <Chip
                                label={hasVideo ? 'Yes' : 'No'}
                                color={hasVideo ? 'success' : 'error'}
                                size="small"
                              />
                            </TableCell>
                            <TableCell>
                              <Typography variant="caption">
                                {analysisJson.volume_percentage != null
                                  ? `${analysisJson.volume_percentage}%`
                                  : 'N/A'}
                              </Typography>
                            </TableCell>
                            <TableCell>
                              <Typography variant="caption">
                                {analysisJson.mean_volume_db != null
                                  ? `${analysisJson.mean_volume_db} dB`
                                  : 'N/A'}
                              </Typography>
                            </TableCell>
                            <TableCell>
                              {(() => {
                                const text = (
                                  <Typography
                                    variant="caption"
                                    color={analysisJson.blackscreen ? 'error' : 'success'}
                                  >
                                    {analysisJson.blackscreen ? 'Yes' : 'No'}
                                  </Typography>
                                );
                                return analysisJson.blackscreen ? incidentLink(image, 'blackscreen', text) : text;
                              })()}
                            </TableCell>
                            <TableCell>
                              {(() => {
                                const text = (
                                  <Typography
                                    variant="caption"
                                    color={analysisJson.freeze ? 'error' : 'success'}
                                  >
                                    {analysisJson.freeze
                                      ? `Yes (${(analysisJson.freeze_diffs || []).length} diffs)`
                                      : 'No'}
                                  </Typography>
                                );
                                return analysisJson.freeze ? incidentLink(image, 'freeze', text) : text;
                              })()}
                            </TableCell>
                          </TableRow>
                        );
                      })}
                  </TableBody>
                </Table>
              </TableContainer>
            ) : (
              <Typography variant="body2" color="textSecondary">
                No analysis data available for current frame
              </Typography>
            )}
          </Box>
        </Collapse>
      </CardContent>
    </Card>
  );
};
