#!/bin/bash
INCAR_OPT=STLRD3
KPT_AC=0.02

echo -e "103" | vaspkit #default POTCAR
mkdir 0_pc
mv POSCAR 0_pc/
ln POTCAR 0_pc/
cd 0_pc
echo -e "406\n3\n1" | vaspkit
cp POSCAR_REV POSCAR
echo -e "101\n${INCAR_OPT}" | vaspkit
sed -i '19a NCORE = 8' INCAR
ENMAX=$(grep ENMAX POTCAR | awk '{print $3}' | sort -n | tail -1 | tr -d ';')
sed -i "s/.*ISTART.*/ISTART =  0/" INCAR
sed -i "s/.*SIGMA.*/SIGMA  =  0.1/" INCAR
sed -i "s/.*ENCUT.*/ENCUT  =  $(echo "$ENMAX * 1.3" | bc)/" INCAR
sed -i "s/.*LWAVE.*/LWAVE  = .FALSE./" INCAR
sed -i "s/.*LCHARG.*/LCHARG = .FALSE./" INCAR
sed -i "s/.*PREC.*/PREC   =  Accurate/" INCAR
sed -i "s/.*ADDGRID.*/# ADDGRID= .FALSE./" INCAR
sed -i "s/.*NWRITE.*/NWRITE = 1/" INCAR
sed -i "s/.*EDIFFG.*/EDIFFG = -0.01/" INCAR
sed -i 's/ *(\([^)]*\)) *$//' INCAR #去掉注释
line=$(grep -n Lattice INCAR | awk -F ':' '{print $1}')
line=$((line+7))
sed -i "${line}d" INCAR
line=$((line-5))
sed -i "${line},+1d" INCAR
line=$((line-23))
sed -i "${line},+19d" INCAR
sed -i '/Static Calculation/d' INCAR
sed -i '/SIGMA.*/a Static Calculation' INCAR
echo -e "102\n2\n${KPT_AC}" | vaspkit

echo "Remember to check the INCAR file!"

../queue.sh ../sub_vasp
../queue.sh ../bandcalculate.sh

echo "Remember to check if use OPTCELL"
cp ../incars/OPTCELL .
