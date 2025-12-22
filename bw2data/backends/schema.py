from copy import deepcopy
from functools import cache

from peewee import DoesNotExist, TextField, FloatField, IntegerField
from playhouse.signals import pre_save, pre_init
from playhouse.sqlite_ext import JSONField

from bw2data.errors import UnknownObject
from bw2data.snowflake_ids import SnowflakeIDBaseClass

class CleanJSONField(JSONField):
    """JSON Field that deletes unwanted fields before saving"""

    def __init__(self, *args, **kwargs):

        super().__init__(*args, **kwargs)

    def setup_model(self, model_class):
        self.remove_fields = [f for f in model_class._meta.fields if f not in ['data', "id"]]


    def db_value(self, dic):
        if dic is None:
            return None
        cleaned = dic.copy()
        for field in self.remove_fields:
            cleaned.pop(field, None)
        return super().db_value(cleaned)



class ActivityDataset(SnowflakeIDBaseClass):
    data = CleanJSONField(default=dict)  # Set just after
    code = TextField()  # Canonical
    database = TextField()
    unit = TextField(null=True)
    location = TextField(null=True)  # Reset from `data`
    name = TextField(null=True)  # Reset from `data`
    product = TextField(null=True)  # Reset from `data`
    type = TextField(null=True)  # Reset from `data`

    @property
    def key(self):
        return (self.database, self.code)

ActivityDataset.data.setup_model(ActivityDataset)


class ExchangeDataset(SnowflakeIDBaseClass):
    data = CleanJSONField(default=dict)   # Canonical, except for other C fields
    amount= FloatField(null=True)
    scale = FloatField(null=True)
    shape = FloatField(null=True)
    loc = FloatField(null=True)
    uncertainty_type = IntegerField(null=True)
    minimum = FloatField(null=True)
    maximum = FloatField(null=True)

    unit = TextField(null=True)

    name= TextField(null=True)
    input_code = TextField()  # Canonical
    input_database = TextField()  # Canonical
    output_code = TextField()  # Canonical
    output_database = TextField()  # Canonical
    type = TextField()  # Reset from `data`

ExchangeDataset.data.setup_model(ExchangeDataset)


def _merge_data_into_fields(instance):
    if not instance.data:
        return
    for key, value in instance.data.items():
        if hasattr(instance, key):
            setattr(instance, key, value)

def _add_field_into_data(model_class, instance):
    if not instance.data:
        instance.data = {}
    for key in model_class._meta.fields:
        if key in  ["data", "id"]:
            continue
        val = getattr(instance, key)
        if val is not None:
            instance.data[key] = getattr(instance, key)

@pre_save(sender=ActivityDataset)
def activity_pre_save(model_class, instance, created):
    _merge_data_into_fields(instance)

@pre_save(sender=ExchangeDataset)
def exchange_pre_save(model_class, instance, created):
    _merge_data_into_fields(instance)

@pre_init(sender=ActivityDataset)
def activity_pre_init(model_class, instance):
    _add_field_into_data(model_class, instance)

@pre_init(sender=ExchangeDataset)
def activity_pre_init(model_class, instance):
    _add_field_into_data(model_class, instance)


@cache
def get_id(key):
    if isinstance(key, int):
        try:
            ActivityDataset.get(ActivityDataset.id == key)
        except DoesNotExist:
            raise UnknownObject
        return key
    else:
        try:
            return ActivityDataset.get(
                ActivityDataset.database == key[0], ActivityDataset.code == key[1]
            ).id
        except DoesNotExist:
            raise UnknownObject
