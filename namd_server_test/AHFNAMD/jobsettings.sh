#!/bin/bash

# 检查是否提供了输入文件名
if [ -z "$1" ]; then
  echo "请提供输入文件名作为参数。"
  exit 1
fi

input_file="$1" # 使用命令行参数作为输入文件名

# 获取每个队列的idle节点数，并找到idle数最多的队列
max_idle=0
target_queue=""

while read -r line; do
  queue=$(echo "$line" | awk '{print $1}')
  if [[ "$queue" != "debug" ]]; then
    idle=$(echo "$line" | awk '{print $3}')
    idle=${idle//[!0-9]/} # 仅保留数字

    if [[ "$idle" -gt "$max_idle" ]]; then
      max_idle=$idle
      target_queue=$queue
    fi
  fi
done < <(sinfo -o "%P %t %D %C" | grep idle)

# 去除队列名称后的*号，如果有的话
target_queue=${target_queue%\**}

# 修改输入文件中的队列名称
if [[ -n "$target_queue" ]]; then
  sed -i "s/^#SBATCH -p .*/#SBATCH -p $target_queue/" "$input_file"
  echo "$input_file 文件已更新，队列设置为: $target_queue"
else
  echo "未找到空闲队列"
  exit 1
fi

# 根据idle数设置new_nodes的值，但不超过4
if [[ "$max_idle" -ge 8 ]]; then
  new_nodes=4
elif [[ "$max_idle" -ge 6 ]]; then
  new_nodes=3
elif [[ "$max_idle" -gt 4 ]]; then
  new_nodes=2
else
  new_nodes=1
fi

# 修改sub_vasp文件中的占用节点数
sed -i "s/^#SBATCH -N [0-9]*/#SBATCH -N $new_nodes/" "$input_file"
echo "$input_file 文件已更新，占用节点数设置为: $new_nodes"