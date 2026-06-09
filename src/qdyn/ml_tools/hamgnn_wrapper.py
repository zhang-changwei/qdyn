from copy import deepcopy
from contextlib import contextmanager
from functools import wraps
import multiprocessing
from multiprocessing.pool import AsyncResult
import queue
import os
from pathlib import Path
import time
import warnings
from typing import Any

from ase import Atoms
from pymatgen.core import Element
import numpy as np
from scipy.linalg import eigh
import torch
from torch_geometric.data import Dataset
from torch_geometric.loader import DataLoader
from torch_geometric.data import Data
import pytorch_lightning as pl
from hamgnn.main import build_hamgnn_model
from hamgnn.config.config_parsing import config_default
from hamgnn.models.Model import Model
from hamgnn.models.hamgnn_output import HamGNNPlusPlusOut
import numpy.typing as npt

from ..calc_common import select_orbitals, change_dir
from ..input import HamGNNInputT
from ..params import ORBITAL_BASIS
from ..output_postprocess import read_scfout, calc_openmx_HK_SK_gamma
from ..tools.run_software import run_software
from ..tools.scf import SCFLogger

NAO_MAX_SPDF = {
    13: (2, 2, 1),
    14: (3, 2, 1),
    19: (3, 2, 2),
    20: (4, 2, 2),
    26: (3, 2, 2, 1),
}

def _load_config(config: HamGNNInputT) -> dict[str, Any]:
    """Build HamGNN internal config dict from HamGNNInputT.

    Pretrained model defaults are already applied by
    HamGNNInputT.apply_pretrained_defaults (model_validator),
    so both pretrained and custom models use the same code path.
    """
    default = deepcopy(config_default)

    out = default['output_nets']['HamGNN_out']
    out['nao_max'] = config.nao_max
    out['add_H0'] = False
    out['ham_type'] = config.ham_type
    out['zero_point_shift'] = False

    rep = default['representation_nets']['HamGNN_pre']
    rep['cutoff'] = config.cutoff
    rep['cutoff_func'] = config.adv.cutoff_func
    rep['irreps_edge_sh'] = config.irreps_edge_sh
    rep['irreps_node_features'] = config.irreps_node_features
    rep['num_layers'] = config.num_layers
    rep['num_radial'] = config.adv.num_radial
    rep['num_types'] = config.adv.num_types
    rep['rbf_func'] = config.adv.rbf_func
    rep['set_features'] = config.adv.set_features
    rep['radial_MLP'] = config.adv.radial_MLP
    rep['use_corr_prod'] = config.adv.use_corr_prod
    rep['num_hidden_features'] = config.adv.num_hidden_features
    rep['use_kan'] = config.adv.use_kan
    rep['radius_scale'] = config.adv.radius_scale
    rep['build_internal_graph'] = config.adv.build_internal_graph
    rep['legacy_edge_update'] = config.adv.legacy_edge_update

    from easydict import EasyDict
    return EasyDict(default)

def get_basis_def(software: str, stru: Atoms, nao_max: int = 26) -> dict[int, npt.NDArray[np.int32]]:
    z = set(stru.numbers)
    nao_max_spdf = NAO_MAX_SPDF[nao_max]
    basis_def = {}
    for zi in z:
        if zi in basis_def:
            continue
        orb = ORBITAL_BASIS[Element.from_Z(zi).symbol]
        spdf = [int(x) for x in orb.split('-')[-1][1::2]]
        # shape (nao_max,)
        # equal to 1 if the corresponding orbital is included in the basis, 0 otherwise
        basis = np.zeros(nao_max, dtype=np.int32)
        left = 0
        for idx, mul in enumerate(spdf):
            if mul > nao_max_spdf[idx]:
                raise ValueError(f"Multiplicity {mul} exceeds maximum for orbital {idx}")
            width = (2 * idx + 1)
            basis[left:left + width * mul] = 1
            left += width * nao_max_spdf[idx]
        basis_def[zi] = basis
    return basis_def

def gen_hamgnn_graph(software: str, stru: Atoms, scfout: Any) -> tuple[int, Data]:
    if software == 'openmx':

        nbr_shift = scfout['nbr_shift']
        cell_shift = scfout['cell_shift']
        edge_index = scfout['edge_index']
        inv_edge_idx = scfout['inv_edge_idx']
        z = stru.numbers
        cell = stru.cell.array
        pos = stru.positions
        f32 = torch.float32
        i64 = torch.long

        graph = Data(
            z = torch.tensor(z, dtype=i64),
            cell = torch.tensor(cell, dtype=f32),
            pos = torch.tensor(pos, dtype=f32),
            node_counts = torch.tensor([len(stru)], dtype=i64),
            edge_index = torch.tensor(edge_index, dtype=i64),
            inv_edge_idx = torch.tensor(inv_edge_idx, dtype=i64),
            nbr_shift = torch.tensor(nbr_shift, dtype=f32),
            cell_shift = torch.tensor(cell_shift, dtype=i64),
            hamiltonian = torch.tensor((0.), dtype=f32),
            overlap = torch.tensor((0.), dtype=f32),
        )
        num_mat = len(stru) + len(scfout['inv_edge_idx'])
    else:
        raise NotImplementedError()
    return num_mat, graph

def calc_hamgnn_HK_gamma(
    HR: npt.NDArray, 
    nao_max: int,
    nao_per_atoms: list[int], 
    basis_def: dict[int, npt.NDArray[np.int32]],
    graph: Data,
    dtype: np.float32 | np.float64
):
    natoms = graph.node_counts[0]
    z = graph.z.numpy()
    edge_index = graph.edge_index.numpy() # type: ignore

    nao_total = np.sum(nao_per_atoms)
    nao_idx_offset = np.zeros_like(nao_per_atoms)
    nao_idx_offset[1:] = np.cumsum(nao_per_atoms[:-1])

    Hon  = HR[:natoms,:].reshape(-1, nao_max, nao_max)
    Hoff = HR[natoms:,:].reshape(-1, nao_max, nao_max)

    HK = np.zeros((nao_total, nao_total), dtype=dtype)

    # orb_mask
    orb_masks = {}
    for zi, basis_i in basis_def.items():
        for zj, basis_j in basis_def.items():
            orb_mask = basis_i[:,None] * basis_j[None,:]
            orb_masks[(zi, zj)] = (orb_mask > 0)

    # on-site
    for i in range(natoms):
        zi = z[i]
        nao_i = nao_per_atoms[i]
        off_i = nao_idx_offset[i]
        orb_mask = orb_masks[(zi, zi)]
        tmp = Hon[i][orb_mask].reshape(nao_i, nao_i)
        HK[off_i:off_i+nao_i, off_i:off_i+nao_i] += tmp

    # off-site
    for idx, (i, j) in enumerate(zip(edge_index[0], edge_index[1])):
        zi = z[i]
        zj = z[j]
        nao_i = nao_per_atoms[i]
        nao_j = nao_per_atoms[j]
        off_i = nao_idx_offset[i]
        off_j = nao_idx_offset[j]
        orb_mask = orb_masks[(zi, zj)]
        tmp = Hoff[idx][orb_mask].reshape(nao_i, nao_j)
        HK[off_i:off_i+nao_i, off_j:off_j+nao_j] += tmp

    return HK


def overwrite_hamgnn_basis(cls):
    def get_basis_for_element(nao_max: int, spdf: list[int]) -> list[int]:
        basis = []
        left = 0
        for idx, mul in enumerate(spdf):
            width = (2*idx+1)
            basis.extend(range(left, left+width*mul))
            left += width * NAO_MAX_SPDF[nao_max][idx]
        return basis

    original_initialize_openmx_basis = cls._initialize_openmx_basis

    @wraps(original_initialize_openmx_basis)
    def new_initialize_openmx_basis(self, *args, **kwargs):
        original_initialize_openmx_basis(self, *args, **kwargs)
        
        basis_def = {}
        orbitals = select_orbitals('openmx', self.nao_max)

        for element, orb in orbitals.items():
            spdf = [int(x) for x in orb.split('-')[-1][1::2]]
            basis_def[Element(element).Z] = get_basis_for_element(self.nao_max, spdf)

        self.basis_def = basis_def

    cls._initialize_openmx_basis = new_initialize_openmx_basis

overwrite_hamgnn_basis(HamGNNPlusPlusOut)

class LMDBDataset(Dataset):
    pass

class HamGNNWrapper:

    def __init__(self, config: HamGNNInputT, model_path: str, device: str = 'cpu'):
        pl.seed_everything(666)
        self.device = device
        self.config = _load_config(config)
        self.nao_max = config.nao_max
        if self.config['setup']['ignore_warnings']:
            warnings.filterwarnings('ignore')

        # train_and_eval
        self.graph_representation, self.output_module, self.post_utility = build_hamgnn_model(self.config)
        self.graph_representation.to(torch.float32)
        self.output_module.to(torch.float32)

        self.model = Model.load_from_checkpoint(checkpoint_path=model_path,
            strict=False,
            representation=self.graph_representation,
            output=self.output_module,
            post_processing=self.post_utility,
            losses=self.config['losses_metrics']['losses'],
            validation_metrics=self.config['losses_metrics']['metrics'],
            lr=self.config['optim_params']['lr'],
            lr_decay=self.config['optim_params']['lr_decay'],
            lr_patience=self.config['optim_params']['lr_patience'],
        )
        self.model.to(self.device)
        self.model.eval()

    def predict(self, data: list[Data], batch_size: int = 1) -> npt.NDArray[np.float32]:
        device = self.device
        with torch.no_grad():
            # prepare_data
            ds = DataLoader(data, batch_size=batch_size, shuffle=False)
            
            hamiltonians = []
            for d in ds:
                d = d.to(device)
                pred = self.model(d)
                hamiltonian = pred.pop('hamiltonian')
                hamiltonians.append(hamiltonian)
            hamiltonians = torch.cat(hamiltonians, dim=0).detach().cpu()
        return hamiltonians.numpy()



_worker_model: HamGNNWrapper | None = None
_worker_software: str | None = None
_worker_add_H0: bool | None = None
_worker_eigen_dtype: np.float32 | np.float64 | None = None
_worker_batch_size = 1

_THREAD_ENV_VARS = (
    "OMP_NUM_THREADS",
    "MKL_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
)

@contextmanager
def _thread_env_context(threads_per_proc: int):
    previous = {
        env_name: os.environ.get(env_name)
        for env_name in _THREAD_ENV_VARS
    }
    threads = str(threads_per_proc)
    for env_name in _THREAD_ENV_VARS:
        os.environ[env_name] = threads
    try:
        yield
    finally:
        for env_name, value in previous.items():
            if value is None:
                os.environ.pop(env_name, None)
            else:
                os.environ[env_name] = value


def _set_spawn_worker_cpu_affinity(nproc: int, threads_per_proc: int):
    import psutil

    worker_identity = multiprocessing.current_process()._identity
    if not worker_identity:
        raise RuntimeError(
            "Unable to determine spawn worker identity for CPU affinity."
        )

    worker_index = (worker_identity[0] - 1) % nproc
    start_cpu = worker_index * threads_per_proc
    # This binds consecutive logical CPUs only; with SMT/Hyper-Threading
    # enabled, these IDs may not map to consecutive physical cores.
    cpu_ids = list(range(start_cpu, start_cpu + threads_per_proc))

    process = psutil.Process()
    available_cpu_ids = sorted(process.cpu_affinity())
    # rule out the superthreading case
    if nproc * threads_per_proc * 2 <= len(available_cpu_ids):
        return
    if not set(cpu_ids).issubset(available_cpu_ids):
        raise RuntimeError(
            "Failed to bind HamGNN spawn worker "
            f"{worker_index + 1} to CPUs {cpu_ids}. "
            f"Available CPUs: {available_cpu_ids}. "
            f"threads_per_proc={threads_per_proc}."
        )

    process.cpu_affinity(cpu_ids)


def init_spawn_worker(
    software: str,
    mlh_input: HamGNNInputT,
    model_path: str,
    nproc: int,
    threads_per_proc: int,
    batch_per_proc: int,
    eigen_dtype: np.float32 | np.float64,
):
    _set_spawn_worker_cpu_affinity(nproc, threads_per_proc)
    torch.set_num_threads(threads_per_proc)
    torch.set_num_interop_threads(1)

    global _worker_model
    global _worker_software
    global _worker_add_H0
    global _worker_eigen_dtype
    global _worker_batch_size

    _worker_software = software
    _worker_add_H0 = mlh_input.add_H0
    _worker_eigen_dtype = eigen_dtype
    _worker_batch_size = max(1, batch_per_proc)
    ORBITAL_BASIS.clear()
    ORBITAL_BASIS.update(select_orbitals(software, mlh_input.nao_max))
    _worker_model = HamGNNWrapper(mlh_input, model_path=model_path, device='cpu')


def n2amd_workflow(
    steps: list[int],
    strus: list[Atoms],
    task_dirs: list[str],
    progress_queue: Any,
):
    global _worker_model
    assert _worker_model is not None, (
        "HamGNN model is not initialized in worker process. "
        "This workflow requires spawn workers initialized with init_spawn_worker."
    )
    assert _worker_software is not None, (
        "HamGNN worker software configuration is not initialized."
    )
    assert _worker_add_H0 is not None, (
        "HamGNN worker add_H0 configuration is not initialized."
    )
    assert _worker_eigen_dtype is not None, (
        "HamGNN worker eigen dtype configuration is not initialized."
    )
    worker_model = _worker_model
    software = _worker_software
    add_H0 = _worker_add_H0
    dtype = _worker_eigen_dtype

    SKs, H0Ks, graphs, num_mats = [], [], [], []
    nao_per_atom = None
    basis_def = None
    idx = -1
    try:
        threads = torch.get_num_threads()
        for idx, (stru, task_dir) in enumerate(zip(strus, task_dirs)):
            # 0. openmx postprocess
            if software == 'openmx':
                with change_dir(task_dir):
                    run_software(
                        software=software, 
                        nprocs=threads, 
                        postprocess=True,
                        omp=1,
                    )
            else:
                raise NotImplementedError
            # 1. parse scfout
            scfout_data = read_scfout(os.path.join(task_dir, 'qdyn.scfout'))
            if nao_per_atom is None:
                nao_per_atom = scfout_data['nao_per_atom']
            if basis_def is None:
                basis_def = get_basis_def(software, stru, worker_model.nao_max)
            # 2. calc SK and HK
            SK = calc_openmx_HK_SK_gamma(scfout_data)
            SKs.append(SK)
            if add_H0:
                H0K = calc_openmx_HK_SK_gamma(scfout_data, isH=True)
                H0Ks.append(H0K)
            # 3. gen graph
            num_mat, graph = gen_hamgnn_graph(software, stru, scfout_data)
            graphs.append(graph)
            num_mats.append(num_mat)
            # logging
            progress_queue.put(
                {
                    'type': 'prehamgnn',
                    'step': steps[idx],
                    'task_dir': task_dirs[idx],
                }
            )
        mat_offsets = np.zeros_like(num_mats)
        mat_offsets[1:] = np.cumsum(num_mats[:-1])
        # 4. predict
        assert nao_per_atom is not None, "NAO per atom information is missing."
        assert basis_def is not None, "Basis definition information is missing."
        batch_size = min(_worker_batch_size, len(graphs))
        hamiltonians = worker_model.predict(graphs, batch_size=batch_size)
        # logging
        progress_queue.put(
            {
                'type': 'hamgnn',
                'step': steps[0] if steps else -1,
                'task_dir': task_dirs[idx],
            }
        )
        # 5. HR -> HK
        HKs = []
        for idx in range(len(graphs)):
            HR = hamiltonians[mat_offsets[idx]:mat_offsets[idx]+num_mats[idx]]
            HK = calc_hamgnn_HK_gamma(
                HR, 
                worker_model.nao_max,
                nao_per_atom, 
                basis_def, 
                graphs[idx], 
                dtype=dtype
            )
            if add_H0:
                HK += H0Ks[idx]
            HKs.append(HK)
        del hamiltonians
        if add_H0:
            del H0Ks
        # 6. diag
        idx = -1
        for idx, (HK, SK, graph) in enumerate(zip(HKs, SKs, graphs)):
            eigvals, eigvecs = eigh(HK, SK, overwrite_a=True, overwrite_b=True)
            eigvecs = eigvecs.T
            # 7. save wfc.npz
            np.savez(
                os.path.join(task_dirs[idx], 'wfc.npz'),
                eigenvalues=eigvals,
                wfc=eigvecs,
            )
            # logging
            progress_queue.put(
                {
                    'type': 'posthamgnn',
                    'step': steps[idx],
                    'task_dir': task_dirs[idx],
                }
            )
    except Exception as exc:
        failed_idx = max(0, idx)
        progress_queue.put(
            {
                'type': 'step_failed',
                'step': steps[failed_idx] if steps else -1,
                'task_dir': task_dirs[failed_idx] if task_dirs else '',
                'error': str(exc),
            }
        )
        raise


class MLSCFSolver:

    def __init__(
        self, 
        software: str,
        mlh_input: HamGNNInputT,
        model_path: str,
        logger: SCFLogger,
        eigen_solver: str = 'scipy',
        use_gpu: bool = False,
        save_lmdb: bool = False,
        nproc: int = 1,
        threads_per_proc: int = 1,
    ):
        self.software = software
        self.logger = logger
        self._manager = None
        self.progress_queue = None
        self.pool = None
        self._pool_closed = False
        self._pool_joined = False
        self._pool_terminated = False
        self._manager_shutdown = False
        self._closed = False

        model_path_ = Path(model_path).expanduser().resolve()
        if not model_path_.is_file():
            raise FileNotFoundError(f"Model file not found at {model_path_}")

        batch_per_proc = max(1, mlh_input.batch_size // nproc)
        self.batch_size = batch_per_proc * nproc
        self.nproc = nproc
        self.threads_per_proc = threads_per_proc

        self._ctx = multiprocessing.get_context("spawn")
        worker_mlh_input = deepcopy(mlh_input)
        try:
            with _thread_env_context(threads_per_proc):
                self._manager = self._ctx.Manager()
                self.progress_queue = self._manager.Queue()
                self.pool = self._ctx.Pool(
                    processes=nproc,
                    initializer=init_spawn_worker,
                    initargs=(
                        self.software,
                        worker_mlh_input,
                        str(model_path_),
                        nproc,
                        threads_per_proc,
                        batch_per_proc,
                        (np.float64 if mlh_input.adv.eigen_dtype == 'float64'
                                    else np.float32),
                    ),
                )
        except Exception:
            self._cleanup_resources(terminate=True)
            raise
        self.tasks = []
        self.task_count = 0
        
        self.add_H0 = mlh_input.add_H0
        self.eigen_solver = eigen_solver
        self.eigen_dtype = (np.float64 
                            if mlh_input.adv.eigen_dtype == 'float64'
                            else np.float32)

        if save_lmdb:
            self.save_lmdb = True


    def add(self, step: int, job_dir: Path, stru: Atoms):
        self.tasks.append((step, job_dir, stru))
        self.task_count += 1
        if self.task_count >= self.batch_size:
            self.run()

    def close(self):
        self._cleanup_resources(terminate=False)

    def _terminate_pool(self):
        self._cleanup_resources(terminate=True)

    def _cleanup_resources(self, *, terminate: bool) -> None:
        if self._closed:
            return

        errors: list[BaseException] = []
        pool = getattr(self, "pool", None)
        if pool is not None:
            if terminate and not self._pool_terminated:
                try:
                    pool.terminate()
                except Exception as exc:
                    errors.append(exc)
                finally:
                    self._pool_terminated = True
            elif not terminate and not self._pool_closed and not self._pool_terminated:
                try:
                    pool.close()
                except Exception as exc:
                    errors.append(exc)
                finally:
                    self._pool_closed = True

            if not self._pool_joined:
                try:
                    pool.join()
                except Exception as exc:
                    errors.append(exc)
                else:
                    self._pool_joined = True

        manager = getattr(self, "_manager", None)
        if manager is not None and not self._manager_shutdown:
            try:
                manager.shutdown()
            except Exception as exc:
                errors.append(exc)
            finally:
                self._manager_shutdown = True

        self._closed = True
        if errors:
            raise RuntimeError("Failed to clean up MLSCFSolver resources.") from errors[0]

    @staticmethod
    def _chunk_tasks(
        tasks: list[tuple[int, Path, Atoms]],
        nproc: int,
    ) -> list[list[tuple[int, Path, Atoms]]]:
        chunks: list[list[tuple[int, Path, Atoms]]] = [[] for _ in range(nproc)]
        for idx, task in enumerate(tasks):
            chunks[idx % nproc].append(task)
        return [chunk for chunk in chunks if chunk]

    def _drain_progress_queue(self):
        while True:
            try:
                message = self.progress_queue.get_nowait()
            except queue.Empty:
                break
            msg_type = message['type']
            if msg_type == 'step_failed':
                raise RuntimeError(
                    f"MLSCFSolver step={message['step']} failed for "
                    f"{message['task_dir']}: {message['error']}"
                )
            else:
                self.logger(
                    step=message['step'],
                    global_idx=Path(message['task_dir']).name,
                    category=msg_type,
                )
    
    def run(self):
        if not self.task_count:
            return
        
        results: list[AsyncResult] = []
        chunks = self._chunk_tasks(self.tasks, self.nproc)

        for chunk in chunks:
            steps = [step for step, _, _ in chunk]
            task_dirs = [str(task_dir) for _, task_dir, _ in chunk]
            strus = [stru for _, _, stru in chunk]
            result = self.pool.apply_async(
                n2amd_workflow, 
                (
                    steps,
                    strus,
                    task_dirs,
                    self.progress_queue,
                )
            )
            results.append(result)
        
        try:
            pending = set(range(len(results)))
            while pending:
                time.sleep(1)
                self._drain_progress_queue()
                for idx in list(pending):
                    if results[idx].ready():
                        pending.remove(idx)
                        # to raise exceptions if any
                        results[idx].get()
            self._drain_progress_queue()
        except Exception as exc:
            try:
                self._drain_progress_queue()
            except Exception as drain_exc:
                warnings.warn(
                    f"Failed to drain MLSCFSolver progress queue during cleanup: "
                    f"{drain_exc}",
                    RuntimeWarning,
                )
            try:
                self._terminate_pool()
            except Exception as cleanup_exc:
                warnings.warn(
                    f"Failed to clean up MLSCFSolver resources after run error: "
                    f"{cleanup_exc}",
                    RuntimeWarning,
                )
            raise RuntimeError(f"MLSCFSolver.run failed: {exc}") from exc
        finally:
            self.tasks.clear()
            self.task_count = 0
