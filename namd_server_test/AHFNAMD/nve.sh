#!/bin/bash
NSW=1000

mkdir 3_NVE

# 查找当前文件夹及其子文件夹中最新的 CONTCAR 文件
latest_contcar=$(find 2_NVT/ -type f -name "CONTCAR" -exec stat --format '%Y %n' {} + | sort -n | tail -1 | awk '{print $2}')

# 检查是否找到最新的 CONTCAR 文件
if [ -n "$latest_contcar" ]; then
    echo "最新的 CONTCAR 文件是: $latest_contcar"
    # 将最新的 CONTCAR 文件复制为 POSCAR
    cp "$latest_contcar" 3_NVE/POSCAR
    echo "已将 $latest_contcar 复制为 3_NVE/POSCAR"
else
    echo "未找到任何 CONTCAR 文件"
fi

cp 2_NVT/INCAR 2_NVT/KPOINTS 3_NVE/
ln Scripts/ksen_from_outcar.py Scripts/vaspT.py 3_NVE/
ln POTCAR 3_NVE/
cd 3_NVE
sed -i '/Electronic relaxation/,+14d' INCAR
cat INCAR ../incars/3_NVEincar > NVEINCAR
mv NVEINCAR INCAR
sed -i "s/.*NSW.*/  NSW     = ${NSW}/" INCAR

sed -i '/^#SBATCH -J/s/_[^_]*$//' ../sub_vasp
sed -i '/^#SBATCH -J/s/$/_NVE/' ../sub_vasp
../queue.sh ../sub_vasp
