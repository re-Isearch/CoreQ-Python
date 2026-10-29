cmake_minimum_required(VERSION 3.24)
project(CoreQuarryPython VERSION 0.1.0 LANGUAGES C CXX)

find_package(Python 3.10 REQUIRED COMPONENTS Interpreter Development.Module)
find_package(nanobind CONFIG REQUIRED)

set(COREQUARRY_IB_SOURCE_DIR "" CACHE PATH "Path to a current re-Isearch/ib checkout")
if(NOT COREQUARRY_IB_SOURCE_DIR AND IS_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/../ib/src")
    set(COREQUARRY_IB_SOURCE_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../ib")
endif()
if(NOT EXISTS "${COREQUARRY_IB_SOURCE_DIR}/src/vidb.hxx")
    message(FATAL_ERROR "Set COREQUARRY_IB_SOURCE_DIR to the current re-Isearch/ib checkout")
endif()

# The engine remains a separate dependency. These are defaults and can be
# overridden with normal CMake settings, including Schmate/vector support.
option(BUILD_VECTOR_INDEX "Enable the engine's optional vector support" OFF)
option(BUILD_LARGE_INDEX "Use the engine's large-index ABI" ON)
option(USE_LIBMAGIC "Enable libmagic" OFF)
option(USE_JEMALLOC "Enable jemalloc" OFF)
option(USE_OPENMP "Enable OpenMP" OFF)
option(USE_BERKELEY_DB "Enable Berkeley DB cache" OFF)
if(NOT USE_BERKELEY_DB)
    # This is the source-level switch used by current IB's cache headers.
    add_compile_definitions(NO_RLDCACHE)
endif()
set(BUILD_SHARED_LIBS ON CACHE BOOL "Bundle the engine component libraries")
set(IB_RUNTIME_OUTPUT_DIRECTORY "${CMAKE_CURRENT_BINARY_DIR}/engine-bin" CACHE PATH "Engine tool output")
add_subdirectory("${COREQUARRY_IB_SOURCE_DIR}" "${CMAKE_CURRENT_BINARY_DIR}/ib" EXCLUDE_FROM_ALL)

nanobind_add_module(_core NB_STATIC bindings/core.cxx)
target_compile_features(_core PRIVATE cxx_std_17)

# Keep the extension and Python wrapper together for imports from the build tree.
# Copy on every build so Python-only edits do not require relinking the extension.
set(_python_package_dir "${CMAKE_CURRENT_BINARY_DIR}/corequarry")
add_custom_target(corequarry_python_files
    COMMAND "${CMAKE_COMMAND}" -E make_directory "${_python_package_dir}"
    COMMAND "${CMAKE_COMMAND}" -E copy_if_different
        "${CMAKE_CURRENT_SOURCE_DIR}/src/corequarry/__init__.py"
        "${CMAKE_CURRENT_SOURCE_DIR}/src/corequarry/_core.pyi"
        "${CMAKE_CURRENT_SOURCE_DIR}/src/corequarry/py.typed"
        "${_python_package_dir}"
    VERBATIM)
add_dependencies(_core corequarry_python_files)
set_target_properties(_core PROPERTIES LIBRARY_OUTPUT_DIRECTORY "${_python_package_dir}")
foreach(_config IN LISTS CMAKE_CONFIGURATION_TYPES)
    string(TOUPPER "${_config}" _config_upper)
    set_target_properties(_core PROPERTIES
        "LIBRARY_OUTPUT_DIRECTORY_${_config_upper}" "${_python_package_dir}")
endforeach()

# IB currently supplies ABI definitions at directory scope rather than through
# exported SDK targets. Consume that exact configuration, including index widths.
get_directory_property(_ib_definitions DIRECTORY "${COREQUARRY_IB_SOURCE_DIR}" COMPILE_DEFINITIONS)
target_compile_definitions(_core PRIVATE ${_ib_definitions})
target_include_directories(_core PRIVATE "$<TARGET_PROPERTY:ibSearch,INCLUDE_DIRECTORIES>")
set(_ib_libraries ibApps ibSearch ibDoc ibProcess ibIO ibUtils ibLocal)
target_link_libraries(_core PRIVATE ${_ib_libraries})
if(UNIX AND NOT APPLE)
    target_link_options(_core PRIVATE "LINKER:--no-as-needed")
    set_target_properties(_core PROPERTIES INSTALL_RPATH "$ORIGIN/lib")
elseif(APPLE)
    set_target_properties(_core PROPERTIES INSTALL_RPATH "@loader_path/lib")
endif()

execute_process(COMMAND git -C "${COREQUARRY_IB_SOURCE_DIR}" rev-parse HEAD
    OUTPUT_VARIABLE _ib_revision OUTPUT_STRIP_TRAILING_WHITESPACE ERROR_QUIET)
target_compile_definitions(_core PRIVATE COREQUARRY_IB_REVISION="${_ib_revision}")
install(TARGETS _core LIBRARY DESTINATION corequarry COMPONENT python)
install(TARGETS ${_ib_libraries} LIBRARY DESTINATION corequarry/lib COMPONENT python)
install(DIRECTORY src/corequarry/ DESTINATION corequarry COMPONENT python
    FILES_MATCHING PATTERN "*.py" PATTERN "*.pyi" PATTERN "py.typed"
    PATTERN "__pycache__" EXCLUDE)
