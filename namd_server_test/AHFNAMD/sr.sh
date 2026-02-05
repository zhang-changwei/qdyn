#!/bin/bash

mkdir 1_sc
cp 0_pc/INCAR 0_pc/CONTCAR 1_sc/
ln POTCAR 1_sc/
cd 1_sc
sed -i '/Static Calculation/,+4d' INCAR
sed -i '/Lattice Relaxation/,+4d' INCAR
cat INCAR ../incars/1_SRincar > SRINCAR
mv SRINCAR INCAR
sed -i '/^#SBATCH -J/s/_[^_]*$//' ../sub_vasp
sed -i '/^#SBATCH -J/s/$/_sc/' ../sub_vasp
