"""把 grey_cloud_ascii.html 里烘焙好的实测数据同步到其它作品文件。

    python measure/sync_data.py <目标.html> [<源.html>]

为什么要有这个：CURVES / STEMS 是从 mp3 实测烘焙出来的大数组（约 34 KB），
两个作品要用同一份。复制粘贴必然漂移——一个文件重烘焙了、另一个还在用旧的，
画面对不上还查不出来。所以定死单一来源：源文件是 grey_cloud_ascii.html，
目标文件里放一对标记，脚本整段替换。
"""
import io, re, sys, pathlib

HERE = pathlib.Path(__file__).resolve().parent
SRC_DEFAULT = HERE.parent / "grey_cloud_ascii.html"
START, END = "/*==DATA-START==*/", "/*==DATA-END==*/"

# 从 `const STEMS={` 到 demoSample 收尾的 `}`——这一段是自包含的实测数据 + 取样函数
BLOCK_RE = re.compile(r"// 实测曲线（0\.5s 一格.*?\nfunction demoSample\(t\)\{.*?\n\}", re.S)


def main():
    if len(sys.argv) < 2:
        print(__doc__); sys.exit(1)
    dst = pathlib.Path(sys.argv[1])
    src = pathlib.Path(sys.argv[2]) if len(sys.argv) > 2 else SRC_DEFAULT
    s = io.open(src, encoding="utf-8").read()
    m = BLOCK_RE.search(s)
    if not m:
        print(f"FAIL 源文件里找不到实测数据块：{src}")
        sys.exit(1)
    block = m.group(0)
    d = io.open(dst, encoding="utf-8").read()
    if START not in d or END not in d:
        print(f"FAIL 目标文件缺少 {START} / {END} 标记：{dst}")
        sys.exit(1)
    new = re.sub(re.escape(START) + r".*?" + re.escape(END),
                 START + "\n" + block + "\n" + END, d, flags=re.S)
    io.open(dst, "w", encoding="utf-8", newline="").write(new)
    keys = re.findall(r"\n  (\w+):", block)
    print(f"OK {src.name} -> {dst.name}   注入 {len(block)/1024:.1f} KB   字段: {' '.join(keys)}")


if __name__ == "__main__":
    main()
