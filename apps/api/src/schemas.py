from __future__ import annotations

from typing import Any, Callable, Dict, Tuple, Type, Union, cast

from pydantic import BaseModel, ConfigDict, Field
from pydantic import create_model as _create_model
from sqlalchemy import ARRAY, Enum, Table
from sqlalchemy.orm import DeclarativeMeta, Mapper, class_mapper

create_model: Callable[..., Any] = cast(Callable[..., Any], _create_model)


# -----------------------------------------------------------------------------
#   tiny helper – map SA column python‑types to ‘nice’ (JSON serialisable) ones
# -----------------------------------------------------------------------------
def _python_type(sqlalchemy_column) -> Any:
    try:
        return sqlalchemy_column.type.python_type  # works for 95 %
    except NotImplementedError:  # e.g. PG ENUM, ARRAY
        from sqlalchemy import ARRAY, Enum

        if isinstance(sqlalchemy_column.type, Enum):
            # Produce a *runtime* Enum subclass compatible with Pydantic
            enum_name = f"{sqlalchemy_column.name.capitalize()}Enum"
            choices = sqlalchemy_column.type.enums
            from enum import Enum as PyEnum

            return PyEnum(enum_name, {c: c for c in choices})  # str‑based
        if isinstance(sqlalchemy_column.type, ARRAY):
            return list[_python_type(sqlalchemy_column.type.item_type)]  # type: ignore
        # Fall‑back
        return str


# -----------------------------------------------------------------------------
#   Main factory – returns *two* Pydantic models per SQLAlchemy class:
#       • FooIn   – for POST/PUT (no PK, all optional)
#       • FooOut  – for GET      (all DB columns, read‑only)
# -----------------------------------------------------------------------------
def make_pydantic_pair(sa_cls: DeclarativeMeta) -> Tuple[Type[BaseModel], Type[BaseModel]]:
    name_base = sa_cls.__name__
    # cast to Table so Pylance knows what .columns is
    sa_table: Table = cast(Table, getattr(sa_cls, "__table__"))  # type: ignore[attr-defined]
    pk_names = {c.name for c in sa_table.columns if c.primary_key}

    fields_in: Dict[str, Tuple[Any, Any]] = {}
    fields_out: Dict[str, Tuple[Any, Any]] = {}
    for col in sa_table.columns:
        # Determine the Python type for this column
        try:
            typ = col.type.python_type
        except NotImplementedError:
            if isinstance(col.type, Enum):
                # …enum handling…
                from enum import Enum as PyEnum

                typ = PyEnum(f"{col.name.capitalize()}Enum", {e: e for e in col.type.enums})
            elif isinstance(col.type, ARRAY):
                typ = list[_python_type(col.type.item_type)]  # type: ignore
            else:
                typ = str

        # Create nullable type if needed
        nullable_typ = Union[typ, None] if col.nullable else typ

        # Set defaults
        default_in = None if col.nullable else ...
        default_out = None if col.nullable else ...

        # build In/Out fields exactly as before…
        if col.name not in pk_names and not col.name.endswith("_ts"):
            fields_in[col.name] = (nullable_typ, Field(default=default_in))
        fields_out[col.name] = (nullable_typ, Field(default=default_out))

    # Relationships are serialised shallowly as *lists of PKs* (keeps JSON flat)
    mapper: Mapper = class_mapper(sa_cls)
    for rel in mapper.relationships:
        if rel.direction.name == "MANYTOONE":
            fields_out[rel.key + "_id"] = (Any | None, None)
        elif rel.direction.name in ("ONETOMANY", "MANYTOMANY"):
            fields_out[rel.key + "_ids"] = (list[Any] | None, Field(default_factory=list))

    # ⚡️ drop __config__ from the call…
    ModelIn = create_model(
        f"{name_base}In",
        **fields_in,
    )
    # …then set your ConfigDict afterwards
    ModelIn.model_config = ConfigDict(from_attributes=True)

    ModelOut = create_model(
        f"{name_base}Out",
        **fields_out,
    )
    ModelOut.model_config = ConfigDict(from_attributes=True)

    return ModelIn, ModelOut
