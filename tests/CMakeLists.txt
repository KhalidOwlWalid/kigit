# kigit tests. Run with `ctest` from the build folder:
#   ctest                    everything that can run here
#   ctest -L unit            C++ unit + integration tests only
#   ctest -L gui             the NiceGUI app (needs uv)
#   ctest -L regression      real-repo netlist checks (needs env, see regression.sh)

# doctest: the submodule in submodules/doctest.
set(DOCTEST_NO_INSTALL ON CACHE INTERNAL "")
add_subdirectory(${KIGIT_SUBMODULES}/doctest ${CMAKE_BINARY_DIR}/doctest EXCLUDE_FROM_ALL)

add_executable(kigit_tests
  cpp/main.cpp
  cpp/helpers.cpp
  cpp/test_sexpr.cpp
  cpp/test_board.cpp
  cpp/test_diff.cpp
  cpp/test_schematic.cpp
  cpp/test_sch_diff.cpp
  cpp/test_git.cpp
  cpp/test_cli.cpp
  cpp/test_source.cpp
)
target_link_libraries(kigit_tests PRIVATE kigit_core doctest::doctest)
# DOCTEST_CONFIG_USE_STD_HEADERS: include the real <tuple> etc. instead of
# doctest declaring std types itself, which new MSVC forbids (C5285).
target_compile_definitions(kigit_tests PRIVATE
  DOCTEST_CONFIG_USE_STD_HEADERS
  KIGIT_FIXTURES="${CMAKE_CURRENT_SOURCE_DIR}/fixtures"
  KIGIT_BIN="$<TARGET_FILE:kigit>")
add_dependencies(kigit_tests kigit) # the CLI tests run the real binary

# One ctest entry per TEST_CASE.
include(${KIGIT_SUBMODULES}/doctest/scripts/cmake/doctest.cmake)
doctest_discover_tests(kigit_tests PROPERTIES LABELS unit)

# The GUI tests (pytest, simulated user) against the same fixture repo.
find_program(UV_EXECUTABLE uv)
if(UV_EXECUTABLE)
  add_test(NAME gui
    COMMAND ${UV_EXECUTABLE} run --quiet --project ${PROJECT_SOURCE_DIR}/gui pytest -q -p no:warnings
    WORKING_DIRECTORY ${PROJECT_SOURCE_DIR}/gui)
  set_tests_properties(gui PROPERTIES LABELS gui
    ENVIRONMENT "KIGIT_BIN=$<TARGET_FILE:kigit>")
endif()

# Optional: check kigit's schematic nets against kicad-cli on real projects.
# Skipped (exit 77) unless KIGIT_REGRESSION_PROJECTS is set; see regression.sh.
# (A shell script, so Linux/macOS only.)
if(UNIX)
  add_test(NAME regression COMMAND ${CMAKE_CURRENT_SOURCE_DIR}/regression.sh $<TARGET_FILE:kigit>)
  set_tests_properties(regression PROPERTIES LABELS regression SKIP_RETURN_CODE 77)
endif()
