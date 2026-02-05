#!/bin/bash

# 初始值 i
i=1

# 循环检查是否存在 "${i}suc" 文件夹
while [ -d "${i}suc" ]; do
    # 如果存在，则 i 加 1
    i=$((i + 1))
done

# 如果不存在，则创建 "${i}suc" 文件夹
mkdir "${i}suc"

# 检查是否存在 "${i-1}suc" 文件夹
prev=$((i - 1))
if [ -d "${prev}suc" ]; then
    # 如果存在，则复制文件
    cp "${prev}suc/INCAR" "${i}suc/"
    cp "${prev}suc/KPOINTS" "${i}suc/"
    cp "${prev}suc/CONTCAR" "${i}suc/POSCAR"
    cp POTCAR "${i}suc/"
    echo "已将 ${prev}suc 文件夹中的文件复制到 ${i}suc 文件夹中。"
else
    cp INCAR KPOINTS POTCAR "${i}suc/"
    cp CONTCAR "${i}suc/POSCAR"
    echo "已将该文件夹中的文件复制到 ${i}suc 文件夹中。"
fi

cd "${i}suc/"
../../queue.sh ../../sub_vasp
sbatch ../../sub_vasp
