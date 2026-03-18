_incar = {
    'ISTART': 0,
    'ISPIN': 1,
    'LREAL': False,
    'PREC': 'Accurate',
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

md_tracks = {
    'vasp': 'XDATCAR',
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
__all__ = ['params_default']
