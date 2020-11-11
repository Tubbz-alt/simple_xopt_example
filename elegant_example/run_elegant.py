import sys
lume_path = ''
sys.path.append(lume_path + 'lume-impact')
sys.path.append(lume_path + 'openPMD-beamphysics')
sys.path.append(lume_path + 'distgen')
sys.path.append(lume_path + 'xopt')


import numpy as np
import subprocess
from pmd_beamphysics.interfaces.elegant import elegant_h5_to_data
from pmd_beamphysics.plot import marginal_plot
from pmd_beamphysics import ParticleGroup
from pmd_beamphysics.plot import slice_statistics
import tempfile
from hashlib import blake2b
import json
import shutil
import os
import h5py
from h5py import File
import re

from xopt.tools import fingerprint

#ELEGANT_BIN='/global/cfs/cdirs/m669/aliaksei/elegant2020_rhel7/oag/apps/bin/linux-x86_64/elegant'
#HDF5_BIN= '/global/cfs/cdirs/m669/aliaksei/elegant2020_rhel7/epics/extensions/bin/linux-x86_64/sdds2hdf'
#H5_SAVE= './output/beams/'

#class NpEncoder(json.JSONEncoder):
#    """
#    See: https://stackoverflow.com/questions/50916422/python-typeerror-object-of-type-int64-is-not-json-serializable/50916741
#    """
#    def default(self, obj):
#        if isinstance(obj, np.integer):
#            return int(obj)
#        elif isinstance(obj, np.floating):
#            return float(obj)
#        elif isinstance(obj, np.ndarray):
#            return obj.tolist()
#        else:
#            return super(NpEncoder, self).default(obj)
#
#def fingerprint(keyed_data, digest_size=16):
#    """
#    Creates a cryptographic fingerprint from keyed data. 
#    Used JSON dumps to form strings, and the blake2b algorithm to hash.
#    
#    """
#    h = blake2b(digest_size=16)
#    for key in sorted(keyed_data.keys()):
#        val = keyed_data[key]
#        s = json.dumps(val, sort_keys=True, cls=NpEncoder).encode()
#        h.update(s)
#    return h.hexdigest()
#

def replaceTextBetween(originalText, delimeterA, delimterB, replacementText):
    leadingText = originalText.split(delimeterA)[0]
    trailingText = originalText.split(delimterB)[1]

    return leadingText + delimeterA + replacementText + delimterB + trailingText

def execute_elegant(settings, elename = 'LCLS2cuH.ele', ltename = 'LCLS2cuH.lte'):

    #if 'timeout' in settings:
    #    timeout = settings['timeout']
    #else:
    #    timeout = None
    
    ####-----grab other relevant info for run from settings-----
    ####-----pop ones that aren't used at the moment too so are not in settings1 -- can fix later
    settings1 = settings.copy()
    elename = settings1.pop('elename')
    ltename = settings1.pop('ltename')
    path_search = settings1.pop('path_search')
    ELEGANT_BIN = settings1.pop('ELEGANT_BIN')
    HDF5_BIN = settings1.pop('HDF5_BIN')
    H5_SAVE= settings1.pop('HDF5_BIN')

    finput_name = settings1.pop('finput_name')
    foutput_name = settings1.pop('foutput_name')

    ####-----temp dir for run-----
    tdir = tempfile.TemporaryDirectory()
    path = tdir.name

    shutil.copy('run'+elename, path)
    shutil.copy(ltename, path)
    
    ####-----run elegant-----

    binname = ELEGANT_BIN
    cmd = binname + ' ' + 'run' + elename 
    
    for s in settings1:
        cmd += ' -macro=' + s + '=' + str(settings1[s]) + ' '

    print (cmd)
    cmd_run = cmd.split()
    output = {'error':True, 'log':''}


    p = subprocess.run(cmd_run, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=path)
    PF = process_output(path,HDF5_BIN,finput_name,foutput_name)
    output['log'] = p.stdout
    output['error'] = False

    return PF

def process_output(path, HDF5_BIN, finput_name='HXRSTART.out', foutput_name='HXRSTART.h5',timeout=None):

    finput = os.path.join(path,finput_name)
    foutput = os.path.join(path,foutput_name)
    
    #init_dir = os.getcwd()
    #os.chdir(path)

    cmd = f'{HDF5_BIN} {finput} {foutput}'
    #print(cmd)
    cmd_run = cmd.split()
    output = {'error':True, 'log':''}

    p = subprocess.run(cmd_run, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    data = elegant_h5_to_data(foutput)
    PF = ParticleGroup(data=data)

    output['log'] = p.stdout
    output['error'] = False
    
    return PF

def run_elegant(settings):

    PF = execute_elegant(settings)

    return PF

def calculate_core_pars(P, n_slice=50, n_slice_av=10):
    
    n_lower = int((n_slice - n_slice_av)/2)
    n_upper = int((n_slice + n_slice_av)/2)
        
    P.t -= P['mean_t']
    keys = ['norm_emit_x', 'sigma_pz', 'ptp_t','charge']
    slice_dat = slice_statistics(P, keys, n_slice, 't')
    slice_dat['density'] = slice_dat['charge']/ slice_dat['ptp_t']
    
    core_current = np.mean(slice_dat['density'][n_lower:n_upper])
    core_pz = np.mean(slice_dat['sigma_pz'][n_lower:n_upper])
    core_norm_emit_x = np.mean(slice_dat['norm_emit_x'][n_lower:n_upper])

    core_dict = {'core_norm_emit_x':core_norm_emit_x, 'core_pz':core_pz, 'core_current': core_current}

    return core_dict


def merit1(P):

    d = {}
    for k in ['sigma_pz', 'norm_emit_x', 'sigma_t', 'mean_pz', 'charge', 'ptp_t']:
        d[k] = P[k]
     
    core_dict = calculate_core_pars(P)
    d_up = {**d, **core_dict}
    
    return d_up

def evaluate_elegant(settings, a=1):
    
    
    ####-----grab other relevant info for run from settings-----
    settings1 = settings.copy()
    elename = settings1.pop('elename')
    ltename = settings1.pop('ltename')
    path_search = settings1.pop('path_search')
    HDF5_BIN = settings1.pop('HDF5_BIN')
    H5_SAVE = settings1.pop('H5_SAVE')
    
    ####-----adjust search path according to YAML and rewrite .ele as 'run<elename>'------    
    
    f = open(elename,'r')
    
    outlines=[]
    
    for line in f.readlines():

        x = line.strip()
        
        if x.startswith('search_path'):
            line = ' search_path = "'+path_search+'"\n'
            
        outlines.append(line)
            
    
    f.close()
    
    with open('run'+elename, 'w') as f:
        for line in outlines:
            f.write(line)
            
    f.close()
    
    
    ####-----run elegant-----
    

    PF = run_elegant(settings)
    
    ####-----save h5 and archive----
    
    fnameh5 = 'elegant_sim_' + fingerprint(settings) + '.h5'
    PF.write(H5_SAVE+fnameh5)
    
    output = merit1(PF)
    output['archive']=H5_SAVE+fnameh5
 
    return output


def main(PATH=''):

    settings = {'L1_9_50_phase':50.5, 'L1_9_25_phase':50.5, 'L1_10_25_phase':50.5, 'X1_Xband_phase':-70, 
                'L2_10_50_phase':55.5, 'L2_10_25_phase':55.5, 'L3_10_25_volt':1.6628471874e7, 'X_MAX':1.3e-3,             
                'DX':0.9e-3, 'DP': 15.0e-5,
                'INPUT_FILE':PATH+'elegant_particles.txt'}
    
    PF = run_elegant(settings)
    #marginal_plot(PF, 't', 'pz')

    #d = evaluate_elegant(settings)
    #print (d)
    
    return 0
    
    
#main()
