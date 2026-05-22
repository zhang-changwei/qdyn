cmake_minimum_required(VERSION 3.18)
project(qdyn_openmx_postprocess LANGUAGES C)

find_package(Python COMPONENTS Interpreter Development.Module REQUIRED)

execute_process(
  COMMAND "${Python_EXECUTABLE}" -c "import numpy; print(numpy.get_include())"
  OUTPUT_VARIABLE NUMPY_INCLUDE_DIR
  OUTPUT_STRIP_TRAILING_WHITESPACE
)

python_add_library(_read_openmx_postprocess_ext MODULE
  src/cpp/read_openmx_postprocess_core.c
  src/cpp/_read_openmx_postprocess_ext.c
  WITH_SOABI
)

target_include_directories(_read_openmx_postprocess_ext PRIVATE
  "${NUMPY_INCLUDE_DIR}"
)

target_compile_features(_read_openmx_postprocess_ext PRIVATE c_std_99)
target_compile_options(_read_openmx_postprocess_ext PRIVATE
  $<$<C_COMPILER_ID:GNU,Clang>:-O3>
  $<$<C_COMPILER_ID:MSVC>:/O2>
)

install(TARGETS _read_openmx_postprocess_ext
  LIBRARY DESTINATION qdyn_openmx_postprocess
  RUNTIME DESTINATION qdyn_openmx_postprocess
)
