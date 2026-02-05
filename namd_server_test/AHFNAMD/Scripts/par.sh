#!/bin/bash

prefix=AAPd

mkdir par 
cp INCAR KPOINTS POSCAR POTCAR CHGCAR WAVECAR par/
cd par
sed -i "s/.*ISTART.*/ISTART =  1/" INCAR
sed -i "s/KPAR/# KPAR/" INCAR
sed -i '$a LPARD=.TRUE.' INCAR
sed -i '$a LSEPB=.TRUE.' INCAR
sed -i '$a LSEPK=.FALSE.' INCAR
#sed -i '$a LSEPK=.TRUE.' INCAR
#sed -i '$a KPUSE= 1' INCAR
sed -i '$a IBAND= 285 286 287 288 289 290 291' INCAR

output=$(sbatch ../../sub_vasp)
job_id=$(echo $output | awk '{print $4}')

while [ ! -f "slurm-${job_id}.out" ]; do
  echo "等待文件生成..."
  sleep 1  # 每隔1秒检查一次
done

echo "文件已生成，执行下一个命令..."

tail -f "slurm-${job_id}.out" | tee /dev/tty | while read LINE; do
  echo "$LINE" | grep -q "VASP will stop now."
  if [ $? -eq 0 ]; then
    echo "找到特定句子，退出监测..."
    pkill -P $$ tail  # 终止 tail -f 进程
    break
  fi
done

echo "执行下一个命令..."

step=$(basename "$(dirname "$PWD")")

count=$(ls PARCHG* 2>/dev/null | wc -l)
for file in PARCHG*; do
    if [ -f "$file" ]; then
        mv "$file" "${prefix}_${step}_${file}.vasp"
    fi
done
