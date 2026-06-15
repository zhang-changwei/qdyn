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


def extract_band_edges(
    software: str, dir_path: str, whichk: int = 1, whichs: int = 1 
) -> Tuple[int, int, int]:
    """Extract VBM and CBM band indices from output files for different software.

    Parses the output files to find the last occupied band (VBM) and the first
    unoccupied band (CBM) for the given k-point and spin.

    Args:
        software: Software name (``'vasp'``, ``'openmx'``, or ``'hamgnn'``).
        dir_path: Directory containing the output files.
        whichk: K-point index (1-based).
        whichs: Spin index (1-based).

    Returns:
        tuple: ``(vbm, cbm, nbands)`` with 1-based band indices and band count.

    Raises:
        NotImplementedError: If software is not supported.
    """
    if software == 'vasp':
        return _extract_vbmcbm_from_vasp_outcar(dir_path, whichk, whichs)
    elif software == 'openmx':
        return _extract_vbmcbm_from_openmx_out(dir_path, whichk, whichs)
    elif software == 'hamgnn':
        return _extract_vbmcbm_from_hamgnn_fake(dir_path)
    raise NotImplementedError(f"Software '{software}' is not supported yet.")

# ===========================================================================
# plot functions (md plots and weights for tdks plots)
# ===========================================================================
def plot_md_results(md_data: dict, filename: str, target_temp: float | None = None):
    """Plot temperature, potential, and total energy evolution of an MD run.

    Args:
        md_data: Parsed MD data containing ``time_ps``, ``temperatures``,
            ``total_energies``, and ``potential_energies`` sequences.
        filename: Path of the output image file to write.
        target_temp: Target temperature in Kelvin drawn as a reference line; no
            reference line is drawn when None.
    """
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

    ax1.set_xlabel('Time (ps)')
    ax1.set_ylabel('Temperature (K)')
    ax1.legend(loc='upper right')
    ax1.set_title('Temperature Evolution')

    # Plot potential energy
    ax2 = axes[1]
    ax2.plot(times, potential_energies, color='tab:green', linewidth=0.8)
    ax2.set_xlabel('Time (ps)')
    ax2.set_ylabel('Potential Energy (eV)')
    ax2.set_title('Potential Energy Evolution')

    # Plot total energy
    ax3 = axes[2]
    ax3.plot(times, total_energies, color='tab:blue', linewidth=0.8)
    ax3.set_xlabel('Time (ps)')
    ax3.set_ylabel('Total Energy (eV)')
    ax3.set_title('Total Energy Evolution')

    fig.tight_layout()
    fig.savefig(filename, dpi=300, transparent=True)
    plt.close()


def extract_wht_with_cache(
    software: str,
    run_dirs: list,
    which_spin: int = 1,
    which_kpoint: int = 1,
    which_atoms: np.ndarray | None = None,
    nproc: int | None = None,
    cache_file_wht: str = 'all_wht.npy',
    cache_file_enr: str = 'all_en.npy',
    force_recalculate: bool = False,
) -> Tuple[np.ndarray, np.ndarray]:
    """Extract and cache wavefunction weight data from different software.

    Atom-projected weights are extracted from output files across multiple SCF
    directories and cached in ``.npy`` files for fast reuse. When ``which_atoms``
    is given the returned weight is ``partial_weight / total_weight``; otherwise it
    is the total weight summed over all atoms.

    Args:
        software: Software name (currently only ``'vasp'`` is supported).
        run_dirs: Directories to process.
        which_spin: Spin index to extract (1-based).
        which_kpoint: K-point index to extract (1-based).
        which_atoms: Atom indices to project weights onto; None sums over all
            atoms.
        nproc: Number of parallel worker processes; None uses all available CPUs.
        cache_file_wht: Base filename for cached weights.
        cache_file_enr: Base filename for cached energies.
        force_recalculate: Recompute and overwrite the cache instead of reusing it.

    Returns:
        tuple: ``(enr, wht)`` where each array has shape ``(nsw, nbands)`` for the
        selected spin and k-point.

    Raises:
        ValueError: If run_dirs is empty.
    """
    if len(run_dirs) == 0:
        raise ValueError("run_dirs must not be empty.")

    cache_wht, cache_enr = _resolve_cache_paths(
        cache_file_wht,
        cache_file_enr,
        software,
        which_spin,
        which_kpoint,
        which_atoms,
        len(run_dirs),
    )

    if (
        not force_recalculate
        and cache_wht.is_file()
        and cache_enr.is_file()
    ):
        wht = np.load(cache_wht)
        enr = np.load(cache_enr)
        return enr, wht

    enr, wht = _compute_wht_for_selection(
        software, run_dirs, which_spin, which_kpoint, which_atoms, nproc
    )

    np.save(cache_wht, wht)
    np.save(cache_enr, enr)
    return enr, wht


def _resolve_cache_paths(
    cache_file_wht: str,
    cache_file_enr: str,
    software: str,
    which_spin: int,
    which_kpoint: int,
    which_atoms: np.ndarray | None,
    n_run_dirs: int,
) -> Tuple[Path, Path]:
    atoms_key = (
        'all'
        if which_atoms is None
        else str(sum(which_atoms)) # TODO: use sum as a simple identifier
    )
    cache_suffix = (
        f".{software}.spin{which_spin}.k{which_kpoint}.atoms_{atoms_key}.n{n_run_dirs}"
    )
    return (
        _append_cache_suffix(cache_file_wht, cache_suffix),
        _append_cache_suffix(cache_file_enr, cache_suffix),
    )


def _compute_wht_for_selection(
    software: str,
    run_dirs: list,
    which_spin: int,
    which_kpoint: int,
    which_atoms: np.ndarray | None,
    nproc: int | None,
) -> Tuple[np.ndarray, np.ndarray]:
    """Compute selected-spin/k-point energies and weights via ``parallel_wht``.

    Args:
        software: Software name passed through to ``parallel_wht``.
        run_dirs: Directories to process.
        which_spin: Spin index to select (1-based).
        which_kpoint: K-point index to select (1-based).
        which_atoms: Atom indices to project onto; None sums over all atoms.
        nproc: Number of parallel worker processes; None uses all available CPUs.

    Returns:
        tuple: ``(enr, wht)`` for the selected spin and k-point. When
        ``which_atoms`` is given, ``wht`` is the partial/total weight ratio.
    """
    which_spin -= 1 # convert to 0-based index
    which_kpoint -= 1 # convert to 0-based index
    sel = np.s_[:, which_spin, which_kpoint, :]
    if which_atoms is not None:
        enr, wht_partial, tot_wht = _parallel_wht(
            run_dirs, which_atoms, software=software, nproc=nproc
        )
        _validate_wht_dimensions(enr, wht_partial, tot_wht)
        _validate_spin_kpoint_indices(enr, which_spin, which_kpoint)
        enr = enr[sel]
        wht_partial = wht_partial[sel]
        tot_wht = tot_wht[sel]
        wht = np.divide(
            wht_partial,
            tot_wht,
            out=np.zeros_like(wht_partial),
            where=tot_wht != 0,
        )
    else:
        enr, wht = _parallel_wht(
            run_dirs, which_atoms, software=software, nproc=nproc
        )
        _validate_wht_dimensions(enr, wht)
        _validate_spin_kpoint_indices(enr, which_spin, which_kpoint)
        enr = enr[sel]
        wht = wht[sel]
    return enr, wht


def _parallel_wht(
    run_dirs: list[str],
    which_atoms: np.ndarray | None,
    software: str,
    nproc: int | None = None,
) -> Tuple:
    """Calculate atom-projected weights in parallel for the given software.

    Args:
        run_dirs: Directories to process, one weight file per directory.
        which_atoms: Atom indices to project weights onto; None projects over all
            atoms.
        software: Software name (currently only ``'vasp'`` is supported).
        nproc: Number of parallel worker processes; None uses all available CPUs.

    Returns:
        tuple: ``(enr, wht)`` when ``which_atoms`` is None, otherwise
        ``(enr, wht_partial, tot_wht)``.

    Raises:
        ValueError: If run_dirs is empty.
        NotImplementedError: If software is not supported.
    """
    import multiprocessing

    run_dir_paths = [Path(rd) for rd in run_dirs]
    if len(run_dir_paths) == 0:
        raise ValueError("run_dirs must not be empty.")

    nproc = multiprocessing.cpu_count() if nproc is None else nproc
    with multiprocessing.Pool(processes=nproc) as pool:

        # Select weight extraction function based on software
        if software == 'vasp':
            weight_func = _weight_from_procar
            weight_file = 'PROCAR'
        else:
            raise NotImplementedError

        results = []
        for rd in run_dir_paths:
            res = pool.apply_async(
                weight_func,
                (
                    rd / weight_file,
                    which_atoms,
                    None,
                ),
            )
            results.append(res)

        enr = []
        wht = []
        if which_atoms is None:
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
            f"which_spin={which_spin + 1} is out of range for nspin={nspin}."
        )
    if not 0 <= which_kpoint < nkpt:
        raise IndexError(
            f"which_kpoint={which_kpoint + 1} is out of range for nkpt={nkpt}."
        )

# ===========================================================================
# qdyn_md.log parser (software-agnostic)
# ===========================================================================
def parse_qdyn_log_text(text: str) -> Dict:
    """Parse the contents of a ``qdyn_md.log`` file.

    The header ``Step: <N>, Interval: <I>`` carries the total MD steps (not the
    frame count). Each data row is anchored to its physical step via the time
    column, so both VASP (no step-0 frame) and ASE/MLFF (with step-0 frame) parse
    correctly without special-casing.

    Args:
        text: Full text content of a ``qdyn_md.log`` file.

    Returns:
        dict: Parsed MD data with keys ``steps``, ``temperatures``,
        ``total_energies``, ``potential_energies``, ``kinetic_energies``,
        ``converged``, ``time_ps``, ``interval``, and ``total_steps``.

    Raises:
        ValueError: If no valid MD data is found.
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
    """Parse MD data from a ``qdyn_md.log`` file path.

    Args:
        log_path: Path to the ``qdyn_md.log`` file.

    Returns:
        dict: Parsed MD data (see ``parse_qdyn_log_text``).

    Raises:
        FileNotFoundError: If the log file does not exist.
    """
    from pathlib import Path as _Path
    log_file = _Path(log_path)
    if not log_file.is_file():
        raise FileNotFoundError(f"qdyn_md.log not found at {log_path}")
    with open(log_file, 'r') as f:
        return parse_qdyn_log_text(f.read())


# ===========================================================================
# VASP specific functions
# ===========================================================================
def _weight_from_procar(
    infile: str = 'PROCAR',
    which_atom: np.ndarray | None = None,
    spd: np.ndarray | None = None,
) -> Tuple:
    """Compute the contribution of selected atoms to each KS orbital.

    Args:
        infile: Path to the VASP ``PROCAR`` file.
        which_atom: 1D array of atom indices to project onto; None sums over all
            atoms.
        spd: Orbital column indices to sum over; None uses the total column.

    Returns:
        tuple: ``(energies, weights)`` when ``which_atom`` is None, otherwise
        ``(energies, partial_weights, total_weights)``.

    Raises:
        FileNotFoundError: If infile does not exist.
        ValueError: If which_atom is not a non-empty 1D array.
        IndexError: If which_atom contains out-of-range indices.
    """
    if not os.path.isfile(infile):
        raise FileNotFoundError(f"{infile} cannot be found!")
    file_contents = [line for line in open(infile) if line.strip()]

    # when the band number is too large, there will be no space between ";" and
    # the actual band number. A bug found by Homlee Guo.
    # Here, #kpts, #bands and #ions are all integers
    nkpts, nbands, nions = [
        int(xx) for xx in re.sub('[^0-9]', ' ', file_contents[1]).split()
    ]

    if spd is not None:
        weights = np.asarray(
            [
                line.split()[1:-1]
                for line in file_contents
                if not re.search('[a-zA-Z]', line)
            ],
            dtype=float,
        )
        weights = np.sum(weights[:, spd], axis=1)
    else:
        weights = np.asarray(
            [
                line.split()[-1]
                for line in file_contents
                if not re.search('[a-zA-Z]', line)
            ],
            dtype=float,
        )

    total_weights = np.asarray(
        [line.split()[-1] for line in file_contents if re.search('^tot', line)],
        dtype=float,
    )

    nspin = weights.shape[0] // (nkpts * nbands * nions)
    weights.resize(nspin, nkpts, nbands, nions)
    total_weights.resize(nspin, nkpts, nbands)

    energies = np.asarray(
        [line.split()[-4] for line in file_contents if 'occ.' in line], dtype=float
    )
    energies.resize(nspin, nkpts, nbands)

    if which_atom is None:
        return energies, np.sum(weights, axis=-1)
    else:
        which_atom = np.asarray(which_atom, dtype=int)
        if which_atom.ndim != 1:
            raise ValueError(
                f"which_atom must be a 1D array, got shape {which_atom.shape}."
            )
        if which_atom.size == 0:
            raise ValueError("which_atom must not be empty when provided.")
        if np.any(which_atom < 0) or np.any(which_atom >= nions):
            raise IndexError(
                f"which_atom indices must be in [0, {nions - 1}], got {which_atom.tolist()}."
            )
        return energies, np.sum(weights[:, :, :, which_atom], axis=-1), total_weights


def _extract_vbmcbm_from_vasp_outcar(
    dir_path: str,
    whichk: int = 1,
    whichs: int = 1,
) -> Tuple[int, int, int]:
    outcar_path = os.path.join(dir_path, 'OUTCAR')
    with open(outcar_path, 'r') as f:
        outcar_lines = [line for line in f if line.strip()]

    nbands = nkpts = ispin = 0
    for line in outcar_lines:
        if 'NBANDS' in line and 'NKPTS' in line:
            nbands = int(line.split()[-1])
            nkpts = int(line.split()[3])
        if 'ISPIN  =' in line:
            ispin = int(line.split()[2])
            break

    # Find the last E-fermi section (for NSW=0, there's only one)
    where_efermi = [ii for ii, line in enumerate(outcar_lines) if 'E-fermi :' in line]

    if not where_efermi:
        raise RuntimeError("Could not find 'E-fermi' in OUTCAR.")

    ii = where_efermi[-1]

    if ispin == 1:
        start = ii + 1
        end = start + (nbands + 2) * nkpts + 1
    else:
        start = ii + 1
        end = start + ((nbands + 2) * nkpts + 1) * ispin + 2

    # Filter out lines containing alphabetic characters (header lines)
    data_lines = [line for line in outcar_lines[start:end] if not re.search('[a-zA-Z]', line)]

    # Select bands for the specified spin and k-point
    offset = ((whichs - 1) * nkpts + (whichk - 1)) * nbands
    band_lines = data_lines[offset : offset + nbands]

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

    return vbm, cbm, nbands


# ===========================================================================
# OPENMX specific functions
# ===========================================================================
def _extract_vbmcbm_from_openmx_out(
    dir_path: str,
    whichk: int = 1,
    whichs: int = 1,
) -> Tuple[int, int, int]: # TODO: fit 4.0 openmx output
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
    """Read an OpenMX ``.scfout`` file via the optional postprocess backend.

    Args:
        path: Path to the ``.scfout`` file.

    Returns:
        dict: Parsed SCF output data.

    Raises:
        ImportError: If the optional OpenMX postprocess support is not installed.
    """
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
    """Assemble the Gamma-point overlap (or Hamiltonian) matrix from scfout data.

    Args:
        scfout_data: Parsed scfout data containing ``atomnum``, ``nao_per_atom``,
            ``edge_index``, and the on-/off-site blocks.
        tdt: Build only the cross-frame (t, t+dt) overlap blocks instead of the
            full on-site + off-site matrix.
        isH: Use the Hamiltonian blocks (``Hon``/``Hoff``) instead of the overlap
            blocks (``Son``/``Soff``).
        ispin: Spin channel index used when ``isH`` is True.

    Returns:
        Dense Gamma-point matrix of shape ``(nao_total, nao_total)``.

    Raises:
        ValueError: If ``isH`` is True but the postprocess level is too low.
    """
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
            SK[off_i:off_i+nao_i, off_i:off_i+nao_i] += tmp.reshape(nao_i, nao_i)
        # off-site (periodic images contribute to the same atom pair)
        for idx, (i, j) in enumerate(zip(edge_index[0], edge_index[1])):
            nao_i = nao_per_atom[i]
            nao_j = nao_per_atom[j]
            off_i = nao_idx_offset[i]
            off_j = nao_idx_offset[j]
            tmp = Soff[idx][:nao_i*nao_j]
            SK[off_i:off_i+nao_i, off_j:off_j+nao_j] += tmp.reshape(nao_i, nao_j)
    else:
        # no on-site, cross-frame overlap
        for idx, (i, j) in enumerate(zip(edge_index[0], edge_index[1])):
            if i < natoms and j >= natoms:
                j -= natoms
                nao_i = nao_per_atom[i]
                nao_j = nao_per_atom[j]
                off_i = nao_idx_offset[i]
                off_j = nao_idx_offset[j]
                tmp = Soff[idx][:nao_i*nao_j]
                SK[off_i:off_i+nao_i, off_j:off_j+nao_j] += tmp.reshape(nao_i, nao_j)

    return SK

# ===========================================================================
# Hamgnn specific functions
# ===========================================================================
def _extract_vbmcbm_from_hamgnn_fake(dir_path: str) -> Tuple[int, int, int]:
    try:
        stru = read_stru('openmx-dat', os.path.join(dir_path, 'qdyn.dat'))
        software_dft = 'openmx'
        hamgnn_out = np.load(os.path.join(dir_path, 'wfc.npz'), mmap_mode='r')
        nbands = hamgnn_out['wfc'].shape[1]
    except Exception as e:
        raise FileNotFoundError(f"Could not read structure from {dir_path}/qdyn.dat: {e}")

    syms = stru.get_chemical_symbols()
    nele = 0
    for sym in syms:
        nele += VALENCE_ELECTRONS[software_dft][sym]
    vbm = (nele + 1) // 2
    cbm = vbm + 1
    return vbm, cbm, nbands