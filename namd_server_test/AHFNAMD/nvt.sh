#!/bin/bash
NSW=1000

mkdir 2_NVT
cp 1_sc/INCAR 1_sc/CONTCAR 1_sc/KPOINTS 2_NVT/
ln Scripts/vaspT.py Scripts/dist.py Scripts/continue.sh 2_NVT/
ln POTCAR 2_NVT/
cd 2_NVT
sed -i '/Electronic Relaxation/,+9d' INCAR
cat INCAR ../incars/2_NVTincar > NVTINCAR
mv NVTINCAR INCAR
sed -i "s/.*NSW.*/  NSW     = ${NSW}/" INCAR
sed -i "s/.*LREAL.*/LREAL  =  Auto/" INCAR
sed -i "s/.*PREC.*/# PREC   =  Accurate/" INCAR

mv CONTCAR POSCAR 
natom=$(sed -n '7p' POSCAR | grep -o '[0-9]\+' | awk '{sum += $1} END {print sum}')
echo $natom
line=$((natom+9))
sed -i "${line}, \$d" POSCAR

sed -i '/^#SBATCH -J/s/_[^_]*$//' ../sub_vasp
sed -i '/^#SBATCH -J/s/$/_NVT/' ../sub_vasp
../queue.sh ../sub_vasp
# sbatch ../sub_vasp
