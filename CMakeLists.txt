# 3.16 or newer; the "...3.31" opts into newer CMake's behaviour where it's
# available (e.g. CMP0135: downloaded files get the extraction time).
cmake_minimum_required(VERSION 3.16...3.31)

# Downloaded dependencies (doctest) still declare CMake < 3.5, which CMake 4
# refuses. Treat them as 3.5. (Ignored by CMake older than 4.)
if(NOT DEFINED CMAKE_POLICY_VERSION_MINIMUM)
  set(CMAKE_POLICY_VERSION_MINIMUM 3.5 CACHE STRING "Minimum CMake policy version for dependencies")
endif()
project(kigit VERSION 0.1.0 LANGUAGES CXX)

# Linux, macOS and Windows (MSVC or MinGW) are all supported; everything
# OS-specific in the code is in src/utils/platform.cpp.
message(STATUS "kigit: building for ${CMAKE_SYSTEM_NAME} with ${CMAKE_CXX_COMPILER_ID} ${CMAKE_CXX_COMPILER_VERSION}")
if(NOT (WIN32 OR APPLE OR UNIX))
  message(WARNING "kigit: ${CMAKE_SYSTEM_NAME} isn't a tested platform")
endif()

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

if(NOT CMAKE_BUILD_TYPE AND NOT CMAKE_CONFIGURATION_TYPES)
  set(CMAKE_BUILD_TYPE Release CACHE STRING "Build type" FORCE)
endif()

# MSVC: link the C++ runtime into kigit.exe, so it runs on any Windows
# without installing the Visual C++ Redistributable. (Set before the
# libraries below so they're built the same way.)
set(CMAKE_MSVC_RUNTIME_LIBRARY "MultiThreaded$<$<CONFIG:Debug>:Debug>")

# nlohmann_json: use the system package if present, otherwise download it.
find_package(nlohmann_json 3.2 QUIET)
if(NOT nlohmann_json_FOUND)
  include(FetchContent)
  FetchContent_Declare(json
    URL https://github.com/nlohmann/json/releases/download/v3.11.3/json.tar.xz)
  FetchContent_MakeAvailable(json)
endif()

# spdlog: use the system package if present, otherwise download it.
find_package(spdlog 1.9 QUIET)
if(NOT spdlog_FOUND)
  include(FetchContent)
  FetchContent_Declare(spdlog
    URL https://github.com/gabime/spdlog/archive/refs/tags/v1.14.1.tar.gz)
  FetchContent_MakeAvailable(spdlog)
endif()

# Embed the HTML viewer into the binary: the page shell plus its scripts,
# combined into one self-contained file.
set(VIEWER_DIR ${CMAKE_CURRENT_SOURCE_DIR}/resources)
set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS
  ${VIEWER_DIR}/viewer.html ${VIEWER_DIR}/pcb.js ${VIEWER_DIR}/sch.js ${VIEWER_DIR}/shell.js)
file(READ ${VIEWER_DIR}/viewer.html KIGIT_VIEWER_HTML)
foreach(part PCB SCH SHELL)
  string(TOLOWER ${part} name)
  file(READ ${VIEWER_DIR}/${name}.js script)
  string(REPLACE "/*@KIGIT_${part}_JS@*/" "${script}" KIGIT_VIEWER_HTML "${KIGIT_VIEWER_HTML}")
endforeach()
# As a byte array (portable to every compiler; see viewer_template.hpp.in).
file(WRITE ${CMAKE_CURRENT_BINARY_DIR}/generated/viewer.html "${KIGIT_VIEWER_HTML}")
file(READ ${CMAKE_CURRENT_BINARY_DIR}/generated/viewer.html viewer_hex HEX)
string(REGEX REPLACE "(................................................................)" "\\1\n" viewer_hex "${viewer_hex}")
string(REGEX REPLACE "([0-9a-f][0-9a-f])" "0x\\1," KIGIT_VIEWER_BYTES "${viewer_hex}")
configure_file(src/report/viewer_template.hpp.in
               ${CMAKE_CURRENT_BINARY_DIR}/generated/viewer_template.hpp @ONLY)

# Everything except main() is a library, so the tests can use it directly.
add_library(kigit_core STATIC
  src/utils/sexpr.cpp
  src/utils/log.cpp
  src/utils/platform.cpp
  src/pcb/board.cpp
  src/pcb/diff.cpp
  src/sch/schematic.cpp
  src/sch/sch_diff.cpp
  src/sch/netcheck.cpp
  src/git/git.cpp
  src/git/locate.cpp
  src/report/html.cpp
)
target_include_directories(kigit_core PUBLIC include ${CMAKE_CURRENT_BINARY_DIR}/generated)
target_compile_definitions(kigit_core PUBLIC KIGIT_VERSION="${PROJECT_VERSION}")
target_link_libraries(kigit_core PUBLIC nlohmann_json::nlohmann_json spdlog::spdlog)

# The command line: main() and one file per command.
add_executable(kigit
  src/main.cpp
  src/commands/options.cpp
  src/commands/common.cpp
  src/commands/summary.cpp
  src/commands/diff.cpp
  src/commands/history.cpp
  src/commands/projects.cpp
  src/commands/gui.cpp
)
target_link_libraries(kigit PRIVATE kigit_core)

# Per-OS / per-compiler settings.
if(WIN32)
  # Plain C library calls without MSVC's "use the _s version" warnings; keep
  # <windows.h> from defining min/max macros.
  target_compile_definitions(kigit_core PUBLIC _CRT_SECURE_NO_WARNINGS NOMINMAX WIN32_LEAN_AND_MEAN)
endif()
if(MSVC)
  # /utf-8: the sources contain UTF-8 text (arrows, dots in messages).
  # /Zc:__cplusplus: report the real C++ standard. /EHsc: C++ exceptions.
  target_compile_options(kigit_core PUBLIC /utf-8 /permissive- /Zc:__cplusplus /EHsc /W3 /bigobj)
  target_compile_options(kigit PRIVATE /W3)
elseif(CMAKE_CXX_COMPILER_ID MATCHES "GNU|Clang")
  target_compile_options(kigit_core PRIVATE -Wall -Wextra -Wpedantic)
  target_compile_options(kigit PRIVATE -Wall -Wextra -Wpedantic)
endif()
if(MINGW)
  # A kigit.exe that runs without MinGW's DLLs next to it.
  target_link_options(kigit PRIVATE -static)
endif()

option(KIGIT_BUILD_TESTS "Build the test suite (ctest)" ON)
if(KIGIT_BUILD_TESTS)
  enable_testing()
  add_subdirectory(tests)
endif()

install(TARGETS kigit RUNTIME DESTINATION bin)
# The Python GUI (kigit gui) is found at <prefix>/share/kigit/gui.
# uv.lock pins the Python packages the installed GUI uses.
install(DIRECTORY gui/ DESTINATION share/kigit/gui
        PATTERN ".venv" EXCLUDE PATTERN "__pycache__" EXCLUDE PATTERN ".pytest_cache" EXCLUDE
        PATTERN "tests" EXCLUDE)
