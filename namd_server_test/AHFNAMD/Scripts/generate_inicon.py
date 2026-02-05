import random

if __name__ == "__main__":
    count = 100  # 生成的随机数数量
    iniband = 177
    min_value = 2  # 随机数的最小值
    max_value = 500  # 随机数的最大值
    file_path = 'INICON'  # 文件路径
    width = 3
    unique_random_numbers = random.sample(range(min_value, max_value + 1), count)
    with open(file_path, 'w') as file:
        for number in unique_random_numbers:
            file.write(f"  {number:>{width}} {iniband}\n")  # 在每个数字后添加一个空格

