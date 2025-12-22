# -*- coding: utf-8 -*-
from __future__ import print_function, unicode_literals

from bw2data.proxies import ProxyBase
from eight import *
from peewee import Model
from playhouse.shortcuts import model_to_dict

from . import sqlite3_lci_db
from ... import databases, mapping, geomapping, config
from ...errors import ValidityError
from ...project import writable_project
from ...proxies import ActivityProxyBase, ExchangeProxyBase
from ...search import IndexManager
from ...utils import get_activity
from .schema import ActivityDataset, ExchangeDataset
from .utils import dict_as_activitydataset, dict_as_exchangedataset
from future.utils import implements_iterator
import copy
import warnings
import uuid
try:
    from collections.abc import Iterable
except ImportError:
    from collections import Iterable


class Exchanges(Iterable):
    """Iterator for exchanges with some additional methods.

    This is not a generator; ``next()`` is not supported. Everything time you start to iterate over the object you get a new list starting from the beginning. However, to get a single item you can do ``next(iter(foo))``.

    Ordering is by database row id.

    Supports the following:

    .. code-block:: python

        exchanges = activity.exchanges()

        # Iterate
        for exc in exchanges:
            pass

        # Length
        len(exchanges)

        # Delete all
        exchanges.delete()

    """
    def __init__(self, key, kinds=None, reverse=False):
        self._key, self._kinds = key, kinds
        if reverse:
            self._args = [
            ExchangeDataset.input_database == self._key[0],
            ExchangeDataset.input_code == self._key[1],
            # No production exchanges - these two clauses have to be together,
            # not individually
            ExchangeDataset.output_database != self._key[0] &
            ExchangeDataset.output_code != self._key[1],
        ]
        else:
            self._args = [
                ExchangeDataset.output_database == self._key[0],
                ExchangeDataset.output_code == self._key[1],
            ]
        if self._kinds:
            self._args.append(ExchangeDataset.type << self._kinds)

    def filter(self, expr):
        self._args.append(expr)

    @writable_project
    def delete(self):
        databases.set_dirty(self._key[0])
        ExchangeDataset.delete().where(*self._args).execute()

    def _get_queryset(self):
        return ExchangeDataset.select().where(*self._args).order_by(ExchangeDataset.id)

    def __iter__(self):
        for obj in self._get_queryset():
            yield Exchange(obj)

    def __len__(self):
        return self._get_queryset().count()


class DocumentDataMixin(ProxyBase):
    """Common mixin for object looking first within _document then in _data"""


    def __init__(self, document, **kwargs):
        self._document = document

        if document.data is None :
            document.data = {}

        self._data = document.data

        for key, val in kwargs.items():
            self[key] = val

    def __contains__(self, key):
        if hasattr(self._document, key):
            return getattr(self._document, key) is not None
        else:
            return self._data.get(key) is not None

    def __getitem__(self, key):
        res = None
        if hasattr(self._document, key) :
            res = getattr(self._document, key)
        elif key in self._data:
            res = self._data.get(key)
        if res is None:
            raise KeyError
        return res

    def __setitem__(self, key, value):
        if hasattr(self._document, key) :
            setattr(self._document, key, value)
        else:
            if key != "data" :
                self._data[key] = value

    def __delitem__(self, key):
        if hasattr(self._document, key) :
            raise ValueError(f"Cannot delete attribute {key}")
        else:
            del self._data[key]

    def __len__(self):
        return len(self.as_dict())

    def as_dict(self):
        res = super().as_dict().copy()
        res.update(model_to_dict(self._document))
        return res



class Activity(DocumentDataMixin, ActivityProxyBase):
    def __init__(self, document=None, **kwargs):
        """Create an `Activity` proxy object.

        If this is a new activity, can pass `kwargs`.

        If the activity exists in the database, `document` should be an `ActivityDataset`."""

        if document is None:
            document = ActivityDataset()

        super().__init__(document=document, **kwargs)


    def __setitem__(self, key, value):
        if key == 'code' and 'code' in self._data:
            self._change_code(value)
            print("Successfully switched activity dataset to new code `{}`".format(value))
        elif key == 'database' and 'database' in self._data:
            self._change_database(value)
            print("Successfully switch activity dataset to database `{}`".format(value))
        else:
            super().__setitem__(key, value)

    def __getitem__(self, key):
        if key == 0:
            return self["database"]
        elif key == 1:
            return self["code"]
        elif key in self:
            return super().__getitem__(key)

        try:
            rp = self.rp_exchange()
        except ValueError:
            raise KeyError


        if key in rp.get('classifications', []):
            return rp['classifications'][key]
        if key in rp.get('properties', []):
            return rp['properties'][key]

        raise KeyError

    @property
    def key(self):
        return (self.get("database"), self.get("code"))

    @writable_project
    def delete(self):
        from ... import Database
        from ...parameters import ActivityParameter, ParameterizedExchange
        try:
            ap = ActivityParameter.get(database=self[0], code=self[1])
            ParameterizedExchange.delete().where(
                ParameterizedExchange.group == ap.group).execute()
            ActivityParameter.delete().where(
                ActivityParameter.database == self[0],
                ActivityParameter.code == self[1]
            ).execute()
        except ActivityParameter.DoesNotExist:
            pass
        IndexManager(Database(self['database']).filename).delete_dataset(self.as_dict())
        self.exchanges().delete()
        self._document.delete_instance()
        self = None

    @writable_project
    def save(self):
        from ... import Database

        if not self.valid():
            raise ValidityError("This activity can't be saved for the "
                "following reasons\n\t* " + \
                "\n\t* ".join(self.valid(why=True)[1])
            )

        databases.set_dirty(self['database'])

        for key, value in dict_as_activitydataset(self.as_dict()).items():
            setattr(self._document, key, value)
        self._document.save()

        if self.key not in mapping:
            mapping.add([self.key])
        if self.get('location') and self['location'] not in geomapping:
            geomapping.add([self['location']])

        if databases[self['database']].get('searchable', True):
            IndexManager(Database(self['database']).filename).update_dataset(self.as_dict())

    def _change_code(self, new_code):
        if self['code'] == new_code:
            return

        if ActivityDataset.select().where(
            ActivityDataset.database == self['database'],
            ActivityDataset.code == new_code
        ).count():
            raise ValueError(
                "Activity database with code `{}` already exists".format(new_code)
            )

        with sqlite3_lci_db.atomic() as txn:
            ActivityDataset.update(code=new_code).where(
                ActivityDataset.database == self['database'],
                ActivityDataset.code == self['code']
            ).execute()
            ExchangeDataset.update(output_code=new_code).where(
                ExchangeDataset.output_database == self['database'],
                ExchangeDataset.output_code == self['code'],
            ).execute()
            ExchangeDataset.update(input_code=new_code).where(
                ExchangeDataset.input_database == self['database'],
                ExchangeDataset.input_code == self['code'],
            ).execute()

        if databases[self['database']].get('searchable'):
            from ... import Database
            IndexManager(Database(self['database']).filename).delete_dataset(self)
            self._data['code'] = new_code
            IndexManager(Database(self['database']).filename).add_datasets([self])
        else:
            self._data['code'] = new_code

    def _change_database(self, new_database):
        if self['database'] == new_database:
            return

        if new_database not in databases:
            raise ValueError("Database {} does not exist".format(new_database))

        with sqlite3_lci_db.atomic() as txn:
            ActivityDataset.update(database=new_database).where(
                ActivityDataset.database == self['database'],
                ActivityDataset.code == self['code']
            ).execute()
            ExchangeDataset.update(output_database=new_database).where(
                ExchangeDataset.output_database == self['database'],
                ExchangeDataset.output_code == self['code'],
            ).execute()
            ExchangeDataset.update(input_database=new_database).where(
                ExchangeDataset.input_database == self['database'],
                ExchangeDataset.input_code == self['code'],
            ).execute()

        if databases[self['database']].get('searchable'):
            from ... import Database
            IndexManager(Database(self['database']).filename).delete_dataset(self)
            self._data['database'] = new_database
            IndexManager(Database(self['database']).filename).add_datasets([self])
        else:
            self._data['database'] = new_database

    def exchanges(self):
        return Exchanges(self.key)

    def technosphere(self, include_substitution=True):
        return Exchanges(
            self.key,
            kinds=(("technosphere", "substitution")
                   if include_substitution
                   else ("technosphere",))
        )

    def biosphere(self):
        return Exchanges(
            self.key,
            kinds=("biosphere",),
        )

    def production(self):
        return Exchanges(
            self.key,
            kinds=("production",),
        )

    def substitution(self):
        return Exchanges(
            self.key,
            kinds=("substitution",),
        )

    def upstream(self, kinds=("technosphere",)):
        return Exchanges(
            self.key,
            kinds=kinds,
            reverse=True
        )

    def rp_exchange(self):
        """Return an ``Exchange`` object corresponding to the reference production. Uses the following in order:

        * The ``production`` exchange, if only one is present
        * The ``production`` exchange with the same name as the activity ``reference product``.

        Raises ``ValueError`` if no suitable exchange is found."""
        candidates = list(self.production())
        if len(candidates) == 1:
            return candidates[0]
        candidates2 = [exc for exc in candidates if exc.input['name'] == self['reference product']]
        if len(candidates2) == 1:
            return candidates2[0]
        else:
            raise ValueError("Can't find a single reference product exchange (found {} candidates)".format(len(candidates)))

    def new_exchange(self, **kwargs):
        """Create a new exchange linked to this activity"""
        exc = Exchange()
        exc.output = self.key
        for key in kwargs:
            exc[key] = kwargs[key]
        return exc

    @writable_project
    def copy(self, code=None, **kwargs):
        """Copy the activity. Returns a new `Activity`.

        `code` is the new activity code; if not given, a UUID is used.

        `kwargs` are additional new fields and field values, e.g. name='foo'

        """
        activity = Activity()
        for key, value in self.items():
            activity[key] = value
        for k, v in kwargs.items():
            activity._data[k] = v
        activity[u'code'] = str(code or uuid.uuid4().hex)
        activity.save()

        for exc in self.exchanges():
            data = exc.as_dict()
            data['output'] = activity.key
            # Change `input` for production exchanges
            if exc['input'] == exc['output']:
                data['input'] = activity.key
            ExchangeDataset.create(**dict_as_exchangedataset(data))
        return activity


class Exchange(DocumentDataMixin, ExchangeProxyBase):
    def __init__(self, document=None, **kwargs):
        """Create an `Exchange` proxy object.

        If this is a new exchange, can pass `kwargs`.

        If the exchange exists in the database, `document` should be an `ExchangeDataset`."""

        if document is None:
            document = ExchangeDataset()

        super().__init__(document=document, **kwargs)

    def __getitem__(self, key):
        """Get onput / output keys from the attribute of the peewee document"""
        if key in ["input", "output"] :
            if self[f"{key}_database"] is None and self[f"{key}_code"] is None:
                return None
            return (self[f"{key}_database"], self[f"{key}_code"])

        return super().__getitem__(key)

    def __setitem__(self, key, value):
        """Unwrapp input / output key tuple into proper attributes of the Peewee document"""
        if key in ['input', 'output'] :
            self[f"{key}_database"], self[f"{key}_code"] = value
        else:
            super().__setitem__(key, value)

    def _set_output(self, value):
        """Override the one from `ExchangeProxyBase`"""
        if isinstance(value, ActivityProxyBase):
            self._output = value
            self['output'] = value.key
        elif isinstance(value, (tuple, list)):
            self['output'] = value
        else:
            raise ValueError("Provided input data is invalid")

    output = property(ExchangeProxyBase._get_output, _set_output)

    def as_dict(self):
        res = super().as_dict()
        res["input"] = self["input"]
        res["output"] = self["output"]
        return res


    @writable_project
    def save(self):
        if not self.valid():
            raise ValidityError("This exchange can't be saved for the "
                "following reasons\n\t* " + \
                "\n\t* ".join(self.valid(why=True)[1])
            )

        databases.set_dirty(self['output'][0])

        for key, value in dict_as_exchangedataset(self.as_dict()).items():
            setattr(self._document, key, value)

        self._document.save()

    @writable_project
    def delete(self):
        from ...parameters import ParameterizedExchange
        ParameterizedExchange.delete().where(
            ParameterizedExchange.exchange == self._document.id).execute()
        self._document.delete_instance()
        databases.set_dirty(self['output'][0])
        self = None
