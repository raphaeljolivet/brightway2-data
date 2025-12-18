# -*- coding: utf-8 -*-
from __future__ import print_function, unicode_literals

from bw2data.backends.peewee import ActivityDataset, ExchangeDataset
from eight import *

from ...method import Method
from ...meta import methods


def generic_dict_as_dataset(ds, model_class) :
    res = {
      key:ds.get(key, None) for key in model_class._meta.fields if key != "id"
    }

    # Other data
    data = {
      key:ds.get(key, None) for key, vak in ds.items() if key not in  model_class._meta.fields
    }

    res["data"] = data
    return res

def dict_as_activitydataset(ds):
    """Distribute values between known attributes and 'data' metadata """
    ds = ds.copy()
    ds["product"] = ds.pop("reference product", None)
    return generic_dict_as_dataset(ds, ActivityDataset)



def dict_as_exchangedataset(ds):
    ds = ds.copy()

    input = ds.pop("input", None)
    output = ds.pop("output", None)

    ds["input_database"] = input[0] if input else ds["input_database"]
    ds["output_database"] = output[0] if output else ds["output_database"]
    ds["input_code"] = input[1] if input else ds["input_code"]
    ds["output_code"] = output[1] if output else ds["output_code"]

    return generic_dict_as_dataset(ds, ExchangeDataset)



def replace_cfs(old_key, new_key):
    """Replace ``old_key`` with ``new_key`` in characterization factors.

    Returns list of modified methods."""
    altered_methods = []
    for name in methods:
        changed = False
        data = Method(name).load()
        for line in data:
            if line[0] == old_key:
                line[0], changed = new_key, True
        if changed:
            Method(name).write(data)
            altered_methods.append(name)
    return altered_methods
