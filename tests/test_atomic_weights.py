"""Physical constants checked against CIAAW's 2024 abridged table."""
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('atomic_weights_under_test', ROOT / 'ebl_stack_designer.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

class AtomicWeightsTests(unittest.TestCase):
    def test_previously_missing_common_elements_use_published_masses(self):
        for symbol, z, mass in [('Ag',47,107.87),('Cd',48,112.41),('Bi',83,208.98),('Li',3,6.94)]:
            with self.subTest(symbol=symbol):
                self.assertAlmostEqual(m._estimate_atomic_weight(symbol,z), mass)
                props = m._material_mc_properties({'density_g_cm3':1.0, 'elements':[
                    {'symbol':symbol,'Z':z,'weight_fraction':1.0}]})
                self.assertAlmostEqual(props['a_eff'],mass)

    def test_silver_chloride_recovers_equal_atomic_amounts(self):
        material = {'elements':[
            {'symbol':'Ag','Z':47,'weight_fraction':107.87/143.32},
            {'symbol':'Cl','Z':17,'weight_fraction':35.45/143.32}]}
        elements=m._canonical_material_elements(material)
        self.assertAlmostEqual(elements[0]['atomic_fraction'],0.5,places=12)
        self.assertAlmostEqual(elements[1]['atomic_fraction'],0.5,places=12)

    def test_element_without_standard_atomic_weight_is_not_invented(self):
        with self.assertRaisesRegex(ValueError,'isotope-specific'):
            m._material_mc_properties({'density_g_cm3':11.,'elements':[
                {'symbol':'Tc','Z':43,'weight_fraction':1.0}]})

if __name__=='__main__': unittest.main()
