from PyInstaller.utils.hooks.tcl_tk import tcltk_info

UNUSED = ("_tcl_data/tzdata/", "_tcl_data/msgs/")


def hook(hook_api):
    if tcltk_info.tcl_data_missing or tcltk_info.tk_data_missing:
        raise SystemExit(f"ERROR: Tcl/Tk data not found in {tcltk_info.tcl_data_dir!r} / {tcltk_info.tk_data_dir!r}")
    hook_api.add_datas([d for d in tcltk_info.data_files if not d[0].replace("\\", "/").startswith(UNUSED)])
