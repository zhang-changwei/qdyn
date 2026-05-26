from copy import deepcopy
import multiprocessing
from multiprocessing.pool import AsyncResult
import os
from pathlib import Path
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
import numpy.typing as npt

from ..input import HamGNNInputT
from ..params import ORBITAL_BASIS
from ..output_postprocess import read_scfout, calc_openmx_HK_SK_gamma
from ..tools.scf import SCFLogger

NAO_MAX_SPDF = {
    13: (2, 2, 1),
    19: (3, 2, 2),
    26: (3, 2, 2, 1),
}

def _load_config(config: HamGNNInputT) -> dict[str, Any]:
    default = deepcopy(config_default)

    out = default['output_nets']['HamGNN_out']
    out['nao_max'] = config.nao_max
    out['add_H0'] = False
    out['ham_type'] = config.ham_type

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
    rep['use_corr_prod'] = False
    rep['num_hidden_features'] = config.adv.num_hidden_features
    rep['use_kan'] = config.adv.use_kan
    rep['radius_scale'] = config.adv.radius_scale
    rep['build_internal_graph'] = config.adv.build_internal_graph

    return default

def get_basis_def(software: str, stru: Atoms, nao_max: int = 26) -> dict[int, npt.NDArray[np.int32]]:
    z = set(stru.numbers)
    nao_max_spdf = NAO_MAX_SPDF[nao_max]
    basis_def = {}
    for zi in z:
        if zi in basis_def:
            continue
        orb = ORBITAL_BASIS[software][Element.from_Z(zi).symbol]
        spdf = [int(x) for x in orb.split('-')[-1][1::2]]
        basis = np.zeros(nao_max, dtype=np.int32)
        left = 0
        for idx, l in enumerate(spdf):
            if l > nao_max_spdf:
                raise ValueError()
            width = (2*idx+1) * l
            basis[l:l+width] = 1
            left += (2*idx+1) * nao_max_spdf[idx]
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
            edge_index = torch.tensor(edge_index, dtype=f32),
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
    for idx, (i, j) in enumerate(edge_index[0], edge_index[1]):
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



model: HamGNNWrapper | None = None

def init_worker(omp: int, config: HamGNNInputT, model_path: str):
    os.environ["OMP_NUM_THREADS"] = str(omp)
    os.environ["MKL_NUM_THREADS"] = str(omp)
    os.environ["OPENBLAS_NUM_THREADS"] = str(omp)
    os.environ["NUMEXPR_NUM_THREADS"] = str(omp)
    os.environ["VECLIB_MAXIMUM_THREADS"] = str(omp)
    torch.set_num_threads(omp)

    global model
    model = HamGNNWrapper(config, model_path=model_path, device='cpu')

def n2amd_workflow(
    software: str,
    add_H0: bool,
    dtype: np.float32 | np.float64,
    steps: list[int],
    strus: list[Atoms],
    task_dirs: list[str]
):
    global model
    assert model is not None, "Model is not initialized in worker process."

    SKs, H0Ks, graphs, num_mats = [], [], [], []
    nao_per_atoms = None
    basis_def = None
    for stru, task_dir in zip(strus, task_dirs):
        # 1. parse scfout
        scfout_data = read_scfout(os.path.join(task_dir, 'qdyn.scfout'))
        if not nao_per_atoms:
            nao_per_atoms = scfout_data['nao_per_atom']
        if not basis_def:
            basis_def = get_basis_def(software, stru, model.nao_max)
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
    mat_offsets = np.zeros_like(num_mats)
    mat_offsets[1:] = np.cumsum(num_mats[:-1])
    # 4. predict
    assert nao_per_atoms is not None, "NAO per atom information is missing."
    assert basis_def is not None, "Basis definition information is missing."
    hamiltonians = model.predict(graphs, batch_size=len(graphs))
    # 5. HR -> HK
    HKs = []
    for idx in range(len(graphs)):
        HR = hamiltonians[mat_offsets[idx]:mat_offsets[idx]+num_mats[idx]]
        HK = calc_hamgnn_HK_gamma(
            HR, 
            model.nao_max, 
            nao_per_atoms, 
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
    for idx, (HK, SK, graph) in enumerate(zip(HKs, SKs, graphs)):
        eigvals, eigvecs = eigh(HK, SK, overwrite_a=True, overwrite_b=True)
        eigvecs = eigvecs.T
        # 7. save wfc.npz
        np.savez(
            os.path.join(task_dirs[idx], 'wfc.npz'),
            eigenvalues=eigvals,
            wfc=eigvecs,
        )
        # 8. logging
        # with lock:
        #     pass、

        # 9. cleanup


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

        model_path_ = Path(model_path).expanduser().resolve()
        if not model_path_.is_file():
            raise FileNotFoundError(f"Model file not found at {model_path_}")

        mlh_input.batch_size = max(1, mlh_input.batch_size // nproc)
        self.batch_size = mlh_input.batch_size * nproc
        self.nproc = nproc
        self.pool = multiprocessing.Pool(
            processes=nproc, 
            initializer=init_worker,
            initargs=(
                threads_per_proc,
                mlh_input,
                model_path_,
            )
        )
        self.lock = multiprocessing.Lock()
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
            self.tasks.clear()
            self.task_count = 0

    def close(self):
        self.pool.close()
        self.pool.join()
    
    def run(self):
        if not self.task_count:
            return
        
        results: list[AsyncResult] = []

        steps, task_dirs, strus = [], [], []
        for step, task_dir, stru in self.tasks[::self.nproc]:
            steps.append(step)
            task_dirs.append(str(task_dir))
            strus.append(stru)

        for idx in range(self.nproc):
            result = self.pool.apply_async(
                n2amd_workflow, 
                (self.software, self.add_H0, self.eigen_dtype, steps, strus, task_dirs)
            )
            results.append(result)
        
        for result in results:
            result.get()

