import os
import tempfile

os.environ.setdefault("ZERO_HOME", tempfile.mkdtemp(prefix="zero_test_"))
