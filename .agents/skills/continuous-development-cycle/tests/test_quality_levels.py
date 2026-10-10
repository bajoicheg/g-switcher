"""Risk floors prevent reduced validation for dangerous changes."""
from pathlib import Path
import copy, sys, unittest
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
try:
    import quality_levels as quality
except ModuleNotFoundError:
    quality = None
from validate_adapter import validate_adapter
from contracts import load_yaml, ContractError

def assessment(project='FAST', categories=None):
    return {'schema': 'quality-assessment/v1', 'project_level': project,
            'risk_level': 'FAST', 'risk_categories': categories or ['local_reversible'],
            'risk_reason': 'scoped observed change', 'mandatory_check_ids': ['windows-release']}

class QualityTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(quality, 'quality levels feature is not implemented')

    def test_risk_floors_and_project_floor(self):
        for project, category, expected in [('FAST','ordinary_feature','MEDIUM'),
                ('FAST','ad_write','FULL'), ('FULL','documentation','FULL'),
                ('FAST','local_reversible','FAST')]:
            with self.subTest(category=category):
                r=quality.evaluate(assessment(project,[category]))
                self.assertEqual(r['effective_level'],expected)
                self.assertEqual(r['mandatory_check_ids'],['windows-release'])
                self.assertFalse(r['authorizes_product_write'])

    def test_all_critical_categories_enforce_full(self):
        for c in ['cdc_core','executor_authority','authentication','ad_write','dangerous_migration']:
            self.assertEqual(quality.evaluate(assessment(categories=[c]))['effective_level'],'FULL')

    def test_unknown_risk_fails_closed(self):
        with self.assertRaises(ValueError): quality.evaluate(assessment(categories=['unknown']))

    def test_empty_or_duplicate_risk_categories_rejected(self):
        for categories in [[], ['ad_write','ad_write']]:
            d=assessment();d['risk_categories']=categories
            with self.assertRaises(ValueError): quality.evaluate(d)

    def test_escalation_requires_reason(self):
        d=assessment(categories=['ad_write']);d['risk_reason']=''
        with self.assertRaises(ValueError): quality.evaluate(d)

    def test_claimed_risk_can_raise_but_cannot_lower(self):
        d=assessment();d['risk_level']='FULL'
        self.assertEqual(quality.evaluate(d)['effective_level'],'FULL')

    def test_invalid_policy_rejected(self):
        for p in [{'default_level':'fast','max_validation_cycles':2},
                  {'default_level':'FAST','max_validation_cycles':True}]:
            with self.assertRaises(ValueError):quality.validate_policy(p)

    def test_adapter_accepts_quality_without_changing_legacy(self):
        d=load_yaml(ROOT/'templates/development-cycle.yaml');d.pop('quality',None)
        before=validate_adapter(d)
        self.assertNotIn('quality',d)
        d['quality']={'default_level':'MEDIUM','max_validation_cycles':2}
        self.assertNotEqual(validate_adapter(d)['policy_digest'],before['policy_digest'])
        d['quality']['default_level']='INVALID'
        with self.assertRaises(ContractError):validate_adapter(d)

if __name__=='__main__':unittest.main()
