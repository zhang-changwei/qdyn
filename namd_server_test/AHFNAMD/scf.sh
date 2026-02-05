#!/bin/bash

NSCF=2500
NDIGIT=$(echo -n $NSCF | wc -c)
batch=250

############################################################
mkdir 4_SCF
sed -i "7s/.*/NSCF   = ${NSCF}/" Scripts/genescf.py
cp 3_NVE/INCAR 3_NVE/KPOINTS 3_NVE/XDATCAR .
python Scripts/genescf.py
if [ -f "4_SCF/${NSCF}/POSCAR" ]; then
    # Continue with the script
    echo "SCF文件夹创建成功"
else
    echo "python程序执行错误"
    exit 1
fi
############################################################
sed -i "s/nsw     =.*/nsw     = ${NSCF}/" Scripts/tdksen.py
ymin=$(grep -w "VBM_energy" VBCB | awk '{print $2}')
ymax=$(grep -w "CBM_energy" VBCB | awk '{print $2}')
sed -i "s/ax.set_ylim.*/ax.set_ylim(${ymin}-0.5, ${ymax}+0.5)/" Scripts/tdksen.py
############################################################
sed -i "s/.*ICHARG.*/ICHARG =  1/" INCAR
sed -i "s/.*PREC.*/PREC   =  Accurate/" INCAR
sed -i "s/LWAVE.*/LWAVE  = .TRUE./" INCAR
sed -i "s/LCHARG.*/LCHARG = .TRUE./" INCAR
sed -i '/Electronic relaxation/,+12d' INCAR
cat INCAR incars/4_SCFincar > SCFINCAR
mv SCFINCAR INCAR
# CB=$(cat CBindex)
# NBAND=$(echo "($CB-1)*1.5" | bc | cut -d '.' -f 1)
# echo $NBAND
# sed -i "/NCORE/a NBAND = ${NBAND}" INCAR
############################################################
for i in `seq 1 ${NSCF}`
do
    ii=`printf "%0${NDIGIT}d" ${i}`
    cd 4_SCF/${ii}
    ln -sf ../../INCAR
    ln -sf ../../KPOINTS
    ln -sf ../../POTCAR
    cd ../../
done
############################################################
sed -i "s/NDIGIT=.*/NDIGIT=${NDIGIT}/" Scripts/vaspscf
./queue.sh Scripts/vaspscf
############################################################
remainder=$(($NSCF % $batch))
quotient=$(($NSCF / $batch))
echo "Remainder: $remainder"
echo "Quotient: $quotient"
mkdir runs
cd runs
for i in `seq 1 ${quotient}`
do
    order=$((i * $batch))
    cp ../Scripts/vaspscf vasp${order}
    sed -i "s/START=.*/START=$(($order - $batch + 1))/" vasp${order}
    sed -i "s/END=.*/END=${order}/" vasp${order}
    # ../queue.sh vasp${order}
    sbatch vasp${order}
done
if [ $remainder -ne 0 ]
then
    cp ../Scripts/vaspscf vasp${NSCF}
    sed -i "s/START=.*/START=$(($quotient * $batch + 1))/" vasp${NSCF}
    sed -i "s/END=.*/END=${NSCF}/" vasp${NSCF}
    ./queue.sh vasp${NSCF}
    sbatch vasp${NSCF}
fi
