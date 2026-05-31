# pyright: reportOptionalSubscript=false

import os
import re
import logging
from pathlib import Path
from typing import Dict, Tuple, Any

import numpy as np
import numpy.typing as npt
from ase import Atoms

from qdyn.calc_common import read_stru
from qdyn.params import  VALENCE_ELECTRONS, ORBITAL_BASIS
    
def plot_md_results(md_data: dict, filename: str, target_temp: float | None = None):
    import matplotlib
    matplotlib.use('agg')
    import matplotlib.pyplot as plt

    times = md_data['time_ps']
    temperatures = md_data['temperatures']
    total_energies = md_data['total_energies'] 
    potential_energies = md_data['potential_energies']

    fig, axes = plt.subplots(3, 1, figsize=(8, 10))

    # Plot temperature
    ax1 = axes[0]
    ax1.plot(times, temperatures, color='tab:red', linewidth=0.8)

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
    ax2.plot(times, potential_energies, color='tab:green', linewidth=0.8)
    ax2.set_xlabel('Step')
    ax2.set_ylabel('Potential Energy (eV)')
    ax2.set_title('Potential Energy Evolution')

    # Plot total energy
    ax3 = axes[2]
    ax3.plot(times, total_energies, color='tab:blue', linewidth=0.8)
    ax3.set_xlabel('Step')
    ax3.set_ylabel('Total Energy (eV)')
    ax3.set_title('Total Energy Evolution')

    fig.tight_layout()
    fig.savefig(filename, dpi=300, transparent=True)
    plt.close()


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
    software: str, dir_path: str, whichk: int = 1, whichs: int = 1 
) -> Tuple[int, int, int]:
    """Extract VBM and CBM band indices from output files for different software.

    This function parses the output files to find the last occupied band (VBM)
    and first unoccupied band (CBM) for a given k-point and spin.

    Parameters
    ----------
    software : str
        Software name: 'vasp', 'cp2k', 'siesta', 'abacus', 'openmx'.
    dir_path : str
        Path to directory containing output files.
    whichk : int
        K-point index (1-based).
    whichs : int
        Spin index (1-based).

    Returns
    -------
    Tuple[int, int, int]
        (vbm, cbm, nbands) - VBM and CBM band indices (1-based) and number of bands.
    """
    if software == 'vasp':
        return _extract_vbmcbm_from_vasp_outcar(dir_path, whichk, whichs)
    elif software == 'openmx':
        return _extract_vbmcbm_from_openmx_out(dir_path, whichk, whichs)
    elif software == 'hamgnn':
        return _extract_vbmcbm_from_hamgnn_fake(dir_path)
    raise NotImplementedError(f"Software '{software}' is not supported yet.")

def _extract_vbmcbm_from_hamgnn_fake(dir_path: str) -> Tuple[int, int, int]:
    """Read structure information from dft inputs to calculate VBM and CBM directly.

    Parameters
    ----------
    dir_path : str
        Path to directory (not used in this fake implementation).

    Returns
    -------
    Tuple[int, int, int]
        (vbm, cbm, nbands) - VBM and CBM band indices (1-based) and number of bands.
    """
    try:
        stru = read_stru('openmx-dat', os.path.join(dir_path, 'qdyn.dat'))
        software_dft = 'openmx'
    except Exception as e:
        raise FileNotFoundError(f"Could not read structure from {dir_path}/qdyn.dat: {e}")
    
    symbol = stru.symbols.indices()
    naos = {}
    for sym in symbol:
        basis = ORBITAL_BASIS[sym]
        orbitals = basis.partition('-')[2]
        numbers = re.findall(r'[spdf](\d+)', orbitals)
        naos[sym] = sum([int(n)*(2*i+1) for i, n in enumerate(numbers)])

    syms = stru.get_chemical_symbols()
    nele = 0
    nbands = 0
    for sym in syms:
        nele += VALENCE_ELECTRONS[software_dft][sym]
        nbands += naos[sym]
    vbm = (nele + 1) // 2
    cbm = vbm + 1
    return vbm, cbm, nbands
# ===========================================================================
# qdyn_md.log parser (software-agnostic)
# ===========================================================================
def parse_qdyn_log_text(text: str) -> Dict:
    """Parse qdyn_md.log content from a string.

    The header ``Step: <N>, Interval: <I>`` carries the total MD steps
    (not frame count).  Each data row is anchored to its physical step
    via the time column, so both VASP (no step-0 frame) and ASE/MLFF
    (with step-0 frame) parse correctly without special-casing.

    Returns dict with keys: steps, temperatures, total_energies,
    potential_energies, kinetic_energies, converged, time_ps,
    interval, total_steps.
    """
    steps: list[int] = []
    temperatures: list[float] = []
    total_energies: list[float] = []
    potential_energies: list[float] = []
    kinetic_energies: list[float] = []
    time_ps: list[float] = []

    lines = text.splitlines()
    if len(lines) < 2:
        raise ValueError("No valid MD data found in qdyn_md.log.")

    step_part, interval_part = lines[0].split(',')
    total_steps = int(step_part.split(':')[1])
    interval = int(interval_part.split(':')[1])

    raw_times: list[float] = []
    raw_data: list[tuple[float, float, float, float]] = []

    for line in lines[2:]:
        stripped = line.strip()
        if not stripped or len(stripped.split()) != 5:
            continue
        t, etot, epot, ekin, temp = map(float, stripped.split())
        raw_times.append(t)
        raw_data.append((etot, epot, ekin, temp))

    if not raw_times:
        raise ValueError("No valid MD data found in qdyn_md.log.")

    if len(raw_times) >= 2:
        dt = raw_times[1] - raw_times[0]
    else:
        dt = raw_times[0] if raw_times[0] > 0 else interval * 1e-3

    for t, (etot, epot, ekin, temp) in zip(raw_times, raw_data):
        step = round(t / dt) * interval if dt > 0 else 0
        steps.append(step)
        time_ps.append(t)
        total_energies.append(etot)
        potential_energies.append(epot)
        kinetic_energies.append(ekin)
        temperatures.append(temp)

    return {
        'steps': steps,
        'temperatures': temperatures,
        'total_energies': total_energies,
        'potential_energies': potential_energies,
        'kinetic_energies': kinetic_energies,
        'converged': [True] * len(steps),
        'time_ps': time_ps,
        'interval': interval,
        'total_steps': total_steps,
    }


def parse_md_data_from_qdyn_log(
    log_path: 'os.PathLike[str] | str',
) -> Dict:
    """Parse MD data from a ``qdyn_md.log`` file path."""
    from pathlib import Path as _Path
    log_file = _Path(log_path)
    if not log_file.is_file():
        raise FileNotFoundError(f"qdyn_md.log not found at {log_path}")
    with open(log_file, 'r') as f:
        return parse_qdyn_log_text(f.read())


# ===========================================================================
# VASP specific functions
# ===========================================================================
def WeightFromPro(
    infile: str = 'PROCAR',
    whichAtom: np.ndarray | None = None,
    spd: np.ndarray | None = None,
) -> Tuple:
    """
    Contribution of selected atoms to the each KS orbital
    """

    if not os.path.isfile(infile):
        raise FileNotFoundError(f"{infile} cannot be found!")
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


def _extract_vbmcbm_from_vasp_outcar(
    dir_path: str,
    whichk: int = 1,
    whichs: int = 1,
) -> Tuple[int, int, int]:
    """Extract VBM and CBM band indices from OUTCAR.

    Parses the eigenvalue section after "E-fermi :" to find the last
    occupied band (VBM) and first unoccupied band (CBM).

    Parameters
    ----------
    dir_path : str
        Path to directory containing OUTCAR file.
    whichk : int
        K-point index (1-based).
    whichs : int
        Spin component index (1-based).

    Returns
    -------
    Tuple[int, int, int]
        (vbm, cbm, nbands) - VBM and CBM band indices (1-based VASP convention) and number of bands.
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
    offset = ((whichs - 1) * NKPTS + (whichk - 1)) * NBANDS
    band_lines = data_lines[offset : offset + NBANDS]

    vbm = 0
    cbm = 0
    for line in band_lines:
        parts = line.split()
        band_idx = int(parts[0])
        occupation = float(parts[-1])

        if occupation >= 0.5:
            vbm = band_idx
        else:
            cbm = band_idx
            break

    if vbm == 0:
        raise RuntimeError("Could not determine VBM from OUTCAR eigenvalues.")
    if cbm != vbm + 1:
        cbm = vbm + 1

    return vbm, cbm, NBANDS


# ===========================================================================
# OPENMX specific functions
# ===========================================================================
def _extract_vbmcbm_from_openmx_out(
    dir_path: str,
    whichk: int = 1,
    whichs: int = 1,
) -> Tuple[int, int, int]: # TODO: fit 4.0 openmx output
    """Extract VBM and CBM from OpenMX qdyn.out using Chemical Potential.

    Parses the eigenvalues section of qdyn.out, finds the Chemical Potential,
    then locates the first band at the specified k-point and spin whose energy
    exceeds the Chemical Potential — that band is the CBM, and VBM = CBM - 1.

    Parameters
    ----------
    dir_path : str
        Path to directory containing qdyn.out.
    whichk : int
        K-point index (1-based).
    whichs : int
        Spin index (1-based, 1=up, 2=down).

    Returns
    -------
    Tuple[int, int, int]
        (vbm, cbm, nbands) — 1-based band indices.
    """
    out_path = os.path.join(dir_path, 'qdyn.out')
    with open(out_path, 'r') as f:
        text = f.read()

    # Parse Chemical Potential from the eigenvalues section header
    chem_pot_match = re.search(
        r'Chemical Potential \(Hartree\)\s*=\s*(-?[\d.]+)', text
    )
    if not chem_pot_match:
        raise RuntimeError(
            "Could not find 'Chemical Potential (Hartree) =' in qdyn.out."
        )
    chem_pot = float(chem_pot_match.group(1))

    # Locate the eigenvalues section
    eig_start = text.find('Eigenvalues (Hartree) of SCF KS-eq.')
    if eig_start == -1:
        raise RuntimeError(
            "Could not find eigenvalues section in qdyn.out."
        )

    # Locate the specified k-point block (kloop is 0-based in OpenMX)
    kloop_tag = f'kloop={whichk - 1}'
    kloop_pos = text.find(kloop_tag, eig_start)
    if kloop_pos == -1:
        raise RuntimeError(
            f"Could not find kloop={whichk - 1} in qdyn.out."
        )

    # Find the end of this k-point block: next kloop or next '***' separator
    end_pos = len(text)
    for marker in ['kloop=', '\n***']:
        pos = text.find(marker, kloop_pos + len(kloop_tag))
        if pos != -1:
            end_pos = min(end_pos, pos)

    block = text[kloop_pos:end_pos]

    col = whichs  # 1 → Up-spin, 2 → Down-spin
    vbm = 0
    cbm = 0
    nbands = 0
    for line in block.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        parts = stripped.split()
        if len(parts) < 3 or not parts[0].isdigit():
            continue
        band_idx = int(parts[0])
        energy = float(parts[col])
        nbands = band_idx
        if cbm == 0 and energy > chem_pot:
            cbm = band_idx
            vbm = band_idx - 1

    if cbm == 0:
        raise RuntimeError(
            "Could not determine CBM: no eigenvalue exceeds Chemical Potential."
        )

    return vbm, cbm, nbands

def read_scfout(path: str) -> dict[str, Any]:
    try:
        from qdyn_openmx_postprocess import read_scfout as _read_scfout
    except ImportError as exc:
        raise ImportError(
            "OpenMX postprocess support is optional. "
            "Install it with `uv sync --extra openmx`."
        ) from exc

    return _read_scfout(path)

def calc_openmx_HK_SK_gamma(
    scfout_data: dict[str, Any], 
    tdt: bool = False, 
    isH: bool = False,
    ispin: int = 0,
):
    natoms: int = scfout_data['atomnum']
    nao_per_atom: npt.NDArray[np.int32] = scfout_data['nao_per_atom']
    if isH:
        level = scfout_data['level']
        if level <= 2:
            raise ValueError("H calculation requires postprocess level > 2.")
        Son: npt.NDArray[np.float64] = scfout_data['Hon'][ispin]
        Soff: npt.NDArray[np.float64] = scfout_data['Hoff'][ispin]
    else:
        Son: npt.NDArray[np.float64] = scfout_data['Son']
        Soff: npt.NDArray[np.float64] = scfout_data['Soff']
    edge_index: npt.NDArray[np.int32] = scfout_data['edge_index']

    nao_total = np.sum(nao_per_atom)
    nao_idx_offset = np.zeros_like(nao_per_atom)
    nao_idx_offset[1:] = np.cumsum(nao_per_atom[:-1])
    if tdt:
        natoms //= 2
        nao_total //= 2

    SK = np.zeros((nao_total, nao_total), dtype=np.float64)
    
    if not tdt:
        # on-site
        for i in range(natoms):
            nao_i = nao_per_atom[i]
            off_i = nao_idx_offset[i]
            tmp = Son[i][:nao_i**2] 
            SK[off_i:off_i+nao_i, off_i:off_i+nao_i] = tmp.reshape(nao_i, nao_i)
        # off-site
        for idx, (i, j) in enumerate(zip(edge_index[0], edge_index[1])):
            nao_i = nao_per_atom[i]
            nao_j = nao_per_atom[j]
            off_i = nao_idx_offset[i]
            off_j = nao_idx_offset[j]
            tmp = Soff[idx][:nao_i*nao_j] 
            SK[off_i:off_i+nao_i, off_j:off_j+nao_j] = tmp.reshape(nao_i, nao_j)
    else:
        # no on-site
        for idx, (i, j) in enumerate(zip(edge_index[0], edge_index[1])):
            if i < natoms and j >= natoms:
                j -= natoms
                nao_i = nao_per_atom[i]
                nao_j = nao_per_atom[j]
                off_i = nao_idx_offset[i]
                off_j = nao_idx_offset[j]
                tmp = Soff[idx][:nao_i*nao_j] 
                SK[off_i:off_i+nao_i, off_j:off_j+nao_j] = tmp.reshape(nao_i, nao_j)

    return SK

from pydantic import BaseModel
from numpy.typing import NDArray
class LACOMetadata:
    nao_total: int
    nao_per_atoms: NDArray[np.int32]
    nao_idx_offset: NDArray[np.int32]
    nao_max_sum: int
    nao_max_spdf: tuple[int]
