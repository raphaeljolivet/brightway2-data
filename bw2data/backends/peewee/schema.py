# -*- coding: utf-8 -*-
from __future__ import print_function, unicode_literals
from eight import *
from playhouse.sqlite_ext import JSONField
from peewee import Model, TextField, FloatField


class ActivityDataset(Model):
    data = JSONField()             # Canonical, except for other C fields
    code = TextField()               # Canonical
    database = TextField()
    unit = TextField(null=True)
    location = TextField(null=True)  # Reset from `data`
    name = TextField(null=True)      # Reset from `data`
    product = TextField(null=True)   # Reset from `data`
    type = TextField(null=True)      # Reset from `data`


class ExchangeDataset(Model):
    data = JSONField()           # Canonical, except for other C fields

    amount= FloatField()
    unit = TextField()

    name= TextField()
    input_code = TextField()       # Canonical
    input_database = TextField()   # Canonical
    output_code = TextField()      # Canonical
    output_database = TextField()  # Canonical
    type = TextField()             # Reset from `data`
