# -*- coding: utf-8 -*-
"""
生成「可上传 GitHub」的项目副本（v29 竖屏版 · 公开版 · 不含密钥）。

要点：
  1. 每次运行先清空目标目录 —— 保证仓库内容整体替换，旧文件不会残留（含旧横屏版）。
  2. 剔除一切密钥：出厂 AI API Key（DEF_ZHIPU_KEY）置空；仓库不含签名私钥、不含中间产物。
  3. 以「已构建好的 v29 竖屏个人版 APK」抽出其 dashboard.html（已是竖屏变换后的版本），
     去密钥后单独打包成公开版竖屏 APK；保证上传的程序也不含密钥、且确为竖屏布局。
  4. 生成后全量扫一遍，断言密钥字符串在导出目录里 0 出现（含 APK 压缩包内）。
  5. 不再产出横屏版（用户已弃用横屏版本）。

用法：
    python build_github_export.py            # 清空旧内容后重新生成
    python build_github_export.py --keep      # 跳过清空，只覆盖写入（沙箱拦截清空后补文件用）
"""
import io, os, re, shutil, subprocess, sys, zipfile

BASE = "C:/Users/Administrator/WorkBuddy/2026-09-13-03-27-43/kindle_dashboard"
DST = "C:/Users/Administrator/WorkBuddy/2026-09-13-03-27-43/kindle_dashboard_github"

VER = "V29"
APP_NAME = "水哥拯救墨水屏"
AUTHOR = "水哥（WATERS）"
PY = "C:/Users/Administrator/.workbuddy/binaries/python/envs/default/Scripts/python.exe"

# 竖屏个人版 APK（已构建好），从中抽出去密钥的竖屏源码来打包公开版
POR_APK = os.path.join(BASE, "KindleDash_A5_v29_portrait.apk")

# 需要从源码里抹掉的密钥（本地版保留，公开版置空）
SECRETS = [
    (re.compile(r'var DEF_ZHIPU_KEY\s*=\s*"[^"]*";'),
     'var DEF_ZHIPU_KEY = "";   /* 公开版：请填入你自己的 Key */'),
]


def scrub(text):
    for pat, rep in SECRETS:
        text, n = pat.subn(rep, text)
        print("    scrub 命中 %d 处：%s" % (n, pat.pattern))
        assert n > 0, "密钥模式没命中，导出中止（可能是源码结构变了）"
    return text


def neutralize_ai_api(text):
    """公开版：彻底移除 AI 接口（端点 + 默认开启 + 请求函数），使其不向任何 AI API 发请求。
    仅作用于导出副本；本地个人版源码不受影响（仍保留可用 AI）。"""
    # 1) 清空 AI_PROVIDERS 表里的所有 API 端点（域名为 https?://... 的 base）
    m = re.search(r"var AI_PROVIDERS\s*=\s*\{.*?\n\};", text, re.S)
    assert m, "找不到 AI_PROVIDERS 表，导出中止"
    block = m.group(0)
    nb = re.sub(r'base:\s*"https?://[^"\n]*"', 'base: ""', block)
    nbase = len(re.findall(r'base:\s*"https?://', block))
    text = text[:m.start()] + nb + text[m.end():]
    print("    AI 端点清空：%d 处 base 改为空" % nbase)
    # 2) 出厂默认关闭 AI（enabled: true -> false），并把硬编码 baseUrl 置空
    text, n1 = re.subn(
        r'enabled:\s*true,\s*provider:\s*"zhipu",\s*apiKey:\s*DEF_ZHIPU_KEY,\s*baseUrl:\s*"https://open\.bigmodel\.cn/api/paas/v4",',
        'enabled: false, provider: "zhipu", apiKey: DEF_ZHIPU_KEY, baseUrl: "",',
        text)
    assert n1 == 1, "AI 默认配置未命中（%d）" % n1
    print("    AI 出厂默认关闭：enabled -> false")
    # 3) 桩掉 aiFetch，任何情况下都不向 AI API 发请求
    text, n2 = re.subn(
        r"function aiFetch\(url, key, body, ok, fail\)\s*\{.*?\n\}",
        'function aiFetch(url, key, body, ok, fail) {\n'
        '  /* 公开版：AI 接口已移除，不向任何 AI API 发起网络请求 */\n'
        '  if (typeof fail === "function") { fail("AI 接口已在公开版中移除"); }\n'
        "}",
        text, flags=re.S)
    assert n2 == 1, "aiFetch 桩替换未命中（%d）" % n2
    print("    AI 请求函数已桩掉（不发起任何网络请求）")
    # 4) 清掉设置界面里残留的 AI 接口示例地址（占位符 / 提示文案），公开版不出现任何 AI API URL
    text, n3 = re.subn(r'placeholder="如 https://api\.deepseek\.com"',
                        'placeholder="你的 AI 接口地址"', text)
    text, n4 = re.subn(r'智谱\(open\.bigmodel\.cn\)', '智谱', text)
    print("    AI 接口示例地址清理：占位符 %d 处、提示文案 %d 处" % (n3, n4))
    return text


def copy(src_rel, dst_rel, scrub_it=False):
    s = os.path.join(BASE, src_rel)
    d = os.path.join(DST, dst_rel)
    os.makedirs(os.path.dirname(d), exist_ok=True)
    if not os.path.exists(s):
        print("  [skip] 源文件不存在:", src_rel)
        return False
    if scrub_it:
        t = io.open(s, encoding="utf-8").read()
        t = scrub(t)
        io.open(d, "w", encoding="utf-8", newline="\n").write(t)
    else:
        shutil.copy2(s, d)
    print("  + %-46s %8d 字节" % (dst_rel, os.path.getsize(d)))
    return True


print("=" * 78)
print("生成 GitHub 导出目录:", DST)
print("=" * 78)

# ---- 1. 清空（保证旧内容被删掉，含旧横屏版） ----
KEEP = "--keep" in sys.argv
if os.path.isdir(DST) and not KEEP:
    for name in os.listdir(DST):
        if name == ".git":
            continue           # 保留 git 历史，让同步脚本能 force push
        p = os.path.join(DST, name)
        if os.path.isdir(p):
            shutil.rmtree(p)
        else:
            os.remove(p)
    print("已清空旧内容（保留 .git）")
elif KEEP:
    print("--keep：跳过清空，直接覆盖写入")
os.makedirs(DST, exist_ok=True)

# ---- 2. 竖屏源码（从个人版竖屏 APK 抽出并去密钥） ----
print("\n[资源]")
if not os.path.exists(POR_APK):
    print("!!! 缺少竖屏个人版 APK：", POR_APK)
    sys.exit(1)
z = zipfile.ZipFile(POR_APK)
por_html = z.read("assets/dashboard.html").decode("utf-8", "replace")
z.close()
por_html = scrub(por_html)
por_html = neutralize_ai_api(por_html)
os.makedirs(os.path.join(DST, "assets"), exist_ok=True)
io.open(os.path.join(DST, "assets/dashboard_a5.html"), "w", encoding="utf-8", newline="\n").write(por_html)
print("  + assets/dashboard_a5.html  (竖屏源码，已去密钥) %8d 字节" % len(por_html))

copy("extracted/assets/radio_presets.js", "assets/radio_presets.js")
copy("extracted/assets/hls.min.js", "assets/hls.min.js")
copy("poems_cn.txt", "assets/poems_cn.txt")
copy("poems_en.txt", "assets/poems_en.txt")

print("\n[文档]")
copy("docs/开发经验教训与提示词库.txt", "docs/开发经验教训与提示词库.txt")

print("\n[构建脚本]")
TOOLS = [
    "build_versions.py",        # 竖屏+横屏 个人版双构建
    "repackage_a5.py",          # 单 APK 重打包 + 重签（v1+v2）
    "verify_apksigner.py",      # 官方 apksigner 校验封装
    "apk_sign_v2.py",           # 纯 Python APK Signature Scheme v2
    "axml_info.py",             # 二进制清单解析
    "patch_manifest_v27.py", "manifest_a5_v27.bin",
    "patch_manifest_v28.py", "manifest_a5_v28.bin",
    "patch_manifest_v29.py", "manifest_a5_v29.bin",
    "build_github_export.py", "sync_github.py",
]
for f in TOOLS:
    copy(f, "tools/" + f)

# ---- 3. 公开版竖屏 APK（用去密钥的竖屏源码打包） ----
print("\n[公开版竖屏 APK]")
pub_html = os.path.join(DST, "assets/dashboard_a5.html")
pub_apk = os.path.join(DST, "release/%s.apk" % ("KindleDash_A5_" + VER.lower() + "_portrait"))
os.makedirs(os.path.dirname(pub_apk), exist_ok=True)
r = subprocess.run([PY, os.path.join(BASE, "repackage_a5.py"), pub_html, pub_apk],
                   capture_output=True, text=True)
print((r.stdout or "")[-600:])
if r.returncode != 0 or not os.path.exists(pub_apk):
    print("公开版 APK 打包失败：", (r.stderr or "")[-800:])
    sys.exit(1)
print("  + release/%s  %d 字节" % (os.path.basename(pub_apk), os.path.getsize(pub_apk)))

# ---- 4. README / .gitignore / VERSION ----
README = """# {name}

作者：{author}　　版本：{ver}（竖屏版）　　适用：Android 4.0（API 14）～ Android 16（API 36）

墨水屏（海信 A5 / Kindle 553 / TopSir H9 等）常显仪表盘：时钟、日历、天气与灾害预警、
新闻 RSS、诗歌、电台收听、AI 问答。全部逻辑内嵌在单个 HTML 里，由 Android 壳工程
（WebView）加载；网络请求走原生通道，避开老 WebView 的种种限制。

本仓库提供 **竖屏版**（已弃用横屏版）。

## 目录结构

```
assets/dashboard_a5.html   主程序（竖屏，单文件，内嵌 CSS/JS/诗歌语料）
assets/radio_presets.js    内置电台库
assets/hls.min.js          m3u8 播放兜底（第三方，MIT）
assets/poems_*.txt         中英文诗歌语料源文件
docs/开发经验教训与提示词库.txt   踩坑实录 + 可复用的开发提示词
tools/                     打包 / 校验 / 导出脚本
release/                   打包好的 APK（竖屏公开版，不含任何密钥）
```

## 构建

```bash
# 用当前源码重打竖屏公开版 APK（需先装 cryptography / asn1crypto）
python tools/repackage_a5.py
python tools/verify_apksigner.py release/KindleDash_A5_v29_portrait.apk
# 或做个人版（含可用 AI）：请用本地源码编译，并在 DEF_ZHIPU_KEY 填入你的 Key，再重打
```

依赖：`cryptography`、`asn1crypto`（仅打包/校验用）。

## 关于密钥

**本仓库不含任何密钥，且公开版已移除 AI 接口。** 出厂 AI Key 在源码里置空、
所有 AI 服务商端点被清空、AI 请求函数被桩掉，公开版不会向任何 AI API 发起请求，
AI 助手默认关闭。如需使用 AI，请用本地源码自行编译个人版并填入自己的 Key。
签名私钥、本地调试产物均不在仓库内（见 .gitignore）。

## 版权声明

本程序（含全部源代码、界面设计、内置电台与新闻源清单、文案与数据组织方式）
由作者 {author} 独立原创开发，作者对上述内容依法享有完整的著作权及其他一切合法权益。
未经作者书面许可，任何单位或个人不得对本程序实施反编译、逆向工程、修改、
删改版权信息、二次打包、再次分发或用于任何商业用途。
本程序中引用的第三方公开数据接口与电台流媒体地址，其权利归各自权利人所有。

## 免责声明

本程序按「现状」提供，作者不提供任何明示或暗示的担保，包括但不限于对适用性、
准确性、及时性与不侵权的担保。因安装或使用本程序而产生的任何后果
（包括但不限于新闻、天气、灾害与地震预警信息的延迟、偏差、缺失或错误；
电台播放中断或无法连接；设备耗电加快、系统异常、数据丢失、存储空间占用；
以及据此作出的任何判断或行动），均由使用者自行承担，作者不承担任何法律责任。
天气、预警、地震等信息来自第三方公开接口，仅供参照，请以政府主管部门的官方发布为准。
""".format(name=APP_NAME, author=AUTHOR, ver=VER)

io.open(os.path.join(DST, "README.md"), "w", encoding="utf-8", newline="\n").write(README)
io.open(os.path.join(DST, "VERSION.txt"), "w", encoding="utf-8", newline="\n").write(
    "%s  %s  %s\n" % (APP_NAME, VER, AUTHOR))

GITIGNORE = """# 私钥与本地产物，绝不入库
signing_key.pem
signing_cert.pem
*.pem
*.apk.bak
.extracted/
_*.py
_*.js
_*.txt
_*.json
__pycache__/
*.pyc
.DS_Store
"""
io.open(os.path.join(DST, ".gitignore"), "w", encoding="utf-8", newline="\n").write(GITIGNORE)
print("\n[元文件] README.md / VERSION.txt / .gitignore 已生成")

# ---- 5. 全量复检：密钥必须 0 出现 ----
print("\n[密钥复检]")


def collect_secret_values():
    vals = []
    local = os.path.join(BASE, "extracted/assets/dashboard_a5.html")
    if os.path.exists(local):
        t = io.open(local, encoding="utf-8", errors="replace").read()
        for m in re.finditer(r'var\s+DEF_ZHIPU_KEY\s*=\s*"([^"]*)"', t):
            v = m.group(1)
            if v:
                vals.append(v)
                for part in v.split("."):
                    if len(part) >= 8:
                        vals.append(part)
    return [v for v in vals if v]


KEY_SNIPPETS = collect_secret_values()
print("  待查密钥片段数:", len(KEY_SNIPPETS))
if not KEY_SNIPPETS:
    print("  警告：没有从本地源码里抽到任何密钥，改为只做 PEM 文件存在性检查")

bad = 0
for root, dirs, files in os.walk(DST):
    if ".git" in root.split(os.sep):
        continue
    for fn in files:
        p = os.path.join(root, fn)
        try:
            if os.path.getsize(p) > 20 * 1024 * 1024:
                continue
            t = io.open(p, encoding="utf-8", errors="replace").read()
        except Exception:
            continue
        for k in KEY_SNIPPETS:
            if k in t:
                print("  !!! 密钥残留:", os.path.relpath(p, DST), k[:16])
                bad += 1
        # APK 是压缩包，单独拆开查
        if fn.lower().endswith(".apk"):
            try:
                zz = zipfile.ZipFile(p)
                for n in zz.namelist():
                    try:
                        c = zz.read(n).decode("utf-8", "replace")
                    except Exception:
                        continue
                    for k in KEY_SNIPPETS:
                        if k in c:
                            print("  !!! APK 内密钥残留:", fn, n, k[:16])
                            bad += 1
            except Exception as e:
                print("  (APK 读取失败)", e)

# 私钥文件绝不能入库
for f in ["signing_key.pem", "signing_cert.pem"]:
    p = os.path.join(DST, f)
    if os.path.exists(p):
        print("  !!! 私钥文件被带入:", f)
        bad += 1
    for root2, dirs2, files2 in os.walk(DST):
        if f in files2:
            print("  !!! 私钥文件被带入:", os.path.relpath(os.path.join(root2, f), DST))
            bad += 1

if bad:
    print("\n导出失败：仍有 %d 处问题" % bad)
    sys.exit(1)
print("  导出目录内密钥残留：0 处  OK")

print("=" * 78)
print("导出完成:", DST)
print("=" * 78)
