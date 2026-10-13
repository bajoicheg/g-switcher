import json,sys,tempfile,unittest,shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
import validate_package

class QualityPackage(unittest.TestCase):
    def test_new_templates_execute_through_real_validators(self):
        self.assertTrue(hasattr(validate_package,'validate_quality_templates'),'new templates not integrated into package validator')
        validate_package.validate_quality_templates(ROOT)
    def test_corrupt_positive_review_producer_rejected(self):
        self.assertTrue(hasattr(validate_package,'validate_quality_templates'),'new templates not integrated into package validator')
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);shutil.copytree(ROOT/'templates',p/'templates')
            f=p/'templates/review-pipeline-v2.json';data=json.loads(f.read_text())
            data['combined_review']['covers']=['quality'];f.write_text(json.dumps(data))
            with self.assertRaises(ValueError):validate_package.validate_quality_templates(p)

if __name__=='__main__':unittest.main()
