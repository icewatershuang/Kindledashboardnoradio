# -*- coding: utf-8 -*-
"""v29：一次产出两个 APK —— 竖屏版 / 横屏版（均为个人版，无公共版）。

在 v28（天气实况 0.7× + 全部 v27 调整）基础上，本版修复后台 RSS 新闻的「准时更新」可靠性：
  - 新闻整轮刷新新增重入占用锁 _newsBusy + 代际令牌 _newsGen：
    定时刷新（每 fetchInterval 秒）若上一轮还在拉取，则跳过本轮、不再叠加重入，
    避免把正在显示的新闻冲掉/互相打转，保证后台更新不卡死、不重影；
  - 硬性看门狗：若某源永久挂起导致 afterAllNews 始终不触发，最迟
    max(60s, fetchInterval+30s) 后强制解占用，下一轮定时刷新一定还能启动；
  - 用户点【强制刷新】/【立刻刷新】/换日自动刷新 走 loadNews(true)，绕开占用立即重抓。
其余 v28/v27 的所有竖屏专属默认与新闻直连修复保持不变，横屏版不受影响。

实现思路：以 extracted/assets/dashboard_a5.html（v29 合一代码）为基线，
通过文本变换分出两个变体，再各自走 repackage_a5.py（已指向 manifest_a5_v29.bin）。

两版均应用「日历节假日去框改灰底白字高亮」修法（v26 选定方案，墨水屏可见、彻底无方框压字）。
包名 / versionCode 完全相同（com.kindledash.app / 693），可互相覆盖升级；
manifest versionName 统一 V29，屏内版本号带 竖屏版/横屏版 后缀便于区分。

用法：python build_versions.py
"""
import io, os, re, subprocess, sys

BASE = "C:/Users/Administrator/WorkBuddy/2026-09-13-03-27-43/kindle_dashboard"
SRC = os.path.join(BASE, "extracted/assets/dashboard_a5.html")
OUT_POR = os.path.join(BASE, "KindleDash_A5_v29_portrait.apk")
OUT_LAN = os.path.join(BASE, "KindleDash_A5_v29_landscape.apk")
PY = "C:/Users/Administrator/.workbuddy/binaries/python/envs/default/Scripts/python.exe"


def read_src():
    return io.open(SRC, encoding="utf-8", newline="").read()


# ---------------- 文本变换 ----------------
def _replace_once(s, old, new, what):
    """普通精确替换，断言恰好命中 1 次。"""
    n = s.count(old)
    assert n == 1, "「%s」命中 %d 次（期望 1）" % (what, n)
    return s.replace(old, new, 1)


def _remove_block(s, label_re, hint_re):
    """删掉一个设置行（label+select/button）及其下方说明 div。"""
    s2 = re.sub(label_re, "", s, flags=re.S)
    assert s2 != s, "未匹配到设置行：%s" % label_re
    s3 = re.sub(hint_re, "", s2, flags=re.S)
    return s3


def apply_calendar_fix(s):
    """v26 选定方案（用户拍板）：去框改底色高亮。
    B&W 墨水屏上浅色底色不可见，故用「灰底白字」实心填充区分节假日，
    彻底去掉方框线，线再也不可能压住日期数字/节日文字。"""
    old = ('.calendar td.hol { border: 1px solid #000; padding: 7px 9px; overflow: visible; }'
           '  /* v24：加大内边距 + 不裁切，避免方框压住日期与节日名 */')
    new = ('.calendar td.hol { background: #666; color: #fff; padding: 5px 3px; overflow: visible; }'
           '  /* v26：去框改灰底白字高亮（墨水屏可见），彻底无方框压字 */')
    return _replace_once(s, old, new, "日历 hol 灰底高亮")


def apply_common(s):
    """两版共同：删 屏幕方向(stRotate) 与 布局方向(stLayoutDir) 两个横屏相关设置行，
    并应用日历 outline 修法。"""
    s = apply_calendar_fix(s)
    # 屏幕方向（旋转）
    s = _remove_block(
        s,
        r'\s*<label class="row"><span>屏幕方向（旋转）</span>\s*<select id="stRotate">.*?</select></label>',
        r'\s*<div class="hint">竖屏沿用原版不变；.*?</div>')
    # 布局方向（自动随设备）
    s = _remove_block(
        s,
        r'\s*<label class="row"><span>布局方向（自动随设备）</span>\s*<select id="stLayoutDir">.*?</select></label>',
        r'\s*<div class="hint">旋转已统一由上方【屏幕方向】控制，且完全不受设备方向影响；此【布局方向】选项仅记录偏好，不影响实际旋转。</div>')
    return s


def apply_portrait(s):
    """竖屏版：纯纵向。强制 ROT=0；删横屏专属的 诗歌占比 / 板块尺寸 设置；
    保存时不再读取已删除的 stRotate。"""
    s = apply_common(s)
    # 横屏·诗歌占比（stLsPoem）
    s = _remove_block(
        s,
        r'\s*<label class="row"><span>横屏·诗歌占比</span>\s*<select id="stLsPoem"[^>]*>.*?</select></label>',
        r'\s*<div class="hint">横屏宽版下，诗歌板块占用「中部左栏」剩余高度的比例，天气占其余。改了立即按新比例重排并保存。</div>')
    # 横屏板块尺寸（lsResetBtn）
    s = _remove_block(
        s,
        r'\s*<label class="row"><span>横屏板块尺寸</span>\s*<button id="lsResetBtn"[^>]*>.*?</button></label>',
        r'\s*<div class="hint">清掉已冻结的横屏板块尺寸，下次进横屏时按内容重新测算一次；之后除非再点这里或调上面占比，否则不再自动调整。</div>')
    # 强制纵向：全部 ROT = (CFG.rotate || 0) 统一改 0（含 lsPoemShareChange / lsResetUi 内的）
    n = s.count("ROT = (CFG.rotate || 0)")
    assert n == 5, "ROT 旋转赋值命中 %d 次（期望 5）" % n
    s = s.replace("ROT = (CFG.rotate || 0)", "ROT = 0")
    # 保存时不再依赖已删除的 stRotate 控件
    s = _replace_once(
        s,
        'CFG.rotate = parseInt($("stRotate").value, 10) || 0;',
        'CFG.rotate = 0;   /* v25 竖屏版：固定纵向，忽略已存旋转设置 */',
        "竖屏版 saveConfig 强制 rotate=0")
    return s


def apply_landscape(s):
    """横屏版：纯横向宽版重排。强制 ROT=90；保留 诗歌占比/板块尺寸；
    保存时不再读取已删除的 stRotate。"""
    s = apply_common(s)
    # 强制横向：全部 ROT 统一改 90（含 lsPoemShareChange / lsResetUi 内的）
    n = s.count("ROT = (CFG.rotate || 0)")
    assert n == 5, "ROT 旋转赋值命中 %d 次（期望 5）" % n
    s = s.replace("ROT = (CFG.rotate || 0)", "ROT = 90")
    # 保存时不再依赖已删除的 stRotate 控件
    s = _replace_once(
        s,
        'CFG.rotate = parseInt($("stRotate").value, 10) || 0;',
        'CFG.rotate = 90;  /* v25 横屏版：固定横向宽版重排 */',
        "横屏版 saveConfig 强制 rotate=90")
    return s


def set_label(s, label):
    s, n = re.subn(r'(var KD_APP_VERSION\s*=\s*")[^"]*(")',
                   r'\g<1>' + label + r'\g<2>', s)
    assert n == 1, "KD_APP_VERSION 命中 %d 次" % n
    return s


def build(html_text, out_apk, tag):
    tmp = os.path.join(BASE, "_variant_%s.html" % tag)
    io.open(tmp, "w", encoding="utf-8", newline="").write(html_text)
    r = subprocess.run([PY, os.path.join(BASE, "repackage_a5.py"), tmp, out_apk],
                       cwd=BASE, capture_output=True, text=True)
    print("---- repackage %s ----\n%s" % (tag, r.stdout[-1800:]))
    if r.returncode != 0:
        print("STDERR:", r.stderr[-2500:])
        raise SystemExit("repackage %s 失败" % tag)
    try:
        os.remove(tmp)
    except OSError:
        pass
    print("已生成", out_apk, os.path.getsize(out_apk), "字节")


def main():
    html = read_src()
    # 原 Key 存在性自检（两版都保留 Key，属个人版）
    m = re.search(r'var DEF_ZHIPU_KEY\s*=\s*"([^"]*)"', html)
    assert m, "源码找不到 DEF_ZHIPU_KEY"
    real_key = m.group(1)
    print("源码 DEF_ZHIPU_KEY 长度:", len(real_key), "(个人版两包均保留)")

    # 竖屏版
    por = set_label(apply_portrait(html), "竖屏版")
    assert real_key in por, "竖屏版丢失真实 Key，中止！"
    # 横屏版
    lan = set_label(apply_landscape(html), "横屏版")
    assert real_key in lan, "横屏版丢失真实 Key，中止！"

    # 自检：横屏设置控件确实已从两版 HTML 中移除
    for tag, h in (("竖屏版", por), ("横屏版", lan)):
        for ctrl in ('id="stRotate"', 'id="stLayoutDir"'):
            assert ctrl not in h, "%s 仍含 %s" % (tag, ctrl)
    assert 'id="stLsPoem"' not in por, "竖屏版仍含 stLsPoem"
    assert 'id="lsResetBtn"' not in por, "竖屏版仍含 lsResetBtn"
    # 横屏版应保留横屏专属控件
    assert 'id="stLsPoem"' in lan, "横屏版误删 stLsPoem"
    assert 'id="lsResetBtn"' in lan, "横屏版误删 lsResetBtn"
    # 日历灰底高亮修法两版均生效
    assert "background: #666; color: #fff;" in por
    assert "background: #666; color: #fff;" in lan
    print("自检通过：横屏设置已按版本拆分移除/保留，日历灰底高亮修法两版均生效")

    build(por, OUT_POR, "portrait")
    build(lan, OUT_LAN, "landscape")
    print("\n两个个人版均已生成：")
    print("  竖屏版(纵向·个人):", OUT_POR)
    print("  横屏版(横向·个人):", OUT_LAN)
    print("（按用户要求：本次不设公共版、不上传 GitHub）")


if __name__ == "__main__":
    main()
