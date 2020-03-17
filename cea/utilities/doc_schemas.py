"""
Create a schemas.yml-compatible entry given a locator method by reading the file from the current scenario.

NOTE: This is meant to help _write_ the schemas.yml file, not to CREATE it - you'll have to edit constraints and types
      by hand too!
"""

from __future__ import division
from __future__ import print_function

import os
import yaml
import pandas as pd
import dateutil.parser
import cea.config
import cea.inputlocator

__author__ = "Daren Thomas"
__copyright__ = "Copyright 2020, Architecture and Building Systems - ETH Zurich"
__credits__ = ["Daren Thomas"]
__license__ = "MIT"
__version__ = "0.1"
__maintainer__ = "Daren Thomas"
__email__ = "cea@arch.ethz.ch"
__status__ = "Production"


def read_schema(scenario, locator_method, args=None):
    if not args:
        args = {}
    abs_path = read_path(args, locator_method, scenario)

    file_type = read_file_type(abs_path)
    return {
        locator_method: {
            "file_path": read_file_path(abs_path, scenario, args),
            "file_type": file_type,
            "schema": read_schema_details(abs_path, file_type),
        }
    }


def read_schema_details(abs_path, file_type):
    """Read out the schema, based on the file_type"""
    schema_readers = {
        "xls": get_xls_schema,
        "xlsx": get_xls_schema,
        "tif": get_tif_schema,
        "tiff": get_tif_schema,
        "csv": get_csv_schema,
        "json": get_json_schema,
        "epw": get_epw_schema,
        "dbf": get_dbf_schema,
        "shp": get_shp_schema,
        "html": get_html_schema,
    }
    return schema_readers[file_type](abs_path)


def read_file_type(abs_path):
    # remove "." at the beginning of extension
    _, ext = os.path.splitext(abs_path)
    if ext.startswith("."):
        ext = ext[1:]
    return ext


def read_path(args, locator_method, scenario):
    """Return the path, as returned by the locator method"""
    locator = cea.inputlocator.InputLocator(scenario=scenario)
    method = getattr(locator, locator_method)
    path = method(**args)
    return path


def read_file_path(abs_path, scenario, args):
    """
    returns the path relative to scenario, with arguments replaced. This assumes that the values in args
    were substituted. this ends up in the "file_path" key in the schema
    """
    file_path = os.path.relpath(abs_path, scenario)
    for k, v in args.items():
        if v in file_path:
            file_path = file_path.replace(v, "{%s}" % k.replace("_", "-"))
    return file_path


def get_csv_schema(filename):
    try:
        db = pd.read_csv(filename)
    except pd.errors.EmptyDataError:
        # csv file is empty
        return None
    schema = {}
    for attr in db:
        attr = replace_repetitive_attr(attr)
        schema[attr.encode('ascii', 'ignore')] = get_meta(db[attr])
    return schema


def replace_repetitive_attr(attr):
    scenario = cea.config.Configuration().__getattr__('scenario')
    buildings = cea.inputlocator.InputLocator(scenario).get_zone_building_names()
    if attr.find('srf') != -1:
        attr = attr.replace(attr, 'srf0')
    if attr.find('PIPE') != -1:
        attr = attr.replace(attr, 'PIPE0')
    if attr.find('NODE') != -1:
        attr = attr.replace(attr, 'NODE0')
    if attr in buildings:
        attr = attr.replace(attr, buildings[0])
    return attr


def get_json_schema(filename):
    with open(filename, 'r') as f:
        import json
        db = json.load(f)
    schema = {}
    for attr in db:
        attr = replace_repetitive_attr(attr)
        schema[attr.encode('ascii', 'ignore')] = get_meta(db[attr])
    return schema


def get_epw_schema(filename):
    epw_labels = ['year (index = 0)', 'month (index = 1)', 'day (index = 2)', 'hour (index = 3)',
                  'minute (index = 4)', 'datasource (index = 5)', 'drybulb_C (index = 6)',
                  'dewpoint_C (index = 7)',
                  'relhum_percent (index = 8)', 'atmos_Pa (index = 9)', 'exthorrad_Whm2 (index = 10)',
                  'extdirrad_Whm2 (index = 11)', 'horirsky_Whm2 (index = 12)',
                  'glohorrad_Whm2 (index = 13)',
                  'dirnorrad_Whm2 (index = 14)', 'difhorrad_Whm2 (index = 15)',
                  'glohorillum_lux (index = 16)',
                  'dirnorillum_lux (index = 17)', 'difhorillum_lux (index = 18)',
                  'zenlum_lux (index = 19)',
                  'winddir_deg (index = 20)', 'windspd_ms (index = 21)',
                  'totskycvr_tenths (index = 22)',
                  'opaqskycvr_tenths (index = 23)', 'visibility_km (index = 24)',
                  'ceiling_hgt_m (index = 25)',
                  'presweathobs (index = 26)', 'presweathcodes (index = 27)',
                  'precip_wtr_mm (index = 28)',
                  'aerosol_opt_thousandths (index = 29)', 'snowdepth_cm (index = 30)',
                  'days_last_snow (index = 31)', 'Albedo (index = 32)',
                  'liq_precip_depth_mm (index = 33)',
                  'liq_precip_rate_Hour (index = 34)']

    db = pd.read_csv(filename, skiprows=8, header=None, names=epw_labels)
    schema = {}
    for attr in db:
        schema[attr.encode('ascii', 'ignore')] = get_meta(db[attr])
    return schema


def get_dbf_schema(filename):
    import pysal
    db = pysal.open(filename, 'r')
    schema = {}
    for attr in db.header:
        schema[attr.encode('ascii', 'ignore')] = get_meta(db.by_col(attr))
    return schema


def get_shp_schema(filename):
    import geopandas
    db = geopandas.read_file(filename)
    schema = {}
    for attr in db:
        attr = replace_repetitive_attr(attr)
        meta = get_meta(db[attr])
        if attr == 'geometry':
            meta['sample_data'] = '((x1 y1, x2 y2, ...))'
        schema[attr.encode('ascii', 'ignore')] = meta
    return schema


def get_xls_schema(filename):
    db = pd.read_excel(filename, sheet_name=None)
    schema = {}
    for sheet in db:
        meta = {}
        nested_df = db[sheet]
        # if xls seems to have row attributes
        if 'Unnamed: 1' in db[sheet].keys():
            nested_df = db[sheet].T
            # filter the nans
            new_cols = []
            for col in nested_df.columns:
                if col == col:
                    new_cols.append(col)
            # change index to numbered
            nested_df.index = range(len(nested_df))
            # select only non-nan columns
            nested_df = nested_df[new_cols]
        for attr in nested_df:
            meta[attr.encode('ascii', 'ignore')] = get_meta(nested_df[attr])
        schema[sheet.encode('ascii', 'ignore')] = meta
    return schema


def get_tif_schema(_):
    return {
        'raster_value': {
            'sample_data': 1.0,
            'types_found': [float]
        }}


def get_html_schema(_):
    """We don't need to keep a schema of html files - these are outputs anyway"""
    return None


def get_meta(df_series):
    types_found = set()
    meta = {}
    for data in df_series:
        if data == data:
            meta['sample_data'] = data
            if is_date(data):
                types_found.add('date')
            elif isinstance(data, basestring):
                meta['sample_data'] = data.encode('ascii', 'ignore')
                types_found.add('string')
            else:
                types_found.add(type(data).__name__)
        # declare nans
        if data != data:
            types_found.add(None)
    meta['types_found'] = list(types_found)
    return meta


def is_date(value):
    if not isinstance(value, basestring):
        return False
    try:
        dateutil.parser.parse(value)
        return True
    except ValueError:
        return False



def main(config):
    """
    Read the schema entry for a locator method, compare it to the current entry and print out a new, updated version.
    """
    print(yaml.safe_dump(read_schema(config.scenario, config.schemas.locator_method, config.schemas.args), default_flow_style=False))


if __name__ == '__main__':
    main(cea.config.Configuration())
