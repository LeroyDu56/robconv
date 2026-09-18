"""Conversion settings and the optional user mapping file.

Everything that cannot be derived from the RAPID source (register numbers,
I/O numbers, frame numbers, speed heuristics) has an automatic default and can
be pinned in a JSON file passed with --map:

{
  "registers":       {"nCycles": 10},          RAPID num      -> R[n]
  "flags":           {"bPartPresent": 5},      RAPID bool     -> F[n]
  "digital_outputs": {"doGrip": 3},            RAPID signal   -> DO[n]
  "digital_inputs":  {"diPartReady": 7},       RAPID signal   -> DI[n]
  "group_outputs":   {"goStatus": 1},          RAPID signal   -> GO[n]
  "group_inputs":    {"giCode": 2},            RAPID signal   -> GI[n]
  "uframes":         {"wobjFixture": 2},       wobjdata       -> UFRAME n
  "utools":          {"tGripper": 1},          tooldata       -> UTOOL n
  "joint_speed_ref_mm_s": 2000,
  "cnt_per_mm": 1.0,
  "config_mapping": true,
  "program_name_max_length": 36
}

Names are matched case-insensitively, like RAPID.
"""

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

_MAPPING_KEYS = (
    "registers", "flags", "digital_outputs", "digital_inputs", "group_outputs", "group_inputs", "uframes", "utools",
)  # fmt: skip


@dataclass
class ConversionConfig:
    # Fixed numbers, upper-cased RAPID name -> number.
    registers: dict[str, int] = field(default_factory=dict)
    flags: dict[str, int] = field(default_factory=dict)
    digital_outputs: dict[str, int] = field(default_factory=dict)
    digital_inputs: dict[str, int] = field(default_factory=dict)
    group_outputs: dict[str, int] = field(default_factory=dict)
    group_inputs: dict[str, int] = field(default_factory=dict)
    uframes: dict[str, int] = field(default_factory=lambda: {"WOBJ0": 0})
    utools: dict[str, int] = field(default_factory=dict)

    # First number used by automatic allocation.
    first_register: int = 1
    first_flag: int = 1
    first_digital_output: int = 1
    first_digital_input: int = 1
    first_group_output: int = 1
    first_group_input: int = 1
    first_uframe: int = 1
    first_utool: int = 1

    # Heuristics (documented in the conversion report).
    joint_speed_ref_mm_s: float = 2000.0  # RAPID TCP speed that maps to J 100%
    cnt_per_mm: float = 1.0  # zone radius (mm) * cnt_per_mm -> CNT, capped to 100
    config_mapping: bool = True  # CONFIG from ABB confdata; False: default_config everywhere
    joint_mapping: bool = True  # MoveAbsJ joints with measured axis conventions; False: copied as is
    default_config: str = "N U T, 0, 0, 0"
    program_name_max_length: int = 36  # R-30iB; older controllers: 8

    timestamp: datetime = field(default_factory=lambda: datetime.now().replace(microsecond=0))

    @classmethod
    def from_mapping_file(cls, path: str | Path, **overrides) -> "ConversionConfig":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        config = cls(**overrides)
        unknown = set(data) - set(_MAPPING_KEYS) - {
            "joint_speed_ref_mm_s", "cnt_per_mm", "config_mapping", "joint_mapping", "default_config",
            "program_name_max_length",
        }  # fmt: skip
        if unknown:
            raise ValueError(f"unknown keys in mapping file: {', '.join(sorted(unknown))}")
        for key in _MAPPING_KEYS:
            table = getattr(config, key)
            for name, number in data.get(key, {}).items():
                if not isinstance(number, int):
                    raise TypeError(f"{key}.{name}: expected an integer, got {number!r}")
                table[name.upper()] = number
        for key in ("joint_speed_ref_mm_s", "cnt_per_mm", "config_mapping", "joint_mapping", "default_config",
                    "program_name_max_length"):
            if key in data:
                setattr(config, key, data[key])
        return config
