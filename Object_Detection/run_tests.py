"""
Runs all functional tests for the Object_Detection package.
"""

import sys
import unittest
from pathlib import Path

# Add project root to sys.path so Object_Detection can be imported cleanly
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

if __name__ == "__main__":
    print("=" * 60)
    print("  Object_Detection Fonksiyonel Test Paketi Çalıştırılıyor")
    print("=" * 60)

    loader = unittest.TestLoader()
    suite = loader.discover(
        start_dir=str(Path(__file__).parent / "tests"),
        pattern="test_*.py"
    )

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    print("=" * 60)
    if result.wasSuccessful():
        print(f"✅ TÜM TESTLER BAŞARIYLA GEÇTİ! (Toplam: {result.testsRun} test)")
        sys.exit(0)
    else:
        print(f"❌ TESTLERDE HATA OLUŞTU! (Hatalar: {len(result.errors)}, Başarısızlıklar: {len(result.failures)})")
        sys.exit(1)
