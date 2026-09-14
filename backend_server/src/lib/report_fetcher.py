"""
Report Fetcher Utility

Standalone function to fetch and parse execution reports.
Used by agent manager to pre-fetch reports before LLM analysis.
"""

import requests
from typing import Dict, Any
from bs4 import BeautifulSoup
from shared.src.lib.utils.cloudflare_utils import fetch_text_from_storage


def _looks_like_storage_reference(source: str) -> bool:
    if not source:
        return False
    lowered = source.lower()
    return (
        'r2.dev' in lowered or
        'r2.cloudflarestorage.com' in lowered or
        '/minio/' in lowered or
        lowered.startswith('script-logs/') or
        lowered.startswith('script-reports/') or
        lowered.startswith('navigation/') or
        lowered.startswith('reference-images/')
    )


def _fetch_text_content(source: str, timeout: int = 30) -> Dict[str, Any]:
    """
    Fetch text via shared storage helper first.
    Falls back to direct HTTP GET for non-storage sources.
    """
    if not source:
        return {'success': False, 'error': 'No source provided'}

    storage_result = fetch_text_from_storage(source)
    if storage_result.get('success'):
        return {
            'success': True,
            'text': storage_result.get('text') or '',
            'mode': 'storage_helper',
            'remote_path': storage_result.get('remote_path')
        }

    # For storage references, enforce helper-only retrieval to keep one flow.
    if _looks_like_storage_reference(source):
        return {
            'success': False,
            'error': storage_result.get('error', 'Storage helper fetch failed'),
            'remote_path': storage_result.get('remote_path')
        }

    if source.startswith('http://') or source.startswith('https://'):
        try:
            response = requests.get(source, timeout=timeout)
            response.raise_for_status()
            return {'success': True, 'text': response.text or '', 'mode': 'http_fallback'}
        except Exception as e:
            return {
                'success': False,
                'error': f"{storage_result.get('error')} | http fallback failed: {e}",
                'remote_path': storage_result.get('remote_path')
            }

    return {
        'success': False,
        'error': storage_result.get('error', 'Failed to fetch source'),
        'remote_path': storage_result.get('remote_path')
    }


def fetch_execution_report(report_url: str, logs_url: str = None) -> Dict[str, Any]:
    """
    Fetch and parse execution report and logs from URLs.
    
    Args:
        report_url: URL to HTML report
        logs_url: URL to logs file (optional)
    
    Returns:
        Dict with parsed report and logs content
    """
    result = {
        'report': None,
        'logs': None,
        'summary': ''
    }
    
    # Fetch and parse report
    try:
        print(f"[@report_fetcher] Fetching report: {report_url[:60]}...")
        fetch_result = _fetch_text_content(report_url, timeout=30)
        if not fetch_result.get('success'):
            raise RuntimeError(fetch_result.get('error', 'Failed to fetch report'))

        soup = BeautifulSoup(fetch_result.get('text') or '', 'html.parser')
        
        parsed = {
            'steps': [],
            'errors': [],
            'raw_text': ''
        }
        
        # Extract steps
        for step in soup.select('.step, .test-step, [class*="step"]'):
            step_data = _extract_step(step)
            if step_data:
                parsed['steps'].append(step_data)
        
        # Fallback: table rows
        if not parsed['steps']:
            for row in soup.select('tr'):
                step_data = _extract_step_from_row(row)
                if step_data:
                    parsed['steps'].append(step_data)
        
        # Extract errors
        for error in soup.select('.error, .failure, .exception, [class*="error"]'):
            error_text = error.get_text(strip=True)
            if error_text:
                parsed['errors'].append(error_text[:500])
        
        # Get raw text
        body = soup.find('body')
        if body:
            parsed['raw_text'] = body.get_text(separator='\n', strip=True)[:8000]
        
        result['report'] = parsed
        
    except requests.exceptions.RequestException as e:
        print(f"[@report_fetcher] Error parsing report: {e}")
        result['report'] = {'error': str(e)}
    except Exception as e:
        print(f"[@report_fetcher] Error parsing report: {e}")
        result['report'] = {'error': str(e)}
    
    # Fetch logs if URL provided
    if logs_url:
        try:
            print(f"[@report_fetcher] Fetching logs: {logs_url[:60]}...")
            fetch_result = _fetch_text_content(logs_url, timeout=30)
            if not fetch_result.get('success'):
                raise RuntimeError(fetch_result.get('error', 'Failed to fetch logs'))

            content = fetch_result.get('text') or ''
            original_size = len(content)
            truncated = False
            
            if original_size > 5000:
                content = content[:5000]
                truncated = True
            
            result['logs'] = {
                'content': content,
                'truncated': truncated,
                'original_size': original_size
            }
            
        except requests.exceptions.RequestException as e:
            print(f"[@report_fetcher] Error fetching logs: {e}")
            result['logs'] = {'error': str(e)}
        except Exception as e:
            print(f"[@report_fetcher] Error fetching logs: {e}")
            result['logs'] = {'error': str(e)}
    
    # Build summary
    result['summary'] = _build_summary(result)
    
    return result


def _extract_step(element) -> Dict[str, Any]:
    """Extract step info from HTML element"""
    try:
        name = element.select_one('.step-name, .name, [class*="name"]')
        status = element.select_one('.status, .result, [class*="status"]')
        error = element.select_one('.error, .exception, [class*="error"]')
        
        step_data = {
            'name': name.get_text(strip=True)[:200] if name else 'Unknown',
            'status': 'unknown',
            'error': None
        }
        
        if status:
            status_text = status.get_text(strip=True).lower()
            if 'pass' in status_text or '✓' in status_text or '✅' in status_text:
                step_data['status'] = 'passed'
            elif 'fail' in status_text or '✗' in status_text or '❌' in status_text:
                step_data['status'] = 'failed'
        
        if error:
            step_data['error'] = error.get_text(strip=True)[:500]
        
        return step_data if step_data['name'] != 'Unknown' else None
        
    except Exception:
        return None


def _extract_step_from_row(row) -> Dict[str, Any]:
    """Extract step info from table row"""
    try:
        cells = row.find_all(['td', 'th'])
        if len(cells) < 2:
            return None
        
        text = ' '.join(c.get_text(strip=True) for c in cells)
        if not text.strip():
            return None
        
        status = 'unknown'
        if 'pass' in text.lower() or '✓' in text or '✅' in text:
            status = 'passed'
        elif 'fail' in text.lower() or '✗' in text or '❌' in text:
            status = 'failed'
        
        return {
            'name': cells[0].get_text(strip=True)[:200],
            'status': status,
            'error': None
        }
    except Exception:
        return None


def _build_summary(result: Dict[str, Any]) -> str:
    """Build summary text for agent"""
    lines = []
    
    # Report
    report = result.get('report')
    if report and not report.get('error'):
        lines.append("═══ REPORT ANALYSIS ═══")
        
        steps = report.get('steps', [])
        if steps:
            passed = sum(1 for s in steps if s['status'] == 'passed')
            failed = sum(1 for s in steps if s['status'] == 'failed')
            lines.append(f"Steps: {len(steps)} total, {passed} passed, {failed} failed")
        
        errors = report.get('errors', [])
        if errors:
            lines.append(f"\nErrors ({len(errors)}):")
            for err in errors[:5]:
                lines.append(f"  - {err[:200]}")
        
        raw_text = report.get('raw_text', '')
        if raw_text:
            lines.append("\n═══ REPORT CONTENT ═══")
            lines.append(raw_text[:5000])
    elif report and report.get('error'):
        lines.append(f"Report error: {report['error']}")
    
    # Logs
    logs = result.get('logs')
    if logs and not logs.get('error'):
        lines.append("\n═══ LOGS ═══")
        if logs.get('truncated'):
            lines.append(f"(Truncated from {logs['original_size']} bytes)")
        lines.append(logs.get('content', '')[:3000])
    elif logs and logs.get('error'):
        lines.append(f"\nLogs error: {logs['error']}")
    
    return '\n'.join(lines)
