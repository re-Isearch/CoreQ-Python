#pragma once

// Python headers must precede IB's platform headers.
#include <nanobind/nanobind.h>
#include <cstring>
#include "common.hxx"

namespace nanobind::detail {
template <> struct type_caster<STRING> {
    NB_TYPE_CASTER(STRING, const_name("str"))

    bool from_python(handle src, uint8_t, cleanup_list *) noexcept {
        PyObject *bytes = nullptr;
        if (PyUnicode_Check(src.ptr()))
            bytes = PyUnicode_AsEncodedString(src.ptr(), "utf-8", "surrogateescape");
        else if (PyBytes_Check(src.ptr())) {
            bytes = src.ptr();
            Py_INCREF(bytes);
        } else return false;
        if (!bytes) return false;
        // IB STRING treats NUL as a terminator even with an explicit length.
        // Reject such input before it can silently shorten a literal or path.
        if (std::memchr(PyBytes_AS_STRING(bytes), 0, static_cast<size_t>(PyBytes_GET_SIZE(bytes)))) {
            Py_DECREF(bytes);
            return false;
        }
        value.Assign(PyBytes_AS_STRING(bytes), static_cast<size_t>(PyBytes_GET_SIZE(bytes)));
        Py_DECREF(bytes);
        return true;
    }

    static handle from_cpp(const STRING& text, rv_policy, cleanup_list *) noexcept {
        return PyUnicode_DecodeUTF8(text.c_str(), static_cast<Py_ssize_t>(text.GetLength()), "surrogateescape");
    }
};
}
