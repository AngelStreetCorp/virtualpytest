import { useEffect } from 'react';

const GrafanaRedirect: React.FC = () => {
  useEffect(() => {
    const grafanaUrl = (import.meta as any).env?.VITE_GRAFANA_URL || 'http://localhost/grafana';
    const path = window.location.pathname.replace(/^\/grafana/, '');
    window.location.href = grafanaUrl + path + window.location.search + window.location.hash;
  }, []);

  return null;
};

export default GrafanaRedirect;

