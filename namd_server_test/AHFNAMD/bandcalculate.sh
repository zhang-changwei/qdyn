#!/bin/bash
#SBATCH -J aln_band
#SBATCH -p queue1-1
#SBATCH -N 4
#SBATCH --ntasks-per-node 64 
#SBATCH --exclusive 
#SBATCH -t 144:00:00
export I_MPI_PMI_LIBRARY=/opt/gridview/slurm/lib/libpmi2.so
ulimit -s unlimited

module purge
module load compiler/intel/2021.3.0
module load mpi/intelmpi/2021.3.0

export UCX_TLS=dc,self
export PATH=/public/home/yaodongqi/softwares/vaspkit.1.3.5/bin/:$PATH
export PATH=/public/home/yaodongqi/VASP:$PATH

echo "============================================================"
env | grep "MKLROOT="
echo "============================================================"
echo "Job ID: $SLURM_JOB_NAME"
echo "Job name: $SLURM_JOB_NAME"
echo "Number of nodes: $SLURM_JOB_NUM_NODES"
echo "Number of processors: $SLURM_NTASKS"
echo "Task is running on the following nodes:"
echo $SLURM_JOB_NODELIST
echo "OMP_NUM_THREADS = $SLURM_CPUS_PER_TASK"
echo "============================================================"
# echo

# ln -sf /public/home/wbchu/src/VASP/vdw_kernel.bindat .
srun --mpi=pmi2 vasp_optcell
#srun --mpi=pmi2 vasp_gam

# Check if jobs ended correctly
if grep 'Total CPU' OUTCAR >& /dev/null; then
# If so, mark the job as ENDED
   echo "CONGRATULATIONS!!!"
else
   exit 1
fi

rm CHG vasprun.xml
#######################################################
#prepare scf calculation
#######################################################
mkdir scf
cp KPOINTS INCAR POTCAR scf/
cd scf
cp ../CONTCAR POSCAR
# sed -i "s/.*LWAVE.*/LWAVE = .TRUE./" INCAR
sed -i "s/.*LCHARG.*/LCHARG = .TRUE./" INCAR
# sed -i "s/.*LREAL.*/LREAL  = Auto/" INCAR
# sed -i "s/.*ISYM.*/# ISYM = 0/" INCAR
sed -i "s/.*KPAR.*/KPAR = 2/" INCAR
sed -i '/Lattice Relaxation/,+4d' INCAR
sed -i '/Static Calculation/,+4d' INCAR
sed -i '/Electronic Relaxation/,+9d' INCAR
# sed -i '4s/.*/   1   1   1/' KPOINTS
cat INCAR ../../incars/4_SCFincar > SCFINCAR
mv SCFINCAR INCAR
sed -i "s/.*EDIFF.*/EDIFF  =  1E-08/" INCAR

#srun vasp_std
#srun vasp_gam
srun --mpi=pmi2 vasp_std

# Check if jobs ended correctly
if grep 'Total CPU' OUTCAR >& /dev/null; then
# If so, mark the job as ENDED
   echo "CONGRATULATIONS!!!"
else
   exit 1
fi

rm CHG vasprun.xml

####################################################
#prepare band calculation
####################################################
mkdir band
cp * band/
ln ../../Scripts/plot.py band/
#ln ../../Scripts/plot_horizon.py band/
cd band
# sed -i "s/.*LWAVE.*/LWAVE = .FALSE./" INCAR
sed -i "s/.*ICHARG.*/ICHARG =  11/" INCAR
# sed -i "s/.*KPAR.*/KPAR =  2/" INCAR
echo -e "302" | vaspkit # 2D structure
# sed -i '2s/.*/   10/' KPATH.in
cp KPATH.in KPOINTS

srun --mpi=pmi2 vasp_std

# Check if jobs ended correctly
if grep 'Total CPU' OUTCAR >& /dev/null; then
# If so, mark the job as ENDED
   echo "CONGRATULATIONS!!!"
else
   exit 1
fi

rm CHG vasprun.xml

echo -e "211" | vaspkit

cat BAND_GAP

# pyband -y -3 3
pyband --occ '1 3' --occ '2 4'
python plot.py
#python plot_horizon.py
