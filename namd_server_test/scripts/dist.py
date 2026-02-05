import numpy as np
from ase.io import read

import matplotlib as mpl
mpl.use('agg')
mpl.rcParams['axes.unicode_minus'] = False

import matplotlib.pyplot as plt

# 提取XDATCAR的第7排的第一个数字,计算第一个元素每层的原子数量
with open('XDATCAR', 'r') as f:
    line = f.readlines()[6]
    atoms_per_layer = int(int(line.split()[0]) * 0.5)

# 读取XDATCAR文件
atoms_list = read('XDATCAR', format='vasp-xdatcar', index=':')

# 初始化一个列表来存储每一步的层间距
layer_distances = []

# 遍历每一步的原子坐标
for atoms in atoms_list:

    # 获取所有原子的Z坐标
    z_coords = atoms.get_positions()[:, 2]

    # 计算上下两层的Z坐标平均值
    upper_layer_z = np.mean(z_coords[: atoms_per_layer])
    lower_layer_z = np.mean(z_coords[atoms_per_layer: atoms_per_layer * 2])

    # 计算上下两层的Z坐标差值
    layer_distance_diff = abs(upper_layer_z - lower_layer_z)

    # 将结果添加到列表中
    layer_distances.append(layer_distance_diff)

# 绘制层间距的变化图像
plt.plot(layer_distances)
plt.xlabel('Step')
plt.ylabel('Z-direction layer distance')
plt.title('Layer Distance Variation')
plt.savefig('Dist.png')
