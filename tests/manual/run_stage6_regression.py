"""Isolated regression runner; does not read Secrets or connect to Turso."""
import json
import logging
import os
from pathlib import Path
import sys
import tempfile
import unittest
from datetime import datetime
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import app_database

output = ROOT / '.tmp_stage6' / ('mock_boundary_' + datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
output.mkdir(parents=True, exist_ok=True)
logging.disable(logging.CRITICAL)
pattern = sys.argv[1] if len(sys.argv)>1 else 'test_*.py'
name = 'full' if pattern=='test_*.py' else Path(pattern).stem.replace('*', 'all').replace('?', '_')
with tempfile.TemporaryDirectory(prefix='stage6-regression-') as workspace:
    with patch.dict(os.environ, {'EBAY_TOOL_WORKSPACE': workspace, 'EBAY_LISTING_DB_PATH': '',
        'TURSO_DATABASE_URL': '', 'TURSO_AUTH_TOKEN': '', 'EBAY_EXECUTION_MODE':'mock'}), \
            patch.object(app_database, '_secret_value', return_value=''):
        suite = unittest.defaultTestLoader.discover(str(ROOT / 'tests'), pattern=pattern)
        with (output / (name+'.log')).open('w', encoding='utf-8') as log:
            result = unittest.TextTestRunner(stream=log, verbosity=2).run(suite)
report = dict(tests=result.testsRun, failures=len(result.failures), errors=len(result.errors), skipped=len(result.skipped))
(output / (name+'.json')).write_text(json.dumps(report, indent=2), encoding='utf-8')
print(json.dumps(report))
print(str(output))
sys.exit(not result.wasSuccessful())
