#!/bin/bash

cd AHFNAMD
cp -r incars/ Scripts/ ../
ln bandcalculate.sh namd.sh nve.sh nvt.sh pc.sh python_sub queue.sh scf.sh sr.sh sub_vasp ../
cd ..
NAME=$(basename "$PWD")
sed -i "s/.*#SBATCH -J .*/#SBATCH -J $NAME/" sub_vasp
sed -i "s/.*#SBATCH -J .*/#SBATCH -J ${NAME}_SCF/" Scripts/vaspscf
sed -i "s/.*#SBATCH -J .*/#SBATCH -J ${NAME}_NAMD/" Scripts/dishnamd_sub
sed -i "s/.*#SBATCH -J .*/#SBATCH -J ${NAME}_NAMD/" Scripts/namd_sub
sed -i "s/.*#SBATCH -J .*/#SBATCH -J ${NAME}_tdksen/" python_sub
sed -i "s/.*#SBATCH -J .*/#SBATCH -J ${NAME}_band/" bandcalculate.sh
