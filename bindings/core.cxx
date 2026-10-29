// Copyright (c) 2026 CoreQuarry contributors. Apache-2.0.
#include "text.hxx"
#include <nanobind/stl/string.h>
#include <nanobind/stl/vector.h>
#include <nanobind/stl/pair.h>
#include <memory>
#include <stdexcept>
#include <sstream>
#include <type_traits>
#include <cstring>
#include <limits>
#include "idb.hxx"
#include "vidb.hxx"
#include "sterm.hxx"
#include "operator.hxx"
#include "doctype.hxx"

namespace nb = nanobind;
using namespace nb::literals;

namespace {
using Owner = std::shared_ptr<IDBOBJ>;

size_t offset_index(Py_ssize_t index, size_t size) {
    if (index < 0) index += static_cast<Py_ssize_t>(size);
    if (index < 0 || static_cast<size_t>(index) >= size) throw nb::index_error();
    return static_cast<size_t>(index);
}
void checked_text(const STRING& value, const char *what, bool allow_empty = false) {
    if ((!allow_empty && value.IsEmpty()) || std::memchr(value.c_str(), 0, value.GetLength()))
        throw nb::value_error(what);
}

// The wrappers retain the database resource directly. A page or copied row
// does not need to retain its entire originating IRSET just to keep the DB open.
struct MetadataRecord { Owner owner; MDTREC value; };
struct MetadataTable { Owner owner; MDT *value; };
struct Result { Owner owner; RESULT value; };
struct Results { Owner owner; std::unique_ptr<RSET> value; };
struct Matches { Owner owner; std::unique_ptr<IRSET> value; };
struct Match { Owner owner; IRESULT value; };

IRSET *copy_matches(const IRSET& input) {
    auto output = std::make_unique<IRSET>(input.GetParent(), input.GetTotalEntries());
    *output = input; // Use IB's explicit assignment, not its implicit base copy.
    return output.release();
}
void same_database(const Matches& left, const Matches& right) {
    if (left.owner.owner_before(right.owner) || right.owner.owner_before(left.owner))
        throw nb::value_error("Result sets must belong to the same database handle");
}
void physical_structure(const Matches& set) {
    const auto *db = dynamic_cast<const VIDB *>(set.owner.get());
    if (db && db->GetIDBCount() > 1)
        throw std::runtime_error("For a federated VIDB, put structural operators in SQUERY before searching");
}

template <class T> struct Database {
    std::shared_ptr<T> value;
    bool searching;
    Database(const STRING& name, bool searching_, const std::vector<STRING>& options) : searching(searching_) {
        checked_text(name, "A database name is required");
        STRLIST native_options;
        for (const auto& option : options) native_options.AddEntry(option);
        value = std::make_shared<T>(name, native_options, searching);
        if constexpr (std::is_same_v<T, VIDB>) {
            if (value->GetIDBCount() == 0) throw std::runtime_error("Cannot open the virtual database");
        }
    }
    T& get() const {
        if (!value) throw std::runtime_error("Database handle is closed");
        return *value;
    }
    Owner owner() const { get(); return value; }
    void close() { value.reset(); }
    void writer() const {
        get();
        if (searching) throw std::runtime_error("Open this database with search_only=False for indexing");
    }
};

DOCTYPE *doctype(const Result& result) {
    if (!result.owner) throw std::runtime_error("This result has no database owner");
    IDBOBJ *db = result.owner.get();
    if (auto *virtual_db = dynamic_cast<VIDB *>(db)) {
        // A single physical DB can have volume zero. The numeric overload
        // accepts that case and otherwise uses one-based volume numbers.
        db = virtual_db->GetIDB(static_cast<size_t>(result.value.GetVirtualIndex()));
    }
    if (!db) throw std::runtime_error("The result's database volume is unavailable");
    return db->GetDocTypePtr(result.value.GetDocumentType());
}

// Read the native stack in execution order, copying values and deleting each
// popped temporary. Only the copying insertion overload crosses this boundary.
void append_query(OPSTACK& output, const SQUERY& query) {
    OPSTACK input;
    query.GetOpstack(&input);
    input.Reverse();
    POPOBJ raw = nullptr;
    while (input >> raw) {
        std::unique_ptr<OPOBJ> item(raw);
        output << *item;
    }
}
SQUERY compose(const SQUERY& left, const SQUERY& right, const OPERATOR& op) {
    if (!IsBinaryOperator(op.GetOperatorType())) throw nb::value_error("A binary operator is required");
    if (!left.GetTotalTerms() || !right.GetTotalTerms()) throw nb::value_error("Both operands must contain a term");
    OPSTACK stack;
    append_query(stack, left);
    append_query(stack, right);
    stack << op;
    SQUERY result;
    result.SetOpstack(stack);
    return result;
}
SQUERY apply_unary(const SQUERY& query, const OPERATOR& op) {
    if (!IsUnaryOperator(op.GetOperatorType())) throw nb::value_error("A unary operator is required");
    OPSTACK stack;
    append_query(stack, query);
    stack << op;
    SQUERY result;
    result.SetOpstack(stack);
    return result;
}
OPERATOR bounded_peer(t_Operator code, nb::handle gap) {
    OPERATOR op(code);
    if (!gap.is_none()) {
        if (!PyLong_Check(gap.ptr()) || PyBool_Check(gap.ptr())) throw nb::type_error("max_gap must be an integer");
        (void) nb::cast<GPTYPE>(gap); // Range-check before preserving its exact decimal spelling.
        op.SetOperatorString(nb::cast<STRING>(nb::str(gap)));
    }
    return op;
}
SQUERY literal(const STRING& term, const STRING& field, const STRING& datatype,
              ZRelations relation, float weight, bool phrase, bool prefix) {
    checked_text(term, "A nonempty literal term without NUL bytes is required");
    ATTRLIST attributes;
    if (!field.IsEmpty()) attributes.AttrSetFieldName(field);
    if (!datatype.IsEmpty()) {
        const int type = FIELDTYPE::GetType(datatype);
        if (type < 0) throw nb::value_error("Unknown field datatype");
        attributes.AttrSetFieldType(FIELDTYPE(type));
    }
    if (relation != ZRelNoop) attributes.AttrSetRelation(relation);
    attributes.AttrSetTermWeight(weight);
    attributes.AttrSetPhrase(phrase);
    attributes.AttrSetRightTruncation(prefix);
    STERM operand;
    operand.SetTerm(term);
    operand.SetAttributes(attributes);
    OPSTACK stack;
    stack << operand;
    SQUERY result;
    result.SetOpstack(stack);
    return result;
}

template <class T> void bind_database(nb::module_& m, const char *name, bool searching) {
    using D = Database<T>;
    nb::class_<D>(m, name)
        .def(nb::init<const STRING&, bool, const std::vector<STRING>&>(),
             "name"_a, "search_only"_a = searching, "doctype_options"_a = std::vector<STRING>())
        .def("close", &D::close)
        .def_prop_ro("closed", [](const D& db) { return !db.value; })
        .def("__enter__", [](D& db) -> D& { db.get(); return db; }, nb::rv_policy::reference)
        .def("__exit__", [](D& db, nb::handle, nb::handle, nb::handle) { db.close(); },
             "exc_type"_a.none(), "exc_value"_a.none(), "traceback"_a.none())
        .def_prop_ro("name", [](const D& db) { return db.get().GetDbFileStem(); })
        .def_prop_ro("total_records", [](const D& db) { return db.get().GetTotalRecords(); })
        .def_prop_ro("total_words", [](const D& db) { return db.get().GetTotalWords(); })
        .def_prop_ro("volume_count", [](const D& db) -> size_t {
            if constexpr (std::is_same_v<T, VIDB>) return db.get().GetIDBCount();
            else { db.get(); return 1; }
        })
        .def("GetVersionID", [](D& db) { return db.get().GetVersionID(); })
        .def("SetLocale", [](D& db, const STRING& locale) { return db.get().SetLocale(locale.c_str()); })
        .def("add_record", [](D& db, const RECORD& record) { db.writer(); return db.get().AddRecord(record); })
        .def("add_file", [](D& db, const STRING& path, const STRING& type) {
            db.writer();
            checked_text(path, "A filename is required");
            RECORD record(path);
            record.SetDocumentType(DOCTYPE_ID(type));
            return db.get().AddRecord(record);
        }, "path"_a, "doctype"_a = STRING("AUTODETECT"))
        .def("index", [](D& db, bool append, t_merge_status merge, size_t memory_mb) {
            db.writer();
            if (db.value.use_count() != 1)
                throw std::runtime_error("Release live results and metadata views before indexing through this handle");
            if (memory_mb > (std::numeric_limits<size_t>::max() >> 20))
                throw nb::value_error("memory_mb is too large");
            const size_t bytes = memory_mb << 20;
            if constexpr (std::is_same_v<T, IDB>) {
                db.get().SetMergeStatus(merge);
                db.get().SetIndexingMemory(bytes);
            }
            else for (size_t i = 1; i <= db.get().GetIDBCount(); ++i) {
                auto *part = dynamic_cast<IDB *>(db.get().GetIDB(i));
                if (part) { part->SetMergeStatus(merge); part->SetIndexingMemory(bytes); }
            }
            return db.get().Index(!append);
        }, "append"_a = true, "merge"_a = iNothing, "memory_mb"_a = 256)
        .def("search", [](D& db, const QUERY& query) {
            std::unique_ptr<IRSET> result(db.get().Search(query));
            if (!result) throw std::runtime_error("IB search failed");
            return Matches{db.owner(), std::move(result)};
        }, "query"_a)
        .def("search", [](D& db, const SQUERY& query, SortBy sort, NormalizationMethods normalization) {
            QUERY request(query, sort, normalization);
            std::unique_ptr<IRSET> result(db.get().Search(request));
            if (!result) throw std::runtime_error("IB search failed");
            return Matches{db.owner(), std::move(result)};
        }, "query"_a, "sort"_a = ByScore, "normalization"_a = defaultNormalization)
        .def("search_smart", [](D& db, const QUERY& query, const STRING& field) {
            QUERY request(query);
            std::unique_ptr<IRSET> result(db.get().SearchSmart(&request, field));
            if (!result) throw std::runtime_error("IB smart search failed");
            return nb::make_tuple(Matches{db.owner(), std::move(result)}, request);
        }, "query"_a, "default_field"_a = STRING())
        .def("get_mdt", [](D& db, size_t volume) {
            MDT *table;
            if constexpr (std::is_same_v<T, IDB>) {
                if (volume != 1) throw nb::index_error("IDB has one metadata table");
                table = db.get().GetMainMdt();
            } else {
                if (volume < 1 || volume > db.get().GetIDBCount()) throw nb::index_error();
                table = db.get().GetMainMdt(static_cast<INT>(volume));
            }
            if (!table) throw std::runtime_error("Metadata table is unavailable");
            return MetadataTable{db.owner(), table};
        }, "volume"_a = 1)
        .def("headline", [](D& db, const Result& row) { return db.get().Headline(row.value, NulString); })
        .def("summary", [](D& db, const Result& row) { return db.get().Summary(row.value, NulString); })
        .def("get_field_data", [](D& db, const Result& row, const STRING& field) -> nb::object {
            STRING text;
            if (!db.get().GetFieldData(row.value, field, &text)) return nb::none();
            return nb::cast(text);
        });
}
}

NB_MODULE(_core, m) {
    m.doc() = "Native CoreQuarry/IB classes and query algebra";
    m.attr("ib_revision") = COREQUARRY_IB_REVISION;
    m.attr("gptype_bits") = sizeof(GPTYPE)*8;
    m.attr("index_id_bits") = sizeof(INDEX_ID)*8;
#ifdef VECTOR_INDEX
    m.attr("vector_enabled") = true;
#else
    m.attr("vector_enabled") = false;
#endif

    nb::enum_<t_merge_status>(m, "Merge")
        .value("NONE", iNothing).value("OPTIMIZE", iOptimize).value("MERGE", iMerge)
        .value("COLLAPSE", iCollapse).value("INCREMENTAL", iIncremental).value("ZIP", iZip);
    nb::enum_<SortBy>(m, "SortBy")
        .value("UNSORTED", Unsorted).value("SCORE", ByScore).value("DATE", ByDate)
        .value("REVERSE_DATE", ByReverseDate).value("HITS", ByHits).value("KEY", ByKey)
        .value("INDEX", ByIndex).value("AUX_COUNT", ByAuxCount);
    nb::enum_<NormalizationMethods>(m, "Normalization")
        .value("NONE", NoNormalization).value("L2", NormalizationL2).value("L1", NormalizationL1)
        .value("BM25", NormalizationBM25).value("E2", E2Normalization).value("HYBRID", HybridNormalization)
        .value("MAX", MaxNormalization).value("DEFAULT", defaultNormalization);
    nb::enum_<ZRelations>(m, "Relation")
        .value("DEFAULT", ZRelNoop).value("LT", ZRelLT).value("LE", ZRelLE).value("EQ", ZRelEQ)
        .value("GE", ZRelGE).value("GT", ZRelGT).value("NE", ZRelNE)
        .value("OVERLAPS", ZRelOverlaps).value("WITHIN", ZRelEnclosedWithin).value("ENCLOSES", ZRelEncloses);
    nb::enum_<t_Operator>(m, "Operator")
        .value("AND", OperatorAnd).value("OR", OperatorOr).value("AND_NOT", OperatorAndNot)
        .value("XOR", OperatorXor).value("XNOR", OperatorXnor).value("NOT_AND", OperatorNotAnd)
        .value("NAND", OperatorNand).value("NOR", OperatorNor)
        .value("LT", OperatorLT).value("LE", OperatorLTE).value("GT", OperatorGT).value("GE", OperatorGTE)
        .value("NOT", OperatorNOT).value("WITHIN", OperatorWithin).value("XWITHIN", OperatorXWithin)
        .value("NOT_WITHIN", OperatorNotWithin).value("INSIDE", OperatorInside).value("INCLUSIVE", OperatorInclusive)
        .value("PEER", OperatorPeer).value("PEER_BEFORE", OperatorBeforePeer).value("PEER_AFTER", OperatorAfterPeer)
        .value("XPEER", OperatorXPeer).value("PROXIMITY", OperatorProximity)
        .value("BEFORE", OperatorBefore).value("AFTER", OperatorAfter).value("ADJ", OperatorAdj)
        .value("FOLLOWS", OperatorFollows).value("PRECEDES", OperatorPrecedes).value("NEAR", OperatorNear)
        .value("FAR", OperatorFar).value("NEIGHBOR", OperatorNeighbor)
        .value("AND_WITHIN", OperatorAndWithin).value("OR_WITHIN", OperatorOrWithin)
        .value("BEFORE_WITHIN", OperatorBeforeWithin).value("AFTER_WITHIN", OperatorAfterWithin)
        .value("JOIN", OperatorJoin).value("JOIN_LEFT", OperatorJoinL)
        .value("JOIN_RIGHT", OperatorJoinR).value("BOOST", OperatorBoostScore).value("SORT", OperatorSortBy)
        .value("WITH_KEY", OperatorWithKey).value("WITHIN_DOCTYPE", OperatorWithinDoctype)
        .value("WITHIN_FILE", OperatorWithinFile).value("WITHIN_FILE_EXTENSION", OperatorWithinFileExtension)
        .value("KEY", OperatorKey).value("FILE", OperatorFile)
        .value("REDUCE", OperatorReduce).value("FOCUS", OperatorFocus)
        .value("HIT_COUNT", OperatorHitCount).value("TRIM", OperatorTrim).value("SIBLING", OperatorSibling)
        .value("ANCESTOR", OperatorAncestor).value("MAYBE", OperatorMaybe).value("NARROW", OperatorNarrow)
        .value("PROMOTE", OperatorPromote).value("DEMOTE", OperatorDemote);

    nb::class_<FIELDTYPE>(m, "FIELDTYPE")
        .def("__init__", [](FIELDTYPE *self, const STRING& name) {
            int type = FIELDTYPE::GetType(name);
            if (type < 0) throw nb::value_error("Unknown field datatype");
            new (self) FIELDTYPE(type);
        }, "name"_a)
        .def_prop_ro("name", [](const FIELDTYPE& type) { return STRING(type.c_str()); })
        .def("__str__", [](const FIELDTYPE& type) { return STRING(type.c_str()); });
    nb::class_<ATTRLIST>(m, "ATTRLIST")
        .def(nb::init<>())
        .def_prop_rw("field", nb::overload_cast<>(&ATTRLIST::AttrGetFieldName, nb::const_), &ATTRLIST::AttrSetFieldName)
        .def_prop_rw("datatype", nb::overload_cast<>(&ATTRLIST::AttrGetFieldType, nb::const_), &ATTRLIST::AttrSetFieldType)
        .def_prop_rw("relation", nb::overload_cast<>(&ATTRLIST::AttrGetRelation, nb::const_), &ATTRLIST::AttrSetRelation)
        .def_prop_rw("weight", &ATTRLIST::AttrGetTermWeight, nb::overload_cast<float>(&ATTRLIST::AttrSetTermWeight))
        .def_prop_rw("phrase", &ATTRLIST::AttrGetPhrase, &ATTRLIST::AttrSetPhrase)
        .def_prop_rw("prefix", &ATTRLIST::AttrGetRightTruncation, &ATTRLIST::AttrSetRightTruncation);
    nb::class_<STERM>(m, "STERM")
        .def(nb::init<>())
        .def_prop_rw("text", nb::overload_cast<>(&STERM::GetTerm, nb::const_), &STERM::SetTerm)
        .def_prop_rw("attributes", [](const STERM& term) { ATTRLIST a; term.GetAttributes(&a); return a; },
            [](STERM& term, const ATTRLIST& a) { term.SetAttributes(a); });
    nb::class_<OPERATOR>(m, "OPERATOR")
        .def(nb::init<const t_Operator&>(), "code"_a)
        .def_prop_rw("code", &OPERATOR::GetOperatorType, &OPERATOR::SetOperatorType)
        .def_prop_rw("metric", &OPERATOR::GetOperatorMetric, &OPERATOR::SetOperatorMetric)
        .def_prop_rw("argument", &OPERATOR::GetOperatorString, &OPERATOR::SetOperatorString);
    nb::class_<OPSTACK>(m, "OPSTACK")
        .def(nb::init<>())
        .def("push", [](OPSTACK& stack, const STERM& term) { stack << term; })
        .def("push", [](OPSTACK& stack, const OPERATOR& op) { stack << op; });

    nb::class_<SQUERY>(m, "SQUERY")
        .def(nb::init<>())
        .def(nb::init<const SQUERY&>())
        .def_static("term", &literal, "text"_a, "field"_a = STRING(), "datatype"_a = STRING(),
            "relation"_a = ZRelNoop, "weight"_a = 1.0f, "phrase"_a = false, "prefix"_a = false)
        .def_static("from_rpn", [](const STRING& text) {
            SQUERY q; if (!q.SetRpnTerm(text)) throw nb::value_error(q.LastErrorMessage().c_str()); return q;
        })
        .def_static("from_infix", [](const STRING& text) {
            SQUERY q; if (!q.SetInfixTerm(text)) throw nb::value_error(q.LastErrorMessage().c_str()); return q;
        })
        .def_static("from_words", [](const STRING& text) { SQUERY q; q.SetWords(text); return q; })
        .def("SetOpstack", &SQUERY::SetOpstack)
        .def("GetOpstack", [](const SQUERY& q) { OPSTACK stack; q.GetOpstack(&stack); return stack; })
        .def("SetRpnTerm", &SQUERY::SetRpnTerm)
        .def("SetInfixTerm", &SQUERY::SetInfixTerm)
        .def("GetRpnTerm", nb::overload_cast<>(&SQUERY::GetRpnTerm, nb::const_))
        .def("LastErrorMessage", &SQUERY::LastErrorMessage)
        .def("SetAttributes", &SQUERY::SetAttributes, "attributes"_a, "replace"_a = true)
        .def("combine", &compose, "other"_a, "operator"_a)
        .def("apply", &apply_unary)
        .def("__and__", [](const SQUERY& a, const SQUERY& b) { return compose(a,b,OPERATOR(OperatorAnd)); })
        .def("__or__", [](const SQUERY& a, const SQUERY& b) { return compose(a,b,OPERATOR(OperatorOr)); })
        .def("__xor__", [](const SQUERY& a, const SQUERY& b) { return compose(a,b,OPERATOR(OperatorXor)); })
        .def_static("field", [](const STRING& name, nb::handle value, ZRelations relation, const STRING& datatype) {
            return literal(nb::cast<STRING>(nb::str(value)),name,datatype,relation,1.0f,false,false);
        }, "name"_a, "value"_a, "relation"_a = ZRelEQ, "datatype"_a = STRING())
        .def("and_not", [](const SQUERY& a, const SQUERY& b) { return compose(a,b,OPERATOR(OperatorAndNot)); })
        .def("peer", [](const SQUERY& a, const SQUERY& b, nb::handle gap) { return compose(a,b,bounded_peer(OperatorPeer,gap)); },
             "other"_a, "max_gap"_a = nb::none())
        .def("before_peer", [](const SQUERY& a, const SQUERY& b, nb::handle gap) { return compose(a,b,bounded_peer(OperatorBeforePeer,gap)); },
             "other"_a, "max_gap"_a = nb::none())
        .def("after_peer", [](const SQUERY& a, const SQUERY& b, nb::handle gap) { return compose(a,b,bounded_peer(OperatorAfterPeer,gap)); },
             "other"_a, "max_gap"_a = nb::none())
        .def("within", [](const SQUERY& q, const STRING& field) { OPERATOR op(OperatorWithin); op.SetOperatorString(field); return apply_unary(q,op); })
        .def("boost", [](const SQUERY& q, FLOAT weight) { OPERATOR op(OperatorBoostScore); op.SetOperatorMetric(weight); return apply_unary(q,op); })
        .def_prop_ro("term_count", &SQUERY::GetTotalTerms)
        .def_static("operators", [] {
            size_t total = 0;
            const auto *docs = SQUERY::GetOperatorDocs(&total);
            nb::list output;
            for (size_t i = 0; i < total; ++i) {
                nb::dict item;
                item["code"] = static_cast<int>(docs[i].Code);
                item["name"] = docs[i].Name;
                item["arity"] = docs[i].Arity;
                item["syntax"] = docs[i].Syntax;
                item["description"] = docs[i].Description;
                output.append(item);
            }
            return output;
        })
        .def_prop_ro("rpn", nb::overload_cast<>(&SQUERY::GetRpnTerm, nb::const_))
        .def("__str__", nb::overload_cast<>(&SQUERY::GetRpnTerm, nb::const_));
    nb::class_<QUERY>(m, "QUERY")
        .def(nb::init<const SQUERY&, SortBy, NormalizationMethods>(), "squery"_a,
             "sort"_a = ByScore, "normalization"_a = defaultNormalization)
        .def_prop_rw("sort", &QUERY::GetSortBy, &QUERY::SetSortBy)
        .def_prop_rw("normalization", &QUERY::GetNormalizationMethod, &QUERY::SetNormalizationMethod)
        .def_prop_rw("squery", [](const QUERY& q) { return SQUERY(q.GetSQUERY()); }, &QUERY::SetSQUERY)
        .def_prop_ro("term_count", &QUERY::GetTotalTerms);

    nb::class_<SRCH_DATE>(m, "SRCH_DATE")
        .def(nb::init<>()).def(nb::init<const STRING&>())
        .def("__str__", nb::overload_cast<>(&SRCH_DATE::ISOdate, nb::const_))
        .def_prop_ro("iso", nb::overload_cast<>(&SRCH_DATE::ISOdate, nb::const_))
        .def_prop_ro("ok", &SRCH_DATE::Ok);
    nb::class_<FC>(m, "FC")
        .def(nb::init<>()).def(nb::init<GPTYPE,GPTYPE>(), "start"_a, "end"_a)
        .def_prop_rw("start", &FC::GetFieldStart, &FC::SetFieldStart)
        .def_prop_rw("end", &FC::GetFieldEnd, &FC::SetFieldEnd)
        .def_prop_ro("length", &FC::GetLength)
        .def_prop_ro("empty", &FC::IsEmpty)
        .def("contains", nb::overload_cast<const FC&>(&FC::Contains, nb::const_))
        .def("__repr__", [](const FC& fc) { return std::string("FC(")+std::to_string(fc.GetFieldStart())+", "+std::to_string(fc.GetFieldEnd())+")"; });
    nb::class_<FCHIT,FC>(m, "FCHIT")
        .def(nb::init<GPTYPE,GPTYPE,FCSOURCE>(), "start"_a, "end"_a, "source_id"_a = 0)
        .def_prop_ro("source_id", &FCHIT::GetSourceId);
    nb::class_<HITTABLE>(m, "HITTABLE")
        .def("__len__", &HITTABLE::Size)
        .def("__getitem__", [](const HITTABLE& hits, Py_ssize_t index) { return hits.GetEntry(offset_index(index,hits.Size())+1); });
    nb::class_<EVIDENCE_COVER>(m, "EVIDENCE_COVER")
        .def_ro("extent", &EVIDENCE_COVER::extent)
        .def_ro("energy", &EVIDENCE_COVER::Energy)
        .def_ro("dispersion", &EVIDENCE_COVER::Dispersion);
    nb::class_<DISPLAY_EVIDENCE>(m, "DISPLAY_EVIDENCE")
        .def_ro("cover", &DISPLAY_EVIDENCE::Cover)
        .def_ro("display_extent", &DISPLAY_EVIDENCE::DisplayExtent)
        .def_ro("container_extent", &DISPLAY_EVIDENCE::ContainerExtent)
        .def_ro("container_name", &DISPLAY_EVIDENCE::ContainerName)
        .def_prop_ro("has_container", &DISPLAY_EVIDENCE::HasContainer);

    nb::class_<RECORD>(m, "RECORD")
        .def(nb::init<>()).def(nb::init<const STRING&>(), "filename"_a)
        .def_prop_rw("filename", nb::overload_cast<>(&RECORD::GetFullFileName, nb::const_), &RECORD::SetFullFileName)
        .def_prop_rw("key", nb::overload_cast<>(&RECORD::GetKey, nb::const_), &RECORD::SetKey)
        .def_prop_rw("start", &RECORD::GetRecordStart, &RECORD::SetRecordStart)
        .def_prop_rw("end", &RECORD::GetRecordEnd, &RECORD::SetRecordEnd)
        .def_prop_rw("doctype", [](const RECORD& r) { return r.GetDocumentType().DocumentType(); },
            [](RECORD& r, const STRING& t) { r.SetDocumentType(DOCTYPE_ID(t)); });

    nb::class_<MetadataRecord>(m, "MDTREC")
        .def(nb::init<>())
        .def_prop_ro("key", [](const MetadataRecord& r) { return r.value.GetKey(); })
        .def_prop_ro("filename", [](const MetadataRecord& r) {
            if (!r.owner) throw std::runtime_error("Load the MDTREC from a metadata table before resolving its filename");
            return r.value.GetFullFileName();
        })
        .def_prop_ro("doctype", [](const MetadataRecord& r) { return r.value.GetDocumentType().DocumentType(); })
        .def_prop_ro("start", [](const MetadataRecord& r) { return r.value.GetLocalRecordStart(); })
        .def_prop_ro("end", [](const MetadataRecord& r) { return r.value.GetLocalRecordEnd(); })
        .def_prop_ro("date", [](const MetadataRecord& r) { return r.value.GetDate(); });
    nb::class_<MetadataTable>(m, "MDT")
        .def("__len__", [](const MetadataTable& table) { return table.value->GetTotalEntries(); })
        .def("get_entry", [](const MetadataTable& table, size_t index, MetadataRecord& output) {
            if (index < 1 || index > table.value->GetTotalEntries()) return false;
            if (!table.value->GetEntry(index,&output.value)) return false;
            output.owner = table.owner;
            return true;
        }, "index"_a, "record"_a)
        .def("__getitem__", [](const MetadataTable& table, Py_ssize_t index) {
            const size_t offset = offset_index(index,table.value->GetTotalEntries());
            MetadataRecord output;
            if (!table.value->GetEntry(offset+1,&output.value)) throw std::runtime_error("Cannot read the metadata record");
            output.owner = table.owner;
            return output;
        })
        .def("lookup_key", [](MetadataTable& table, const STRING& key) { return table.value->LookupByKey(key); });

    nb::class_<Match>(m, "IRESULT")
        .def_prop_ro("score", [](const Match& r) { return r.value.GetScore(); })
        .def_prop_ro("hit_count", [](const Match& r) { return r.value.GetHitCount(); })
        .def_prop_ro("hits", [](const Match& r) { return r.value.GetHitTable(); })
        .def_prop_ro("mdt_index", [](const Match& r) { return r.value.GetMdtIndex(); })
        .def_prop_ro("virtual_index", [](const Match& r) { return r.value.GetVirtualIndex(); });
    nb::class_<Result>(m, "RESULT")
        .def_prop_ro("key", [](const Result& r) { return r.value.GetKey(); })
        .def_prop_ro("filename", [](const Result& r) { return r.value.GetFullFileName(); })
        .def_prop_ro("doctype", [](const Result& r) { return r.value.GetDoctype(); })
        .def_prop_ro("score", [](const Result& r) { return r.value.GetScore(); })
        .def_prop_ro("date", [](const Result& r) { return r.value.GetDate(); })
        .def_prop_ro("start", [](const Result& r) { return r.value.GetRecordStart(); })
        .def_prop_ro("end", [](const Result& r) { return r.value.GetRecordEnd(); })
        .def_prop_ro("hits", [](const Result& r) { return r.value.GetHitTable(); })
        .def_prop_ro("mdt_index", [](const Result& r) { return r.value.GetMdtIndex(); })
        .def_prop_ro("virtual_index", [](const Result& r) { return r.value.GetVirtualIndex(); })
        .def("get_evidence_covers", [](const Result& r, size_t max) { return r.value.GetEvidenceCovers(max); }, "max_covers"_a = 3)
        .def("get_display_evidence", [](const Result& r, size_t max) { return r.value.GetDisplayEvidence(max,doctype(r)); }, "max_bytes"_a = 130)
        .def("evidence", [](const Result& r, size_t max, const STRING& before, const STRING& after) {
            STRING text, field;
            if (!r.value.PresentBestDisplayEvidence(max,&text,nullptr,before,after,doctype(r),&field))
                throw std::runtime_error("Cannot present display evidence");
            return nb::make_tuple(text,field);
        }, "max_bytes"_a = 130, "before"_a = STRING("**"), "after"_a = STRING("**"))
        .def("get_record_data", [](const Result& r) { STRING text; r.value.GetRecordData(&text,doctype(r)); return text; });
    nb::class_<Results>(m, "RSET")
        .def("__len__", [](Results& results) { return results.value->GetTotalEntries(); })
        .def("__getitem__", [](const Results& results, Py_ssize_t index) {
            const size_t offset = offset_index(index,results.value->GetTotalEntries());
            RESULT row;
            if (!results.value->GetEntry(offset+1,&row)) throw std::runtime_error("Cannot read the result");
            return Result{results.owner,std::move(row)};
        })
        .def_prop_ro("total_found", [](const Results& results) { return results.value->GetTotalFound(); })
        .def_prop_ro("hit_total", [](const Results& results) { return results.value->GetHitTotal(); })
        .def("sort_by", [](Results& results, SortBy sort) { results.value->SortBy(sort); });

    auto matches = nb::class_<Matches>(m, "IRSET")
        .def("__len__", [](const Matches& set) { return set.value->GetTotalEntries(); })
        .def("__getitem__", [](const Matches& set, Py_ssize_t index) {
            const size_t offset = offset_index(index,set.value->GetTotalEntries());
            IRESULT row;
            if (!set.value->GetEntry(offset+1,&row)) throw std::runtime_error("Cannot read the match");
            return Match{set.owner,std::move(row)};
        })
        .def_prop_ro("hit_total", [](Matches& set) { return set.value->GetHitTotal(); })
        .def("copy", [](const Matches& set) { return Matches{set.owner,std::unique_ptr<IRSET>(copy_matches(*set.value))}; })
        .def("sort_by", [](Matches& set, SortBy sort) { set.value->SortBy(sort); })
        .def("normalize", [](Matches& set, NormalizationMethods method, float weight) { set.value->ComputeScores(weight,method); },
             "method"_a, "weight"_a = 1.0f)
        .def("get_rset", [](const Matches& set, nb::handle total, size_t start) {
            size_t count = total.is_none() ? set.value->GetTotalEntries() : nb::cast<size_t>(total);
            if (start >= set.value->GetTotalEntries() || count == 0)
                return Results{set.owner,std::make_unique<RSET>()};
            count = std::min(count,set.value->GetTotalEntries()-start);
            return Results{set.owner,std::unique_ptr<RSET>(set.value->GetRset(start,start+count))};
        }, "total"_a = nb::none(), "start"_a = 0);
    matches.def("__and__", [](const Matches& a, const Matches& b) {
        same_database(a,b); auto result = std::unique_ptr<IRSET>(copy_matches(*a.value)); result->And(*b.value);
        return Matches{a.owner,std::move(result)};
    });
    matches.def("__or__", [](const Matches& a, const Matches& b) {
        same_database(a,b); auto result = std::unique_ptr<IRSET>(copy_matches(*a.value)); result->Or(*b.value);
        return Matches{a.owner,std::move(result)};
    });
    matches.def("and_not", [](const Matches& a, const Matches& b) {
        same_database(a,b); auto result = std::unique_ptr<IRSET>(copy_matches(*a.value)); result->AndNot(*b.value);
        return Matches{a.owner,std::move(result)};
    });
    matches.def("peer", [](const Matches& a, const Matches& b, nb::handle gap) {
        same_database(a,b); physical_structure(a);
        auto result = std::unique_ptr<IRSET>(copy_matches(*a.value));
        if (gap.is_none()) result->Peer(*b.value);
        else { (void) bounded_peer(OperatorPeer,gap); result->Peer(*b.value,nb::cast<GPTYPE>(gap)); }
        return Matches{a.owner,std::move(result)};
    }, "other"_a, "max_gap"_a = nb::none());
    matches.def("within", [](const Matches& a, const STRING& field) {
        physical_structure(a);
        auto result = std::unique_ptr<IRSET>(copy_matches(*a.value)); result->Within(field);
        return Matches{a.owner,std::move(result)};
    });

    bind_database<IDB>(m,"IDB",false);
    bind_database<VIDB>(m,"VIDB",true);
}
