import json
import pickle
from threading import RLock

from peewee import BlobField, SqliteDatabase, TextField, Model, IntegerField, CharField
from bw2data.logs import stdout_feedback_logger


class PickleField(BlobField):
    def db_value(self, value):
        return super(PickleField, self).db_value(pickle.dumps(value, protocol=4))

    def python_value(self, value):
        return pickle.loads(bytes(value))


class SubstitutableDatabase:
    def __init__(self, filepath, tables):
        self._filepath = filepath
        self._tables = add_enum_tables(tables)
        self._database = self._create_database()

    def _create_database(self):
        db = SqliteDatabase(self._filepath)
        for model in self._tables:
            model.bind(db, bind_refs=False, bind_backrefs=False)
        db.connect()
        db.create_tables(self._tables)
        return db

    @property
    def db(self):
        return self._database

    def change_path(self, filepath):
        self.db.close()
        self._filepath = filepath
        self._database = self._create_database()

    def atomic(self):
        return self.db.atomic()

    def execute_sql(self, *args, **kwargs):
        return self.db.execute_sql(*args, **kwargs)

    def transaction(self):
        return self.db.transaction()

    def vacuum(self):
        stdout_feedback_logger.info("Vacuuming database ")
        self.execute_sql("VACUUM;")

def add_enum_tables(tables:list[type[Model]]):
    res = set(tables)
    for table in tables :
        for field in table._meta.fields.values() :
            if isinstance(field, EnumField):
                res.add(field.registry_model)
    return list(res)

class JSONField(TextField):
    """Simpler JSON field that doesn't support advanced querying and is human-readable"""

    def db_value(self, value):
        return super().db_value(
            json.dumps(
                value,
                ensure_ascii=False,
                indent=2,
                default=lambda x: x.isoformat() if hasattr(x, "isoformat") else x,
            )
        )

    def python_value(self, value):
        return json.loads(value)


class TupleJSONField(JSONField):
    def python_value(self, value):
        if value is None:
            return None
        data = json.loads(value)
        if isinstance(data, list):
            data = tuple(data)
        return data


class CleanJSONField(JSONField):
    """JSON Field that deletes unwanted fields before saving to DB"""

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


def spread_data_into_fields(model_class, instance):
    """Called before save to DB, to put the fields of 'data' into proper fields."""

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


def add_field_into_data(model_class, instance):
    """Called after load from DB to put back  attributes of Peewee Dataset into data """
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


class EnumRegistry(Model):
    """
    Abstract model to maintain a table of string to int enums
    """

    value = IntegerField(primary_key=True)
    key = CharField(unique=True)

    class Meta:
        abstract = True
        initial_mapping = {}

    @classmethod
    def _ensure_loaded(cls):

        if getattr(cls, "_loaded", False):
            return

        cls._lock = RLock()

        with cls._lock:

            cls._loaded = False
            cls._str_to_int = {}
            cls._int_to_str = {}

            cls.create_table(safe=True)

            existing = {row.key: row.value for row in cls.select()}

            # Initial settings
            with cls._meta.database.atomic():
                for key, value in cls._meta.initial_mapping.items():
                    if key in existing:
                        continue
                    cls.create(key=key, value=value).save()
                    existing[key] = value

            # Fill cache
            for key, vaue in existing.items():
                cls._str_to_int[key] = value
                cls._int_to_str[value] = key

            cls._loaded = True

    @classmethod
    def to_int(cls, key: str) -> int:
        cls._ensure_loaded()

        with cls._lock:
            if key in cls._str_to_int:
                return cls._str_to_int[key]

            with cls._meta.database.atomic():
                # New value => insert it into DB
                value = max(cls._int_to_str.keys(), default=-1) + 1
                cls.create(key=key, value=value).save()
                cls._str_to_int[key] = value
                cls._int_to_str[value] = key
                return value

    @classmethod
    def to_str(cls, value: int):
        cls._ensure_loaded()
        return cls._int_to_str.get(value)


class EnumField(IntegerField):
    """Integer enum field, bound to an enum table """

    def __init__(self, registry_model, **kwargs):
        super().__init__(**kwargs)
        self.registry_model = registry_model

    def db_value(self, value):
        if value is None:
            return None
        if isinstance(value, int):
            return value
        return self.registry_model.to_int(value)

    def python_value(self, value):
        if value is None:
            return None
        return self.registry_model.to_str(value)


