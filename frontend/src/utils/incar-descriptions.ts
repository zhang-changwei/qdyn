/**
 * Common VASP INCAR parameter descriptions.
 *
 * This is a static lookup table for display purposes.
 * Any INCAR parameter not listed here will simply have no tooltip.
 */
export const INCAR_DESCRIPTIONS: Record<string, string> = {
  // General
  SYSTEM: 'Job name / comment',
  PREC: 'Precision mode (Normal, Accurate, Low, etc.)',
  ENCUT: 'Plane-wave cutoff energy (eV)',
  ALGO: 'Electronic minimization algorithm',
  NELM: 'Max electronic SCF iterations',
  NELMIN: 'Min electronic SCF iterations',
  EDIFF: 'Electronic convergence criterion (eV)',
  LREAL: 'Real-space projection (.TRUE., Auto, .FALSE.)',
  ISYM: 'Symmetry (0=off, 1=on, 2=PAW)',
  NCORE: 'Cores per orbital band',
  KPAR: 'K-point parallelization groups',
  NPAR: 'Band parallelization groups',

  // Smearing
  ISMEAR: 'Smearing method (-1=Fermi, 0=Gaussian, 1=MP1)',
  SIGMA: 'Smearing width (eV)',

  // Ionic relaxation
  NSW: 'Max ionic steps',
  IBRION: 'Ionic relaxation method (0=MD, 1=RMM, 2=CG)',
  ISIF: 'Stress/relaxation flags (2=ions, 3=ions+cell)',
  EDIFFG: 'Ionic convergence criterion (eV/Å, negative=force)',
  POTIM: 'Ionic step width / MD time step (fs)',

  // MD
  TEBEG: 'Initial temperature (K)',
  TEEND: 'Final temperature (K)',
  SMASS: 'Nosé mass parameter (-1=NVE, ≥0=NVT)',
  MDALGO: 'MD thermostat algorithm',

  // Wavefunction / charge
  LWAVE: 'Write WAVECAR',
  LCHARG: 'Write CHGCAR',
  LORBIT: 'Projected DOS / write PROCAR (10, 11, 12)',
  LAECHG: 'Write all-electron charge density',

  // Spin
  ISPIN: 'Spin polarization (1=no, 2=yes)',
  MAGMOM: 'Initial magnetic moments',

  // DFT+U
  LDAU: 'Enable DFT+U',
  LDAUTYPE: 'DFT+U type (1=Liechtenstein, 2=Dudarev)',
  LDAUL: 'L quantum number per species (-1=off)',
  LDAUU: 'U parameter per species (eV)',
  LDAUJ: 'J parameter per species (eV)',

  // vdW
  IVDW: 'van der Waals correction method',
  LUSE_VDW: 'Enable non-local vdW functional',

  // Hybrid functionals
  LHFCALC: 'Enable Hartree-Fock / hybrid functional',
  AEXX: 'Exact exchange fraction',
  HFSCREEN: 'Screening parameter for HSE (1/Å)',

  // Output
  LELF: 'Write electron localization function',
  LVTOT: 'Write total potential',
  NEDOS: 'Number of DOS points',
  EMIN: 'DOS energy range minimum (eV)',
  EMAX: 'DOS energy range maximum (eV)',

  // SOC
  LSORBIT: 'Enable spin-orbit coupling',
  LNONCOLLINEAR: 'Non-collinear magnetism',
  SAXIS: 'Spin quantization axis',

  // Misc
  NBANDS: 'Number of bands',
  ICHARG: 'Charge density initialization',
  ISTART: 'Wavefunction initialization',
  ADDGRID: 'Additional support grid',
  LASPH: 'Non-spherical PAW contributions',
  GGA: 'Exchange-correlation functional type',
  METAGGA: 'Meta-GGA functional type',
}
