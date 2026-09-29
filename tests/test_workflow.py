"""Run the complete calculation and persistence path without opening Tk windows."""
import copy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('ebl_workflow_under_test',ROOT/'ebl_stack_designer.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class Var:
    def __init__(self,value=''): self.value=value
    def get(self): return self.value
    def set(self,value): self.value=value

class WorkflowTests(unittest.TestCase):
    def test_simulation_fit_snapshot_json_and_exports(self):
        library=m.preset_material_library()
        names=['ma-N 2400 (approx.)','Silicon Nitride (Si3N4)','InP']
        materials=[next(x for x in library if x['name']==name) for name in names]
        app=m.StackDesignerApp.__new__(m.StackDesignerApp)
        app.materials=materials
        app.project={'schema_version':m.PROJECT_SCHEMA_VERSION,'project_name':'workflow',
            'beam':{'energy_keV':50.,'beam_diameter_nm':10.,'current_pA':None,'current_input_unit':'pA'},
            'materials':materials,'stack':[
                {'material_name':name,'thickness_nm':height,'role':role}
                for name,height,role in zip(names,[500.,200.,350000.],['resist','dielectric','substrate'])],
            'pec_fits':[]}
        app.last_fit_result=None
        for name,value in [('project_name','workflow'),('energy','50'),('diam','10'),('current',''),('current_unit','pA'),('fit_info',''),('workflow_hint',''),('sim_progress',0)]:
            setattr(app,name+'_var',Var(value))
        app.root=SimpleNamespace(cget=lambda _: '',config=lambda **_:None,update_idletasks=lambda:None)
        for name in ['_open_sim_progress_window','_close_sim_progress_window','_set_sim_progress_text','_set_sim_progress_message','_show_fit_result_dialog']:
            setattr(app,name,lambda *a,**kw:None)
        params={'electrons':150,'seed':12345,'min_energy_keV':.05,'max_collisions_per_electron':4000,
            'max_radius_nm':30000,'resist_layer_index':0,'resist_layer_indices':[0],'forward_nm':100.,'beamer_fwhm_um':.03}
        with patch.object(m.messagebox,'showerror') as error:
            app._run_standalone_mc_job(params)
            error.assert_not_called()
        result=app.last_fit_result
        self.assertIsNotNone(result)
        self.assertEqual(app._fit_state(result),'current')
        diag=result['transport_diagnostics']
        self.assertAlmostEqual(diag['incident_energy_keV'],7500.)
        self.assertLess(abs(diag['energy_balance_error_keV'])/diag['incident_energy_keV'],1e-10)
        self.assertEqual(sum(diag['termination_counts'].values()),150)
        self.assertEqual(result['simulation']['program_version'],m.PROGRAM_VERSION)
        serialized=json.loads(json.dumps(app.collect_project()))
        loaded,_=app._migrate_project_data(serialized)
        reloaded=loaded['pec_fits'][-1]
        self.assertEqual(reloaded['transport_diagnostics'],diag)
        self.assertEqual(reloaded['input_snapshot'],result['input_snapshot'])
        with tempfile.TemporaryDirectory(prefix='ebl_workflow_') as folder:
            for ext,writer in [('psf',app._write_psf_two_column),('csv',app._write_psf_csv),('lpsf',app._write_lpsf_archive)]:
                path=Path(folder)/('curve.'+ext)
                writer(str(path),reloaded)
                self.assertGreater(path.stat().st_size,100)
        # An edit must not relabel or silently export the old physics result.
        old_hash=app._export_metadata(result)['stack_hash']
        app.project['stack'][0]['thickness_nm']=600.
        self.assertEqual(app._fit_state(result),'stale')
        self.assertEqual(app._export_metadata(result)['stack_hash'],old_hash)
        with self.assertRaises(ValueError): app._require_exportable_fit(result)

    def test_truncation_diagnostics_are_visible(self):
        diagnostic={'incident_energy_keV':50.,'energy_balance_error_keV':0.,
            'termination_counts':{'max_collisions':1,'radial_limit':1},
            'deposited_energy_selected_resist_keV':2.,'deposited_energy_selected_outside_radius_keV':.2}
        warnings=m._transport_diagnostic_warnings(diagnostic)
        self.assertEqual(len(warnings),3)
        self.assertTrue(any('10%' in warning for warning in warnings))
        diagnostic['energy_balance_error_keV']=1.
        self.assertTrue(any('does not balance' in warning for warning in m._transport_diagnostic_warnings(diagnostic)))

if __name__=='__main__':unittest.main()
