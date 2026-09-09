"""Repo-side catalog: sensor model  ->  pyglider `netcdf_variables` entries.

This is the part of `deployment.yml` that OGDB deliberately does not model
(decision 0003): the pyglider configuration schema — CF variable names,
`source` sensor strings, unit conversions, valid ranges. It is coupled to
the pyglider version, not to the glider inventory, so it lives here as
versioned code.

`config.resolve()` gets the *list of sensor models* from OGDB and uses this
catalog to turn each into its `netcdf_variables` block + a `profile_variables`
`instrument_*` entry. The `source` names are cross-checked against the mission's
actual binary sensor list where possible.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# --------------------------------------------------------------------------
# Fixed blocks — identical for every Slocum mission
# --------------------------------------------------------------------------
NAV_VARIABLES: dict = {
    "time": {
        "source": "sci_m_present_time", "long_name": "Time", "standard_name": "time",
        "calendar": "gregorian", "units": "seconds since 1970-01-01T00:00:00Z",
        "axis": "T", "observation_type": "measured",
        "coordinates": "time depth latitude longitude",
    },
    "latitude": {
        "source": "m_lat", "long_name": "latitude", "standard_name": "latitude",
        "units": "degrees_north", "axis": "Y",
        "coordinates": "time depth latitude longitude",
        "comment": "Estimated between surface fixes", "observation_type": "measured",
        "platform": "platform", "reference": "WGS84",
        "valid_max": 90.0, "valid_min": -90.0,
        "coordinate_reference_frame": "urn:ogc:crs:EPSG::4326",
    },
    "longitude": {
        "source": "m_lon", "long_name": "longitude", "standard_name": "longitude",
        "units": "degrees_east", "axis": "X",
        "coordinates": "time depth latitude longitude",
        "comment": "Estimated between surface fixes", "observation_type": "measured",
        "platform": "platform", "reference": "WGS84",
        "valid_max": 180.0, "valid_min": -180.0,
        "coordinate_reference_frame": "urn:ogc:crs:EPSG::4326",
    },
    "heading": {
        "source": "m_heading", "long_name": "glider heading angle",
        "standard_name": "platform_orientation", "units": "rad",
        "coordinates": "time depth latitude longitude",
    },
    "pitch": {
        "source": "m_pitch", "long_name": "glider pitch angle",
        "standard_name": "platform_pitch_angle", "units": "rad",
        "coordinates": "time depth latitude longitude",
    },
    "roll": {
        "source": "m_roll", "long_name": "glider roll angle",
        "standard_name": "platform_roll_angle", "units": "rad",
        "coordinates": "time depth latitude longitude",
    },
    "waypoint_latitude": {
        "source": "c_wpt_lat", "long_name": "waypoint latitude",
        "standard_name": "latitude", "units": "degree_north",
        "coordinates": "time depth latitude longitude",
    },
    "waypoint_longitude": {
        "source": "c_wpt_lon", "long_name": "waypoint longitude",
        "standard_name": "longitude", "units": "degree_east",
        "coordinates": "time depth latitude longitude",
    },
}

# The CF-DSG boilerplate pyglider's profile / gridding steps expect. Fixed.
PROFILE_VARIABLES: dict = {
    "profile_id": {
        "comment": "Sequential profile number within the trajectory. This value "
                   "is unique in each file that is part of a single "
                   "trajectory/deployment.",
        "long_name": "Profile ID", "valid_max": 2147483647, "valid_min": 1,
    },
    "profile_time": {
        "comment": "Timestamp corresponding to the mid-point of the profile",
        "long_name": "Profile Center Time", "observation_type": "calculated",
        "platform": "platform", "standard_name": "time",
        "units": "seconds since 1970-01-01T00:00:00Z",
    },
    "profile_time_start": {
        "comment": "Timestamp corresponding to the start of the profile",
        "long_name": "Profile Start Time", "observation_type": "calculated",
        "platform": "platform", "standard_name": "time",
        "units": "seconds since 1970-01-01T00:00:00Z",
    },
    "profile_time_end": {
        "comment": "Timestamp corresponding to the end of the profile",
        "long_name": "Profile End Time", "observation_type": "calculated",
        "platform": "platform", "standard_name": "time",
        "units": "seconds since 1970-01-01T00:00:00Z",
    },
    "profile_lat": {
        "comment": "Value is interpolated to provide an estimate of the latitude "
                   "at the mid-point of the profile",
        "long_name": "Profile Center Latitude", "observation_type": "calculated",
        "platform": "platform", "standard_name": "latitude",
        "units": "degrees_north", "valid_max": 90.0, "valid_min": -90.0,
    },
    "profile_lon": {
        "comment": "Value is interpolated to provide an estimate of the longitude "
                   "at the mid-point of the profile",
        "long_name": "Profile Center Longitude", "observation_type": "calculated",
        "platform": "platform", "standard_name": "longitude",
        "units": "degrees_east", "valid_max": 180.0, "valid_min": -180.0,
    },
    "u": {
        "comment": "The depth-averaged current is an estimate of the net current "
                   "measured while the glider is underwater. The value is "
                   "calculated over the entire underwater segment, which may "
                   "consist of 1 or more dives.",
        "long_name": "Depth-Averaged Eastward Sea Water Velocity",
        "observation_type": "calculated", "platform": "platform",
        "standard_name": "eastward_sea_water_velocity", "units": "m s-1",
        "valid_max": 10.0, "valid_min": -10.0,
    },
    "v": {
        "comment": "The depth-averaged current is an estimate of the net current "
                   "measured while the glider is underwater. The value is "
                   "calculated over the entire underwater segment, which may "
                   "consist of 1 or more dives.",
        "long_name": "Depth-Averaged Northward Sea Water Velocity",
        "observation_type": "calculated", "platform": "platform",
        "standard_name": "northward_sea_water_velocity", "units": "m s-1",
        "valid_max": 10.0, "valid_min": -10.0,
    },
    "lon_uv": {
        "comment": "Not computed", "long_name": "Longitude",
        "observation_type": "calculated", "platform": "platform",
        "standard_name": "longitude", "units": "degrees_east",
        "valid_max": 180.0, "valid_min": -180.0,
    },
    "lat_uv": {
        "comment": "Not computed", "long_name": "Latitude",
        "observation_type": "calculated", "platform": "platform",
        "standard_name": "latitude", "units": "degrees_north",
        "valid_max": 90.0, "valid_min": -90.0,
    },
    "time_uv": {
        "comment": "Not computed", "long_name": "Time", "standard_name": "time",
        "calendar": "gregorian", "units": "seconds since 1970-01-01T00:00:00Z",
        "observation_type": "calculated",
    },
}


# --------------------------------------------------------------------------
# Per-instrument definitions
# --------------------------------------------------------------------------
@dataclass
class SensorKind:
    """One instrument family the pipeline knows how to map."""

    key: str                       # deployment.yml glider_devices key
    instrument_key: str            # profile_variables instrument_* key
    binary_prefix: str             # the sci_* proglet prefix in the raw data
    asset_type: str                # OGDB asset_types.name it matches
    model_pattern: str             # regex on the OGDB model / L22 label (case-insensitive)
    netcdf_variables: dict         # var name -> attrs (with "source")
    long_name: str                 # human label for glider_devices / instrument_*

    def matches(self, asset_type: str, model_text: str) -> bool:
        return (asset_type == self.asset_type
                and re.search(self.model_pattern, model_text or "", re.I) is not None)


_COORD = "time depth latitude longitude"

CTD = SensorKind(
    key="ctd", instrument_key="instrument_ctd", binary_prefix="sci_ctd41cp", asset_type="ct_sensor", model_pattern=r"",  # any CT sensor (incl. no model)
    long_name="glider CTD",
    netcdf_variables={
        "conductivity": {
            "source": "sci_water_cond", "long_name": "water conductivity",
            "standard_name": "sea_water_electrical_conductivity", "units": "S m-1",
            "coordinates": _COORD, "instrument": "instrument_ctd",
            "valid_min": 0.0, "valid_max": 10.0, "observation_type": "measured",
            "accuracy": 0.0003, "precision": 0.0001, "resolution": 0.00002,
        },
        "temperature": {
            "source": "sci_water_temp", "long_name": "water temperature",
            "standard_name": "sea_water_temperature", "units": "Celsius",
            "coordinates": _COORD, "instrument": "instrument_ctd",
            "valid_min": -5.0, "valid_max": 50.0, "observation_type": "measured",
            "accuracy": 0.002, "precision": 0.001, "resolution": 0.0002,
        },
        "pressure": {
            "source": "sci_water_pressure", "long_name": "water pressure",
            "standard_name": "sea_water_pressure", "units": "dbar",
            "coordinates": _COORD, "conversion": "bar2dbar",
            "valid_min": 0.0, "valid_max": 2000.0, "positive": "down",
            "reference_datum": "sea-surface", "instrument": "instrument_ctd",
            "observation_type": "measured",
            "accuracy": 1.0, "precision": 2.0, "resolution": 0.02,
            "comment": "ctd pressure sensor",
        },
    },
)

FLNTU = SensorKind(
    key="optics", instrument_key="instrument_flntu", binary_prefix="sci_flntu", asset_type="eco_sensor", model_pattern=r"FLNTU",
    long_name="WET Labs ECO FLNTU (chlorophyll fluorescence + turbidity)",
    netcdf_variables={
        "chlorophyll": {
            "source": "sci_flntu_chlor_units", "long_name": "chlorophyll concentration",
            "standard_name": "mass_concentration_of_chlorophyll_in_sea_water",
            "units": "mg m-3", "coordinates": _COORD,
            "instrument": "instrument_flntu", "observation_type": "measured",
        },
        "turbidity": {
            "source": "sci_flntu_turb_units", "long_name": "sea water turbidity",
            "standard_name": "sea_water_turbidity", "units": "1",
            "coordinates": _COORD, "instrument": "instrument_flntu",
            "observation_type": "measured",
            "comment": "WET Labs FLNTU turbidity channel, reported in NTU",
        },
    },
)

FLBBCD = SensorKind(
    key="optics", instrument_key="instrument_flbbcd", binary_prefix="sci_flbbcd", asset_type="eco_sensor", model_pattern=r"FLBBCD|BB2FL|Triplet",
    long_name="WET Labs ECO FLBBCD (chlorophyll + backscatter + CDOM)",
    netcdf_variables={
        "chlorophyll": {
            "source": "sci_flbbcd_chlor_units", "long_name": "chlorophyll concentration",
            "standard_name": "mass_concentration_of_chlorophyll_in_sea_water",
            "units": "mg m-3", "coordinates": _COORD,
            "instrument": "instrument_flbbcd", "observation_type": "measured",
        },
        "cdom": {
            "source": "sci_flbbcd_cdom_units", "long_name": "coloured dissolved organic matter",
            "units": "ppb", "coordinates": _COORD,
            "instrument": "instrument_flbbcd", "observation_type": "measured",
        },
        "backscatter_700": {
            "source": "sci_flbbcd_bb_units",
            "long_name": "700 nm wavelength backscatter", "units": "1",
            "coordinates": _COORD, "instrument": "instrument_flbbcd",
            "observation_type": "measured",
        },
    },
)

OPTODE_3835 = SensorKind(
    key="oxygen", instrument_key="instrument_oxygen", binary_prefix="sci_oxy3835", asset_type="do_sensor", model_pattern=r"38[0-9]{2}",  # 3830 / 3835
    long_name="Aanderaa Oxygen Optode (3830/3835 family)",
    netcdf_variables={
        "oxygen_concentration": {
            "source": "sci_oxy3835_oxygen", "long_name": "oxygen concentration",
            "standard_name": "mole_concentration_of_dissolved_molecular_oxygen_in_sea_water",
            "units": "umol l-1", "coordinates": _COORD,
            "instrument": "instrument_oxygen", "observation_type": "measured",
            "comment": "onboard-computed concentration; no optode recalculation / "
                       "lag / salinity compensation applied at L1 (a QC-stage step)",
        },
        "oxygen_saturation": {
            "source": "sci_oxy3835_saturation", "long_name": "oxygen saturation",
            "standard_name": "fractional_saturation_of_oxygen_in_sea_water",
            "units": "percent", "coordinates": _COORD,
            "instrument": "instrument_oxygen", "observation_type": "measured",
        },
    },
)

OPTODE_4X = SensorKind(
    key="oxygen", instrument_key="instrument_oxygen", binary_prefix="sci_oxy4", asset_type="do_sensor", model_pattern=r"4[0-9]{3}",  # 4330 / 4831 ...
    long_name="Aanderaa Oxygen Optode (4xxx family)",
    netcdf_variables={
        "oxygen_concentration": {
            "source": "sci_oxy4_oxygen", "long_name": "oxygen concentration",
            "standard_name": "mole_concentration_of_dissolved_molecular_oxygen_in_sea_water",
            "units": "umol l-1", "coordinates": _COORD,
            "instrument": "instrument_oxygen", "observation_type": "measured",
            "comment": "onboard-computed concentration; no optode recalculation / "
                       "lag / salinity compensation applied at L1 (a QC-stage step)",
        },
        "oxygen_saturation": {
            "source": "sci_oxy4_saturation", "long_name": "oxygen saturation",
            "standard_name": "fractional_saturation_of_oxygen_in_sea_water",
            "units": "percent", "coordinates": _COORD,
            "instrument": "instrument_oxygen", "observation_type": "measured",
        },
    },
)

# order matters: more specific patterns first within an asset_type
CATALOG: list[SensorKind] = [CTD, FLBBCD, FLNTU, OPTODE_3835, OPTODE_4X]


def match_sensor(asset_type: str, model_text: str) -> SensorKind | None:
    for kind in CATALOG:
        if kind.matches(asset_type, model_text):
            return kind
    return None
