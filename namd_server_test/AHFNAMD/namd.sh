#!/bin/bash

GAMMA=True
dirname=spindown

file_sizes=$(ls -l 4_SCF/*/WAVECAR | awk '{print $5}' | uniq -c)
echo "$file_sizes"
if [[ $(echo "$file_sizes" | wc -l) -gt 1 ]]; then
    echo "File sizes are not consistent. Exiting program."
    exit 1
fi

mkdir ${dirname}
cp incars/5_dishinp ${dirname}/inp
cd Scripts/
cp generate_inicon.py input.py population.py Dephase.py fixinput.sh dishnamd_sub ../${dirname}/
# cp incars/5_fsshspinp ${dirname}/inp
# cd Scripts/
# cp generate_inicon.py input.py poen_fssh.py fixinput.sh namd_sub ../${dirname}/
cd ../${dirname}
mv dishnamd_sub namd_sub

touch COUPCAR
CB=$(cat ../CBindex)
BMAX_stored=$(($CB + 10))
BMIN_stored=$(($CB - 11))
sed -i "s/bmin_stored    =.*/bmin_stored    = ${BMIN_stored}/" input.py
sed -i "s/bmax_stored    =.*/bmax_stored    = ${BMAX_stored}/" input.py
sed -i "s/is_gamma_version  =.*/is_gamma_version  = ${GAMMA}/" input.py
