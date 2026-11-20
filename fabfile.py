import fh_fablib as fl


fl.require("1.0.20260817")
fl.config.update(
    app="biwak",
    domain="biwak.feinheit.app",
    branch="main",
    remote="production",
    python="3.15",
)


ns = fl.Collection(*fl.GENERAL)
