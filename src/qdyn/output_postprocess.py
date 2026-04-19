import os
import re
import logging
from pathlib import Path
from typing import Dict, Tuple

import matplotlib

matplotlib.use('agg')
import matplotlib.pyplot as plt
import numpy as np


# ===========================================================================
# Universal functions
# ===========================================================================
def check_scf_convergence(
    converged_list: list[bool],
    check_nsw: int | None = None,
    max_unconverged_ratio: float = 0.01,
) -> bool:
    """Check SCF convergence from MD data (universal for all software).

    This function checks if SCF converged properly based on the converged
    flags in the MD data.

    Parameters
    ----------
    converged_list : list of bool
        List of SCF convergence flags for each MD step.
    check_nsw : int, optional
        Number of steps to check (from the end). If None, check last 5% of steps.
    max_unconverged_ratio : float
        Maximum ratio of unconverged steps allowed (default: 0.01 = 1%).

    Returns
    -------
    bool
        True if SCF converged properly, False if there are too many unconverged steps.
    """

    n_steps = len(converged_list)

    if n_steps == 0:
        raise ValueError("No convergence data available to check SCF convergence.")

    # Default: check last 5% of steps
    if check_nsw is None:
        check_nsw = n_steps // 10

    # Get the range to check
    check_range = converged_list[-check_nsw:]

    # n_total = len(check_range)
    n_unconverged = sum(1 for c in check_range if not c)
    max_unconverged = int(check_nsw * max_unconverged_ratio)

    # Converged if unconverged steps in check range <= max_unconverged
    converged = n_unconverged <= max_unconverged

    return converged


def save_md_data(md_data: Dict, md_dt: float, filename: str = 'md.dat') -> str:
    """Save MD data to a file in unified format.

    This function saves MD data in a unified format that works for all
    supported software (VASP, CP2K, SIESTA, ABACUS, OpenMX, etc.).

    Parameters
    ----------
    md_data : dict
        MD data dictionary with unified format:
        - 'steps': list of step numbers
        - 'temperatures': list of temperatures (K)
        - 'total_energies': list of total energies (eV)
        - 'potential_energies': list of potential energies (eV)
        - 'kinetic_energies': list of kinetic energies (eV)
        - 'converged': list of bool, SCF convergence status for each step
        - 'md_dt': time step (fs)
    filename : str
        Output filename (default: 'md.dat').

    Returns
    -------
    str
        Path to the saved file.
    """
    with open(filename, 'w') as f:
        f.write(f"# Time step (fs): {md_dt}\n")
        f.write(
            "# Step  Temperature(K)  Total_Energy(eV)  E_pot(eV)  E_kin(eV)  Converged\n"
        )

        for i in range(len(md_data['steps'])):
            conv_flag = 1 if md_data['converged'][i] else 0
            f.write(
                f"{md_data['steps'][i]:6d} "
                f"{md_data['temperatures'][i]:12.2f} "
                f"{md_data['total_energies'][i]:16.8f} "
                f"{md_data['potential_energies'][i]:14.8f} "
                f"{md_data['kinetic_energies'][i]:14.8f} "
                f"{conv_flag}\n"
            )

        # Summary lines
        temps = np.array(md_data['temperatures'])
        converged_list = md_data['converged']
        n_converged = sum(converged_list)
        n_total = len(converged_list)

        f.write(f"# Total steps: {n_total}\n")
        f.write(f"# Converged steps: {n_converged}/{n_total}\n")
        f.write(f"# Average T (K): {np.mean(temps):.2f}\n")

    return os.path.abspath(filename)


def plot_md_results(
    md_data: Dict,
    filename: str,
    target_temp: float | None = None,
) -> str:
    """Plot MD simulation results.

    Parameters
    ----------
    md_data : dict
        MD data dictionary from extract_md_data_from_oszicar().
    target_temp : float
        Target temperature for reference line.
    filename : str
        Output filename for the plot.

    Returns
    -------
    str
        Path to the saved plot.
    """
    steps = md_data['steps']
    temperatures = md_data['temperatures']
    total_energies = md_data['total_energies']
    potential_energies = md_data['potential_energies']

    fig, axes = plt.subplots(3, 1, figsize=(8, 10))

    # Plot temperature
    ax1 = axes[0]
    ax1.plot(steps, temperatures, color='tab:red', linewidth=0.8)

    if target_temp is not None:
        ax1.axhline(
            y=target_temp,
            color='gray',
            linestyle='--',
            linewidth=1,
            label=f'Target: {target_temp} K',
        )

    ax1.set_xlabel('Step')
    ax1.set_ylabel('Temperature (K)')
    ax1.legend(loc='upper right')
    ax1.set_title('Temperature Evolution')

    # Plot potential energy
    ax2 = axes[1]
    ax2.plot(steps, potential_energies, color='tab:green', linewidth=0.8)
    ax2.set_xlabel('Step')
    ax2.set_ylabel('Potential Energy (eV)')
    ax2.set_title('Potential Energy Evolution')

    # Plot total energy
    ax3 = axes[2]
    ax3.plot(steps, total_energies, color='tab:blue', linewidth=0.8)
    ax3.set_xlabel('Step')
    ax3.set_ylabel('Total Energy (eV)')
    ax3.set_title('Total Energy Evolution')

    fig.tight_layout()
    plt.savefig(filename, dpi=300)
    plt.close()

    return os.path.abspath(filename)


def parallel_wht(
    runDirs: list[str],
    whichAtoms: np.ndarray | None,
    software: str,
    nproc: int | None = None,
) -> Tuple:
    """Calculate atom-projected weights in parallel for different software.

    Parameters
    ----------
    runDirs : list
        List of directories to process.
    whichAtoms : np.ndarray, optional
        Array of atom indices for which to calculate weights.
    software : str
        Software name: 'vasp', 'cp2k', 'siesta', 'abacus', 'openmx'.
    nproc : int, optional
        Number of parallel processes. If None, uses all available CPUs.

    Returns
    -------
    tuple
        (Enr, Wht) or (Enr, Wht_partial, TotWht) depending on whichAtoms.
    """
    import multiprocessing

    run_dir_paths = [Path(rd) for rd in runDirs]
    if len(run_dir_paths) == 0:
        raise ValueError("runDirs must not be empty.")

    nproc = multiprocessing.cpu_count() if nproc is None else nproc
    with multiprocessing.Pool(processes=nproc) as pool:

        # Select weight extraction function based on software
        if software == 'vasp':
            weight_func = WeightFromPro
            weight_file = 'PROCAR'
        else:
            raise NotImplementedError

        results = []
        for rd in run_dir_paths:
            res = pool.apply_async(
                weight_func,
                (
                    rd / weight_file,
                    whichAtoms,
                    None,
                ),
            )
            results.append(res)

        enr = []
        wht = []
        if whichAtoms is None:
            for ii in range(len(results)):
                tmp_enr, tmp_wht = results[ii].get()
                enr.append(tmp_enr)
                wht.append(tmp_wht)
            return np.stack(enr, axis=0), np.stack(wht, axis=0)
        else:
            totwht = []
            for ii in range(len(results)):
                tmp_enr, tmp_wht, tmp_totwht = results[ii].get()
                enr.append(tmp_enr)
                wht.append(tmp_wht)
                totwht.append(tmp_totwht)
            return (
                np.stack(enr, axis=0),
                np.stack(wht, axis=0),
                np.stack(totwht, axis=0),
            )


def extract_wht_with_cache(
    software: str,
    run_dirs: list,
    which_spin: int = 0,
    which_kpoint: int = 0,
    which_atoms: np.ndarray | None = None,
    nproc: int | None = None,
    cache_file_wht: str = 'all_wht.npy',
    cache_file_enr: str = 'all_en.npy',
    force_recalculate: bool = False,
) -> Tuple[np.ndarray, np.ndarray]:
    """Extract and cache wavefunction weight data from different software.

    This function extracts atom-projected weights from output files across
    multiple SCF directories. Results are cached in .npy files for fast reuse.

    Parameters
    ----------
    run_dirs : list
        List of directories to process.
    software : str
        Software name: 'vasp', 'cp2k', 'siesta', 'abacus', 'openmx'.
    which_spin : int
        Spin index to extract (default: 0, index starts from 0).
    which_kpoint : int
        K-point index to extract (default: 0, index starts from 0).
    which_atoms : np.ndarray, optional
        Array of atom indices for which to calculate weights.
        If None, returns total weights for all atoms.
    nproc : int, optional
        Number of parallel processes. If None, uses all available CPUs.
    cache_file_wht : str
        Filename for cached weights (default: 'all_wht.npy').
    cache_file_enr : str
        Filename for cached energies (default: 'all_en.npy').
    force_recalculate : bool
        If True, ignore cache and recalculate (default: False).

    Returns
    -------
    tuple
        (Enr, Wht) where:
        - Enr: np.ndarray of shape (nsw, nbands) - energies for each step and band
        - Wht: np.ndarray of shape (nsw, nbands) - weights for each step and band

    Notes
    -----
    - When which_atoms is provided, Wht = partial_weight / total_weight
    - When which_atoms is None, Wht = total_weight (sum over all atoms)
    """

    if len(run_dirs) == 0:
        raise ValueError("run_dirs must not be empty.")

    atoms_key = 'all' if which_atoms is None else '-'.join(map(str, np.asarray(which_atoms, dtype=int).tolist()))
    cache_suffix = (
        f".{software}.spin{which_spin}.k{which_kpoint}.atoms_{atoms_key}.n{len(run_dirs)}"
    )

    cache_file_wht = _append_cache_suffix(cache_file_wht, cache_suffix)
    cache_file_enr = _append_cache_suffix(cache_file_enr, cache_suffix)

    # Check for cached results
    if (
        not force_recalculate
        and cache_file_wht.is_file()
        and cache_file_enr.is_file()
    ):
        Wht = np.load(cache_file_wht)
        Enr = np.load(cache_file_enr)
        return Enr, Wht

    # Calculate weights in parallel
    if which_atoms is not None:
        Enr, Wht_partial, TotWht = parallel_wht(
            run_dirs, which_atoms, software=software, nproc=nproc
        )
        _validate_wht_dimensions(Enr, Wht_partial, TotWht)
        _validate_spin_kpoint_indices(Enr, which_spin, which_kpoint)
        # Select specific spin and k-point
        Enr = Enr[:, which_spin, which_kpoint, :]
        Wht_partial = Wht_partial[:, which_spin, which_kpoint, :]
        TotWht = TotWht[:, which_spin, which_kpoint, :]
        Wht = np.divide(
            Wht_partial,
            TotWht,
            out=np.zeros_like(Wht_partial),
            where=TotWht != 0,
        )
    else:
        Enr, Wht = parallel_wht(run_dirs, which_atoms, software=software, nproc=nproc)
        _validate_wht_dimensions(Enr, Wht)
        _validate_spin_kpoint_indices(Enr, which_spin, which_kpoint)
        # Select specific spin and k-point
        Enr = Enr[:, which_spin, which_kpoint, :]
        Wht = Wht[:, which_spin, which_kpoint, :]

    # Save to cache files
    np.save(cache_file_wht, Wht)
    np.save(cache_file_enr, Enr)

    return Enr, Wht


def _append_cache_suffix(filename: str, suffix: str) -> Path:
    path = Path(os.path.expanduser(filename))
    return path.with_name(f"{path.stem}{suffix}{path.suffix}")


def _validate_wht_dimensions(*arrays: np.ndarray) -> None:
    reference_shape = arrays[0].shape
    if len(reference_shape) != 4:
        raise ValueError(
            f"Expected weight arrays with shape (nsw, nspin, nkpt, nband), got {reference_shape}."
        )

    for arr in arrays[1:]:
        if arr.shape != reference_shape:
            raise ValueError(
                f"Weight arrays must share the same shape, got {reference_shape} and {arr.shape}."
            )


def _validate_spin_kpoint_indices(
    energies: np.ndarray,
    which_spin: int,
    which_kpoint: int,
) -> None:
    _, nspin, nkpt, _ = energies.shape
    if not 0 <= which_spin < nspin:
        raise IndexError(
            f"which_spin={which_spin} is out of range for nspin={nspin}."
        )
    if not 0 <= which_kpoint < nkpt:
        raise IndexError(
            f"which_kpoint={which_kpoint} is out of range for nkpt={nkpt}."
        )


def extract_band_edges(
    software: str, dir_path: str, whichK: int = 0, whichS: int = 0
) -> Tuple[int, int]:
    """Extract VBM and CBM band indices from output files for different software.

    This function parses the output files to find the last occupied band (VBM)
    and first unoccupied band (CBM) for a given k-point and spin.

    Parameters
    ----------
    software : str
        Software name: 'vasp', 'cp2k', 'siesta', 'abacus', 'openmx'.
    dir_path : str
        Path to directory containing output files.
    whichK : int
        K-point index (0-based).
    whichS : int
        Spin index (0-based).

    Returns
    -------
    Tuple[int, int]
        (vbm, cbm) - VBM and CBM band indices (0-based).
    """
    if software == 'vasp':
        return extract_from_vasp_outcar(dir_path, whichK, whichS)
    raise NotImplementedError


# ===========================================================================
# VASP specific functions
# ===========================================================================
def parse_md_data_from_oszicar(
    oszicar_path: 'os.PathLike[str] | str',
    incar_path: 'os.PathLike[str] | str | None' = None,
) -> Dict:
    """Parse MD data from a VASP OSZICAR file using streaming line scan.

    This is the low-level helper that accepts absolute paths and uses
    streaming I/O (no ``readlines()``).  Higher-level wrappers such as
    ``extract_md_data_from_oszicar`` and the frontend API service layer
    should call this function instead of duplicating OSZICAR parsing.

    Parameters
    ----------
    oszicar_path : path-like
        Absolute or relative path to the OSZICAR file.
    incar_path : path-like or None
        Path to the INCAR file used to read NELM for SCF convergence
        checking.  If *None*, the default NELM=60 is assumed.

    Returns
    -------
    dict
        Dictionary with keys:
        - ``steps``              : list[int]
        - ``temperatures``       : list[float]
        - ``total_energies``     : list[float]   (E_pot + E_kin)
        - ``potential_energies`` : list[float]
        - ``kinetic_energies``   : list[float]
        - ``converged``          : list[bool]
    """
    from pathlib import Path

    oszicar = Path(oszicar_path)
    if not oszicar.is_file():
        raise FileNotFoundError(
            f"OSZICAR file not found at {oszicar_path}. "
            "Please check the output for errors."
        )

    # --- Resolve NELM from INCAR ---
    nelm = 60  # VASP default
    if incar_path is not None:
        incar = Path(incar_path)
        if incar.is_file():
            nelm_re = re.compile(r'^\s*NELM\s*=\s*(\d+)', re.IGNORECASE)
            try:
                with open(incar, 'r') as f:
                    for line in f:
                        m = nelm_re.match(line)
                        if m:
                            nelm = int(m.group(1))
                            break
            except OSError as e:
                logging.warning('Failed to open INCAR at %s: %s, using default NELM=60', incar_path, e)

    # --- Streaming parse of OSZICAR ---
    steps: list[int] = []
    temperatures: list[float] = []
    total_energies: list[float] = []
    potential_energies: list[float] = []
    kinetic_energies: list[float] = []
    converged: list[bool] = []

    prev_line: str = ''
    with open(oszicar, 'r') as f:
        for line in f:
            if 'T=' in line:
                values = line.split()
                try:
                    step = int(values[0])
                    T = float(values[2])
                    E_pot = float(values[8])
                    E_kin = float(values[10])
                    E_total = E_pot + E_kin

                    # SCF convergence: check if the previous electronic-step
                    # line hit the NELM limit.
                    step_converged = True
                    if prev_line:
                        try:
                            if int(prev_line.split()[1]) == nelm:
                                step_converged = False
                        except (ValueError, IndexError):
                            pass

                    steps.append(step)
                    temperatures.append(T)
                    total_energies.append(E_total)
                    potential_energies.append(E_pot)
                    kinetic_energies.append(E_kin)
                    converged.append(step_converged)
                except (ValueError, IndexError) as e:
                    logging.warning(
                        'Skipping OSZICAR line due to parsing error: %s — %s',
                        e, line.strip(),
                    )
            prev_line = line

    if len(steps) == 0:
        raise ValueError("No valid MD steps found in OSZICAR file.")

    return {
        'steps': steps,
        'temperatures': temperatures,
        'total_energies': total_energies,
        'potential_energies': potential_energies,
        'kinetic_energies': kinetic_energies,
        'converged': converged,
    }


def extract_md_data_from_oszicar(oszicar_path: str = 'OSZICAR') -> Dict:
    """Extract MD data and SCF convergence info from VASP OSZICAR file.

    Compatibility wrapper around :func:`parse_md_data_from_oszicar`.
    Reads INCAR from the current working directory (matching legacy
    behaviour).

    Parameters
    ----------
    oszicar_path : str
        Path to OSZICAR file (default: 'OSZICAR').

    Returns
    -------
    dict
        Dictionary containing MD data (unified format for all software):
        - 'steps': list of step numbers
        - 'temperatures': list of temperatures (K)
        - 'total_energies': list of total energies (eV)
        - 'potential_energies': list of potential energies (eV)
        - 'kinetic_energies': list of kinetic energies (eV)
        - 'converged': list of bool, whether each SCF step converged
    """
    incar_path: str | None = 'INCAR' if os.path.isfile('INCAR') else None
    return parse_md_data_from_oszicar(oszicar_path, incar_path)


def WeightFromPro(
    infile: str = 'PROCAR',
    whichAtom: np.ndarray | None = None,
    spd: np.ndarray | None = None,
) -> Tuple:
    """
    Contribution of selected atoms to the each KS orbital
    """

    assert os.path.isfile(infile), '%s cannot be found!' % infile
    FileContents = [line for line in open(infile) if line.strip()]

    # when the band number is too large, there will be no space between ";" and
    # the actual band number. A bug found by Homlee Guo.
    # Here, #kpts, #bands and #ions are all integers
    nkpts, nbands, nions = [
        int(xx) for xx in re.sub('[^0-9]', ' ', FileContents[1]).split()
    ]

    if spd is not None:
        Weights = np.asarray(
            [
                line.split()[1:-1]
                for line in FileContents
                if not re.search('[a-zA-Z]', line)
            ],
            dtype=float,
        )
        Weights = np.sum(Weights[:, spd], axis=1)
    else:
        Weights = np.asarray(
            [
                line.split()[-1]
                for line in FileContents
                if not re.search('[a-zA-Z]', line)
            ],
            dtype=float,
        )

    TotalWeights = np.asarray(
        [line.split()[-1] for line in FileContents if re.search('^tot', line)],
        dtype=float,
    )

    nspin = Weights.shape[0] // (nkpts * nbands * nions)
    Weights.resize(nspin, nkpts, nbands, nions)
    TotalWeights.resize(nspin, nkpts, nbands)

    Energies = np.asarray(
        [line.split()[-4] for line in FileContents if 'occ.' in line], dtype=float
    )
    Energies.resize(nspin, nkpts, nbands)

    if whichAtom is None:
        return Energies, np.sum(Weights, axis=-1)
    else:
        whichAtom = np.asarray(whichAtom, dtype=int)
        if whichAtom.ndim != 1:
            raise ValueError(f"whichAtom must be a 1D array, got shape {whichAtom.shape}.")
        if whichAtom.size == 0:
            raise ValueError("whichAtom must not be empty when provided.")
        if np.any(whichAtom < 0) or np.any(whichAtom >= nions):
            raise IndexError(
                f"whichAtom indices must be in [0, {nions - 1}], got {whichAtom.tolist()}."
            )
        return Energies, np.sum(Weights[:, :, :, whichAtom], axis=-1), TotalWeights


def extract_from_vasp_outcar(
    dir_path: str,
    whichK: int = 1,
    whichS: int = 1,
) -> Tuple[int, int]:
    """Extract VBM and CBM band indices from OUTCAR.

    Parses the eigenvalue section after "E-fermi :" to find the last
    occupied band (VBM) and first unoccupied band (CBM).

    Parameters
    ----------
    dir_path : str
        Path to directory containing OUTCAR file.
    whichK : int
        K-point index (1-based).
    whichS : int
        Spin component index (1-based).

    Returns
    -------
    Tuple[int, int]
        (vbm, cbm) - VBM and CBM band indices (1-based VASP convention).
    """
    outcar_path = os.path.join(dir_path, 'OUTCAR')
    with open(outcar_path, 'r') as f:
        OUTCAR = [line for line in f if line.strip()]

    NBANDS = NKPTS = ISPIN = 0
    for line in OUTCAR:
        if 'NBANDS' in line and 'NKPTS' in line:
            NBANDS = int(line.split()[-1])
            NKPTS = int(line.split()[3])
        if 'ISPIN  =' in line:
            ISPIN = int(line.split()[2])
            break

    # Find the last E-fermi section (for NSW=0, there's only one)
    where_Efermi = [ii for ii, line in enumerate(OUTCAR) if 'E-fermi :' in line]

    if not where_Efermi:
        raise RuntimeError("Could not find 'E-fermi' in OUTCAR.")

    ii = where_Efermi[-1]

    if ISPIN == 1:
        start = ii + 1
        end = start + (NBANDS + 2) * NKPTS + 1
    else:
        start = ii + 1
        end = start + ((NBANDS + 2) * NKPTS + 1) * ISPIN + 2

    # Filter out lines containing alphabetic characters (header lines)
    data_lines = [line for line in OUTCAR[start:end] if not re.search('[a-zA-Z]', line)]

    # Select bands for the specified spin and k-point
    offset = ((whichS - 1) * NKPTS + (whichK - 1)) * NBANDS
    band_lines = data_lines[offset : offset + NBANDS]

    vbm = 0
    cbm = 0
    for line in band_lines:
        parts = line.split()
        band_idx = int(parts[0])
        occupation = float(parts[-1])

        if occupation > 0.5:
            vbm = band_idx
        else:
            cbm = band_idx
            break

    if vbm == 0:
        raise RuntimeError("Could not determine VBM from OUTCAR eigenvalues.")
    if cbm != vbm + 1:
        cbm = vbm + 1

    return vbm, cbm
