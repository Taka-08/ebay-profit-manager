"""Isolated regression runner. Never reads Secrets or connects to Turso."""
import json
import logging
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import app_database

output = ROOT / '.tmp_stage5'
output.mkdir(exist_ok=True)
logging.disable(logging.CRITICAL)
with tempfile.TemporaryDirectory(prefix='stage5-regression-') as workspace:
    with patch.dict(os.environ, {'EBAY_TOOL_WORKSPACE': workspace, 'EBAY_LISTING_DB_PATH': '',
                                 'TURSO_DATABASE_URL': '', 'TURSO_AUTH_TOKEN': ''}), \
            patch.object(app_database, '_secret_value', return_value=''):
        suite = unittest.defaultTestLoader.discover(str(ROOT / 'tests'), pattern=sys.argv[1] if len(sys.argv) > 1 else 'test_*.py')
        with (output / 'regression.log').open('w', encoding='utf-8') as log:
            result = unittest.TextTestRunner(stream=log, verbosity=2).run(suite)
report = dict(tests=result.testsRun, failures=len(result.failures), errors=len(result.errors), skipped=len(result.skipped))
(output / 'regression.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
print(json.dumps(report))
sys.exit(not result.wasSuccessful())
