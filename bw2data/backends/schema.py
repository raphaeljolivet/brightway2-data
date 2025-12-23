from copy import deepcopy
from functools import cache

from peewee import DoesNotExist, TextField, FloatField, IntegerField, Model
from playhouse.signals import pre_save, pre_init
from playhouse.sqlite_ext import JSONField

from bw2data.errors import UnknownObject
from bw2data.snowflake_ids import SnowflakeIDBaseClass

class CleanJSONField(JSONField):
    """JSON Field that deletes unwanted fields before saving"""

    def __init__(self, *args, **kwargs):

        super().__init__(*args, **kwargs)

    def setup_model(self, model_class):
        """Called after setup of the model because we can't circular reference a class in construction"""
        self.remove_fields = [f for f in model_class._meta.fields if f not in ['data', "id"]]

        # Add extra mapping from the Meta attribute of the model
        self.remove_fields.extend(list(model_class._meta.extra_data_mapping.keys()))


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

    class Meta:
        extra_data_mapping = {"reference product": "product"}


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

    class Meta:
        extra_data_mapping = {
            "uncertainty type" : "uncertainty_type",
            "input" : ("input_database", "input_code"),
            "output" : ("output_database", "output_code")}


ExchangeDataset.data.setup_model(ExchangeDataset)


def _spread_data_into_fields(model_class, instance):
    """Called before save to DB, to put the feidsl of 'data' into proper fields."""

    if isinstance(instance, Model):
        # This should accomodate instance being either a Dataset instance of a dict (as called by insert_many)
        instance = instance.__data__

    data = instance["data"]

    if not data:
        return
    for key, value in data.items():
        if key in model_class._meta.fields:
            instance[key] = value

    # Process extra mapping
    for data_key, attr in model_class._meta.extra_data_mapping.items():
        val = data.get(data_key)
        if val is not None:
            if isinstance(attr, tuple):
                for key, val in zip(attr, val):
                    instance[key] = val
            else:
                instance[attr] = val


def _add_field_into_data(model_class, instance):
    if not instance.data:
        instance.data = {}
    for key in model_class._meta.fields:
        if key in  ["data", "id"]:
            continue
        val = getattr(instance, key)
        if val is not None:
            instance.data[key] = getattr(instance, key)

    # Process extra mapping
    for data_key, attr in model_class._meta.extra_data_mapping.items():
        if isinstance(attr, tuple):
            val = tuple(getattr(instance, key) for key in attr)
        else:
            val = getattr(instance, attr)
        instance.data[data_key] = val


@pre_save(sender=ActivityDataset)
def activity_pre_save(model_class, instance, created):
    _spread_data_into_fields(model_class, instance)

@pre_save(sender=ExchangeDataset)
def exchange_pre_save(model_class, instance, created):
    _spread_data_into_fields(model_class, instance)

@pre_init(sender=ActivityDataset)
def activity_pre_init(model_class, instance:ActivityDataset):
    _add_field_into_data(model_class, instance)


@pre_init(sender=ExchangeDataset)
def activity_pre_init(model_class, instance:ExchangeDataset):
    _add_field_into_data(model_class, instance)


def insert_many_exchanges(exchanges : list[ExchangeDataset]):
    """Signal don't work automatically on insery_many(). Do it manually"""
    for exchange in exchanges:
        exchange_pre_save(ExchangeDataset, exchange, False)
    ExchangeDataset.insert_many(exchanges).execute()

def insert_many_activities(activities : list[ActivityDataset]):
    """Signal don't work automatically on insery_many(). Do it manually"""
    for activity in activities:
        exchange_pre_save(ActivityDataset, activity, False)
    ActivityDataset.insert_many(activities).execute()

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
