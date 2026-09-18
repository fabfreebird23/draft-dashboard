"""py2app packaging:  ./macapp/build.sh  ->  ~/Applications/BloodySunday.app

The bundle is deliberately thin: pywebview and PyObjC, no Streamlit and no
draftkit. The app runs the dashboard out of ~/draft-dashboard/.venv, so a
`git pull` is the whole update and this bundle is rebuilt only when the
wrapper itself changes. See macapp/app.py for why.
"""
from setuptools import setup

APP = ["app.py"]
OPTIONS = {
    "argv_emulation": False,
    "iconfile": "BloodySunday.icns",
    "plist": {
        "CFBundleName": "Bloody Sunday",
        "CFBundleDisplayName": "Bloody Sunday",
        "CFBundleIdentifier": "com.brandonclifton.bloodysunday",
        "CFBundleShortVersionString": "0.1.0",
        "LSUIElement": False,          # Dock icon AND a menu-bar item
        "NSHighResolutionCapable": True,
        # LaunchServices does not pass the shell's LANG to an app, so Python's
        # default encoding inside a bundle is ASCII — and every score line here
        # carries a "·" and an en dash. Sportsbot learned this the hard way.
        "LSEnvironment": {"PYTHONUTF8": "1", "LANG": "en_US.UTF-8"},
    },
    "includes": ["webview", "objc", "AppKit", "Foundation", "WebKit"],
}

setup(app=APP, options={"py2app": OPTIONS}, setup_requires=["py2app"])
