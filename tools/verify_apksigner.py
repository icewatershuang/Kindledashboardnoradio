# -*- coding: utf-8 -*-
"""权威校验：直接调用 Android 官方 apksigner（不是自写、也不是 apksigtool）。

为什么必须有它
--------------
手写的 apk_sign_v2 与 apksigtool 都曾把「算法 ID 映射」记反过
（0x0101 到底是 PSS 还是 PKCS1v15），于是自写校验、"第三方"校验互相点头
都报绿，真机却拒装。只有 Android 官方 apksigner 是权威裁判。

用法：python verify_apksigner.py <apk>
退出码 0=验证通过；非 0=失败（设备会拒装）。
"""
import os
import subprocess
import sys

ANDROID_DIR = "C:/Users/Administrator/.workbuddy/binaries/android"
JAVA = os.path.join(ANDROID_DIR, "jre17", "jdk-17.0.20.1+1-jre", "bin", "java.exe")
JAR = os.path.join(ANDROID_DIR, "android-13", "lib", "apksigner.jar")


def main():
    apk = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        "C:/Users/Administrator/WorkBuddy/2026-09-13-03-27-43/kindle_dashboard",
        "KindleDash_A5_v21_personal.apk")
    if not os.path.exists(apk):
        print("找不到 APK:", apk)
        sys.exit(2)
    if not os.path.exists(JAVA) or not os.path.exists(JAR):
        print("缺少官方 apksigner: JAVA=%s JAR=%s" % (JAVA, JAR))
        sys.exit(3)
    cmd = [JAVA, "-jar", JAR, "verify", "--verbose", apk]
    r = subprocess.run(cmd, capture_output=True, text=True)
    out = r.stdout + r.stderr
    print(out)
    # apksigner 通过时输出以 "Verifies" 开头（不区分大小写）
    if r.returncode == 0 and "Verifies" in r.stdout:
        print("RESULT: 官方 apksigner 验证通过（设备应可安装）")
        sys.exit(0)
    else:
        print("RESULT: 官方 apksigner 验证失败（设备会拒装）")
        sys.exit(1)


if __name__ == "__main__":
    main()
