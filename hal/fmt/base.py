import ultraplot as uplt
import yaml

from hal.config import cfg

uplt_cfg = yaml.safe_load(
    (cfg.root / "hal" / "fmt" / "ultraplot_presets.yaml").read_text()
)


def load_uplt_config(preset: str = "paper") -> None:
    dict_config = uplt_cfg[preset]
    uplt.rc.update(dict_config)
