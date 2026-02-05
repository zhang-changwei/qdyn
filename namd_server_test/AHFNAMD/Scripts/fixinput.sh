#!/bin/bash

BMIN=289
BMAX=299
INIBAND=294
NSAMPLE=100
Min_value=2
Max_value=500
NSW=$(grep -oP '(?<=NSCF=)\d+' ../scf.sh)
NAMDTIME=1000
LHOLE=.FALSE.

sed -i "s/count =.*/count = ${NSAMPLE}/" generate_inicon.py
sed -i "s/iniband =.*/iniband = ${INIBAND}/" generate_inicon.py
sed -i "s/min_value =.*/min_value = ${Min_value}/" generate_inicon.py
sed -i "s/max_value =.*/max_value = ${Max_value}/" generate_inicon.py
python generate_inicon.py

sed -i "s/BMIN       =.*/BMIN       = ${BMIN}/" inp
sed -i "s/BMAX       =.*/BMAX       = ${BMAX}/" inp
sed -i "s/NSAMPLE    =.*/NSAMPLE    = ${NSAMPLE}/" inp
sed -i "s/NSW        =.*/NSW        = $(($NSW - 1))/" inp
sed -i "s/NAMDTIME   =.*/NAMDTIME   = ${NAMDTIME}/" inp
sed -i "s/LHOLE      =.*/LHOLE      = ${LHOLE}/" inp

sed -i "s/nsw     =.*/nsw     = ${NSW}/" poen_fssh.py
sed -i "s/namdTime =.*/namdTime = ${NAMDTIME}/" poen_fssh.py
sed -i "s/bmin     =.*/bmin     = ${BMIN}/" poen_fssh.py
sed -i "s/bmax     =.*/bmax     = ${BMAX}/" poen_fssh.py

sed -i "s/is_hole  =.*/is_hole  = ${LHOLE}/" population.py
sed -i "s/NSAMPLE  =.*/NSAMPLE  = ${NSAMPLE}/" population.py
sed -i "s/NAMDTIME =.*/NAMDTIME = ${NAMDTIME}/" population.py

sed -i "s/T_end   =.*/T_end   = ${NSW}/" input.py
sed -i "s/bmin    =.*/bmin    = ${BMIN}/" input.py
sed -i "s/bmax    =.*/bmax    = ${BMAX}/" input.py

sed -i "s/bmin=.*/bmin=${BMIN}/" Dephase.py
sed -i "s/bmax=.*/bmax=${BMAX}/" Dephase.py

sed -i "s/BMIN=.*/BMIN=${BMIN}/" namd_sub
sed -i "s/BMAX=.*/BMAX=${BMAX}/" namd_sub

../queue.sh namd_sub
