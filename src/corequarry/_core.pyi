"""Native CoreQuarry/IB classes and query algebra"""

from collections.abc import Sequence
import enum
from typing import overload


ib_revision: str = ...

gptype_bits: int = ...

index_id_bits: int = ...

vector_enabled: bool = ...

class Merge(enum.Enum):
    NONE = 0

    OPTIMIZE = 1

    MERGE = 2

    COLLAPSE = 3

    INCREMENTAL = 4

    ZIP = 5

class SortBy(enum.Enum):
    UNSORTED = 0

    SCORE = 3

    DATE = 1

    REVERSE_DATE = 2

    HITS = 6

    KEY = 8

    INDEX = 9

    AUX_COUNT = 5

class Normalization(enum.Enum):
    NONE = 1

    L2 = 2

    L1 = 3

    BM25 = 5

    E2 = 17

    HYBRID = 16

    MAX = 6

    DEFAULT = 2

class Relation(enum.Enum):
    DEFAULT = 0

    LT = 1

    LE = 2

    EQ = 3

    GE = 4

    GT = 5

    NE = 6

    OVERLAPS = 7

    WITHIN = 8

    ENCLOSES = 9

class Operator(enum.Enum):
    AND = 21

    OR = 20

    AND_NOT = 22

    XOR = 23

    XNOR = 24

    NOT_AND = 25

    NAND = 27

    NOR = 26

    LT = 28

    LE = 29

    GT = 30

    GE = 31

    NOT = 1

    WITHIN = 2

    XWITHIN = 3

    NOT_WITHIN = 7

    INSIDE = 4

    INCLUSIVE = 5

    PEER = 53

    PEER_BEFORE = 54

    PEER_AFTER = 55

    XPEER = 56

    PROXIMITY = 40

    BEFORE = 41

    AFTER = 42

    ADJ = 43

    FOLLOWS = 44

    PRECEDES = 45

    NEAR = 46

    FAR = 47

    NEIGHBOR = 48

    AND_WITHIN = 49

    OR_WITHIN = 50

    BEFORE_WITHIN = 51

    AFTER_WITHIN = 52

    JOIN = 32

    JOIN_LEFT = 33

    JOIN_RIGHT = 34

    BOOST = 17

    SORT = 16

    WITH_KEY = 15

    WITHIN_DOCTYPE = 14

    WITHIN_FILE = 12

    WITHIN_FILE_EXTENSION = 13

    KEY = 18

    FILE = 19

    REDUCE = 9

    FOCUS = 8

    HIT_COUNT = 10

    TRIM = 11

    SIBLING = 6

    ANCESTOR = 57

    MAYBE = 58

    NARROW = 59

    PROMOTE = 60

    DEMOTE = 61

class FIELDTYPE:
    def __init__(self, name: str) -> None: ...

    @property
    def name(self) -> str: ...

    def __str__(self) -> str: ...

class ATTRLIST:
    def __init__(self) -> None: ...

    @property
    def field(self) -> str: ...

    @field.setter
    def field(self, arg: str, /) -> None: ...

    @property
    def datatype(self) -> FIELDTYPE: ...

    @datatype.setter
    def datatype(self, arg: FIELDTYPE, /) -> None: ...

    @property
    def relation(self) -> int: ...

    @relation.setter
    def relation(self, arg: int, /) -> None: ...

    @property
    def weight(self) -> float: ...

    @weight.setter
    def weight(self, arg: float, /) -> None: ...

    @property
    def phrase(self) -> bool: ...

    @phrase.setter
    def phrase(self, arg: bool, /) -> None: ...

    @property
    def prefix(self) -> bool: ...

    @prefix.setter
    def prefix(self, arg: bool, /) -> None: ...

class STERM:
    def __init__(self) -> None: ...

    @property
    def text(self) -> str: ...

    @text.setter
    def text(self, arg: str, /) -> None: ...

    @property
    def attributes(self) -> ATTRLIST: ...

    @attributes.setter
    def attributes(self, arg: ATTRLIST, /) -> None: ...

class OPERATOR:
    def __init__(self, code: Operator) -> None: ...

    @property
    def code(self) -> Operator: ...

    @code.setter
    def code(self, arg: Operator, /) -> None: ...

    @property
    def metric(self) -> float: ...

    @metric.setter
    def metric(self, arg: float, /) -> None: ...

    @property
    def argument(self) -> str: ...

    @argument.setter
    def argument(self, arg: str, /) -> None: ...

class OPSTACK:
    def __init__(self) -> None: ...

    @overload
    def push(self, arg: STERM, /) -> None: ...

    @overload
    def push(self, arg: OPERATOR, /) -> None: ...

class SQUERY:
    @overload
    def __init__(self) -> None: ...

    @overload
    def __init__(self, arg: SQUERY, /) -> None: ...

    @staticmethod
    def term(text: str, field: str = ..., datatype: str = ..., relation: Relation = Relation.DEFAULT, weight: float = ..., phrase: bool = ..., prefix: bool = ...) -> SQUERY: ...

    @staticmethod
    def from_rpn(arg: str, /) -> SQUERY: ...

    @staticmethod
    def from_infix(arg: str, /) -> SQUERY: ...

    @staticmethod
    def from_words(arg: str, /) -> SQUERY: ...

    def SetOpstack(self, arg: OPSTACK, /) -> None: ...

    def GetOpstack(self) -> OPSTACK: ...

    def SetRpnTerm(self, arg: str, /) -> int: ...

    def SetInfixTerm(self, arg: str, /) -> int: ...

    def GetRpnTerm(self) -> str: ...

    def LastErrorMessage(self) -> str: ...

    def SetAttributes(self, attributes: ATTRLIST, replace: bool = ...) -> int: ...

    def combine(self, other: SQUERY, operator: OPERATOR) -> SQUERY: ...

    def apply(self, arg: OPERATOR, /) -> SQUERY: ...

    def __and__(self, arg: SQUERY, /) -> SQUERY: ...

    def __or__(self, arg: SQUERY, /) -> SQUERY: ...

    def __xor__(self, arg: SQUERY, /) -> SQUERY: ...

    @staticmethod
    def field(name: str, value: object, relation: Relation = Relation.EQ, datatype: str = ...) -> SQUERY: ...

    def and_not(self, arg: SQUERY, /) -> SQUERY: ...

    def peer(self, other: SQUERY, max_gap: object | None = ...) -> SQUERY: ...

    def before_peer(self, other: SQUERY, max_gap: object | None = ...) -> SQUERY: ...

    def after_peer(self, other: SQUERY, max_gap: object | None = ...) -> SQUERY: ...

    def within(self, arg: str, /) -> SQUERY: ...

    def boost(self, arg: float, /) -> SQUERY: ...

    @property
    def term_count(self) -> int: ...

    @staticmethod
    def operators() -> list: ...

    @property
    def rpn(self) -> str: ...

    def __str__(self) -> str: ...

class QUERY:
    def __init__(self, squery: SQUERY, sort: SortBy = SortBy.SCORE, normalization: Normalization = Normalization.L2) -> None: ...

    @property
    def sort(self) -> SortBy: ...

    @sort.setter
    def sort(self, arg: SortBy, /) -> None: ...

    @property
    def normalization(self) -> Normalization: ...

    @normalization.setter
    def normalization(self, arg: Normalization, /) -> None: ...

    @property
    def squery(self) -> SQUERY: ...

    @squery.setter
    def squery(self, arg: SQUERY, /) -> None: ...

    @property
    def term_count(self) -> int: ...

class SRCH_DATE:
    @overload
    def __init__(self) -> None: ...

    @overload
    def __init__(self, arg: str, /) -> None: ...

    def __str__(self) -> str: ...

    @property
    def iso(self) -> str: ...

    @property
    def ok(self) -> bool: ...

class FC:
    @overload
    def __init__(self) -> None: ...

    @overload
    def __init__(self, start: int, end: int) -> None: ...

    @property
    def start(self) -> int: ...

    @start.setter
    def start(self, arg: int, /) -> None: ...

    @property
    def end(self) -> int: ...

    @end.setter
    def end(self, arg: int, /) -> None: ...

    @property
    def length(self) -> int: ...

    @property
    def empty(self) -> bool: ...

    def contains(self, arg: FC, /) -> bool: ...

    def __repr__(self) -> str: ...

class FCHIT(FC):
    def __init__(self, start: int, end: int, source_id: int = ...) -> None: ...

    @property
    def source_id(self) -> int: ...

class HITTABLE:
    def __len__(self) -> int: ...

    def __getitem__(self, arg: int, /) -> FCHIT: ...

class EVIDENCE_COVER:
    @property
    def extent(self) -> FC: ...

    @property
    def energy(self) -> float: ...

    @property
    def dispersion(self) -> float: ...

class DISPLAY_EVIDENCE:
    @property
    def cover(self) -> EVIDENCE_COVER: ...

    @property
    def display_extent(self) -> FC: ...

    @property
    def container_extent(self) -> FC: ...

    @property
    def container_name(self) -> str: ...

    @property
    def has_container(self) -> bool: ...

class RECORD:
    @overload
    def __init__(self) -> None: ...

    @overload
    def __init__(self, filename: str) -> None: ...

    @property
    def filename(self) -> str: ...

    @filename.setter
    def filename(self, arg: str, /) -> None: ...

    @property
    def key(self) -> str: ...

    @key.setter
    def key(self, arg: str, /) -> None: ...

    @property
    def start(self) -> int: ...

    @start.setter
    def start(self, arg: int, /) -> None: ...

    @property
    def end(self) -> int: ...

    @end.setter
    def end(self, arg: int, /) -> None: ...

    @property
    def doctype(self) -> str: ...

    @doctype.setter
    def doctype(self, arg: str, /) -> None: ...

class MDTREC:
    def __init__(self) -> None: ...

    @property
    def key(self) -> str: ...

    @property
    def filename(self) -> str: ...

    @property
    def doctype(self) -> str: ...

    @property
    def start(self) -> int: ...

    @property
    def end(self) -> int: ...

    @property
    def date(self) -> SRCH_DATE: ...

class MDT:
    def __len__(self) -> int: ...

    def get_entry(self, index: int, record: MDTREC) -> bool: ...

    def __getitem__(self, arg: int, /) -> MDTREC: ...

    def lookup_key(self, arg: str, /) -> int: ...

class IRESULT:
    @property
    def score(self) -> float: ...

    @property
    def hit_count(self) -> int: ...

    @property
    def hits(self) -> HITTABLE: ...

    @property
    def mdt_index(self) -> int: ...

    @property
    def virtual_index(self) -> int: ...

class RESULT:
    @property
    def key(self) -> str: ...

    @property
    def filename(self) -> str: ...

    @property
    def doctype(self) -> str: ...

    @property
    def score(self) -> float: ...

    @property
    def date(self) -> SRCH_DATE: ...

    @property
    def start(self) -> int: ...

    @property
    def end(self) -> int: ...

    @property
    def hits(self) -> HITTABLE: ...

    @property
    def mdt_index(self) -> int: ...

    @property
    def virtual_index(self) -> int: ...

    def get_evidence_covers(self, max_covers: int = ...) -> list[EVIDENCE_COVER]: ...

    def get_display_evidence(self, max_bytes: int = ...) -> DISPLAY_EVIDENCE: ...

    def evidence(self, max_bytes: int = ..., before: str = ..., after: str = ...) -> tuple: ...

    def get_record_data(self) -> str: ...

class RSET:
    def __len__(self) -> int: ...

    def __getitem__(self, arg: int, /) -> RESULT: ...

    @property
    def total_found(self) -> int: ...

    @property
    def hit_total(self) -> int: ...

    def sort_by(self, arg: SortBy, /) -> None: ...

class IRSET:
    def __len__(self) -> int: ...

    def __getitem__(self, arg: int, /) -> IRESULT: ...

    @property
    def hit_total(self) -> int: ...

    def copy(self) -> IRSET: ...

    def sort_by(self, arg: SortBy, /) -> None: ...

    def normalize(self, method: Normalization, weight: float = ...) -> None: ...

    def get_rset(self, total: object | None = ..., start: int = ...) -> RSET: ...

    def __and__(self, arg: IRSET, /) -> IRSET: ...

    def __or__(self, arg: IRSET, /) -> IRSET: ...

    def and_not(self, arg: IRSET, /) -> IRSET: ...

    def peer(self, other: IRSET, max_gap: object | None = ...) -> IRSET: ...

    def within(self, arg: str, /) -> IRSET: ...

class IDB:
    def __init__(self, name: str, search_only: bool = ..., doctype_options: Sequence[str] = ...) -> None: ...

    def close(self) -> None: ...

    @property
    def closed(self) -> bool: ...

    def __enter__(self) -> IDB: ...

    def __exit__(self, exc_type: object | None, exc_value: object | None, traceback: object | None) -> None: ...

    @property
    def name(self) -> str: ...

    @property
    def total_records(self) -> int: ...

    @property
    def total_words(self) -> int: ...

    @property
    def volume_count(self) -> int: ...

    def GetVersionID(self) -> str: ...

    def SetLocale(self, arg: str, /) -> bool: ...

    def add_record(self, arg: RECORD, /) -> bool: ...

    def add_file(self, path: str, doctype: str = ...) -> bool: ...

    def index(self, append: bool = ..., merge: Merge = Merge.NONE, memory_mb: int = ...) -> bool: ...

    @overload
    def search(self, query: QUERY) -> IRSET: ...

    @overload
    def search(self, query: SQUERY, sort: SortBy = SortBy.SCORE, normalization: Normalization = Normalization.L2) -> IRSET: ...

    def search_smart(self, query: QUERY, default_field: str = ...) -> tuple: ...

    def get_mdt(self, volume: int = ...) -> MDT: ...

    def headline(self, arg: RESULT, /) -> str: ...

    def summary(self, arg: RESULT, /) -> str: ...

    def get_field_data(self, arg0: RESULT, arg1: str, /) -> object: ...

class VIDB:
    def __init__(self, name: str, search_only: bool = ..., doctype_options: Sequence[str] = ...) -> None: ...

    def close(self) -> None: ...

    @property
    def closed(self) -> bool: ...

    def __enter__(self) -> VIDB: ...

    def __exit__(self, exc_type: object | None, exc_value: object | None, traceback: object | None) -> None: ...

    @property
    def name(self) -> str: ...

    @property
    def total_records(self) -> int: ...

    @property
    def total_words(self) -> int: ...

    @property
    def volume_count(self) -> int: ...

    def GetVersionID(self) -> str: ...

    def SetLocale(self, arg: str, /) -> bool: ...

    def add_record(self, arg: RECORD, /) -> bool: ...

    def add_file(self, path: str, doctype: str = ...) -> bool: ...

    def index(self, append: bool = ..., merge: Merge = Merge.NONE, memory_mb: int = ...) -> bool: ...

    @overload
    def search(self, query: QUERY) -> IRSET: ...

    @overload
    def search(self, query: SQUERY, sort: SortBy = SortBy.SCORE, normalization: Normalization = Normalization.L2) -> IRSET: ...

    def search_smart(self, query: QUERY, default_field: str = ...) -> tuple: ...

    def get_mdt(self, volume: int = ...) -> MDT: ...

    def headline(self, arg: RESULT, /) -> str: ...

    def summary(self, arg: RESULT, /) -> str: ...

    def get_field_data(self, arg0: RESULT, arg1: str, /) -> object: ...
