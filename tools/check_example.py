"""Reproducible numerical smoke run; this is not an experimental validation."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import time

ROOT=Path(__file__).resolve().parents[1]
APP=ROOT/'ebl_stack_designer.py'
spec=importlib.util.spec_from_file_location('ebl_example',APP)
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--electrons',type=int,default=3000)
    parser.add_argument('--seed',type=int,default=12345)
    parser.add_argument('--output',type=Path)
    parser.add_argument('--project-output',type=Path)
    parser.add_argument('--plot-output',type=Path)
    args=parser.parse_args()
    app=m.StackDesignerApp.__new__(m.StackDesignerApp)
    materials=m.preset_material_library()
    names=['ma-N 2400 (approx.)','Silicon Nitride (Si3N4)','InP']
    app.materials=[next(mat for mat in materials if mat['name']==name) for name in names]
    app.project={'project_name':'50 keV numerical validation example',
        'beam':{'energy_keV':50.,'beam_diameter_nm':0.,'current_pA':None,'current_input_unit':'pA'},
        'materials':app.materials,'stack':[
            {'material_name':name,'thickness_nm':thickness,'role':role}
            for name,thickness,role in zip(names,[500.,200.,350000.],['resist','dielectric','substrate'])],
        'pec_fits':[]}
    app.root=SimpleNamespace(update_idletasks=lambda:None)
    app._set_sim_progress_text=lambda *a,**kw:None
    params={'electrons':args.electrons,'seed':args.seed,'min_energy_keV':.05,
        'max_collisions_per_electron':4000,'max_radius_nm':30000,
        'resist_layer_index':0,'resist_layer_indices':[0],'forward_nm':100.}
    start=time.monotonic()
    sim=app._simulate_standalone_radial_distribution(params)
    fit=app._fit_alpha_beta_eta_from_histogram(sim['rvals_nm'],sim['evals'],params['forward_nm'],
        source_label='reproducible_example',layer_label=sim['resist_layer_name'],
        collision_count=sim['collision_count_in_resist'],beam_energy_keV=50.,
        resist_thickness_nm=500.,beam_sigma_nm=sim['beam_sigma_nm'])
    fit['transport_diagnostics']=sim['transport_diagnostics']
    fit['simulation']={**params,'program_version':m.PROGRAM_VERSION,'beam_energy_keV':50.,
        'engine':'approximate_mc_material_local_v2',
        'stopping_model':'legacy_0.65_JoyLuo_plus_0.35_range_0.72'}
    fit['warnings']=list(dict.fromkeys(fit.get('warnings',[])+m._transport_diagnostic_warnings(sim['transport_diagnostics'])))
    fit=app._store_fit_result(fit)
    if args.project_output:
        args.project_output.parent.mkdir(parents=True,exist_ok=True)
        saved={**app.project,'schema_version':m.PROJECT_SCHEMA_VERSION,
            'program':{'name':m.PROGRAM_NAME,'version':m.PROGRAM_VERSION,'creator':m.PROGRAM_CREATOR}}
        args.project_output.write_text(json.dumps(saved,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    if args.plot_output:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        data=fit['plot_data']
        fig,ax=plt.subplots(figsize=(8.5,5.6),layout='constrained')
        ax.loglog(data['r_nm'],data['measured_density'],'.',ms=2.0,label='Гистограмма моделирования')
        ax.loglog(data['r_nm'],data['fitted_density'],lw=1.6,label='Степенно-гауссова аппроксимация' if fit['fit_model']=='power_gaussian' else 'Двухгауссова аппроксимация')
        ax.loglog(data['r_nm'],data['beamer_gaussian_density'],'--',lw=1.5,label='Гауссово представление для BEAMER')
        forward=('p='+format(fit['alpha_power'],'.3f')) if fit['fit_model']=='power_gaussian' else ('α='+format(fit['alpha_nm'],'.2f')+' нм')
        ax.set_title(f"EBL Stack Designer {m.PROGRAM_VERSION}: {forward}, β={fit['beta_nm']/1000:.3f} мкм, η={fit['eta_fit']:.4f}",fontsize=11)
        ax.set_xlabel('Радиус, нм');ax.set_ylabel('Плотность энерговыделения, нм⁻²')
        ax.grid(True,which='both',alpha=.22);ax.legend(loc='upper right',fontsize=9)
        args.plot_output.parent.mkdir(parents=True,exist_ok=True)
        fig.savefig(args.plot_output,dpi=240);plt.close(fig)
    # Low-level writers use the immutable result snapshot; no visible UI is needed.
    exports={}
    with tempfile.TemporaryDirectory(prefix='ebl_example_exports_') as directory:
        for extension,writer in [('psf',app._write_psf_two_column),('csv',app._write_psf_csv),('lpsf',app._write_lpsf_archive)]:
            path=Path(directory)/('example.'+extension)
            writer(str(path),fit)
            exports[extension]={'bytes':path.stat().st_size,'validated':True}
    diag=sim['transport_diagnostics']
    relative_error=abs(diag['energy_balance_error_keV'])/diag['incident_energy_keV']
    if relative_error>1e-8:
        raise RuntimeError('Transport energy balance failed.')
    report={'purpose':'Numerical execution and conservation check; not independent physical or PEC process validation',
        'program_version':m.PROGRAM_VERSION,'source_sha256':hashlib.sha256(APP.read_bytes()).hexdigest(),
        'inputs':fit['input_snapshot'],'simulation_parameters':params,'elapsed_s':time.monotonic()-start,
        'transport_diagnostics':diag,'relative_energy_balance_error':relative_error,
        'fit_representation':fit['fit_representation'],'fit_weighted_mse_log10':fit['fit_mse'],
        'fit_window_max_nm':fit['fit_window_max_nm'],'warnings':fit['warnings'],'exports':exports}
    text=json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False)+'\n'
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(text,encoding='utf-8')
    print(text)

if __name__=='__main__': main()
