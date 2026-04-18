_incar = {
    'ISTART': 0,
    'ISPIN': 1,
    'LREAL': 'Auto',
    'PREC': 'Normal',
    'LWAVE': False,
    'LCHARG': False,
    'NWRITE': 1,
    'KPAR': 2,
    'NCORE': 8,
    'ISMEAR': 0,
    'SIGMA': 0.1,
    'ENCUT': 500,
}

params_default = {
    'sr': {
        'vasp': {
            **_incar,
            'NELM': 90,
            'NELMIN': 6,
            'EDIFF': 1e-8,
            'NSW': 100,
            'IBRION': 2,
            'ISIF': 2,
            'EDIFFG': -0.01,
        }
    },
    'nvt': {
        'vasp': {
            **_incar,
            'ALGO': 'Normal',
            'NELMIN': 4,
            'NELM': 120,
            'EDIFF': 1e-6,
            'ISYM': 0,
            'IBRION': 0,
            'NSW': 1000,
            'POTIM': 1,
            'SMASS': 0,
            'NBLOCK': 4,
            'TEBEG': 300,
            'TEEND': 300,
        }
    },
    'nve': {
        'vasp': {
            **_incar,
            'ALGO': 'Normal',
            'NELMIN': 4,
            'NELM': 120,
            'EDIFF': 1e-6,
            'ISYM': 0,
            'IBRION': 0,
            'NSW': 5000,
            'POTIM': 1,
            'SMASS': -3,
            'NBLOCK': 1,
        }
    },
    'scf': {
        'vasp': {
            **_incar,
            'LORBIT': 11,
            # 'NEDOS': 2001,
            'NELM': 120,
            'EDIFF': 1e-6,
            'LWAVE': True,
            'LCHARG': True,
            'ICHARG': 1,
        }
    },
}

# MD5 hash pattern for uploaded file validation (32-char lowercase hex).
# Used by InputT validator and /upload/hash endpoint.
import re
HASH_PATTERN = re.compile(r'^[0-9a-f]{32}$')

md_tracks = {
    'vasp': 'XDATCAR',
}

# ASE format strings for reading/writing trajectory files per software.
# Used by read_strus(), write_strus(), and upload validation.
md_ase_formats = {
    'vasp': 'vasp-xdatcar',
}

backup_files = {
    'vasp': [
        'POSCAR',
        'CONTCAR',
        'XDATCAR',
        'OSZICAR',
        'OUTCAR',
        'INCAR',
        'KPOINTS',
        'POTCAR',
    ],
}

chg_name = {
    'vasp': 'CHGCAR',
}

ipt_files = {
    'vasp': ['INCAR', 'KPOINTS', 'POTCAR'],
}

stru_files = {
    'vasp': 'POSCAR',
}

# PBE
potcar_default = {
    'H': 'H',
    'He': 'He',
    'Li': 'Li_sv',
    'Be': 'Be',
    'B': 'B',
    'C': 'C',
    'N': 'N',
    'O': 'O',
    'F': 'F',
    'Ne': 'Ne',
    'Na': 'Na_pv',
    'Mg': 'Mg',
    'Al': 'Al',
    'Si': 'Si',
    'P': 'P',
    'S': 'S',
    'Cl': 'Cl',
    'Ar': 'Ar',
    'K': 'K_sv',
    'Ca': 'Ca_sv',
    'Sc': 'Sc_sv',
    'Ti': 'Ti_sv',
    'V': 'V_sv',
    'Cr': 'Cr_pv',
    'Mn': 'Mn_pv',
    'Fe': 'Fe',
    'Co': 'Co',
    'Ni': 'Ni',
    'Cu': 'Cu',
    'Zn': 'Zn',
    'Ga': 'Ga_d',
    'Ge': 'Ge_d',
    'As': 'As',
    'Se': 'Se',
    'Br': 'Br',
    'Kr': 'Kr',
    'Rb': 'Rb_sv',
    'Sr': 'Sr_sv',
    'Y': 'Y_sv',
    'Zr': 'Zr_sv',
    'Nb': 'Nb_sv',
    'Mo': 'Mo_sv',
    'Tc': 'Tc_pv',
    'Ru': 'Ru_pv',
    'Rh': 'Rh_pv',
    'Pd': 'Pd',
    'Ag': 'Ag',
    'Cd': 'Cd',
    'In': 'In_d',
    'Sn': 'Sn_d',
    'Sb': 'Sb',
    'Te': 'Te',
    'I': 'I',
    'Xe': 'Xe',
    'Cs': 'Cs_sv',
    'Ba': 'Ba_sv',
    'La': 'La',
    'Ce': 'Ce',
    'Pr': 'Pr_3',
    'Nd': 'Nd_3',
    'Pm': 'Pm_3',
    'Sm': 'Sm_3',
    'Eu': 'Eu_2',
    'Gd': 'Gd_3',
    'Tb': 'Tb_3',
    'Dy': 'Dy_3',
    'Ho': 'Ho_3',
    'Er': 'Er_3',
    'Tm': 'Tm_3',
    'Yb': 'Yb_2',
    'Lu': 'Lu_3',
    'Hf': 'Hf_pv',
    'Ta': 'Ta_pv',
    'W': 'W_sv',
    'Re': 'Re',
    'Os': 'Os',
    'Ir': 'Ir',
    'Pt': 'Pt',
    'Au': 'Au',
    'Hg': 'Hg',
    'Tl': 'Tl_d',
    'Pb': 'Pb_d',
    'Bi': 'Bi_d',
    'Po': 'Po_d',
    'At': 'At',
    'Rn': 'Rn',
    'Fr': 'Fr_sv',
    'Ra': 'Ra_sv',
    'Ac': 'Ac',
    'Th': 'Th',
    'Pa': 'Pa',
    'U': 'U',
    'Np': 'Np',
    'Pu': 'Pu',
    'Am': 'Am',
    'Cm': 'Cm',
}

valence_electrons = {}

__all__ = ['params_default']
