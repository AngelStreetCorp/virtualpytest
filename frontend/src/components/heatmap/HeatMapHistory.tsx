import { OpenInNew, Refresh } from '@mui/icons-material';
import {
  Typography,
  Card,
  CardContent,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Paper,
  IconButton,
  Chip,
  Box,
  Button,
} from '@mui/material';
import { useState, useEffect, useImperativeHandle, forwardRef } from 'react';

import { buildServerUrl } from '../../utils/buildUrlUtils';
import { api } from '../../utils/apiClient';
import { openR2Url } from '../../utils/infrastructure/cloudflareUtils';

interface HeatmapReport {
  id: string;
  timestamp: string;
  html_r2_url: string;
  mosaic_r2_url: string;
  hosts_included: number;
  hosts_total: number;
  incidents_count: number;
  generated_at: string;
}

interface HeatMapHistoryProps {
  // We can add props later if needed to filter by team, etc.
}

export interface HeatMapHistoryRef {
  refreshReports: () => Promise<void>;
}

export const HeatMapHistory = forwardRef<HeatMapHistoryRef, HeatMapHistoryProps>((_props, ref) => {
  const [reports, setReports] = useState<HeatmapReport[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Fetch last 10 heatmap reports
  const fetchReports = async () => {
    try {
      setLoading(true);
      setError(null);

      const data = await api.get<{
        success?: boolean;
        reports?: HeatmapReport[];
        error?: string;
      }>(
        buildServerUrl('/server/heatmap/history?limit=10')
      );
      console.log('[@component:HeatMapHistory] Fetched reports:', data.reports?.length || 0);
      setReports(data.reports || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch reports');
      console.error('[@component:HeatMapHistory] Error fetching reports:', err);
    } finally {
      setLoading(false);
    }
  };

  // Open R2 URL with automatic signed URL generation (handles both public and private modes)
  const handleOpenR2Url = async (url: string) => {
    try {
      await openR2Url(url);
    } catch (error) {
      console.error('[@HeatMapHistory] Failed to open R2 URL:', error);
      setError('Failed to open file. Please try again.');
    }
  };

  // Expose refresh function to parent components
  useImperativeHandle(ref, () => ({
    refreshReports: fetchReports,
  }));

  // Load reports on component mount
  useEffect(() => {
    fetchReports();
  }, []);

  // Auto-refresh when component becomes visible (page focus)
  useEffect(() => {
    const handleVisibilityChange = () => {
      if (!document.hidden) {
        fetchReports();
      }
    };

    document.addEventListener('visibilitychange', handleVisibilityChange);
    return () => document.removeEventListener('visibilitychange', handleVisibilityChange);
  }, []);

  // Format timestamp for display
  const formatTimestamp = (timestamp: string): string => {
    try {
      // Handle both ISO format and YYYYMMDDHHMMSS format
      let date: Date;

      if (timestamp.includes('T') || timestamp.includes('-')) {
        // ISO format
        date = new Date(timestamp);
      } else if (timestamp.length === 14) {
        // YYYYMMDDHHMMSS format
        const year = timestamp.substring(0, 4);
        const month = timestamp.substring(4, 6);
        const day = timestamp.substring(6, 8);
        const hour = timestamp.substring(8, 10);
        const minute = timestamp.substring(10, 12);
        const second = timestamp.substring(12, 14);
        date = new Date(`${year}-${month}-${day}T${hour}:${minute}:${second}`);
      } else {
        return timestamp; // Return as-is if unknown format
      }

      return date.toLocaleString();
    } catch {
      return timestamp; // Return as-is if parsing fails
    }
  };

  // Generate report name from timestamp
  const generateReportName = (timestamp: string): string => {
    const formatted = formatTimestamp(timestamp);
    return `Heatmap Report - ${formatted}`;
  };

  if (loading) {
    return (
      <Card sx={{ backgroundColor: 'transparent', boxShadow: 'none' }}>
        <CardContent>
          <Typography variant="body2" color="textSecondary" sx={{ mt: 1 }}>
            Loading reports...
          </Typography>
        </CardContent>
      </Card>
    );
  }

  if (error) {
    return (
      <Card sx={{ backgroundColor: 'transparent', boxShadow: 'none' }}>
        <CardContent>
          <Typography variant="body2" color="error" sx={{ mt: 1 }}>
            {error}
          </Typography>
        </CardContent>
      </Card>
    );
  }

  if (reports.length === 0) {
    return (
      <Card sx={{ backgroundColor: 'transparent', boxShadow: 'none' }}>
        <CardContent>
          <Typography variant="body2" color="textSecondary" sx={{ mt: 1 }}>
            No heatmap reports found. Run your first test to see results here.
          </Typography>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card sx={{ backgroundColor: 'transparent', boxShadow: 'none' }}>
      <CardContent>
        <Box display="flex" justifyContent="space-between" alignItems="center" mb={2}>
          <Typography variant="h6" sx={{ mb: 1, my: 0 }}>
            Heatmap History
          </Typography>
          <Button
            startIcon={<Refresh />}
            onClick={fetchReports}
            disabled={loading}
            size="small"
            variant="outlined"
          >
            Refresh
          </Button>
        </Box>

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
                backgroundColor: 'rgba(0, 0, 0, 0.04) !important',
              },
              '& .MuiTableCell-root': {
                backgroundColor: 'transparent !important',
              },
            }}
          >
            <TableHead>
              <TableRow sx={{ backgroundColor: 'transparent !important' }}>
                <TableCell>
                  <strong>Timestamp</strong>
                </TableCell>
                <TableCell>
                  <strong>Report Name</strong>
                </TableCell>
                <TableCell>
                  <strong>Devices</strong>
                </TableCell>
                <TableCell>
                  <strong>Incidents</strong>
                </TableCell>
                <TableCell align="center">
                  <strong>Link</strong>
                </TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {reports.map((report) => (
                <TableRow
                  key={report.id}
                  sx={{
                    backgroundColor: 'transparent !important',
                    '&:hover': {
                      backgroundColor: 'rgba(0, 0, 0, 0.04) !important',
                    },
                  }}
                >
                  <TableCell>
                    <Typography variant="caption">{formatTimestamp(report.timestamp)}</Typography>
                  </TableCell>
                  <TableCell>
                    <Typography variant="body2">{generateReportName(report.timestamp)}</Typography>
                  </TableCell>
                  <TableCell>
                    <Chip
                      label={report.hosts_included || 0}
                      size="small"
                      color="primary"
                      variant="outlined"
                    />
                  </TableCell>
                  <TableCell>
                    <Chip
                      label={report.incidents_count || 0}
                      size="small"
                      color={report.incidents_count > 0 ? 'error' : 'success'}
                      variant="outlined"
                    />
                  </TableCell>
                  <TableCell align="center">
                    <IconButton
                      size="small"
                      onClick={() => handleOpenR2Url(report.html_r2_url)}
                      disabled={!report.html_r2_url}
                    >
                      <OpenInNew fontSize="small" />
                    </IconButton>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      </CardContent>
    </Card>
  );
});
