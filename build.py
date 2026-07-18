import os
import sys
import shutil
import PyInstaller.__main__
from PyInstaller.utils.hooks import collect_data_files

os.environ["CUDA_VISIBLE_DEVICES"] = ""

ENTRY_POINT = "main.py"
APP_NAME = "WhisperNote"
ICON_PATH = os.path.join("assets", "icons", "app_icon.ico")

def build():
    icon_option = []
    if os.path.exists(ICON_PATH):
        icon_option = [f"--icon={ICON_PATH}"]

    whisper_datas = collect_data_files("whisper")
    whisper_add_data_args = [f"--add-data={s};{d}" for s, d in whisper_datas]

    args = [
        ENTRY_POINT,
        f"--name={APP_NAME}",
        "--noconfirm",
        "--onedir",
        "--windowed",
        "--clean",
        "--add-data=assets;assets",
        "--add-data=utils;utils",
        "--add-data=core;core",
        "--add-data=widgets;widgets",

        "--exclude-module=torch",
        "--exclude-module=torchaudio",
        "--exclude-module=torchvision",
        "--hidden-import=sympy",
        "--hidden-import=networkx",
        "--hidden-import=jinja2",
        "--hidden-import=fsspec",
        "--hidden-import=filelock",
        "--hidden-import=typing_extensions",
        "--hidden-import=colorama",
        "--hidden-import=tqdm",
        "--hidden-import=pydub",
        "--hidden-import=whisper",
        "--hidden-import=numpy",
        "--hidden-import=PyQt6",
        "--hidden-import=pickletools",
    ] + icon_option + whisper_add_data_args

    print("🚀 Starting build process (ONEDIR mode)...")
    PyInstaller.__main__.run(args)
    print("✅ PyInstaller build finished!")

def copy_full_packages():
    import torch
    import torchaudio
    import torchvision
    import torchgen

    internal_dir = os.path.join("dist", APP_NAME, "_internal")
    os.makedirs(internal_dir, exist_ok=True)

    packages_to_copy = [torch, torchaudio, torchvision, torchgen]
    for pkg in packages_to_copy:
        src_dir = os.path.dirname(pkg.__file__)
        pkg_name = os.path.basename(src_dir)
        dst_dir = os.path.join(internal_dir, pkg_name)

        print(f"🔄 Copy package: {pkg_name}")
        if os.path.exists(dst_dir):
            shutil.rmtree(dst_dir)
        shutil.copytree(src_dir, dst_dir)
        print(f"✅ Copied: {pkg_name} -> {dst_dir}")

    torch_lib_src = os.path.join(os.path.dirname(torch.__file__), "lib")
    torch_lib_dst = os.path.join("dist", APP_NAME, "_internal", "torch", "lib")
    if os.path.isdir(torch_lib_src):
        src_cnt = len([f for f in os.listdir(torch_lib_src) if f.lower().endswith(".dll")])
        print(f"📦 torch\\lib DLL in venv: {src_cnt}")
    if os.path.isdir(torch_lib_dst):
        dst_cnt = len([f for f in os.listdir(torch_lib_dst) if f.lower().endswith(".dll")])
        print(f"📦 torch\\lib DLL in dist: {dst_cnt}")

def copy_msvc_runtimes():
    dist_root = os.path.join("dist", APP_NAME)
    os.makedirs(dist_root, exist_ok=True)

    search_paths = [
        os.path.join(sys.base_prefix),
        os.path.join(sys.base_prefix, "DLLs"),
        r"C:\Windows\System32",
    ]

    dlls_to_find = [
        "vcruntime140.dll",
        "vcruntime140_1.dll",
        "msvcp140.dll",
        "msvcp140_1.dll",
        "msvcp140_2.dll",
    ]

    print("🔄 Copy MSVC runtimes (next to exe)...")
    for dll in dlls_to_find:
        copied = False
        for spath in search_paths:
            src = os.path.join(spath, dll)
            if os.path.exists(src):
                shutil.copy2(src, os.path.join(dist_root, dll))
                print(f" + {dll} (from {spath})")
                copied = True
                break
        if not copied:
            print(f" ⚠️ Not found: {dll}")

if __name__ == "__main__":
    try:
        if os.path.exists("build"):
            shutil.rmtree("build")
        if os.path.exists("dist"):
            shutil.rmtree("dist")
        if os.path.exists(f"{APP_NAME}.spec"):
            os.remove(f"{APP_NAME}.spec")
    except Exception as e:
        print(f"⚠️ Could not clean: {e}")

    build()
    copy_full_packages()
    copy_msvc_runtimes()

    print("🎉 Build done. Try running dist\\WhisperNote\\WhisperNote.exe")