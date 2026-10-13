/**
 * Export button: CSV, print/PDF and PNG chart from the payload the caller already holds.
 * The caller builds the export once (`buildExport`) so every format shows the same data.
 */

import { FileDownload as ExportIcon } from '@mui/icons-material';
import { Button, ListItemText, Menu, MenuItem } from '@mui/material';
import React, { useState } from 'react';

import { useToast } from '../../hooks/useToast';
import {
  downloadChartPng,
  downloadCsv,
  fileStem,
  findChartSvg,
  openPrintView,
  svgElementToPngDataUrl,
  type CsvCell,
  type PrintDocument,
} from './exporters';

export interface ExportPayload {
  title: string;
  summary: Array<[string, CsvCell]>;
  headers: string[];
  rows: CsvCell[][];
}

export interface ExportMenuProps {
  buildExport: () => ExportPayload;
  /** `data-export-chart` id of the chart to export as PNG; omit when the view has none. */
  chartExportId?: string;
  disabled?: boolean;
}

export const ExportMenu: React.FC<ExportMenuProps> = ({ buildExport, chartExportId, disabled }) => {
  const [anchor, setAnchor] = useState<HTMLElement | null>(null);
  const { showError, showWarning } = useToast();

  const close = () => setAnchor(null);

  const exportCsv = () => {
    close();
    const payload = buildExport();
    downloadCsv(`${fileStem(payload.title)}.csv`, payload.headers, payload.rows);
  };

  const exportPrint = async () => {
    close();
    const payload = buildExport();
    let chartDataUrl: string | null = null;
    const svg = chartExportId ? findChartSvg(document, chartExportId) : null;
    if (svg) {
      try {
        chartDataUrl = await svgElementToPngDataUrl(svg);
      } catch {
        chartDataUrl = null;
      }
    }
    const doc: PrintDocument = {
      title: payload.title,
      summary: payload.summary,
      sections: [{ heading: 'Rows', headers: payload.headers, rows: payload.rows }],
      chartDataUrl,
    };
    if (!openPrintView(doc)) showWarning('Allow pop-ups for this site to print or save as PDF.');
  };

  const exportPng = async () => {
    close();
    if (!chartExportId) return;
    try {
      const ok = await downloadChartPng(chartExportId, `${fileStem(buildExport().title)}.png`);
      if (!ok) showWarning('No chart is displayed to export.');
    } catch (error) {
      showError(error instanceof Error ? error.message : 'PNG export failed');
    }
  };

  return (
    <>
      <Button
        size="small"
        variant="outlined"
        startIcon={<ExportIcon fontSize="small" />}
        onClick={(event) => setAnchor(event.currentTarget)}
        disabled={disabled}
      >
        Export
      </Button>
      <Menu anchorEl={anchor} open={Boolean(anchor)} onClose={close}>
        <MenuItem onClick={exportCsv}>
          <ListItemText primary="CSV" />
        </MenuItem>
        <MenuItem onClick={() => void exportPrint()}>
          <ListItemText primary="Print / PDF" />
        </MenuItem>
        {chartExportId && (
          <MenuItem onClick={() => void exportPng()}>
            <ListItemText primary="Chart as PNG" />
          </MenuItem>
        )}
      </Menu>
    </>
  );
};
