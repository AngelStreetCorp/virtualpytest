import importlib.util
from pathlib import Path
import pytest
spec = importlib.util.spec_from_file_location('parser', Path(__file__).resolve().parents[2] / 'backend_server/src/lib/utils/script_output_parser.py')
parser = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parser)
@pytest.mark.parametrize('value', ['https://reports.example.org/report.html', 'https://reports.example.org/report.html?signature=synthetic&expires=0', 'reports/team/run/report.html'])
def test_preserves_uploader_reference(value):
    line = '[@cloudflare_utils:upload_script_report] INFO: Uploaded script report: ' + value
    assert parser.extract_report_url_from_output(line) == value
    assert parser.parse_script_execution_output(line + '\nSCRIPT_SUCCESS:true')['report_url'] == value
@pytest.mark.parametrize('line', ['', 'unrelated output', '[@cloudflare_utils:upload_script_report] INFO: Uploaded script report: '])
def test_no_reference(line):
    assert parser.extract_report_url_from_output(line) is None
