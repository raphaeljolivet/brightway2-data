from functools import cache

from peewee import DoesNotExist, TextField, FloatField, IntegerField
from playhouse.signals import pre_save, pre_init

from bw2data.sqlite import CleanJSONField, spread_data_into_fields, add_field_into_data, EnumField, EnumRegistry
from bw2data.errors import UnknownObject
from bw2data.snowflake_ids import SnowflakeIDBaseClass

class DatabaseEnum(EnumRegistry):
    class Meta:
        table_name = "enum_database"

class UnitEnum(EnumRegistry):
    class Meta:
        table_name = "enum_unit"

class TypeEnum(EnumRegistry):
    class Meta:
        table_name = "enum_type"

class ActivityDataset(SnowflakeIDBaseClass):
    data = CleanJSONField(default=dict)  # Set just after
    code = TextField()  # Canonical
    database = EnumField(DatabaseEnum)
    unit = EnumField(UnitEnum, null=True)
    location = TextField(null=True)  # Reset from `data`
    name = TextField(null=True)  # Reset from `data`
    product = TextField(null=True)  # Reset from `data`
    type = EnumField(TypeEnum, null=True)  # Reset from `data`

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

    unit = EnumField(UnitEnum, null=True)

    name= TextField(null=True)
    input_code = TextField()  # Canonical
    input_database = EnumField(DatabaseEnum)  # Canonical
    output_code = TextField()  # Canonical
    output_database = EnumField(DatabaseEnum)  # Canonical
    type = EnumField(TypeEnum)  # Reset from `data`

    class Meta:
        extra_data_mapping = {
            "uncertainty type" : "uncertainty_type",
            "input" : ("input_database", "input_code"),
            "output" : ("output_database", "output_code")}


ExchangeDataset.data.setup_model(ExchangeDataset)


@pre_save(sender=ActivityDataset)
def activity_pre_save(model_class, instance, created):
    spread_data_into_fields(model_class, instance)

@pre_save(sender=ExchangeDataset)
def exchange_pre_save(model_class, instance, created):
    spread_data_into_fields(model_class, instance)

@pre_init(sender=ActivityDataset)
def activity_pre_init(model_class, instance:ActivityDataset):
    add_field_into_data(model_class, instance)


@pre_init(sender=ExchangeDataset)
def activity_pre_init(model_class, instance:ExchangeDataset):
    add_field_into_data(model_class, instance)


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


