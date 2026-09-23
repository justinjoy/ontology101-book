import re, sys

# stdin 또는 파일에서 cell(...) 라인을 읽음
data = sys.stdin.read()
matches = re.findall(r"cell\((\d+),(\d+),(\d+)\)", data)

# 9x9 배열 초기화
grid = [[0]*9 for _ in range(9)]
for r, c, n in matches:
    grid[int(r)-1][int(c)-1] = int(n)

# 시각화
print("+-------+-------+-------+")
for i, row in enumerate(grid):
    line = ""
    for j, v in enumerate(row):
        if j % 3 == 0:
            line += "| "
        line += str(v) + " "
    line += "|"
    print(line)
    if i % 3 == 2:
        print("+-------+-------+-------+")
